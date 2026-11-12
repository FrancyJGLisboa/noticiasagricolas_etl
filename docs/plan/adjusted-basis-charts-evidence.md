# Evidência: gráficos de basis ajustado

Data: 2026-11-12

## Testes

Comando:

```text
uv run pytest -q tests/test_viz.py tests/test_viz_shaper.py
```

Resultado: `33 passed`, com 45 avisos de depreciação do pandas já existentes.

Os testes cobrem escolha ajustada, fallback bruto, níveis atuais no bruto e marcador de `roll_gap_missing`.

## Renderização com dados publicados

Comando usado: leitura de `origin/data:csv/basis-soja.csv` e `origin/data:csv/basis-milho.csv`, filtragem dos pares soja-CBOT e milho-B3, construção com `multi_location.build` e gravação HTML em `/tmp`.

- soja-CBOT: 55.035 linhas, coluna `basis_cents_bu_adj`, 100% das linhas com valor histórico, 39 observações `roll_gap_missing`.
- milho-B3: 51.419 linhas, coluna `basis_brl_adj`, 100% das linhas com valor histórico, 46 observações `roll_gap_missing`.

Os arquivos renderizados foram `/tmp/soja-cbot-adjusted.html` e `/tmp/milho-b3-adjusted.html`. O primeiro trace é uma série de praça e os gráficos incluem traces de marcador para gaps ausentes quando presentes.

## Ruff e limites

`uvx ruff check` encontrou 52 avisos C408 e três regras PLC/SIM preexistentes em código de visualização. Eles não indicam erro funcional deste trabalho.

`uvx pip-audit --skip-editable` terminou com `No known vulnerabilities found`.

O conjunto completo não coletou `tests/test_api.py` porque o ambiente não instalou a dependência opcional FastAPI. Os testes focados acima foram executados no ambiente com as dependências de desenvolvimento.

Não foi implementado um seletor raw/adjusted. O gráfico histórico usa ajustado por padrão e identifica isso no título. Percentis e níveis atuais continuam brutos.
