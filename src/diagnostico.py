"""Diagnóstico: mostra as linhas BRUTAS da CVM de uma empresa (consolidado e individual, todas as versões),
sem a escolha con/ind e de versão que o pipeline faz. Serve para investigar números estranhos.

Uso:  python src/diagnostico.py <parte do nome da empresa> [ano]
Ex.:  python src/diagnostico.py TIM 2025
"""
import re
import sys
import zipfile

import pandas as pd

from common import RAW

CONTAS = ["3.01", "3.05", "3.11", "3.11.01", "3.11.02", "7.04.01"]
COLS = ["DENOM_CIA", "consol", "VERSAO", "ORDEM_EXERC", "DT_REFER", "ESCALA_MOEDA", "CD_CONTA", "DS_CONTA", "VL_CONTA"]


def main():
    nome = sys.argv[1].upper()
    ano = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
    zp = RAW / "cvm" / f"dfp_{ano}.zip"
    with zipfile.ZipFile(zp) as z:
        for tipo in ("DRE", "DVA"):
            todas, resumo = [], []
            for arq in z.namelist():
                m = re.search(rf"_{tipo}_(con|ind)_\d{{4}}\.csv$", arq, flags=re.I)
                if not m:
                    continue
                with z.open(arq) as f:
                    d = pd.read_csv(f, sep=";", encoding="latin1", dtype=str)
                d = d[d["DENOM_CIA"].str.upper().str.contains(nome, na=False)].assign(consol=m.group(1).lower())
                valores = pd.to_numeric(d["VL_CONTA"].str.replace(",", ".", regex=False), errors="coerce").fillna(0)
                for (emp, ver), g in d.groupby(["DENOM_CIA", "VERSAO"]):
                    resumo.append((emp, m.group(1).lower(), ver, len(g), int((valores.loc[g.index] != 0).sum())))
                todas.append(d[d["CD_CONTA"].isin(CONTAS)])
            print(f"\n=== {tipo}: linhas totais / com valor diferente de zero, por empresa, consolidado/individual e versão")
            print(pd.DataFrame(resumo, columns=["empresa", "consol", "versao", "linhas", "nao_zero"]).to_string(index=False))
            if todas:
                with pd.option_context("display.width", 250, "display.max_colwidth", 45):
                    print(pd.concat(todas)[COLS].to_string(index=False))


if __name__ == "__main__":
    main()
