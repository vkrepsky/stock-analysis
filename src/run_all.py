"""Roda o pipeline inteiro com um comando: 01 -> 02 -> 03 -> 04 -> 05.

Uso:
    python src/run_all.py                 # tudo
    python src/run_all.py --de 4          # recomeça do passo 4 (reaproveita o que já foi gerado)
    python src/run_all.py --ate 2         # só baixa e calcula fundamentos
    python src/run_all.py --so 5          # só um passo

Para no primeiro passo que falhar. Os downloads usam cache em data/raw.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
PASSOS = {
    1: "01_baixar_cvm.py",
    2: "02_fundamentos.py",
    3: "03_precos.py",
    4: "04_consolidar.py",
    5: "05_triagem.py",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--de", type=int, default=1, help="primeiro passo (1-5)")
    ap.add_argument("--ate", type=int, default=5, help="último passo (1-5)")
    ap.add_argument("--so", type=int, help="roda apenas este passo")
    a = ap.parse_args()
    de, ate = (a.so, a.so) if a.so else (a.de, a.ate)

    for n in range(de, ate + 1):
        print(f"\n{'=' * 70}\nPASSO {n}: {PASSOS[n]}\n{'=' * 70}", flush=True)
        t0 = time.time()
        r = subprocess.run([sys.executable, str(SRC / PASSOS[n])])
        if r.returncode != 0:
            sys.exit(f"\nPasso {n} falhou (código {r.returncode}). Corrija e rode: python src/run_all.py --de {n}")
        print(f"-- passo {n} ok em {time.time() - t0:.0f}s", flush=True)
    print("\nPipeline concluído. Saídas em data/out/")


if __name__ == "__main__":
    main()
