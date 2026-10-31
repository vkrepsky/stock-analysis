"""Leitura dos zips da CVM (DFP/ITR): cada zip tem vários CSVs separados por ';' em latin1."""
import re
import zipfile

import pandas as pd


def ler_demonstracao(zip_path, tipo):
    """Junta os CSVs de `tipo` (DRE, BPA, BPP, DVA) de um zip.

    - valores em R$ (aplica ESCALA_MOEDA);
    - só a última VERSAO de cada empresa/data de referência;
    - usa o consolidado quando a empresa tem; senão, o individual.
    """
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
    df["VL_CONTA"] *= df["ESCALA_MOEDA"].str.upper().map({"MIL": 1000.0}).fillna(1.0)
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


def soma_filhas(df, padrao_cd, padrao_ds):
    """Soma VL_CONTA das contas cujo código bate com `padrao_cd` e a descrição com `padrao_ds`."""
    m = df["CD_CONTA"].str.match(padrao_cd) & df["DS_CONTA"].str.contains(
        padrao_ds, case=False, regex=True, na=False
    )
    return df.loc[m].groupby("CNPJ_CIA")["VL_CONTA"].sum()
