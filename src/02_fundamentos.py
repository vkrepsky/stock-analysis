"""Passo 2: lê os zips da CVM e monta data/out/fundamentos.csv (1 linha por empresa).

Anos 2021-2025 (DFP): lucro atribuível aos controladores (ll), receita, EBIT, D&A (da, vem da DVA),
caixa, dívida financeira (div_fin, sem arrendamentos), arrendamentos (div_arr, em todo o passivo), PL dos
controladores e ativo. LTM: último ITR do ano corrente
(12 meses = exercício anterior + acumulado atual - acumulado do ano anterior).

Valores em R$. Uso:  python src/02_fundamentos.py
"""
import zipfile

import pandas as pd

from common import ANO_ITR, ANOS_DFP, OUT, RAW
from cvm_lib import ler_demonstracao, passivo_arrendamento, serie

ULT, PEN = "ÚLTIMO", "PENÚLTIMO"
EH_ARR = r"arrendamento|leasing|direitos? de uso"
CODIGOS = {"receita": "3.01", "ebit": "3.05"}


def combina(*ss):
    """Soma séries tratando NaN como 0, mas devolvendo NaN se todas faltarem."""
    return pd.concat(ss, axis=1).sum(axis=1, min_count=1)


def lucro_controladores(dre):
    """Lucro atribuível aos controladores (3.11.01).

    Algumas empresas só preenchem o total (3.11) e deixam 3.11.01 e 3.11.02 em 0 (ex.: Klabin, Sabesp):
    pegar o 0 como se fosse o lucro zerava o resultado. Nesse caso (ou se 3.11.01 faltar), vale
    3.11 - 3.11.02 (total menos minoritários).
    """
    t = pd.DataFrame({"ctrl": serie(dre, "3.11.01"), "nc": serie(dre, "3.11.02"), "total": serie(dre, "3.11")})
    sem_ctrl = t["ctrl"].isna() | ((t["ctrl"] == 0) & (t["total"].fillna(0) != 0))
    return t["ctrl"].where(~sem_ctrl, t["total"] - t["nc"].fillna(0))


def extrair(nome, df):
    """Conta `nome` por empresa; df já filtrado por período/ordem. D&A em módulo."""
    if nome == "ll":
        return lucro_controladores(df)
    if nome == "da":  # a DVA lança a depreciação (7.04.01) como retenção, ou seja, NEGATIVA
        return serie(df, "7.04.01").abs()
    return serie(df, CODIGOS[nome])


def balanco(zp):
    """Posição patrimonial (ORDEM ÚLTIMO) na data mais recente de cada empresa."""
    bpa, bpp = (ler_demonstracao(zp, t) for t in ("BPA", "BPP"))
    ultimos = []
    for df in (bpa, bpp):
        df = df[df["ORDEM_EXERC"] == ULT]
        ultimos.append(df[df["DT_REFER"] == df.groupby("CNPJ_CIA")["DT_REFER"].transform("max")])
    bpa, bpp = ultimos
    arr = passivo_arrendamento(bpp, EH_ARR)
    res = pd.DataFrame({
        "dt_balanco": bpa.groupby("CNPJ_CIA")["DT_REFER"].max(),
        "caixa": combina(serie(bpa, "1.01.01"), serie(bpa, "1.01.02")),
        "div_total": combina(serie(bpp, "2.01.04"), serie(bpp, "2.02.01")),
        "div_arr": arr["arr"],
        "arr_em_divida": arr["arr_em_divida"],
        "pl_total": serie(bpp, "2.03"),
        "pl_nc": serie(bpp, "2.03.09"),
        "ativo": serie(bpa, "1"),
    })
    res[["div_arr", "arr_em_divida"]] = res[["div_arr", "arr_em_divida"]].fillna(0.0)
    res["div_fin"] = res["div_total"] - res["arr_em_divida"]    # arrendamento fora de 2.01.04/2.02.01 não está em div_total
    res["pl_ctrl"] = res["pl_total"] - res["pl_nc"].fillna(0.0)
    return res.drop(columns=["div_total", "pl_total", "pl_nc", "arr_em_divida"])


