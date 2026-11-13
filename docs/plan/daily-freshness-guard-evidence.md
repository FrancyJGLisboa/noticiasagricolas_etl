# Evidência: proteção de atualização e frescor diário

Status: `IMPLEMENTED_WITH_UPSTREAM_ACCESS_BLOCKED`

## Resultado

- HTTP 403 e erros de rede agora geram `FetchError`.
- Uma atualização com erro ou zero indicadores válidos termina com código diferente de zero.
- Soja CBOT, milho CBOT e PTAX devem alcançar a data esperada antes da exportação.
- O workflow repete a validação antes do release e do branch `data`.
- Execuções simultâneas do workflow são canceladas para evitar publicação concorrente.

## Evidência

| Critério | Camada | Método | Resultado | Limite |
|---|---|---|---|---|
| HTTP 403 interrompe a atualização | Engenharia | teste com resposta HTTP 403 | PASS | não remove o bloqueio do provedor |
| Zero registros interrompe a atualização | Engenharia | teste de pipeline vazio | PASS | não mede disponibilidade externa |
| Dados atrasados bloqueiam etapas posteriores | Produto | teste do orquestrador e comando CLI | PASS | usa dias úteis sem calendário de feriados |
| Publicação ocorre depois da validação | Engenharia | teste da ordem do workflow | PASS | não executa o GitHub Actions localmente |
| Fonte atual alcança 12/11/2026 | Produto | coleta e parse ao vivo dos três indicadores | PASS | executado fora do GitHub Actions |
| Dependências sem vulnerabilidades conhecidas | Engenharia | `uvx pip-audit` | PASS | depende da base pública do auditor |

## Comandos e resultados

```text
uv run pytest tests/test_scraper.py tests/test_pipeline_update.py tests/test_daily_freshness.py tests/test_daily_pipeline.py tests/test_daily_workflow.py -q
# 21 passed

uv run pytest -q --tb=short
# 470 passed, 2 failed
# As duas falhas procuram catalog.yaml no worktree de dados.
# Elas já existiam antes desta mudança e não passam pelos arquivos alterados.

uv run python -m compileall -q src tests
# exit 0

uvx pip-audit
# No known vulnerabilities found

# Coleta ao vivo com os parsers do projeto:
# expected=2026-11-12 fresh=True
# soja CBOT: 2026-11-12
# milho CBOT: 2026-11-12
# PTAX: 2026-11-12
```

## Limites e risco restante

- O GitHub Actions ainda recebe HTTP 403 do Notícias Agrícolas.
- O novo comportamento preserva os dados publicados e marca o workflow como falho.
- Um feriado pode exigir `expected_date` no disparo manual.
- `ruff` e `actionlint` não estão instalados neste ambiente.
