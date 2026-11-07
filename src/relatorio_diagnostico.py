"""Relatório de diagnóstico ENXUTO para enviar ao Claude no lugar da pasta data/.

Gera data/out/relatorio_diagnostico.md só com exceções e resumos: campos mal cobertos, lucros
zerados, causas de dívida/EBITDA vazio, linhas brutas da CVM apenas das empresas-problema,
units suspeitas, checagens de consistência e contagens da triagem. Não altera nenhum dado.

Uso:  python src/relatorio_diagnostico.py
"""
import traceback

import numpy as np
import pandas as pd

from common import ANOS_DFP, OUT, RAW
from cvm_lib import ler_demonstracao

CAMPOS = ["ll_2025", "ll_ltm", "receita_ltm", "ebit_ltm", "da_ltm", "ebitda_ltm", "caixa_ltm", "div_fin_ltm",
          "div_arr_ltm", "pl_ctrl_ltm", "acoes_on", "valor_mercado", "preco", "ret_12m",
          "dl_ebitda_com_arr", "p_l", "p_vp", "dy_12m"]
EXTRA_RAW = ["TIM S.A", "KLABIN", "SABESP", "SUZANO", "PRIO"]   # sempre investigadas
MAX_LINHAS = 12          # limite de linhas por tabela
MAX_RAW = 6              # empresas-problema com linhas brutas
SAIDA = []


def txt(s=""):
    SAIDA.append(str(s))


def mi(s):
    """R$ -> R$ milhões, 0 casas."""
    return (s / 1e6).round(0)


def tabela(d, n=MAX_LINHAS):
    resto = len(d) - n
    with pd.option_context("display.width", 200, "display.max_colwidth", 28, "display.max_columns", 30):
        SAIDA.append("```\n" + d.head(n).round(2).to_string() + (f"\n... (+{resto} linhas)" if resto > 0 else "") + "\n```")


def secao(titulo):
    """Cada seção roda isolada; erro vira texto no relatório, não derruba o resto."""
    def deco(f):
        txt(f"\n## {titulo}")
        try:
            f()
        except Exception:  # noqa: BLE001
            txt("ERRO nesta seção:\n```\n" + traceback.format_exc(limit=-2) + "\n```")
        return f
    return deco


def carregar():
    df = pd.read_csv(OUT / "b3_dataset.csv", dtype={"cnpj": str}).set_index("cnpj")
    df["setor"] = df["SETOR_ATIV"] if "SETOR_ATIV" in df else ""
    fin = df["setor"].fillna("").str.contains(r"Banco|Intermedia[cç][aã]o Financeira|Seguradora|Previd", case=False, regex=True)
    df["_nf"] = ~fin & (df["liq_total_90d"] >= 5e6)      # não financeira líquida
    return df


def linhas_brutas(zp, tipo, nome, prefixos, termos=None):
    d = ler_demonstracao(zp, tipo)
    d = d[(d["ORDEM_EXERC"] == "ÚLTIMO") & d["DENOM_CIA"].str.upper().str.contains(nome, na=False)]
    m = d["CD_CONTA"].str.startswith(tuple(prefixos))
    if termos:
        m |= d["DS_CONTA"].str.contains(termos, case=False, regex=True, na=False)
    d = d.loc[m].assign(tipo=tipo, VL_mi=lambda x: (x["VL_CONTA"] / 1e6).round(1))
    return d[["DENOM_CIA", "tipo", "consol", "ESCALA_MOEDA", "VERSAO", "CD_CONTA", "DS_CONTA", "VL_mi"]]


