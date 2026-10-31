"""Diagnóstico: mostra as linhas brutas da CVM de uma empresa (para investigar números estranhos).

Uso:  python src/diagnostico.py <parte do nome da empresa> [ano]
Ex.:  python src/diagnostico.py KLABIN 2025
"""
import sys

from common import RAW
from cvm_lib import ler_demonstracao

nome = sys.argv[1].upper()
ano = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
zp = RAW / "cvm" / f"dfp_{ano}.zip"

import pandas as pd  # noqa: E402

for tipo in ("DRE", "DVA"):
    df = ler_demonstracao(zp, tipo)
    d = df[df["DENOM_CIA"].str.upper().str.contains(nome, na=False)]
    print(f"\n=== {tipo}: {d['DENOM_CIA'].nunique()} empresa(s): {sorted(d['DENOM_CIA'].unique())}")
    cols = ["DENOM_CIA", "consol", "VERSAO", "ORDEM_EXERC", "DT_INI_EXERC", "DT_FIM_EXERC", "CD_CONTA", "DS_CONTA", "VL_CONTA"]
    filtro = d["CD_CONTA"].isin(["3.01", "3.05", "3.11", "3.11.01", "3.11.02", "7.04.01"])
    with pd.option_context("display.width", 250, "display.max_colwidth", 45):
        print(d.loc[filtro, cols].to_string(index=False))