def resultado_anual(zp):
    dre = ler_demonstracao(zp, "DRE")
    dre = dre[dre["ORDEM_EXERC"] == ULT]
    dva = ler_demonstracao(zp, "DVA")
    dva = dva[dva["ORDEM_EXERC"] == ULT]
    return pd.DataFrame({
        "ll": extrair("ll", dre),
        "receita": extrair("receita", dre),
        "ebit": extrair("ebit", dre),
        "da": extrair("da", dva),
    })


def resultado_ltm(zp, fy):
    """12 meses até o último ITR: `fy` (exercício anterior) + acumulado atual - acumulado anterior."""
    dre, dva = ler_demonstracao(zp, "DRE"), ler_demonstracao(zp, "DVA")
    res = pd.DataFrame(index=fy.index)
    res["dt_ltm"] = dre.groupby("CNPJ_CIA")["DT_REFER"].max()

    def acumulado(df, ordem):
        df = df[df["DT_REFER"] == df.groupby("CNPJ_CIA")["DT_REFER"].transform("max")]
        inicio_ano = (df["DT_INI_EXERC"].dt.month == 1) & (df["DT_INI_EXERC"].dt.day == 1)
        return df[(df["ORDEM_EXERC"] == ordem) & inicio_ano]

    for nome, df in {"ll": dre, "receita": dre, "ebit": dre, "da": dva}.items():
        atual = extrair(nome, acumulado(df, ULT))
        anterior = extrair(nome, acumulado(df, PEN))
        res[f"{nome}_ltm"] = fy[nome] + atual - anterior
    return res


def capital(zp):
    """Ações ON e PN (sem tesouraria) na data mais recente do zip."""
    with zipfile.ZipFile(zp) as z:
        nome = next(n for n in z.namelist() if "composicao_capital" in n.lower())
        with z.open(nome) as f:
            d = pd.read_csv(f, sep=";", encoding="latin1", dtype=str)
    qt = [c for c in d.columns if c.startswith("QT_ACAO")]
    d[qt] = d[qt].apply(pd.to_numeric, errors="coerce")
    d["VERSAO"] = pd.to_numeric(d["VERSAO"], errors="coerce")
    d["DT_REFER"] = pd.to_datetime(d["DT_REFER"], errors="coerce")
    d = d[d["DT_REFER"] == d.groupby("CNPJ_CIA")["DT_REFER"].transform("max")]
    d = d[d["VERSAO"] == d.groupby("CNPJ_CIA")["VERSAO"].transform("max")]
    d = d.drop_duplicates("CNPJ_CIA").set_index("CNPJ_CIA")
    return pd.DataFrame({
        "acoes_on": d["QT_ACAO_ORDIN_CAP_INTEGR"] - d["QT_ACAO_ORDIN_TESOURO"].fillna(0),
        "acoes_pn": d["QT_ACAO_PREF_CAP_INTEGR"] - d["QT_ACAO_PREF_TESOURO"].fillna(0),
    })


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cad = pd.read_csv(RAW / "cvm" / "cad_cia_aberta.csv", sep=";", encoding="latin1", dtype=str)
    manter = [c for c in ("CNPJ_CIA", "DENOM_SOCIAL", "CD_CVM", "SETOR_ATIV", "SIT", "SIT_EMISSOR") if c in cad]
    cad = cad[manter].drop_duplicates("CNPJ_CIA").set_index("CNPJ_CIA")

    por_ano = {}
    for ano in ANOS_DFP:
        zp = RAW / "cvm" / f"dfp_{ano}.zip"
        por_ano[ano] = resultado_anual(zp).join(balanco(zp), how="outer")
        print(f"DFP {ano}: {len(por_ano[ano])} empresas")

    zi = RAW / "cvm" / f"itr_{ANO_ITR}.zip"
    ltm = resultado_ltm(zi, por_ano[ANOS_DFP[-1]]).join(balanco(zi).add_suffix("_ltm"), how="outer")
    print(f"ITR {ANO_ITR}: {len(ltm)} empresas")

    fund = pd.concat([por_ano[a].add_suffix(f"_{a}") for a in ANOS_DFP] + [ltm], axis=1)
    fund = cad.join(fund, how="right").join(capital(zi))
    fund.index.name = "cnpj"
    fund.to_csv(OUT / "fundamentos.csv")
    print("Gravado:", OUT / "fundamentos.csv", fund.shape)


if __name__ == "__main__":
    main()
