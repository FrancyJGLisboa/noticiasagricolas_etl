# Proteção de atualização e frescor diário

## Resultado

O workflow diário deve interromper a execução quando a coleta falhar.
Ele também deve impedir a publicação quando soja CBOT, milho CBOT ou PTAX estiverem atrasados.

## Escopo

- Propagar erros HTTP do scraper para o pipeline.
- Fazer a atualização falhar quando existir erro de coleta ou nenhum indicador válido.
- Verificar a data dos três indicadores críticos antes de exportar e publicar.
- Permitir uma data esperada explícita para feriados e reconstruções históricas.
- Adicionar testes unitários e um comando de validação independente.

## Não objetivos

- Contornar o bloqueio HTTP 403 do Notícias Agrícolas.
- Trocar a fonte de CBOT ou PTAX.
- Preencher datas ausentes.
- Alterar cálculos de basis ou escolha de contrato.

## Decisões

1. HTTP 404 continua significando página ausente.
2. Outros erros HTTP e erros de rede geram `FetchError`.
3. A atualização processa os indicadores restantes e falha ao final se algum fetch falhar.
4. A data esperada padrão é o último dia útil anterior em São Paulo.
5. `NA_ETL_EXPECTED_DATE` aceita uma data explícita no formato `YYYY-MM-DD`.
6. A validação usa somente linhas de fechamento CBOT e o valor do dólar PTAX.
7. O workflow executa uma validação separada antes de publicar o release e o branch `data`.

## Riscos e controles

- Um feriado pode causar falha conservadora. O operador deve informar a data esperada explícita.
- Uma mudança de coluna pode ocultar dados válidos. Os testes fixam os seletores usados.
- Uma falha parcial pode deixar o Parquet atualizado parcialmente. Nenhum artefato será publicado nessa execução.
- O bloqueio 403 pode continuar. O workflow deve mostrar a falha sem publicar dados antigos.

## Critérios de aceitação

- HTTP 403 gera erro e código de saída diferente de zero.
- Zero indicadores válidos gera erro e código de saída diferente de zero.
- Dados críticos anteriores à data esperada bloqueiam exportação, basis, gráficos, release e branch `data`.
- Dados críticos na data esperada permitem a execução.
- O comando `na-etl validate-freshness` mostra a data esperada e a data de cada indicador.
- O workflow não alcança as etapas de publicação após qualquer falha anterior.

## Verificação

```sh
uv run pytest tests/test_scraper.py tests/test_pipeline_update.py tests/test_daily_freshness.py tests/test_daily_pipeline.py -q
uv run pytest -q
uv run ruff check src tests
```

## Rollback

Reverter os arquivos desta mudança restaura o comportamento anterior.
Os arquivos Parquet e CSV não mudam de formato.
