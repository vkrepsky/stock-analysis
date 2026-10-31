"""Passo 5: triagem (lucro estável + pouca dívida + preço em queda) e ranking.

Uso:  python src/05_triagem.py [b3_dataset.csv] [pasta_de_saida]
Saídas: triagem_completa.csv, aprovadas.csv, quase_aprovadas.csv (quase = falha em 1 critério).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import ANOS_DFP, OUT

P = dict(
    liq_min=5e6,             # liquidez mediana diária mínima (R$), soma das classes
    queda_lucro_max=-0.30,   # nenhuma queda anual de lucro pior que isso (inclui LTM vs último ano)
    dl_ebitda_max=1.0,       # dívida líquida/EBITDA máximo (ou caixa líquido)
    usar_arrendamento=True,  # True: arrendamentos (IFRS 16) entram na dívida
    ret_12m_max=-0.15,       # preço 15%+ abaixo de 12 meses atrás ...
    dist_max_52w_max=-0.25,  # ... ou 25%+ abaixo da máxima de 52 semanas
)
PESOS = dict(valuation=0.30, estabilidade=0.25, balanco=0.20, dividendos=0.15, qualidade=0.10)
SEM_ESCOPO = r"Banco|Intermedia[cç][aã]o Financeira"
CRITERIOS = ["lucro_estavel", "pouca_divida", "preco_em_queda"]


def colunas_lucro():
    return [f"ll_{a}" for a in ANOS_DFP] + ["ll_ltm"]


def filtros(df):
    ll = df[colunas_lucro()]
    f = pd.DataFrame(index=df.index)
    f["escopo"] = ~df["setor"].fillna("").str.contains(SEM_ESCOPO, case=False, regex=True)
    f["situacao"] = (df["SIT"].fillna("ATIVO") == "ATIVO") & ~df["SIT_EMISSOR"].fillna("").str.contains(
        "RECUPERA|LIQUIDA|FAL[EÊ]NCIA", case=False, regex=True)
    f["liquidez"] = df["liq_total_90d"] >= P["liq_min"]
    variacao = ll.pct_change(axis=1, fill_method=None)
    f["lucro_estavel"] = (ll > 0).all(axis=1) & (variacao.min(axis=1) >= P["queda_lucro_max"])
    dl, dle = ("dl_total_ltm", "dl_ebitda_com_arr") if P["usar_arrendamento"] else ("dl_fin_ltm", "dl_ebitda_sem_arr")
    f["pouca_divida"] = (df[dl] <= 0) | (df[dle] <= P["dl_ebitda_max"])
    f["preco_em_queda"] = (df["ret_12m"] <= P["ret_12m_max"]) | (df["dist_max_52w"] <= P["dist_max_52w_max"])
    return f, dle


def componentes(u, dle):
    """Notas 0-1 (percentil dentro do universo) por dimensão."""
    ll = u[colunas_lucro()]
    cv = ll.std(axis=1) / ll.mean(axis=1).abs()
    c = pd.DataFrame(index=u.index)
    c["valuation"] = 0.5 * (u["ll_ltm"] / u["valor_mercado"]).rank(pct=True) + 0.5 * (1 / u["p_vp"]).rank(pct=True)
    c["estabilidade"] = cv.rank(pct=True, ascending=False)
    c["balanco"] = u[dle].rank(pct=True, ascending=False)
    c["dividendos"] = u["dy_12m"].rank(pct=True) * np.where(u["payout_12m"] > 1.0, 0.5, 1.0)
    c["qualidade"] = u["roe_ltm"].rank(pct=True)
    return c.fillna(0.0)


def freq_top(c, top, n=2000, seed=0):
    """Fração dos sorteios de pesos (ao redor dos pesos-base) em que cada empresa fica no top-N."""
    w = np.random.default_rng(seed).dirichlet(np.array(list(PESOS.values())) * 20, size=n)
    notas = c[list(PESOS)].values @ w.T
    posicao = (-notas).argsort(axis=0).argsort(axis=0)
    return pd.Series((posicao < top).mean(axis=1), index=c.index)


def mostrar(d, extra=()):
    cols = ["ticker", "DENOM_SOCIAL", "preco", "ret_12m", "dist_max_52w", "dl_ebitda_com_arr", "p_l", "p_vp",
            "dy_12m", "score", "freq_top"] + list(extra)
    d = d[[c for c in cols if c in d]].copy()
    if "DENOM_SOCIAL" in d:
        d["DENOM_SOCIAL"] = d["DENOM_SOCIAL"].astype(str).str[:24]
    print(d.round(2).to_string())


def main():
    caminho = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT / "b3_dataset.csv"
    saida = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT
    saida.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(caminho, dtype={"cnpj": str}).set_index("cnpj")
    df.loc[df["valor_mercado"] <= 0, "valor_mercado"] = np.nan
    df["setor"] = df["SETOR_ATIV"] if "SETOR_ATIV" in df else ""
    for col in ("SIT", "SIT_EMISSOR"):
        if col not in df:
            df[col] = ""
    f, dle = filtros(df)

    base = f["escopo"] & f["situacao"] & f["liquidez"]
    comp = componentes(df[base], dle)
    df["score"] = (comp * pd.Series(PESOS)).sum(axis=1).reindex(df.index)

    ok = base & f[CRITERIOS].all(axis=1)
    quase = base & ((~f[CRITERIOS]).sum(axis=1) == 1)
    df["freq_top"] = freq_top(comp.loc[ok[ok].index], top=min(5, int(ok.sum()))).reindex(df.index) if ok.any() else np.nan
    df["falhou"] = [", ".join(c for c in CRITERIOS if not f.at[i, c]) for i in df.index]

    print(f"Universo (escopo+situação+liquidez): {int(base.sum())} empresas")
    for c in CRITERIOS:
        print(f"  passam em {c}: {int((base & f[c]).sum())}")
    print(f"APROVADAS nos 3 critérios: {int(ok.sum())} | quase (falha em 1): {int(quase.sum())}\n")

    aprov = df[ok].sort_values("score", ascending=False)
    qua = df[quase].sort_values("score", ascending=False)
    print("== APROVADAS (ordenadas por score) ==")
    mostrar(aprov)
    print("\n== QUASE APROVADAS (top 25) ==")
    mostrar(qua.head(25), extra=["falhou"])

    pd.concat([df, f.add_prefix("ok_")], axis=1).to_csv(saida / "triagem_completa.csv")
    aprov.to_csv(saida / "aprovadas.csv")
    qua.to_csv(saida / "quase_aprovadas.csv")
    print("\nArquivos gravados em", saida)


if __name__ == "__main__":
    main()
