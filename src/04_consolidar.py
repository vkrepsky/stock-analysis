"""Passo 4: junta fundamentos (CVM) + preços/dividendos (Yahoo) em data/out/b3_dataset.csv.

Uma linha por empresa (CNPJ); o ticker principal é o de maior liquidez.
Uso:  python src/04_consolidar.py
"""
import numpy as np
import pandas as pd

from common import ANOS_DFP, OUT

LIMITE_ESCALA = 0.05   # P/VP ou P/L abaixo disso é impossível na prática: a CVM trouxe as ações em milhares


def corrigir_escala_acoes(df):
    """Multiplica por 1000 as ações (e o valor de mercado) das empresas que informam em milhares.

    A composição do capital da CVM não traz escala e parte das empresas preenche em milhares (Renner:
    961 mil ações, ABEV3: 15 milhões), o que deixava o valor de mercado 1000x menor e o P/L e P/VP ~0.
    Sinais (qualquer um): P/VP ou P/L < LIMITE_ESCALA com lucro/PL positivos; ou, para units, valor de
    mercado ~1/1000 do valor do Yahoo. Devolve a máscara das empresas corrigidas.
    """
    vm = df["valor_mercado"]
    pl = df["pl_ctrl_ltm"].where(df["pl_ctrl_ltm"] > 0)
    ll = df["ll_ltm"].where(df["ll_ltm"] > 0)
    mil = (vm / pl < LIMITE_ESCALA) | (vm / ll < LIMITE_ESCALA) | (vm / df["mcap_yahoo"]).between(2e-4, 4e-3)
    cols = ["acoes_on", "acoes_pn", "valor_mercado"]
    df.loc[mil, cols] = df.loc[mil, cols] * 1000
    df["acoes_em_mil"] = mil
    df.loc[mil, "mcap_fonte"] += "_x1000"
    return mil


def checagens(df):
    """Avisos de sanidade do dataset (não interrompem o pipeline)."""
    ll = df[[f"ll_{a}" for a in ANOS_DFP] + ["ll_ltm"]]
    testes = {
        "EBITDA < EBIT (sinal da D&A)": df["ebitda_ltm"] < df["ebit_ltm"],
        f"P/L ou P/VP < {LIMITE_ESCALA} (escala das ações)": (df["p_l"] < LIMITE_ESCALA) | (df["p_vp"] < LIMITE_ESCALA),
        "lucro exatamente zero em algum ano (investigar)": (ll == 0).any(axis=1),
    }
    print("\nChecagens do dataset:")
    for nome, m in testes.items():
        n = int(m.sum())
        exemplos = f" ({', '.join(df.loc[m, 'ticker'].head(6))})" if n else ""
        print(f"  {'OK      ' if n == 0 else 'ATENÇÃO '}{nome}: {n}{exemplos}")


