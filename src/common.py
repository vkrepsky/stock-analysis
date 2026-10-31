"""Caminhos, parâmetros e utilitários compartilhados pelo pipeline."""
from pathlib import Path
import time

import requests

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "data" / "raw"
OUT = BASE / "data" / "out"

CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA"
ANOS_DFP = [2021, 2022, 2023, 2024, 2025]   # balanços anuais (lucro de 2021 a 2025)
ANO_ITR = 2026                               # trimestrais do ano corrente (para o LTM)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) pesquisa-b3/1.0"}


def baixar(url, destino, tentativas=3):
    """Baixa url para destino (com cache). Retorna o Path ou None se falhar."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and destino.stat().st_size > 0:
        print(f"  já existe: {destino.name}")
        return destino
    for i in range(1, tentativas + 1):
        try:
            r = requests.get(url, headers=UA, timeout=180, stream=True)
            r.raise_for_status()
            with open(destino, "wb") as f:
                for pedaco in r.iter_content(1 << 20):
                    f.write(pedaco)
            print(f"  baixado: {destino.name} ({destino.stat().st_size/1e6:.1f} MB)")
            return destino
        except Exception as e:  # noqa: BLE001
            print(f"  falha {i}/{tentativas} em {url}: {e}")
            time.sleep(3 * i)
    destino.unlink(missing_ok=True)
    print(f"  NÃO BAIXOU: {url}")
    return None
