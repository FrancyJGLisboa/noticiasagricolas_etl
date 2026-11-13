# Séries IMEA contra CBOT

## Resultado

Publicar `soja-imea-cbot` e `milho-imea-cbot` como séries físicas independentes.
O ETL e o Radar não podem agregar, emendar ou comparar essas séries com fontes físicas existentes.

## Usuário e problema

O usuário do Radar precisa ver a última cotação física disponível sem perder a identidade da fonte.
O IMEA atualiza antes de algumas fontes atuais, mas mede um preço próprio e documentado.

## Não objetivos

- Não preencher lacunas das séries atuais com IMEA.
- Não alterar a escolha de contrato futuro.
- Não corrigir preços anormais automaticamente.
- Não comparar rotas entre fontes físicas diferentes.
- Não alterar séries B3.

## Decisões

1. Cada `BasisPairConfig` recebe identidade e metadados explícitos da fonte física.
2. O CSV de basis recebe `basis_pair`, `physical_source`, `source_name` e `source_url`.
3. `quote-quality.csv` usa a chave `basis_pair + commodity + date + location`.
4. O Radar seleciona uma série. Todos os rankings, históricos, movimentos, percentis e rotas usam somente essa série.
5. IMEA usa comparação transversal robusta por data. Um preço fora de 0,5 a 2 vezes a mediana positiva é bloqueado.
6. O bloqueio ocorre antes do basis. O relatório diário de qualidade conserva a contagem e o motivo.
7. A atribuição visível é `Fonte: IMEA, via Notícias Agrícolas`, com links para fonte e metodologia.

## Justificativa da regra de outlier

A regra depende apenas das praças IMEA da mesma commodity e data.
Ela não usa a série atual e não cria uma correção de preço.
Com pelo menos três praças, a razão transversal bloqueia R$ 1.399,01 contra uma mediana próxima de R$ 136/sc.
A faixa de 0,5 a 2 vezes a mediana preserva diferenças regionais muito maiores que as observadas no histórico normal.
Sem três praças, o ETL não aplica essa regra e registra zero bloqueios transversais.

## Riscos e falhas verificadas

- **Colisão de chaves:** duas fontes podem ter a mesma praça e data. A chave inclui `basis_pair`.
- **Mistura em visualizações:** o filtro antigo usava somente `futures_indicator`. O novo filtro também usa os indicadores físicos do par.
- **Mistura no Site:** todas as funções recebem `series` e rejeitam pares diferentes.
- **Arquivo antigo:** o parser do Site falha fechado quando os campos de identidade não existem.
- **Outlier silencioso:** o resumo de qualidade registra contagem, motivo e rótulo bloqueado.
- **Fonte sem futuros/PTAX:** a série fica sem data, sem emprestar valores de outra série.

## Tarefas

### ETL

- **Objetivo:** produzir duas séries independentes e qualidade por série.
- **Arquivos:** `basis_config.py`, loaders, builder, schema, quote quality, visualizações e testes.
- **Dependências:** parquet diário de soja, milho, CBOT e PTAX.
- **Aceite:** labels distintos, outlier bloqueado, 8/7 praças em 12/11/2026 e regressões atuais intactas.
- **Excluído:** publicação do branch `data`.

### Site

- **Objetivo:** selecionar uma série e manter todos os cálculos dentro dela.
- **Arquivos:** `dist/`, auditorias, testes e README.
- **Dependências:** novos CSVs do ETL.
- **Aceite:** IMEA mostra a última data comum entre físico, CBOT e PTAX, além de fonte e metodologia. Série atual mantém 503/385 rotas e bloqueios 67/9.
- **Excluído:** deploy.

## Critérios de aceitação

- `soja-imea-cbot` contém somente `soja-disponivel-imea`.
- `milho-imea-cbot` contém somente `milho-disponivel-imea`.
- O valor R$ 1.399,01 de 05/11/2026 não entra em basis, percentis ou rotas.
- A qualidade explica o bloqueio.
- O físico IMEA de 12/11/2026 tem 8 praças de soja e 7 de milho. O basis usa a última data comum com CBOT e PTAX.
- O Radar não cria rota com séries diferentes.
- A fonte e a metodologia ficam visíveis.
- Testes ETL, Site, integração, navegador e segurança passam com resultados não vazios.

## Verificação planejada

```sh
uv run pytest
npm test
npm run test:integration
npm run test:semantic
npm run test:independent
npm run build
npm run validate
npm audit --audit-level=high
```

## Rollback

Remover os dois novos pares e restaurar o Site anterior. Os arquivos existentes continuam válidos porque as séries atuais não mudam.
