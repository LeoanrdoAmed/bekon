# Fin na Mao

Produto web de assistente financeiro pessoal com:

- conexao de contas e cartoes via Open Finance
- configuracao inicial guiada por conversa
- importacao e normalizacao de transacoes
- dashboard com resumo financeiro
- chat em linguagem natural sobre movimentacoes

## Executar

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

A aplicacao sobe por padrao em `http://127.0.0.1:8000`.

## Docker

Para ambiente com Ollama local via Docker:

```powershell
Copy-Item .env.production.example .env
docker-compose up -d --build
docker exec -it fin-na-mao-ollama ollama pull llama3:8b
```

O app fica publicado internamente na porta `18020` do host e pronto para reverse proxy no `nginx`.

Em producao, a aplicacao agora exige autenticacao e token CSRF para todas as rotas operacionais. Defina as credenciais no `.env` antes de subir o container.

O projeto agora suporta multi-tenant na mesma instancia. Cada licenca fica isolada em `dados/tenants/<tenant_slug>/...`, sem exigir novo subdominio ou novo deploy por cliente.

## Variaveis de ambiente

- `LLM_PROVIDER`: provider do chat. Padrao: `ollama`. Opcoes: `ollama`, `openai`, `auto`, `fallback`.
- `OLLAMA_BASE_URL`: endpoint local do Ollama. Padrao: `http://127.0.0.1:11434`.
- `OLLAMA_MODEL`: modelo local usado no chat. Padrao: `llama3:8b`.
- `OPENAI_API_KEY`: opcional, habilita respostas com OpenAI quando `LLM_PROVIDER=openai` ou `auto`.
- `OPENAI_MODEL`: sobrescreve o modelo da OpenAI. Padrao: `gpt-5.4-mini`.
- `OPENFINANCE_ENVIRONMENT`: `staging` ou `production`.
- `OPENFINANCE_BASE_URL`: opcional, sobrescreve a URL base interna do Open Finance.
- `OPENFINANCE_CNPJSH`: CNPJ da Software House.
- `OPENFINANCE_TOKENSH`: token da Software House.
- `APP_SECRET_KEY`: segredo de sessao Flask. Obrigatorio quando `APP_DEBUG=0`.
- `APP_AUTH_ENABLED`: habilita autenticacao do painel. Padrao: ligado em todos os ambientes.
- `APP_AUTH_USERNAME`: usuario bootstrap opcional do painel. Padrao: `admin`.
- `APP_AUTH_PASSWORD_HASH`: hash Werkzeug da senha do usuario bootstrap. Recomendado para producao.
- `APP_AUTH_PASSWORD`: senha bootstrap em texto puro. Use apenas em ambiente temporario/local.
- `APP_ALLOW_SELF_REGISTRATION`: libera a tela publica para criar novas licencas no mesmo dominio. Padrao: `1` em debug e `0` em producao. Mesmo com `0`, o primeiro cadastro continua liberado se ainda nao existir nenhum usuario local.
- `APP_DEBUG`: opcional, `1` para debug.
- `APP_SESSION_COOKIE_SECURE`: envia cookie de sessao apenas em HTTPS. Recomendado: `1` em producao.
- `PORT`: opcional, porta HTTP.

Use as credenciais do Open Finance preferencialmente por variavel de ambiente (`OPENFINANCE_CNPJSH` e `OPENFINANCE_TOKENSH`). Nao mantenha segredos ativos em `dados/openfinance_config.json`.

Os logs tecnicos do Open Finance agora sao sanitizados antes de serem persistidos. Ainda assim, trate a pasta `dados/` como sensivel e fora de versionamento.

Os usuarios locais ficam em `dados/users.json` e cada usuario fica vinculado a um `tenant_id`. Os dados operacionais de cada licenca ficam separados em `dados/tenants/<tenant_slug>/`. Se voce preferir um primeiro acesso controlado, mantenha `APP_AUTH_USERNAME` + `APP_AUTH_PASSWORD_HASH` definidos. Se quiser permitir a criacao publica de novas licencas pela interface, habilite `APP_ALLOW_SELF_REGISTRATION=1`.

Se ja existir um tenant com dados importados e ainda nao houver usuario cadastrado, o primeiro cadastro publico passa a assumir essa licenca existente em vez de criar outra separada.

O cadastro publico agora tambem coleta os dados do cliente e grava o perfil base no tenant antes do primeiro login. Com isso, a etapa inicial de onboarding por conversa e pulada, e o fluxo segue direto para contas e cartoes.

O chat agora usa Ollama local por padrao, aproveitando o modelo instalado na maquina. Se quiser voltar para OpenAI, defina `LLM_PROVIDER=openai`.

## Estrutura

- `backend/core/openfinance`: adaptacao do nucleo de Open Finance do projeto legado.
- `backend/core/auth`: usuarios locais, login e cadastro.
- `backend/core/tenancy`: tenants/licencas e isolamento de dados.
- `backend/core/customer`: cadastro unico do cliente e estado da configuracao inicial.
- `backend/core/finance`: categorizacao e analytics.
- `backend/core/ai`: sessoes e servico do chat.
- `templates/`: telas do produto.
- `dados/`: persistencia JSON local, com separacao por tenant em `dados/tenants/`.
