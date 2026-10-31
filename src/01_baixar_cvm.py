"""Passo 1: baixa os dados abertos da CVM (cadastro, tickers, DFP anual, ITR do ano corrente).

Uso:  python src/01_baixar_cvm.py
Os arquivos ficam em data/raw/cvm/ e o script pode ser repetido (usa cache).
"""
from common import ANO_ITR, ANOS_DFP, CVM, RAW, baixar

DEST = RAW / "cvm"


def main():
    print("Cadastro de companhias abertas")
    baixar(f"{CVM}/CAD/DADOS/cad_cia_aberta.csv", DEST / "cad_cia_aberta.csv")

    print("FCA (códigos de negociação) - tenta o ano corrente e cai para o anterior")
    for ano in (ANO_ITR, ANO_ITR - 1, ANO_ITR - 2):
        if baixar(f"{CVM}/DOC/FCA/DADOS/fca_cia_aberta_{ano}.zip", DEST / f"fca_{ano}.zip"):
            break

    print("DFP (demonstrações anuais)")
    for ano in ANOS_DFP:
        baixar(f"{CVM}/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip", DEST / f"dfp_{ano}.zip")

    print("ITR (trimestrais do ano corrente; traz o comparativo do ano anterior)")
    baixar(f"{CVM}/DOC/ITR/DADOS/itr_cia_aberta_{ANO_ITR}.zip", DEST / f"itr_{ANO_ITR}.zip")

    print("\nConcluído. Confira se não houve 'NÃO BAIXOU' acima.")


if __name__ == "__main__":
    main()
