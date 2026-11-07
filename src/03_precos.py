"""Passo 3: lista os tickers (FCA da CVM) e baixa preços e dividendos no Yahoo Finance.

Saídas em data/out/: tickers.csv, precos_resumo.csv, dividendos_ano.csv, dividendos_extraordinarios.csv,
precos_diarios.csv.gz
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
EXTRA_VEZES = 5      # pagamento > 5x a mediana dos pagamentos dos últimos 3 anos = extraordinário
RETRIES = 2          # rodadas extras para os tickers que o Yahoo não devolveu (falha intermitente)
LOTE_RETRY = 5
PAUSA_RETRY = 20     # segundos (multiplicado pelo número da rodada)


def norm(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def achar(cols, *inicios):
    for c in cols:
        if any(norm(c).startswith(i) for i in inicios):
            return c
    raise KeyError(f"coluna não encontrada: {inicios} em {list(cols)}")


def tickers_fca():
    zips = sorted((RAW / "cvm").glob("fca_*.zip"))
    if not zips:
        raise SystemExit("Falta data/raw/cvm/fca_*.zip (lista de tickers). Rode o passo 1: python src/run_all.py --so 1")
    zp = zips[-1]
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


def classificar_dividendos(df, fim):
    """Pagamentos dos últimos 12 meses (R$ por ação) com a marca `extra`.

    Extraordinário = passa de EXTRA_VEZES x a mediana dos pagamentos dos últimos 3 anos (ex.: GRND3 pagou
    R$ 1,09 em dez/2025 contra ~R$ 0,09 nos demais, 73% do que a janela somava). Quem paga uma vez por ano
    tem mediana = o próprio pagamento: nada sai. Limite conhecido: quem mistura pagamentos pequenos e
    frequentes (JCP trimestral) com um grande por ano pode ter o grande tratado como extraordinário.
    """
    pagos = df["Dividends"][df["Dividends"] > 0]
    h12 = pagos[pagos.index > fim - pd.Timedelta(days=365)]
    ref = pagos[pagos.index > fim - pd.Timedelta(days=3 * 365)]
    mediana = float(ref.median()) if len(ref) else 0.0
    return pd.DataFrame({"valor": h12, "mediana_3a": mediana, "extra": h12 > EXTRA_VEZES * mediana})


def dividendos_12m(df, fim):
    """(total, recorrente) pagos nos últimos 12 meses (R$ por ação)."""
    c = classificar_dividendos(df, fim)
    return float(c["valor"].sum()), float(c.loc[~c["extra"], "valor"].sum())


def pagamentos_extraordinarios(tk, df):
    """Pagamentos de 12 meses tratados como extraordinários (trilha de auditoria do dy_12m_rec)."""
    df = df.dropna(subset=["Close"])
    c = classificar_dividendos(df, df.index.max())
    c = c[c["extra"]].drop(columns="extra")
    out = c.reset_index(names="data").assign(ticker=tk, vezes=lambda z: z["valor"] / z["mediana_3a"])
    out["data"] = out["data"].dt.strftime("%Y-%m-%d")
    return out[["ticker", "data", "valor", "mediana_3a", "vezes"]]


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
    div_total, div_rec = dividendos_12m(df, fim)
    r = {
        "ticker": tk, "dt_preco": fim.date(), "preco": ult,
        "ret_12m": ult / base - 1, "ret_12m_total": df["Adj Close"].iloc[-1] / base_aj - 1,
        "max_52w": h12["Close"].max(), "dist_max_52w": ult / h12["Close"].max() - 1,
        "liq_mediana_90d": (df["Close"] * df["Volume"]).tail(90).median(),
        "div_12m": div_total, "div_12m_rec": div_rec,
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


def processar_lote(lote):
    """Baixa um lote no Yahoo. Devolve (ok, falhos); ok[ticker] = (resumo, dividendos_ano, extras, diario)."""
    try:
        dados = yf.download([x + ".SA" for x in lote], start=INICIO, interval="1d", auto_adjust=False,
                            actions=True, group_by="ticker", threads=True, progress=False)
    except Exception as e:  # noqa: BLE001
        print("  lote falhou:", e)
        return {}, list(lote)
    ok, falhos = {}, []
    for tk in lote:
        try:
            df = dados[tk + ".SA"] if isinstance(dados.columns, pd.MultiIndex) else dados
            r, d = resumo_ticker(tk, df)
        except Exception:  # noqa: BLE001
            r = None
        if r is None:
            falhos.append(tk)
            continue
        x = df.dropna(subset=["Close"]).tail(520)[["Close", "Adj Close", "Volume"]].assign(ticker=tk)
        ok[tk] = (r, d, pagamentos_extraordinarios(tk, df), x.reset_index())
    return ok, falhos


def baixar_tudo(lista):
    """Baixa todos os tickers. O Yahoo falha de forma intermitente e o erro ("possibly delisted") é o mesmo
    de um ticker extinto; por isso quem falhou é tentado de novo, em lotes menores e com pausa. Para quando
    uma rodada não recupera nenhum (os que sobram são, de fato, tickers sem dados)."""
    resultados, falhas = {}, []
    for i in range(0, len(lista), LOTE):
        ok, falhos = processar_lote(lista[i:i + LOTE])
        resultados.update(ok)
        falhas += falhos
        print(f"  {min(i + LOTE, len(lista))}/{len(lista)}")
        time.sleep(2)
    for rodada in range(1, RETRIES + 1):
        if not falhas:
            break
        print(f"  nova tentativa {rodada}/{RETRIES} para {len(falhas)} tickers sem dados")
        time.sleep(PAUSA_RETRY * rodada)
        pendentes, falhas = falhas, []
        for i in range(0, len(pendentes), LOTE_RETRY):
            ok, falhos = processar_lote(pendentes[i:i + LOTE_RETRY])
            resultados.update(ok)
            falhas += falhos
            time.sleep(2)
        if len(falhas) == len(pendentes):
            break
    return resultados, falhas


def avisar_sumidos(antigos, falhas):
    """Tickers que tinham dados na execução anterior e agora ficaram sem: sinal de Yahoo instável."""
    sumiram = sorted(set(antigos) & set(falhas))
    if sumiram:
        print(f"ATENÇÃO: {len(sumiram)} tickers que tinham dados na execução anterior ficaram sem: "
              f"{' '.join(sumiram)}\n  Pode ser instabilidade do Yahoo: rode o passo 3 de novo antes de usar o resultado.")
    return sumiram


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    t = tickers_fca()
    t.to_csv(OUT / "tickers.csv", index=False)
    print(f"{len(t)} tickers em {t['cnpj'].nunique()} empresas")
    antigos = pd.read_csv(OUT / "precos_resumo.csv")["ticker"].tolist() if (OUT / "precos_resumo.csv").exists() else []

    lista = t["ticker"].tolist()
    resultados, falhas = baixar_tudo(lista)
    ordem = [tk for tk in lista if tk in resultados]
    resumos = [resultados[tk][0] for tk in ordem]
    divs = [resultados[tk][1] for tk in ordem]
    extras = [resultados[tk][2] for tk in ordem]
    diarios = [resultados[tk][3] for tk in ordem]

    pd.DataFrame(resumos).to_csv(OUT / "precos_resumo.csv", index=False)
    pd.concat(extras).to_csv(OUT / "dividendos_extraordinarios.csv", index=False)
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
    avisar_sumidos(antigos, falhas)


if __name__ == "__main__":
    main()
