# Plano: gráficos de basis ajustado

## Resultado esperado

Os gráficos históricos de soja e milho devem usar `basis_*_adj` quando a coluna existir. Tabelas de nível atual, distribuição e percentil devem continuar no `basis_*` bruto.

## Limites

- Não altera cálculo do basis, escolha de contrato B3, CSV, API ou serviços de percentil.
- Outras commodities mantêm o comportamento anterior.
- Arquivos sem colunas ajustadas continuam funcionando.

## Implementação

`load_pair_data` preserva `value_raw` e escolhe a coluna ajustada para `value` somente em soja e milho. `compute_stats` lê `value_raw` para níveis atuais, médias e percentis. Séries históricas usam `value`.

Gráficos de série exibem um marcador `x` quando `roll_gap_missing=true`. O texto informa que o passo do contrato permanece bruto naquele ponto.

## Verificação

O arquivo de evidência registra testes e renderização dos CSVs publicados.
