"""Leitura dos zips da CVM (DFP/ITR): cada zip tem vários CSVs separados por ';' em latin1."""
import re
import zipfile
from pathlib import Path

import pandas as pd

ESCALAS = {"MIL": 1000.0, "UNIDADE": 1.0}
_AVISADAS = set()


def ler_demonstracao(zip_path, tipo):
    """Junta os CSVs de `tipo` (DRE, BPA, BPP, DVA) de um zip.

    - valores em R$ (aplica ESCALA_MOEDA);
    - só a última VERSAO de cada empresa/data de referência;
    - usa o consolidado quando a empresa tem; senão, o individual.
    """
    zip_path = Path(zip_path)
    quadros = []
    with zipfile.ZipFile(zip_path) as z:
        for nome in z.namelist():
            m = re.search(rf"_{tipo}_(con|ind)_\d{{4}}\.csv$", nome, flags=re.I)
            if m:
                with z.open(nome) as f:
                    d = pd.read_csv(f, sep=";", encoding="latin1", dtype=str)
                d["consol"] = m.group(1).lower()
                quadros.append(d)
    if not quadros:
        raise FileNotFoundError(f"sem arquivos {tipo} em {zip_path}")
    df = pd.concat(quadros, ignore_index=True)
    df["VL_CONTA"] = pd.to_numeric(df["VL_CONTA"].str.replace(",", ".", regex=False), errors="coerce")
    escala = df["ESCALA_MOEDA"].str.upper()
    novas = set(escala.dropna()) - set(ESCALAS) - _AVISADAS
    if novas:  # qualquer outra escala seria lida como R$ unidade (valor ~1000x ou 1.000.000x menor)
        _AVISADAS.update(novas)
        print(f"  ATENÇÃO: ESCALA_MOEDA desconhecida em {zip_path.name}: {sorted(novas)} (tratada como unidade)")
    df["VL_CONTA"] *= escala.map(ESCALAS).fillna(1.0)
    for c in ("DT_REFER", "DT_INI_EXERC", "DT_FIM_EXERC"):
        if c in df:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    df["VERSAO"] = pd.to_numeric(df["VERSAO"], errors="coerce").fillna(0)
    tem_con = df.loc[df["consol"] == "con", "CNPJ_CIA"].unique()
    df = df[(df["consol"] == "con") | (~df["CNPJ_CIA"].isin(tem_con))]
    vmax = df.groupby(["CNPJ_CIA", "DT_REFER"])["VERSAO"].transform("max")
    return df[df["VERSAO"] == vmax].reset_index(drop=True)


def serie(df, codigo):
    """VL_CONTA da conta `codigo` por empresa (df já filtrado por período/ordem)."""
    s = df.loc[df["CD_CONTA"] == codigo].drop_duplicates("CNPJ_CIA")
    return s.set_index("CNPJ_CIA")["VL_CONTA"]


def passivo_arrendamento(bpp, padrao_ds):
    """Passivo de arrendamento (IFRS 16/leasing) por empresa, olhando TODO o passivo 2.01.* e 2.02.*.

    Muitas empresas (a Renner, por exemplo) lançam o arrendamento em "outras obrigações" e não dentro
    de empréstimos, então procurar só nas filhas de 2.01.04/2.02.01 deixava a conta zerada.
    As contas agregadas 2.01.04 e 2.02.01 são ignoradas (uma conta "Empréstimos, financiamentos e
    arrendamentos" não é toda arrendamento) e, se uma conta e sua filha casam, vale só a de cima.

    Devolve `arr` (total) e `arr_em_divida` (a parte que está dentro de 2.01.04/2.02.01: já entra na dívida
    bruta e por isso sai dela para não contar duas vezes).
    """
    m = (
        bpp["CD_CONTA"].str.match(r"^2\.0[12]\.\d+(\.\d+)*$")
        & ~bpp["CD_CONTA"].isin(["2.01.04", "2.02.01"])
        & bpp["DS_CONTA"].str.contains(padrao_ds, case=False, regex=True, na=False)
    )
    d = bpp.loc[m, ["CNPJ_CIA", "CD_CONTA", "VL_CONTA"]].drop_duplicates(["CNPJ_CIA", "CD_CONTA"])
    codigos = d.groupby("CNPJ_CIA")["CD_CONTA"].agg(set).to_dict()
    topo = [not any(c.startswith(o + ".") for o in codigos[k]) for k, c in zip(d["CNPJ_CIA"], d["CD_CONTA"])]
    d = d[topo]
    dentro = d["CD_CONTA"].str.match(r"^2\.(01\.04|02\.01)\.")
    return pd.DataFrame({
        "arr": d.groupby("CNPJ_CIA")["VL_CONTA"].sum(),
        "arr_em_divida": d[dentro].groupby("CNPJ_CIA")["VL_CONTA"].sum(),
    })
