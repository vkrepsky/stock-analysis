# Triagem da B3: lucro estável, pouca dívida e preço em queda

Pipeline em Python que monta uma base com todas as empresas listadas e aplica a triagem.

## Fontes
| Dado | Fonte | Script |
|---|---|---|
| Lucro (controladores), receita, EBIT, D&A, caixa, dívida, arrendamentos, patrimônio, ações | CVM Dados Abertos (DFP anual 2021-2025 e ITR do ano corrente) | `01`, `02` |
| Tickers e situação (recuperação judicial etc.) | CVM (FCA e cadastro) | `01`, `03` |
| Preço, volume, dividendos, Ibovespa | Yahoo Finance via `yfinance` | `03` |

## Como rodar (na sua máquina, com internet)
```bash
pip install pandas numpy requests yfinance
python src/run_all.py           # roda tudo (01 a 05); use --de N / --ate N / --so N para parte

# ou passo a passo:
python src/01_baixar_cvm.py     # ~100-200 MB, com cache
python src/02_fundamentos.py    # -> data/out/fundamentos.csv
python src/03_precos.py         # -> precos_resumo, dividendos_ano, precos_diarios.csv.gz, ibov_diario (10-20 min)
python src/04_consolidar.py     # -> data/out/b3_dataset.csv (1 linha por empresa) + validação com a Renner
python src/05_triagem.py        # triagem e ranking (ou rode com o b3_dataset.csv anexado ao Claude)
```
Ajuste anos e janelas em `src/common.py` (`ANOS_DFP`, `ANO_ITR`) e os critérios em `P` e `PESOS` no `05_triagem.py`.

## Critérios (padrão)
- Escopo: sem bancos; sem recuperação judicial/liquidação; liquidez mediana 90d >= R$ 5 mi.
- Lucro estável: positivo em 2021-2025 e no LTM, sem queda anual pior que 30%.
- Pouca dívida: caixa líquido ou dívida líquida/EBITDA <= 1,0x (com arrendamentos por padrão).
- Preço em queda: >= 15% abaixo de 12 meses atrás ou >= 25% abaixo da máxima de 52 semanas.
- Ranking: percentis de valuation (30%), estabilidade (25%), balanço (20%), dividendos (15%), qualidade (10%), com teste de sensibilidade dos pesos.

## Limites conhecidos
- Dívida financeira = contas 2.01.04 + 2.02.01 do passivo; arrendamentos são identificados pelo texto da conta ("arrendamento"/"leasing"), então podem faltar em alguns balanços.
- EBITDA = EBIT (3.05) + depreciação/amortização da DVA (7.04.01); empresas sem essas contas ficam sem EBITDA.
- Valor de mercado = preço por classe x ações da CVM; para quem só tem unit, usa o valor de mercado do Yahoo.
- Preços do Yahoo podem ter falhas; o script lista os tickers sem dados.
- Seguradoras e holdings entram, mas dívida/EBITDA não é comparável para elas.
- Janela de preço de ~2 anos: dá para triar hoje, mas não para um backtest longo.
