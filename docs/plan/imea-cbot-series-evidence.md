# Evidência: séries IMEA contra CBOT

Status final: `IMPLEMENTED_WITH_UPSTREAM_DATE_LIMIT`

| Critério | Camada | Método | Resultado | Artefato | Limite |
|---|---|---|---|---|---|
| Pares IMEA independentes | Engenharia | testes unitários e CSV materializado | PASS | 12.608 linhas soja e 10.763 milho | não valida publicação |
| Outlier R$ 1.399,01 bloqueado | Produto | fixture e snapshot de 05/11/2026 | PASS | ausente do basis; presente em `blocked_examples` | não corrige a fonte |
| Snapshot 8/7 em 12/11/2026 | Produto | geração sobre `origin/data` | PARTIAL | físico bruto tem 8/7; basis fica em 11/11 | CBOT e PTAX não existem em 12/11 no commit `8e2c267` |
| Cálculos isolados por série | Engenharia | testes de rotas, histórico e percentis | PASS | 27 testes Site e integração de quatro séries | não prova execução comercial |
| Fonte e metodologia visíveis | Experiência | navegador local | PASS | fluxo `imea` no browser smoke | avaliação visual local |
| Regressões 503/385 e 67/9 | Produto | integração fixada | PASS | soja 503, milho 385, bloqueios 67/9 | snapshot de 11/11/2026 |

## Comandos reproduzíveis

```text
uv run pytest tests/test_basis_builder.py tests/test_quote_quality.py tests/test_viz.py -q
# 93 passed

uv run python scripts/validate_imea_series.py --git-ref origin/data
# raw 2026-11-12: soja 8, milho 7
# latest computed basis 2026-11-11: soja 8, milho 7
# latest computed basis equals the latest common physical, CBOT and PTAX date
# Campo Verde/MT 2026-11-05 1399.01: blocked before basis and stats

# Exact comparison against origin/data after selecting the 23 legacy columns:
# soja: 103,869 legacy rows identical
# milho: 102,209 legacy rows identical

RADAR_DATA_DIR=/tmp/radar-imea-data bun tests/integration.mjs
# PASS: 503/28/385/21 rotas para soja atual/IMEA e milho atual/IMEA

RADAR_DATA_DIR=/tmp/radar-imea-data bun scripts/audit-numbers.mjs
# PASS: erro máximo zero nas identidades de basis, spread e stats

bun tests/browser-smoke.mjs
# PASS: radar, simulador, ranking, visualizações, mobile e IMEA

node scripts/validate-artifact.mjs
# Artefato Worker válido

npm audit --audit-level=high
# found 0 vulnerabilities
```

## Limites confirmados

- O commit de dados tem oito preços físicos IMEA de soja e sete de milho em 12/11/2026.
- O mesmo commit termina CBOT e PTAX em 11/11/2026.
- O ETL exige a mesma data. Ele não usa carry-forward silencioso.
- O Radar mostra 11/11/2026 até a fonte publicar CBOT e PTAX de 12/11/2026.
- O validador aceita automaticamente o avanço quando as três fontes ganharem uma data comum mais recente.
- A suíte completa teve 457 testes aprovados e dois erros ambientais. Esses dois testes procuram `catalog.yaml` no outro worktree `/Users/francylisboacharuto/noticiasagricolas_etl/`.
