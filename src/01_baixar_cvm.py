"""Passo 1: baixa os dados abertos da CVM (cadastro, tickers, DFP anual, ITR do ano corrente).

Uso:  python src/01_baixar_cvm.py
Os arquivos ficam em data/raw/cvm/ e o script pode ser repetido (usa cache).
"""
import sys

from common import ANO_ITR, ANOS_DFP, CVM, RAW, baixar

DEST = RAW / "cvm"


def main():
    falhou = []

    def pegar(url, destino):
        if not baixar(url, destino):
            falhou.append(destino.name)

    print("Cadastro de companhias abertas")
    pegar(f"{CVM}/CAD/DADOS/cad_cia_aberta.csv", DEST / "cad_cia_aberta.csv")

    print("FCA (códigos de negociação) - tenta o ano corrente e cai para o anterior")
    if not any(baixar(f"{CVM}/DOC/FCA/DADOS/fca_cia_aberta_{ano}.zip", DEST / f"fca_{ano}.zip")
               for ano in (ANO_ITR, ANO_ITR - 1, ANO_ITR - 2)):
        falhou.append("fca_*.zip")

    print("DFP (demonstrações anuais)")
    for ano in ANOS_DFP:
        pegar(f"{CVM}/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip", DEST / f"dfp_{ano}.zip")

    print("ITR (trimestrais do ano corrente; traz o comparativo do ano anterior)")
    pegar(f"{CVM}/DOC/ITR/DADOS/itr_cia_aberta_{ANO_ITR}.zip", DEST / f"itr_{ANO_ITR}.zip")

    if falhou:  # sem isso o pipeline seguia e quebrava (ou usava dado velho) vários passos depois
        sys.exit(f"\nNÃO BAIXOU: {', '.join(falhou)}. Rode o passo 1 de novo: python src/run_all.py --so 1")
    print("\nConcluído: todos os arquivos da CVM estão em data/raw/cvm.")


if __name__ == "__main__":
    main()
