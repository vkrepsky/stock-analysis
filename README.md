# Triagem da B3: lucro estável, pouca dívida e preço em queda

Pipeline em Python que monta uma base com todas as empresas listadas e aplica a triagem.

## Fontes
| Dado | Fonte | Script |
|---|---|---|
| Lucro (controladores), receita, EBIT, D&A, caixa, dívida, arrendamentos, patrimônio, ações | CVM Dados Abertos (DFP anual 2021-2025 e ITR do ano corrente) | `01`, `02` |
| Tickers e situação (recuperação judicial etc.) | CVM (FCA e cadastro) | `01`, `03` |
| Preço, volume, dividendos, Ibovespa | Yahoo Finance via `yfinance` | `03` |

## Preparar o ambiente (uma vez)
Precisa de Python 3.10+ e internet. Na pasta do projeto, crie e ative um ambiente virtual e instale as dependências:

```bash
# Windows (cmd)
python -m venv .venv
.venv\Scripts\activate
# Windows (PowerShell): .venv\Scripts\Activate.ps1

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```
Com o venv ativo o prompt mostra `(.venv)`. Em outro terminal, ative de novo antes de rodar (`.venv\Scripts\activate` ou `source .venv/bin/activate`). Para sair: `deactivate`. A pasta `.venv/` não vai para o git.

## Como rodar (na sua máquina, com internet)
```bash
python src/run_all.py           # roda tudo (01 a 06; o 06 gera data/out/relatorio_diagnostico.md, pequeno, para enviar ao Claude); use --de N / --ate N / --so N para parte

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
- Dívida financeira = contas 2.01.04 + 2.02.01 do passivo, sem arrendamentos. Arrendamentos são procurados pelo texto da conta ("arrendamento"/"leasing"/"direito de uso") em todo o passivo 2.01.* e 2.02.* (muitas empresas lançam fora de empréstimos); a parte que já está dentro de 2.01.04/2.02.01 sai da dívida financeira para não contar duas vezes. Se o texto da conta for diferente, o arrendamento pode faltar.
- EBITDA = EBIT (3.05) + depreciação/amortização da DVA (7.04.01, que a CVM traz NEGATIVA: usamos o módulo); empresas sem essas contas ficam sem EBITDA.
- Lucro dos controladores = 3.11.01; se vier 0 com o total (3.11) diferente de 0 (empresa que só preenche o total), vale 3.11 - 3.11.02.
- Valor de mercado = preço por classe x ações da CVM; para quem só tem unit, usa preço da unit x ações ON (aproximação; o valor do Yahoo fica só para comparação). A composição de capital da CVM não informa a escala e parte das empresas preenche em milhares: o passo 4 detecta (P/VP ou P/L < 0,05, ou unit ~1/1000 do Yahoo), multiplica por 1000 e lista os tickers corrigidos (coluna `acoes_em_mil`). Não detecta empresas sem lucro e sem PL positivos.
- Preços do Yahoo podem ter falhas; o script lista os tickers sem dados.
- Dividendos: `dy_12m` soma tudo o que foi pago em 12 meses; `dy_12m_rec` exclui pagamentos extraordinários (mais de 5x a mediana dos pagamentos dos últimos 3 anos) e é o que o ranking usa, junto com `payout_12m_rec`. Quem muda o padrão de pagamento de verdade (ex.: passa a pagar bem mais) fica subestimado.
- Seguradoras e holdings entram, mas dívida/EBITDA não é comparável para elas.
- Janela de preço de ~2 anos: dá para triar hoje, mas não para um backtest longo.