def main():
    df = carregar()
    nf = df[df["_nf"]]
    txt(f"# Diagnóstico B3 ({pd.Timestamp.today().date()})\n\nEmpresas: {len(df)} | não financeiras líquidas: {len(nf)}")

    @secao("1. Campos com cobertura < 95% (não financeiras líquidas)")
    def _():
        s = pd.DataFrame({c: [100 * nf[c].notna().mean(), 100 * (nf[c].fillna(0) != 0).mean()]
                          for c in CAMPOS if c in nf}, index=["%preench", "%não_zero"]).T
        s = s[(s["%preench"] < 95) | (s["%não_zero"] < 95)].round(0)
        if s.empty:
            txt("Todos os campos-chave >= 95%.")
        else:
            tabela(s.sort_values("%preench"), 25)

    @secao("2. Lucros exatamente zero")
    def _():
        cols = [c for c in df if c.startswith("ll_")]
        z = df[(df[cols] == 0).any(axis=1)]
        txt(f"{len(z)} empresas.")
        if len(z):
            z = z.assign(anos_zero=[", ".join(c[3:] for c in cols if z.at[i, c] == 0) for i in z.index])
            tabela(z[["ticker", "anos_zero"]])

    @secao("3. Dívida/EBITDA (com arrendamentos) vazio")
    def _():
        d = nf[nf["dl_ebitda_com_arr"].isna()]
        n_ok = len(nf) - len(d)
        txt(f"Cobertura: {n_ok}/{len(nf)} = {100 * n_ok / max(len(nf), 1):.0f}% (meta > 90%). Vazias: {len(d)}.")
        causas = pd.Series({
            "sem EBIT": int(d["ebit_ltm"].isna().sum()),
            "sem D&A": int(d["da_ltm"].isna().sum()),
            "sem caixa": int(d["caixa_ltm"].isna().sum()),
            "sem dívida fin.": int(d["div_fin_ltm"].isna().sum()),
            "EBITDA <= 0": int((d["ebitda_ltm"] <= 0).sum()),
        })
        txt("Causas (podem se sobrepor): " + "; ".join(f"{k}={v}" for k, v in causas.items()))
        x = d.sort_values("valor_mercado", ascending=False)
        x = x.assign(vm_mi=mi(x["valor_mercado"]), ebit_mi=mi(x["ebit_ltm"]), da_mi=mi(x["da_ltm"]), caixa_mi=mi(x["caixa_ltm"]))
        tabela(x[["ticker", "vm_mi", "ebit_mi", "da_mi", "caixa_mi"]])

    @secao("4. Linhas brutas da CVM (DFP 2025) das empresas-problema")
    def _():
        zp = RAW / "cvm" / f"dfp_{ANOS_DFP[-1]}.zip"
        alvos = list(EXTRA_RAW)
        for n in df[(df.filter(like="ll_").fillna(1) == 0).any(axis=1) | (df["_nf"] & df["dl_ebitda_com_arr"].isna())] \
                .sort_values("valor_mercado", ascending=False)["DENOM_SOCIAL"].astype(str).head(MAX_RAW):
            alvos.append(n.upper()[:25])
        vistos = []
        for nome in alvos[:MAX_RAW + len(EXTRA_RAW)]:
            if any(nome in v or v in nome for v in vistos):
                continue
            vistos.append(nome)
            blocos = []
            for tipo, pref, termo in (("DRE", ("3.05", "3.11"), None), ("DVA", ("7.04.01",), None),
                                      ("DFC_MD", (), r"deprecia|amortiza"), ("DFC_MI", (), r"deprecia|amortiza")):
                try:
                    r = linhas_brutas(zp, tipo, nome, pref, termo)
                except FileNotFoundError:
                    continue
                if len(r):
                    blocos.append(r)
            if blocos:
                txt(f"**{nome}**")
                tabela(pd.concat(blocos), 14)

    @secao("5. Units sem proporção 1:1 óbvia ou com valor divergente do Yahoo")
    def _():
        u = df[df["mcap_fonte"] == "unit_x_acoes_on"].copy()
        u["razao_vs_yahoo"] = u["valor_mercado"] / u["mcap_yahoo"]
        u["pn_por_on"] = u["acoes_pn"].fillna(0) / u["acoes_on"]
        sus = u[(u["pn_por_on"] > 0.01) | (u["mcap_divergente"].fillna(False).astype(bool))]
        txt(f"{len(u)} empresas com valor de mercado por unit; {len(sus)} suspeitas (têm PN ou divergem do Yahoo).")
        sus = sus.assign(vm_mi=mi(sus["valor_mercado"]), on_mi=(sus["acoes_on"] / 1e6).round(0), pn_mi=(sus["acoes_pn"] / 1e6).round(0))
        tabela(sus[["ticker", "preco", "on_mi", "pn_mi", "vm_mi", "razao_vs_yahoo"]], 20)

    @secao("6. Tickers sem dados no Yahoo")
    def _():
        tk = pd.read_csv(OUT / "tickers.csv", dtype=str)
        px = pd.read_csv(OUT / "precos_resumo.csv")
        falta = tk[~tk["ticker"].isin(px["ticker"])]
        txt(f"{len(falta)} de {len(tk)}: {' '.join(falta['ticker'].head(60))}")

    @secao("7. Checagens de consistência (contagem + até 4 exemplos)")
    def _():
        achados = {}

        def marca(nome, mask):
            idx = df.index[mask.fillna(False)]
            if len(idx):
                achados[nome] = [str(df.at[i, "ticker"]) for i in idx]

        marca("lucro LTM > receita LTM", df["ll_ltm"] > df["receita_ltm"].abs())
        marca("|lucro| > R$ 200 bi (escala?)", df["ll_ltm"].abs() > 2e11)
        marca("dívida financeira < 0 (arrendamento > dívida total)", df["div_fin_ltm"] < 0)
        marca("valor de mercado > R$ 1 tri", df["valor_mercado"] > 1e12)
        marca("P/L < 1", df["p_l"] < 1)
        marca("DY > 30%", df["dy_12m"] > 0.30)
        marca("ações ON+PN = 0", (df["acoes_on"].fillna(0) + df["acoes_pn"].fillna(0)) <= 0)
        marca("P/L ou P/VP < 0,05 (escala das ações; deveria ser 0)", (df["p_l"] < 0.05) | (df["p_vp"] < 0.05))
        if "escala_duvidosa" in df:
            marca("valor de mercado anulado (escala duvidosa; sem P/L e P/VP)", df["escala_duvidosa"].astype(bool))
        if "acoes_em_mil" in df:
            marca("ações em milhares na CVM, corrigidas x1000 (informativo)", df["acoes_em_mil"].astype(bool))
        marca("EBITDA < EBIT (D&A negativa)", df["ebitda_ltm"] < df["ebit_ltm"])
        try:   # exercício que não é de 12 meses terminando em dezembro
            d = ler_demonstracao(RAW / "cvm" / f"dfp_{ANOS_DFP[-1]}.zip", "DRE")
            d = d[d["ORDEM_EXERC"] == "ÚLTIMO"].drop_duplicates("CNPJ_CIA")
            dur = (d["DT_FIM_EXERC"] - d["DT_INI_EXERC"]).dt.days
            atip = d[(d["DT_FIM_EXERC"].dt.month != 12) | (dur < 350) | (dur > 380)]
            if len(atip):
                achados["ano fiscal atípico (DFP 2025)"] = [f"{n[:18]}" for n in atip["DENOM_CIA"]]
        except Exception as e:  # noqa: BLE001
            achados["ano fiscal: não verificado"] = [str(e)[:60]]
        if not achados:
            txt("Nenhuma ocorrência.")
        for k, v in achados.items():
            txt(f"- {k}: **{len(v)}** ({', '.join(v[:4])}{'…' if len(v) > 4 else ''})")

    @secao("8. Renner (LREN3), R$ mi: calculado vs referência")
    def _():
        ref = {"ll_2021": 633.11, "ll_2022": 1291.70, "ll_2023": 976.26, "ll_2024": 1196.67, "ll_2025": 1457.57}
        x = df[df["ticker"] == "LREN3"]
        if x.empty:
            txt("LREN3 ausente.")
            return
        x = x.iloc[0]
        txt(" | ".join(f"{k[3:]}: {x[k] / 1e6:,.1f} (ref {v:,.1f})" for k, v in ref.items()))
        txt(f"LTM: lucro {x['ll_ltm'] / 1e6:,.0f} (esperado ~1.490); caixa líquido {-x['dl_total_ltm'] / 1e6:,.0f} com arr. / "
            f"{-x['dl_fin_ltm'] / 1e6:,.0f} sem arr. (esperado ~1.160)")

    @secao("9. Hipóteses de sanidade: critérios que cada uma falha")
    def _():
        tc = pd.read_csv(OUT / "triagem_completa.csv", dtype={"cnpj": str}).set_index("cnpj")
        hip = ["VIVA3", "GRND3", "VULC3", "TFCO4", "CURY3", "DIRR3", "EZTC3", "LREN3"]
        ok = [c for c in tc if c.startswith("ok_")]
        x = tc[tc["ticker"].isin(hip)].set_index("ticker")
        r = pd.DataFrame({"falha": [", ".join(c[3:] for c in ok if not x.at[t, c]) or "nenhum" for t in x.index]}, index=x.index)
        tabela(r.join(x[[c for c in ("ret_12m", "dist_max_52w", "dl_ebitda_com_arr") if c in x]]))
        faltam = [t for t in hip if t not in x.index]
        if faltam:
            txt("Fora do dataset: " + ", ".join(faltam))

    @secao("10. Triagem")
    def _():
        tc = pd.read_csv(OUT / "triagem_completa.csv", dtype={"cnpj": str}).set_index("cnpj")
        txt("Passam por filtro: " + "; ".join(f"{c[3:]}={int(tc[c].sum())}" for c in tc if c.startswith("ok_")))
        for arq in ("aprovadas.csv", "quase_aprovadas.csv"):
            a = pd.read_csv(OUT / arq)
            txt(f"**{arq}**: {len(a)}")
            if len(a):
                tabela(a[[c for c in ("ticker", "ret_12m", "dl_ebitda_com_arr", "p_l", "p_vp", "dy_12m", "score", "falhou") if c in a]], 40)

    @secao("11. Lucro por ano (R$ mi) das quase aprovadas que só falham em lucro_estavel")
    def _():
        q = pd.read_csv(OUT / "quase_aprovadas.csv", dtype={"cnpj": str})
        q = q[q["falhou"] == "lucro_estavel"].set_index("ticker")
        cols = [f"ll_{a}" for a in ANOS_DFP] + ["ll_ltm"]
        if q.empty:
            txt("Nenhuma.")
            return
        tabela(q[cols].apply(mi), 25)

    destino = OUT / "relatorio_diagnostico.md"
    destino.write_text("\n".join(SAIDA), encoding="utf-8")
    print(f"Gravado: {destino} ({destino.stat().st_size / 1e3:.0f} KB). Envie este arquivo + o log do terminal ao Claude.")


if __name__ == "__main__":
    main()
