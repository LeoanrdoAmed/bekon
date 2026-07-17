# Analise do Produto

## Concorrente: Pierre

Leitura feita em 6 de maio de 2026 sobre a landing page `lp.pierre.finance` e materias publicadas em 30 e 31 de marco de 2026.

### O que o Pierre vende bem

- narrativa simples: "nao gerencie mais seu dinheiro sozinho"
- conversa em vez de dashboard complexo
- consolidacao de multiplos bancos e cartoes via Open Finance
- agentes especializados por frequencia e funcao
- seguranca e somente leitura como argumento central
- monetizacao clara por numero de bancos, agentes e relatorios

### Funcionalidades percebidas

- conexao com contas bancarias e cartoes
- importacao e consolidacao de transacoes
- chat em linguagem natural
- alertas de gastos fora do padrao
- visao de proximo mes, assinaturas e parcelas
- relatorios personalizados
- experiencia multicanal, inclusive WhatsApp

### Diferencial estrutural

O produto nao depende de o usuario interpretar planilhas. O valor esta em traduzir Open Finance em perguntas e respostas acionaveis.

## O que ja existia no projeto legado

O projeto `pagamentos_noélia - v11` ja tinha, em producao:

- configuracao de Open Finance com `cnpjsh` e `tokensh`
- cadastro de pagadores
- cadastro de contas com `accountHash`, `openfinanceId` e `openfinanceLink`
- vinculo de cartoes por conta
- criacao de conta remota na API
- geracao de protocolo de extrato para conta e cartao
- consulta posterior do protocolo e parse das transacoes

## Adaptacao feita para o novo produto

Em vez de levar todo o ERP para o novo projeto, a adaptacao ficou assim:

- manteve-se apenas o nucleo Open Finance
- removeu-se dependencias de conciliacao contabil, agenda e multi-tenant
- criou-se um storage proprio para contas, pagadores, protocolos e chat
- adicionou-se uma camada de analytics para:
  - entradas
  - saidas
  - saldo liquido
  - top categorias
  - volume por cartao
  - historico mensal
- adicionou-se um chat financeiro para consultar as movimentacoes em linguagem natural

## MVP entregue

- dashboard
- tela de conexoes Open Finance
- tela de transacoes filtraveis
- chat com sessoes
- fallback local sem IA
- integracao pronta para OpenAI quando `OPENAI_API_KEY` estiver configurada

## Proximos passos recomendados

1. adicionar autenticacao por usuario final
2. separar os dados por cliente
3. incluir alertas proativos e jobs agendados
4. melhorar categorizacao com regras treinadas ou classificador assistido por IA
5. expor API propria para app mobile e WhatsApp
