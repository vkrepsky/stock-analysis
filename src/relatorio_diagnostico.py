"""Relatório de diagnóstico (texto pequeno) para enviar ao Claude no lugar da pasta data/.

Gera data/out/relatorio_diagnostico.md com: cobertura dos campos, zeros suspeitos, causas de
dívida/EBITDA vazio, linhas brutas da CVM de empresas-problema, units, tickers sem Yahoo,
checagens de consistência e resultado da triagem. Não altera nenhum dado.

Uso:  python src/relatorio_diagnostico.py
"""
import traceback
import zipfile

import numpy as np
import pandas as pd

from common import ANOS_DFP, OUT, RAW
from cvm_lib import ler_demonstracao

EMPRESAS_RAW = ["SABESP", "KLABIN", "TELEFONICA BRASIL", "VIVO", "SUZANO", "PRIO", "RENNER", "TAESA"]
CAMPOS = ["ll_2025", "ll_ltm", "receita_ltm", "ebit_ltm", "da_ltm", "ebitda_ltm", "caixa_ltm", "div_fin_ltm",
          "div_arr_ltm", "pl_ctrl_ltm", "acoes_on", "acoes_pn", "valor_mercado", "preco", "ret_12m",
          "dl_ebitda_sem_arr", "dl_ebitda_com_arr", "p_l", "p_vp", "dy_12m"]
SAIDA = []


def sec(titulo):
    SAIDA.append(f"\n## {titulo}\n")


def txt(s=""):
    SAIDA.append(str(s))


def tabela(d, n=60):
    with pd.option_context("display.width", 250, "display.max_colwidth", 50, "display.max_columns", 40):
        SAIDA.append("```\n" + d.head(n).round(3).to_string() + "\n```")


def secao(titulo):
    """Decorador: cada seção roda isolada; erro vira texto no relatório, não derruba o resto."""
    def deco(f):
        sec(titulo)
        try:
            f()
        except Exception:  # noqa: BLE001
            txt("ERRO nesta seção (envie assim mesmo):\n```\n" + traceback.format_exc() + "\n```")
        return f
    return deco


def carregar():
    df = pd.read_csv(OUT / "b3_dataset.csv", dtype={"cnpj": str}).set_index("cnpj")
    df["setor"] = df["SETOR_ATIV"] if "SETOR_ATIV" in df else ""
    fin = df["setor"].fillna("").str.contains(r"Banco|Intermedia[cç][aã]o Financeira|Seguradora|Previd", case=False, regex=True)
    liq = df["liq_total_90d"] >= 5e6
    df["_nao_fin_liquida"] = ~fin & liq
    return df


def linhas_brutas(zip_path, tipo, nome, codigos_prefixos, termos=None):
    d = ler_demonstracao(zip_path, tipo)
    d = d[(d["ORDEM_EXERC"] == "ÚLTIMO") & d["DENOM_CIA"].str.upper().str.contains(nome, na=False)]
    m = d["CD_CONTA"].str.startswith(tuple(codigos_prefixos))
    if termos:
        m |= d["DS_CONTA"].str.contains(termos, case=False, regex=True, na=False)
    cols = ["DENOM_CIA", "consol", "VERSAO", "DT_INI_EXERC", "DT_FIM_EXERC", "CD_CONTA", "DS_CONTA", "VL_CONTA"]
    return d.loc[m, cols]


