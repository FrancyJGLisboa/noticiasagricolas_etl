# data branch — auto-published daily

This branch is **force-pushed daily** by `.github/workflows/daily-update.yml`.
It always contains exactly one commit — never commit here, your changes will be wiped.

Code lives on `main`. Bulk binary data (parquet) lives in the `data-latest`
GitHub Release. This branch exposes CSVs and charts via raw URLs.

## Charts (interactive Plotly HTMLs)

Open in browser via GitHub Pages (if enabled on this branch) or via
`htmlpreview.github.io`:

  https://htmlpreview.github.io/?https://github.com/FrancyJGLisboa/noticiasagricolas_etl/blob/data/charts/seasonality.html

## CSVs (raw URLs, consumable directly)

```python
import pandas as pd
BASE = "https://raw.githubusercontent.com/FrancyJGLisboa/noticiasagricolas_etl/data/csv"
df = pd.read_csv(f"{BASE}/basis-soja.csv", parse_dates=["date"])
```

---
Last updated: 2026-09-04T23:41:25Z
