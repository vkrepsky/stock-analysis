"""Passo 3: lista os tickers (FCA da CVM) e baixa preços e dividendos no Yahoo Finance.

Saídas em data/out/: tickers.csv, precos_resumo.csv, dividendos_ano.csv, precos_diarios.csv.gz
Uso:  pip install yfinance  &&  python src/03_precos.py      (precisa de internet)
"""
import re
import time
import unicodedata
import zipfile

import pandas as pd
import yfinance as yf

from common import OUT, RAW

INICIO = "2020-12-01"
LOTE = 25


def norm(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def achar(cols, *inicios):
    for c in cols:
        if any(norm(c).startswith(i) for i in inicios):
            return c
    raise KeyError(f"coluna não encontrada: {inicios} em {list(cols)}")


def tickers_fca():
    zp = sorted((RAW / "cvm").glob("fca_*.zip"))[-1]
    with zipfile.ZipFile(zp) as z:
        nome = next(n for n in z.namelist() if "valor_mobiliario" in n.lower())
        with z.open(nome) as f:
            d = pd.read_csv(f, sep=";", encoding="latin1", dtype=str)
    c_cnpj, c_cod = achar(d.columns, "cnpj"), achar(d.columns, "codigo_negoc")
    c_mer, c_fim = achar(d.columns, "mercado"), achar(d.columns, "data_fim_negoc")
    c_vm, c_ver = achar(d.columns, "valor_mobiliario"), achar(d.columns, "versao")
    d = d[d[c_mer].fillna("").str.contains("bolsa", case=False) & d[c_fim].isna()]
    d = d[d[c_vm].fillna("").str.contains("a[cç][õo]es|units", case=False, regex=True)]
    d[c_ver] = pd.to_numeric(d[c_ver], errors="coerce")
    linhas = []
    for _, r in d.iterrows():
        for tk in re.split(r"[^A-Za-z0-9]+", str(r[c_cod]).upper()):
            if re.fullmatch(r"[A-Z]{4}\d{1,2}", tk):
                linhas.append((r[c_cnpj], tk, r[c_ver]))
    t = pd.DataFrame(linhas, columns=["cnpj", "ticker", "versao"])
    t = t.sort_values("versao").drop_duplicates(["cnpj", "ticker"], keep="last").drop(columns="versao")
    t["classe"] = t["ticker"].map(lambda x: "UNIT" if x.endswith("11") else "ON" if x.endswith("3") else "PN")
    return t.reset_index(drop=True)


def resumo_ticker(tk, df):
    """Métricas de preço, liquidez e dividendos de um ticker (df = OHLCV+Dividends do Yahoo)."""
    df = df.dropna(subset=["Close"])
    if df.empty:
        return None, None
    fim = df.index.max()
    h12 = df[df.index > fim - pd.Timedelta(days=365)]
    ant = df[df.index <= fim - pd.Timedelta(days=365)]
    ult = df["Close"].iloc[-1]
    base = ant["Close"].iloc[-1] if len(ant) else h12["Close"].iloc[0]
    base_aj = ant["Adj Close"].iloc[-1] if len(ant) else h12["Adj Close"].iloc[0]
    r = {
        "ticker": tk, "dt_preco": fim.date(), "preco": ult,
        "ret_12m": ult / base - 1, "ret_12m_total": df["Adj Close"].iloc[-1] / base_aj - 1,
        "max_52w": h12["Close"].max(), "dist_max_52w": ult / h12["Close"].max() - 1,
        "liq_mediana_90d": (df["Close"] * df["Volume"]).tail(90).median(),
        "div_12m": h12["Dividends"].sum(),
    }
    div = df["Dividends"][df["Dividends"] > 0]
    por_ano = div.groupby(div.index.year).sum().rename(tk)
    return r, por_ano


def mcap_units(t):
    """Valor de mercado (Yahoo) dos tickers do tipo UNIT, que não dá para derivar das ações ON/PN."""
    saida = []
    for tk in t.loc[t["classe"] == "UNIT", "ticker"]:
        try:
            fi = yf.Ticker(tk + ".SA").fast_info
            saida.append((tk, float(fi["market_cap"])))
        except Exception:  # noqa: BLE001
            print("  sem valor de mercado no Yahoo para", tk)
        time.sleep(0.5)
    return pd.DataFrame(saida, columns=["ticker", "mcap_yahoo"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    t = tickers_fca()
    t.to_csv(OUT / "tickers.csv", index=False)
    print(f"{len(t)} tickers em {t['cnpj'].nunique()} empresas")

    resumos, divs, diarios, falhas = [], [], [], []
    lista = t["ticker"].tolist()
    for i in range(0, len(lista), LOTE):
        lote = lista[i:i + LOTE]
        try:
            dados = yf.download([x + ".SA" for x in lote], start=INICIO, interval="1d", auto_adjust=False,
                                actions=True, group_by="ticker", threads=True, progress=False)
        except Exception as e:  # noqa: BLE001
            print("  lote falhou:", e)
            falhas += lote
            continue
        for tk in lote:
            try:
                df = dados[tk + ".SA"] if isinstance(dados.columns, pd.MultiIndex) else dados
                r, d = resumo_ticker(tk, df)
            except Exception:  # noqa: BLE001
                r = None
            if r is None:
                falhas.append(tk)
                continue
            resumos.append(r)
            divs.append(d)
            x = df.dropna(subset=["Close"]).tail(520)[["Close", "Adj Close", "Volume"]].assign(ticker=tk)
            diarios.append(x.reset_index())
        print(f"  {min(i + LOTE, len(lista))}/{len(lista)}")
        time.sleep(2)

    pd.DataFrame(resumos).to_csv(OUT / "precos_resumo.csv", index=False)
    mcap_units(t).to_csv(OUT / "mcap_units.csv", index=False)
    try:  # Ibovespa, para medir a queda relativa ao mercado
        ib = yf.download("^BVSP", start=INICIO, interval="1d", auto_adjust=False, progress=False)
        if isinstance(ib.columns, pd.MultiIndex):
            ib.columns = ib.columns.get_level_values(0)
        ib[["Close"]].to_csv(OUT / "ibov_diario.csv")
    except Exception as e:  # noqa: BLE001
        print("  Ibovespa não baixou:", e)
    pd.concat(divs, axis=1).T.to_csv(OUT / "dividendos_ano.csv", index_label="ticker")
    pd.concat(diarios).to_csv(OUT / "precos_diarios.csv.gz", index=False)
    print(f"Sem dados no Yahoo: {len(falhas)} tickers -> {falhas[:40]}")


if __name__ == "__main__":
    main()