def main():
    df = carregar()
    nf = df[df["_nao_fin_liquida"]]
    txt(f"# Diagnóstico do pipeline B3\n\nEmpresas no dataset: {len(df)} | não financeiras com liquidez >= R$ 5 mi: {len(nf)}")

    @secao("1. Cobertura (% preenchido e diferente de zero)")
    def _():
        linhas = []
        for c in [c for c in CAMPOS if c in df]:
            for nome, d in (("todas", df), ("não fin. líquidas", nf)):
                s = d[c]
                linhas.append((c, nome, round(100 * s.notna().mean(), 1), round(100 * (s.fillna(0) != 0).mean(), 1)))
        r = pd.DataFrame(linhas, columns=["campo", "grupo", "pct_preenchido", "pct_nao_zero"])
        tabela(r.pivot(index="campo", columns="grupo", values=["pct_preenchido", "pct_nao_zero"]), 100)

    @secao("2. Lucros exatamente zero (suspeito)")
    def _():
        cols = [c for c in df if c.startswith("ll_") and "ltm" not in c or c == "ll_ltm"]
        z = df[(df[cols] == 0).any(axis=1)]
        txt(f"{len(z)} empresas")
        tabela(z[["ticker", "DENOM_SOCIAL"] + cols])

    @secao("3. Dívida/EBITDA vazio em não financeiras líquidas: o que falta")
    def _():
        d = nf[nf["dl_ebitda_com_arr"].isna()].copy()
        txt(f"{len(d)} de {len(nf)} vazias ({100 * len(d) / max(len(nf), 1):.0f}%); cobertura = {100 * (1 - len(d) / max(len(nf), 1)):.0f}%")
        faltam = pd.DataFrame({c: d[c].isna() for c in ("ebit_ltm", "da_ltm", "caixa_ltm", "div_fin_ltm")})
        faltam["ebitda<=0"] = d["ebitda_ltm"] <= 0
        txt("Contagem por causa:")
        tabela(faltam.sum().to_frame("empresas"))
        d = d.assign(**{k: faltam[k] for k in faltam})
        tabela(d.sort_values("valor_mercado", ascending=False)[
            ["ticker", "DENOM_SOCIAL", "valor_mercado", "ebit_ltm", "da_ltm", "caixa_ltm", "div_fin_ltm", "ebitda_ltm"]], 60)

    @secao("4. Linhas brutas da CVM (DFP 2025, exercício atual) das empresas-problema")
    def _():
        zp = RAW / "cvm" / f"dfp_{ANOS_DFP[-1]}.zip"
        for nome in EMPRESAS_RAW:
            txt(f"### {nome}")
            for tipo, pref, termo in (("DRE", ("3.01", "3.05", "3.11"), None),
                                      ("DVA", ("7.04",), r"deprecia|amortiza"),
                                      ("DFC_MD", ("6.01",), r"deprecia|amortiza"),
                                      ("DFC_MI", ("6.01",), r"deprecia|amortiza")):
                try:
                    r = linhas_brutas(zp, tipo, nome, pref, termo)
                except FileNotFoundError:
                    continue
                if len(r):
                    txt(f"{tipo}:")
                    tabela(r, 40)

    @secao("5. Units: valor de mercado calculado vs Yahoo")
    def _():
        u = df[df["mcap_fonte"] == "unit_x_acoes_on"]
        c = ["ticker", "tickers", "DENOM_SOCIAL", "preco", "acoes_on", "acoes_pn", "valor_mercado", "mcap_yahoo", "mcap_divergente"]
        u = u[[x for x in c if x in u]].copy()
        u["razao_calc_yahoo"] = u["valor_mercado"] / u["mcap_yahoo"]
        u["acoes_total"] = u["acoes_on"].fillna(0) + u["acoes_pn"].fillna(0)
        u["pn_por_on"] = u["acoes_pn"] / u["acoes_on"]
        tabela(u, 60)

    @secao("6. Tickers sem dados no Yahoo")
    def _():
        tk = pd.read_csv(OUT / "tickers.csv", dtype=str)
        px = pd.read_csv(OUT / "precos_resumo.csv")
        falta = tk[~tk["ticker"].isin(px["ticker"])]
        txt(f"{len(falta)} de {len(tk)} tickers: {' '.join(falta['ticker'])}")

    @secao("7. Checagens de consistência")
    def _():
        achados = []

        def marca(nome, mask):
            for cnpj in df.index[mask.fillna(False)]:
                achados.append((nome, df.at[cnpj, "ticker"], str(df.at[cnpj, "DENOM_SOCIAL"])[:28]))

        marca("lucro > receita (escala?)", df["ll_ltm"] > df["receita_ltm"].abs() * 1.0)
        marca("|lucro| > R$ 200 bi (escala?)", df["ll_ltm"].abs() > 2e11)
        marca("dívida financeira < 0 (arrendamento > dívida total)", df["div_fin_ltm"] < 0)
        marca("arrendamentos > dívida total (div_fin ~ 0)", df["div_arr_ltm"] > df["div_fin_ltm"] * 5)
        marca("caixa > ativo total", df["caixa_ltm"] > df.get("ativo_ltm", np.inf))
        marca("valor de mercado > R$ 1 tri", df["valor_mercado"] > 1e12)
        marca("P/L < 1 (provável erro)", df["p_l"] < 1)
        marca("ações ON+PN = 0", (df["acoes_on"].fillna(0) + df["acoes_pn"].fillna(0)) <= 0)
        marca("DY > 30%", df["dy_12m"] > 0.30)
        marca("EBITDA < EBIT (D&A negativa)", df["ebitda_ltm"] < df["ebit_ltm"])
        try:
            # mudança de ano fiscal: exercício do DFP 2025 que não termina em dezembro
            zp = RAW / "cvm" / f"dfp_{ANOS_DFP[-1]}.zip"
            d = ler_demonstracao(zp, "DRE")
            d = d[d["ORDEM_EXERC"] == "ÚLTIMO"].drop_duplicates("CNPJ_CIA")
            fim = d["DT_FIM_EXERC"].dt.month
            dur = (d["DT_FIM_EXERC"] - d["DT_INI_EXERC"]).dt.days
            for _, r in d[(fim != 12) | ((dur < 350) | (dur > 380))].iterrows():
                achados.append(("ano fiscal atípico (fim/duração)", r["DENOM_CIA"][:28],
                                f"{r['DT_INI_EXERC'].date()} a {r['DT_FIM_EXERC'].date()} ({int(dur[_])} d)"))
        except Exception as e:  # noqa: BLE001
            achados.append(("ano fiscal: não verificado", "-", str(e)[:80]))
        r = pd.DataFrame(achados, columns=["checagem", "ticker/empresa", "detalhe"])
        txt(f"{len(r)} ocorrências")
        if len(r):
            txt("Resumo:")
            tabela(r["checagem"].value_counts().to_frame("n"))
            tabela(r, 120)

    @secao("8. Validação com a Renner (LREN3, R$ mi)")
    def _():
        ref = {"ll_2021": 633.11, "ll_2022": 1291.70, "ll_2023": 976.26, "ll_2024": 1196.67, "ll_2025": 1457.57}
        x = df[df["ticker"] == "LREN3"]
        if x.empty:
            txt("LREN3 ausente do dataset")
            return
        r = pd.DataFrame({"calculado": {k: x.iloc[0][k] / 1e6 for k in ref}, "referencia": ref})
        tabela(r)
        txt(f"caixa líquido LTM (esperado ~ +1.160 mi em jun/2026): "
            f"{-(x.iloc[0]['dl_fin_ltm']) / 1e6:,.0f} (sem arr.) | {-(x.iloc[0]['dl_total_ltm']) / 1e6:,.0f} (com arr.); "
            f"lucro LTM {x.iloc[0]['ll_ltm'] / 1e6:,.0f} (esperado ~1.490)")

    @secao("9. Hipóteses (sanidade): onde cada uma está")
    def _():
        t = ["VIVA3", "GRND3", "VULC3", "TFCO4", "CURY3", "DIRR3", "EZTC3", "LREN3"]
        try:
            tc = pd.read_csv(OUT / "triagem_completa.csv", dtype={"cnpj": str}).set_index("cnpj")
        except FileNotFoundError:
            txt("triagem_completa.csv não existe (rode o passo 5)")
            return
        ok = [c for c in tc if c.startswith("ok_")]
        x = tc[tc["ticker"].isin(t)]
        tabela(x[[c for c in ["ticker", "ll_ltm", "dl_ebitda_com_arr", "ret_12m", "dist_max_52w", "score"] if c in x] + ok].T, 40)

    @secao("10. Resultado da triagem")
    def _():
        tc = pd.read_csv(OUT / "triagem_completa.csv", dtype={"cnpj": str}).set_index("cnpj")
        for c in [c for c in tc if c.startswith("ok_")]:
            txt(f"- {c}: {int(tc[c].sum())}")
        for arq in ("aprovadas.csv", "quase_aprovadas.csv"):
            a = pd.read_csv(OUT / arq)
            txt(f"\n{arq}: {len(a)}")
            tabela(a[[c for c in ("ticker", "DENOM_SOCIAL", "ret_12m", "dist_max_52w", "dl_ebitda_com_arr", "p_l", "p_vp",
                                  "dy_12m", "score", "falhou") if c in a]], 40)

    destino = OUT / "relatorio_diagnostico.md"
    destino.write_text("\n".join(SAIDA), encoding="utf-8")
    print(f"Gravado: {destino} ({destino.stat().st_size / 1e3:.0f} KB). Envie este arquivo + o log do terminal ao Claude.")


if __name__ == "__main__":
    main()