def main():
    fund = pd.read_csv(OUT / "fundamentos.csv", dtype={"cnpj": str}).set_index("cnpj")
    tk = pd.read_csv(OUT / "tickers.csv", dtype=str)
    px = pd.read_csv(OUT / "precos_resumo.csv")
    dv = pd.read_csv(OUT / "dividendos_ano.csv").set_index("ticker")
    dv.columns = [f"div_{c}" for c in dv.columns]

    t = tk.merge(px, on="ticker", how="inner")
    t = t.sort_values("liq_mediana_90d", ascending=False)
    principal = t.drop_duplicates("cnpj").set_index("cnpj").add_suffix("_p").rename(columns={"ticker_p": "ticker"})
    todos = t.groupby("cnpj")["ticker"].agg(lambda s: " ".join(s)).rename("tickers")
    liq_total = t.groupby("cnpj")["liq_mediana_90d"].sum().rename("liq_total_90d")

    # valor de mercado: melhor preço por classe (ON/PN); sem preço da classe, usa o do principal
    on = t[t["classe"] == "ON"].drop_duplicates("cnpj").set_index("cnpj")["preco"]
    pn = t[t["classe"] == "PN"].drop_duplicates("cnpj").set_index("cnpj")["preco"]

    df = fund.join(principal).join(todos).join(liq_total)
    df = df[df["ticker"].notna()].copy()
    p = df["preco_p"]
    df["valor_mercado"] = (
        df["acoes_on"].fillna(0) * on.reindex(df.index).fillna(p)
        + df["acoes_pn"].fillna(0) * pn.reindex(df.index).fillna(p)
    )
    df["mcap_fonte"] = "classes"
    sem_acoes = (df["acoes_on"].fillna(0) + df["acoes_pn"].fillna(0)) <= 0
    df.loc[sem_acoes, "valor_mercado"] = np.nan
    df.loc[sem_acoes, "mcap_fonte"] = "sem_acoes"
    # só unit negociada: o preço da unit não é o da ação ON/PN, então usa o valor de mercado do Yahoo
    so_unit = on.reindex(df.index).isna() & pn.reindex(df.index).isna()
    # aproximação: nº de units = ações ON (1 ON por unit, o padrão da B3). O valor do Yahoo costuma
    # multiplicar o preço da unit por TODAS as ações e inflar o resultado; fica só para comparação.
    df["mcap_yahoo"] = np.nan
    if (OUT / "mcap_units.csv").exists():
        mu = tk[tk["classe"] == "UNIT"].merge(pd.read_csv(OUT / "mcap_units.csv"), on="ticker")
        df["mcap_yahoo"] = mu.groupby("cnpj")["mcap_yahoo"].max().reindex(df.index)
    df.loc[so_unit, "valor_mercado"] = df["preco_p"] * df["acoes_on"]
    df.loc[so_unit, "mcap_fonte"] = "unit_x_acoes_on"
    mil = corrigir_escala_acoes(df)
    print(f"Ações informadas em milhares na CVM (corrigidas x1000): {int(mil.sum())} empresas")
    if mil.any():
        print("  " + " ".join(df.loc[mil, "ticker"]))
    razao = df["valor_mercado"] / df["mcap_yahoo"]
    df["mcap_divergente"] = so_unit & ((razao > 1.5) | (razao < 0.67))
    df = df.join(dv, on="ticker")

    ult = ANOS_DFP[-1]
    df["ebitda_ltm"] = df["ebit_ltm"] + df["da_ltm"]                    # da já vem em módulo (02_fundamentos)
    df["dl_fin_ltm"] = df["div_fin_ltm"] - df["caixa_ltm"]              # sem arrendamentos
    df["dl_total_ltm"] = df["dl_fin_ltm"] + df["div_arr_ltm"]           # com arrendamentos
    pos = df["ebitda_ltm"] > 0
    df["dl_ebitda_sem_arr"] = np.where(pos, df["dl_fin_ltm"] / df["ebitda_ltm"], np.nan)
    df["dl_ebitda_com_arr"] = np.where(pos, df["dl_total_ltm"] / df["ebitda_ltm"], np.nan)
    df["p_l"] = np.where(df["ll_ltm"] > 0, df["valor_mercado"] / df["ll_ltm"], np.nan)
    df["p_vp"] = np.where(df["pl_ctrl_ltm"] > 0, df["valor_mercado"] / df["pl_ctrl_ltm"], np.nan)
    df["roe_ltm"] = df["ll_ltm"] / df["pl_ctrl_ltm"]
    df["dy_12m"] = df["div_12m_p"] / df["preco_p"]
    df["payout_12m"] = df["dy_12m"] * df["valor_mercado"] / df["ll_ltm"]

    df = df.rename(columns={c: c[:-2] for c in df.columns if c.endswith("_p") and c != "ll_p"})
    df.to_csv(OUT / "b3_dataset.csv")
    print("Gravado:", OUT / "b3_dataset.csv", df.shape)
    print(df[["ticker", "preco", "valor_mercado", "ll_2025", "ll_ltm", "dl_ebitda_com_arr", "ret_12m"]]
          .sort_values("valor_mercado", ascending=False).head(10).to_string())
    checagens(df)

    # validação: lucros anuais da Renner segundo agregadores (Suno/HG Brasil), em R$ milhões
    ref = {"ll_2021": 633.11, "ll_2022": 1291.70, "ll_2023": 976.26, "ll_2024": 1196.67, "ll_2025": 1457.57}
    x = df[df["ticker"] == "LREN3"]
    if len(x):
        print("\nValidação com LREN3 (lucro controladores, R$ mi): calculado vs referência")
        for k, v in ref.items():
            print(f"  {k}: {x.iloc[0][k] / 1e6:10,.1f} vs {v:10,.1f}")
    else:
        print("\nLREN3 não está no dataset: confira os passos 1 a 3.")


if __name__ == "__main__":
    main()
