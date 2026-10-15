# Dashboard de commodities – Agroliga FGV

Fluxo: **GitHub Actions** (agenda) → `atualizar.py` (Yahoo Finance) → **Google Sheets** → **Looker Studio** (dashboard).

## Montagem (uma vez só, ~30 min)

### 1. Conta de serviço do Google (o "robô" que escreve na planilha)
1. https://console.cloud.google.com → criar projeto "agroliga".
2. *APIs e serviços → Biblioteca*: ativar **Google Sheets API** e **Google Drive API**.
3. *IAM → Contas de serviço → Criar*. Depois, aba *Chaves → Adicionar chave → JSON*. Baixa um arquivo.
4. Abra o JSON, copie o campo `client_email`.
5. Na planilha do Google Sheets: **Compartilhar** com esse e-mail como **Editor**.

### 2. GitHub
1. Criar repositório (de preferência numa conta/organização da Liga, não pessoal) e subir esta pasta.
2. *Settings → Secrets and variables → Actions → New repository secret*:
   - `GOOGLE_CREDENTIALS_JSON` = conteúdo inteiro do arquivo JSON
   - `SPREADSHEET_ID` = trecho da URL da planilha entre `/d/` e `/edit`
3. Aba *Actions → Atualizar cotações → Run workflow*, marcando **backfill** na primeira vez (carrega 1 ano de histórico).

Nunca commite o JSON da conta de serviço (o `.gitignore` já bloqueia `*.json`).

### 3. Looker Studio
1. https://lookerstudio.google.com → Criar → Relatório → fonte **Google Sheets**.
2. Adicione as abas `Atual` (cartões e tabela) e `Historico` (gráficos de linha: dimensão `data`, métrica `preco`, quebra por `ativo`).
3. Compartilhe o link do relatório com a Liga.

## Abas da planilha
| Aba | Conteúdo | Quem escreve |
|---|---|---|
| `Atual` | Último pregão, variação diária, equivalente em R$/saca | script (sobrescreve) |
| `Historico` | Uma linha por ativo por pregão | script (só acrescenta) |
| `Fisico_Manual` | Preços físicos (CEPEA etc.) | **vocês, à mão** |

## Preços físicos (CEPEA)
O código original tinha valores fixos inventados para o físico, então foram removidos: o dashboard mostraria números falsos com a data de hoje.
Por ora, preencham `Fisico_Manual` com data, praça, unidade, preço e fonte (ex.: semanalmente, citando CEPEA/ESALQ). Automatizar exige conferir os termos de uso do CEPEA; pode ser a próxima etapa.

## Manutenção
- **Contratos vencem**: `ZSX26.CBT` (soja nov/26) deixa de existir após o vencimento. Troque os tickers em `ATIVOS` a cada trimestre (ou use `ZS=F`, `ZC=F`, `ZW=F`, que rolam sozinhos).
- Se o job falhar, o GitHub manda e-mail ao dono do repositório.
- Em repositórios públicos, o GitHub pausa workflows agendados após ~60 dias sem atividade no repositório. Se acontecer, reative na aba Actions.
- Teste local: `pip install -r requirements.txt && python atualizar.py --dry-run` (gera CSVs em `saida/`).
