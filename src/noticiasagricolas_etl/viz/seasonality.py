"""Viz #1 — Climate-normal seasonality chart (daily, calendar-based).

For each praça, shows daily basis. Layers:
  - Min-max envelope (lightest gray fill) — historical extremes per day-of-year
  - P25-P75 IQR band (medium gray fill) — typical range per day-of-year
  - Median line (dashed black) — the "normal" for each day-of-year (7-day smoothed)
  - Each past year as a thin line (hidden by default, click legend to show)
  - Current year (bold red, daily markers, raw — no smoothing)
  - "HOJE" star marker — last available day in current year, with Δ-vs-median tooltip

Three cascading dropdowns: Commodity → Referência (B3/CBOT/NYBOT) → Praça.
Big commodity banner that updates with selection.
"""

from __future__ import annotations

import logging

import pandas as pd
import plotly.graph_objects as go

from ..basis_config import BasisPairConfig
from .common import PAIR_DISPLAY

logger = logging.getLogger(__name__)


HIGHLIGHT_COLOR = "#d62728"
MEAN_COLOR = "#000000"
ENVELOPE_COLOR = "rgba(127,127,127,0.10)"
IQR_COLOR = "rgba(127,127,127,0.28)"

# Sequential blue palette for past years (oldest = light, newest = dark)
HISTORY_PALETTE = ["#bdd7e7", "#6baed6", "#3182bd", "#08519c", "#08306b"]

# Month tick anchors on a 1-366 day-of-year axis (non-leap year layout)
DOY_TICKVALS = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
DOY_TICKTEXT = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
PT_MONTHS = DOY_TICKTEXT

# Display labels for futures references (3rd-level slug → button label)
FUTURES_LABELS = {"b3": "B3", "cbot": "CBOT", "nybot": "NYBOT"}

# Default preference order within a commodity: international refs first (where
# the basis convention originated and where Marcos Araújo's formula applies).
FUTURES_PRIORITY = {"cbot": 0, "nybot": 1, "b3": 2}

# Display labels for commodities
COMMODITY_LABELS = {
    "soja": "Soja",
    "milho": "Milho",
    "trigo": "Trigo",
    "algodao": "Algodão",
    "cafe": "Café",
    "boi-gordo": "Boi Gordo",
}


def _doy_to_date_str(doy: int) -> str:
    """Convert day-of-year (1-366) to '25-Jul' style label using a non-leap reference."""
    d = pd.Timestamp("2001-01-01") + pd.Timedelta(days=int(doy) - 1)
    return f"{d.day:02d}-{PT_MONTHS[d.month - 1]}"


def _futures_slug(pair_label: str) -> str:
    """Extract the futures-reference slug ('b3', 'cbot', 'nybot') from a pair label."""
    return pair_label.rsplit("-", 1)[-1]


def _climate_normal_traces(
    loc_df: pd.DataFrame,
    today: pd.Timestamp,
    window_years: int = 5,
    real_today: pd.Timestamp | None = None,
) -> list[go.Scatter]:
    """Build climate-normal traces for a single praça with daily granularity.

    Args:
        today: reference date for the chart (typically last data date in the pair).
        real_today: actual calendar today; used to label the marker honestly when
            data is stale. Defaults to `today` if not provided.

    Bands are smoothed by 7-day centered rolling for visual clarity; current year
    line is raw daily values so movements are honest.
    """
    if real_today is None:
        real_today = today

    if loc_df.empty:
        return []

    cutoff = today - pd.DateOffset(years=window_years)
    df = loc_df[(loc_df["date"] >= cutoff) & loc_df["value"].notna()].copy()
    if df.empty:
        return []

    df["year"] = df["date"].dt.year
    df["doy"] = df["date"].dt.dayofyear  # 1-366

    daily = df.groupby(["year", "doy"], as_index=False)["value"].mean()
    current_year = int(today.year)
    past_years = sorted(int(y) for y in daily.loc[daily["year"] < current_year, "year"].unique())

    pivot = daily.pivot(index="doy", columns="year", values="value").reindex(range(1, 367))

    if not past_years:
        return []

    past_only = pivot[past_years]
    p_min = past_only.min(axis=1)
    p25 = past_only.quantile(0.25, axis=1)
    p_med = past_only.median(axis=1)
    p75 = past_only.quantile(0.75, axis=1)
    p_max = past_only.max(axis=1)

    # Smooth daily stats with 7-day centered rolling window (handles missing days)
    def _smooth(s: pd.Series) -> pd.Series:
        return s.rolling(window=7, center=True, min_periods=3).mean()

    p_min_s = _smooth(p_min)
    p25_s = _smooth(p25)
    p_med_s = _smooth(p_med)
    p75_s = _smooth(p75)
    p_max_s = _smooth(p_max)

    days = list(range(1, 367))
    days_x = [_doy_to_date_str(d) for d in days]
    traces: list[go.Scatter] = []

    # 1. Min-max envelope
    traces.append(go.Scatter(
        x=days, y=p_min_s.tolist(), mode="lines",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))
    traces.append(go.Scatter(
        x=days, y=p_max_s.tolist(), mode="lines",
        line=dict(width=0), fill="tonexty", fillcolor=ENVELOPE_COLOR,
        name="Min–max histórico", hoverinfo="skip",
    ))

    # 2. IQR (P25–P75) band
    traces.append(go.Scatter(
        x=days, y=p25_s.tolist(), mode="lines",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))
    traces.append(go.Scatter(
        x=days, y=p75_s.tolist(), mode="lines",
        line=dict(width=0), fill="tonexty", fillcolor=IQR_COLOR,
        name="P25–P75 (faixa típica)", hoverinfo="skip",
    ))

    # 3. Past years — hidden by default; user clicks legend to overlay
    n_history = len(past_years)
    for idx, yr in enumerate(past_years):
        color = (
            HISTORY_PALETTE[-1] if n_history == 1
            else HISTORY_PALETTE[int(idx * (len(HISTORY_PALETTE) - 1) / (n_history - 1))]
        )
        s = pivot[yr].dropna()
        if s.empty:
            # Plotly still needs a placeholder trace for visibility-array indexing
            traces.append(go.Scatter(x=[], y=[], mode="lines", visible="legendonly", name=str(yr)))
            continue
        traces.append(go.Scatter(
            x=s.index.tolist(),
            y=s.values.tolist(),
            mode="lines",
            line=dict(color=color, width=1.0),
            opacity=0.6,
            visible="legendonly",
            connectgaps=True,
            name=str(yr),
            hovertemplate=f"<b>{yr}</b><br>%{{customdata}}<br>%{{y:.2f}}<extra></extra>",
            customdata=[_doy_to_date_str(int(d)) for d in s.index],
        ))

    # 4. Median (smoothed)
    traces.append(go.Scatter(
        x=days, y=p_med_s.tolist(), mode="lines",
        line=dict(color=MEAN_COLOR, dash="dash", width=2.5),
        name=f"Mediana histórica ({n_history} anos)",
        hovertemplate="<b>Mediana</b><br>%{customdata}<br>%{y:.2f}<extra></extra>",
        customdata=days_x,
    ))

    # 5. Current year — raw daily, no smoothing
    if current_year in pivot.columns:
        cy = pivot[current_year].dropna()
        if not cy.empty:
            cy_dates = [_doy_to_date_str(int(d)) for d in cy.index]
            traces.append(go.Scatter(
                x=cy.index.tolist(),
                y=cy.values.tolist(),
                mode="lines+markers",
                line=dict(color=HIGHLIGHT_COLOR, width=2.2),
                marker=dict(size=4, line=dict(width=0)),
                connectgaps=False,
                name=f"{current_year} (atual)",
                hovertemplate=(
                    f"<b>{current_year}</b><br>%{{customdata}}<br>%{{y:.2f}}<extra></extra>"
                ),
                customdata=cy_dates,
            ))

            # 6. Last-observation marker — honestly labeled based on staleness
            today_doy = int(today.dayofyear)
            valid = [int(d) for d in cy.index if int(d) <= today_doy]
            if valid:
                td = max(valid)
                tv = float(cy.loc[td])
                hist_med_val = (
                    float(p_med_s.loc[td])
                    if td in p_med_s.index and pd.notna(p_med_s.loc[td]) else None
                )
                date_str = _doy_to_date_str(td)

                # Compute staleness vs real calendar today
                last_data_date = pd.Timestamp(year=current_year, month=1, day=1) + pd.Timedelta(days=td - 1)
                stale_days = max(0, (real_today.normalize() - last_data_date.normalize()).days)
                if stale_days <= 3:
                    marker_label = "HOJE"
                    title_line = f"<b>HOJE</b> — {date_str}"
                else:
                    marker_label = "ÚLT. OBS"
                    title_line = (
                        f"<b>ÚLTIMA OBS</b> — {date_str}<br>"
                        f"<span style='color:#c62828'>{stale_days} dias defasado</span>"
                    )

                lines = [title_line, f"Basis: {tv:.2f}"]
                if hist_med_val is not None:
                    delta = tv - hist_med_val
                    sign = "+" if delta >= 0 else ""
                    direction = "ACIMA" if delta > 0 else ("ABAIXO" if delta < 0 else "= a")
                    lines.append(f"Mediana histórica: {hist_med_val:.2f}")
                    lines.append(f"Δ: {sign}{delta:.2f} ({direction} do normal)")
                traces.append(go.Scatter(
                    x=[td], y=[tv], mode="markers",
                    marker=dict(
                        size=22, color=HIGHLIGHT_COLOR, symbol="star",
                        line=dict(width=2, color="white"),
                    ),
                    name=marker_label,
                    hovertemplate="<br>".join(lines) + "<extra></extra>",
                ))

    return traces


def _empty_fig(title: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(title=title, template="plotly_white")
    return fig


def _trace_visibility_helpers(traces_per_loc, total):
    def _vis(loc: str) -> list[bool]:
        v = [False] * total
        s, e = traces_per_loc[loc]
        for i in range(s, e):
            v[i] = True
        return v
    return _vis


def build(df: pd.DataFrame, pair: BasisPairConfig) -> go.Figure:
    """Build per-pair figure with single praça dropdown (legacy mode + tests)."""
    info = PAIR_DISPLAY[pair.label]
    if df.empty:
        return _empty_fig(f"{info.title} — sem dados")

    today = df["date"].max()
    fig = go.Figure()
    traces_per_loc: dict[str, tuple[int, int]] = {}

    # Order praças by total observations (most-traded first)
    loc_order = (
        df.groupby("location")["value"].count().sort_values(ascending=False).index.tolist()
    )

    for loc in loc_order:
        loc_df = df[df["location"] == loc]
        traces = _climate_normal_traces(loc_df, today)
        if not traces:
            continue
        s = len(fig.data)
        for t in traces:
            t.visible = False
            fig.add_trace(t)
        traces_per_loc[loc] = (s, len(fig.data))

    if not traces_per_loc:
        return _empty_fig(f"{info.title} — sem dados")

    first_loc = next(iter(traces_per_loc))
    total = len(fig.data)
    _vis = _trace_visibility_helpers(traces_per_loc, total)

    for i, val in enumerate(_vis(first_loc)):
        # Preserve legend-only state for past-year traces
        if fig.data[i].visible == "legendonly":
            continue
        fig.data[i].visible = val

    buttons = [
        dict(
            label=loc,
            method="update",
            args=[{"visible": _vis(loc)}, {"title": f"{info.title} — {loc}"}],
        )
        for loc in traces_per_loc
    ]

    fig.update_layout(
        title=f"{info.title} — {first_loc}",
        xaxis=dict(
            title="Dia do ano (calendário)",
            tickmode="array",
            tickvals=DOY_TICKVALS,
            ticktext=DOY_TICKTEXT,
            range=[0.5, 366.5],
        ),
        yaxis=dict(title=info.yaxis, zeroline=True, zerolinecolor="rgba(0,0,0,0.3)"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=-0.28, xanchor="center", x=0.5),
        updatemenus=[dict(
            type="dropdown", direction="down",
            x=0.0, xanchor="left", y=1.15, yanchor="top",
            buttons=buttons, showactive=True,
        )],
        template="plotly_white",
        height=680,
    )
    return fig


def build_combined(pair_data: list[tuple[BasisPairConfig, pd.DataFrame]]) -> go.Figure:
    """Build ONE figure with 3-level cascading dropdowns: Commodity → Vs → Praça.

    The commodity dropdown re-populates the Vs dropdown's buttons (which in turn
    re-populates the praça dropdown). All via Plotly relayout, no JS.
    """
    fig = go.Figure()

    trace_idx_map: dict[tuple[str, str], tuple[int, int]] = {}
    pair_locations: dict[str, list[str]] = {}
    pair_meta: dict[str, dict] = {}
    # Per-praça status: last_date, dropdown_label, status ('active'|'stale')
    loc_meta: dict[tuple[str, str], dict] = {}

    # Order: preserve commodity order from input, build commodity → list of pairs
    commodity_to_pairs: dict[str, list[BasisPairConfig]] = {}

    real_today = pd.Timestamp.today().normalize()
    # A praça is "stale" if its last observation is > 30 days from real_today.
    # 30 days tolerates weekend gaps + market holidays + brief outages.
    STALE_THRESHOLD_DAYS = 30

    for pair, df in pair_data:
        if df.empty:
            continue
        info = PAIR_DISPLAY[pair.label]
        today = df["date"].max()
        stale_days = max(0, (real_today - today.normalize()).days)
        pair_meta[pair.label] = {
            "title": info.title,
            "yaxis": info.yaxis,
            "commodity": pair.commodity,
            "commodity_label": COMMODITY_LABELS.get(pair.commodity, pair.commodity.upper()),
            "futures_slug": _futures_slug(pair.label),
            "futures_label": FUTURES_LABELS.get(_futures_slug(pair.label), _futures_slug(pair.label).upper()),
            "last_data_str": today.strftime("%Y-%m-%d"),
            "stale_days": stale_days,
        }
        commodity_to_pairs.setdefault(pair.commodity, []).append(pair)

        loc_counts = df.groupby("location")["value"].count().sort_values(ascending=False)
        last_per_loc = df.groupby("location")["date"].max()

        for loc in loc_counts.index:
            loc_df = df[df["location"] == loc]
            traces = _climate_normal_traces(loc_df, today, real_today=real_today)
            if not traces:
                continue
            s = len(fig.data)
            for t in traces:
                # Past-year traces stay legend-only; others start hidden
                if t.visible != "legendonly":
                    t.visible = False
                fig.add_trace(t)
            trace_idx_map[(pair.label, loc)] = (s, len(fig.data))
            pair_locations.setdefault(pair.label, []).append(loc)

            loc_last = last_per_loc[loc]
            loc_stale_days = max(0, (real_today - loc_last.normalize()).days)
            if loc_stale_days <= STALE_THRESHOLD_DAYS:
                status = "active"
                dropdown_label = loc
            else:
                status = "stale"
                # Compact prefix: [parou YYYY] for older, [parou YYYY-MM] for recent
                if loc_last.year < real_today.year:
                    dropdown_label = f"[parou {loc_last.year}] {loc}"
                else:
                    dropdown_label = f"[parou {loc_last.strftime('%Y-%m')}] {loc}"
            loc_meta[(pair.label, loc)] = {
                "last_date": loc_last,
                "loc_stale_days": loc_stale_days,
                "status": status,
                "dropdown_label": dropdown_label,
            }

    # Reorder each pair's locations: active first (preserve loc_counts order),
    # then stale at the end sorted by last_date desc (most recently dead first).
    for plabel in pair_locations:
        active = [
            l for l in pair_locations[plabel] if loc_meta[(plabel, l)]["status"] == "active"
        ]
        stale = sorted(
            [l for l in pair_locations[plabel] if loc_meta[(plabel, l)]["status"] == "stale"],
            key=lambda l: loc_meta[(plabel, l)]["last_date"],
            reverse=True,
        )
        pair_locations[plabel] = active + stale

    if not trace_idx_map:
        return _empty_fig("Seasonality — sem dados")

    # Sort each commodity's pairs by futures preference (CBOT > NYBOT > B3)
    for c in commodity_to_pairs:
        commodity_to_pairs[c].sort(
            key=lambda p: FUTURES_PRIORITY.get(_futures_slug(p.label), 99)
        )

    total = len(fig.data)

    def _vis(pair_label: str, loc: str) -> list[bool]:
        s, e = trace_idx_map.get((pair_label, loc), (0, 0))
        v = [False] * total
        for i in range(s, e):
            # Preserve legend-only state for past-year traces (they stay hidden by default)
            if fig.data[i].visible == "legendonly":
                v[i] = "legendonly"  # Plotly accepts string "legendonly" in visibility array
            else:
                v[i] = True
        return v

    def _banner(pair_label: str, loc: str) -> str:
        m = pair_meta[pair_label]
        lm = loc_meta.get((pair_label, loc), {})
        loc_last = lm.get("last_date")
        last_str = loc_last.strftime("%Y-%m-%d") if loc_last is not None else m["last_data_str"]

        if lm.get("status") == "stale":
            # Defunct praça — explicit red warning
            fresh_html = (
                f"<span style='color:#c62828;font-weight:bold'>"
                f"⚠ DEFUNTA — parou em {last_str} (sem ano corrente)"
                f"</span>"
            )
        else:
            # Active praça — colored chip based on praça's own staleness
            days = lm.get("loc_stale_days", m["stale_days"])
            if days <= 1:
                fresh_html = "<span style='color:#2e7d32'>(atualizado)</span>"
            elif days <= 7:
                fresh_html = f"<span style='color:#ef6c00'>({days} dias atrás)</span>"
            else:
                fresh_html = f"<span style='color:#c62828'>({days} dias defasado)</span>"
        return (
            f"<b style='font-size:24px;color:#1f3a5c'>{m['commodity_label']}</b>"
            f"<span style='font-size:14px;color:#555'>"
            f"  ·  basis vs <b>{m['futures_label']}</b>"
            f"  ·  <b style='color:#1f3a5c'>{loc}</b>"
            f"  ·  últ. obs: {last_str}"
            f"  {fresh_html}"
            f"  ·  hoje: {real_today.strftime('%Y-%m-%d')}"
            f"</span>"
        )

    def _praca_buttons(pair_label: str) -> list[dict]:
        m = pair_meta[pair_label]
        return [
            dict(
                label=loc_meta[(pair_label, loc)]["dropdown_label"],
                method="update",
                args=[
                    {"visible": _vis(pair_label, loc)},
                    {
                        "annotations[0].text": _banner(pair_label, loc),
                        "yaxis.title.text": m["yaxis"],
                    },
                ],
            )
            for loc in pair_locations[pair_label]
        ]

    def _vs_buttons(commodity: str) -> list[dict]:
        """Buttons for the 'Vs' dropdown: list of futures references in this commodity."""
        out = []
        for pair in commodity_to_pairs[commodity]:
            if pair.label not in pair_locations:
                continue
            first_loc = pair_locations[pair.label][0]
            m = pair_meta[pair.label]
            out.append(dict(
                label=m["futures_label"],
                method="update",
                args=[
                    {"visible": _vis(pair.label, first_loc)},
                    {
                        "annotations[0].text": _banner(pair.label, first_loc),
                        "yaxis.title.text": m["yaxis"],
                        "updatemenus[2].buttons": _praca_buttons(pair.label),
                        "updatemenus[2].active": 0,
                    },
                ],
            ))
        return out

    def _commodity_button(commodity: str) -> dict:
        first_pair = next(p for p in commodity_to_pairs[commodity] if p.label in pair_locations)
        first_loc = pair_locations[first_pair.label][0]
        m = pair_meta[first_pair.label]
        return dict(
            label=m["commodity_label"],
            method="update",
            args=[
                {"visible": _vis(first_pair.label, first_loc)},
                {
                    "annotations[0].text": _banner(first_pair.label, first_loc),
                    "yaxis.title.text": m["yaxis"],
                    "updatemenus[1].buttons": _vs_buttons(commodity),
                    "updatemenus[1].active": 0,
                    "updatemenus[2].buttons": _praca_buttons(first_pair.label),
                    "updatemenus[2].active": 0,
                },
            ],
        )

    commodities_in_order = [c for c in commodity_to_pairs.keys()
                            if any(p.label in pair_locations for p in commodity_to_pairs[c])]
    default_commodity = commodities_in_order[0]
    default_pair = next(p for p in commodity_to_pairs[default_commodity] if p.label in pair_locations)
    default_loc = pair_locations[default_pair.label][0]
    default_meta = pair_meta[default_pair.label]

    # Apply default visibility (preserve legendonly for past years)
    for i, val in enumerate(_vis(default_pair.label, default_loc)):
        fig.data[i].visible = val

    fig.update_layout(
        title="",
        xaxis=dict(
            title="Dia do ano (calendário)",
            tickmode="array",
            tickvals=DOY_TICKVALS,
            ticktext=DOY_TICKTEXT,
            range=[0.5, 366.5],
        ),
        yaxis=dict(title=default_meta["yaxis"], zeroline=True, zerolinecolor="rgba(0,0,0,0.3)"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=-0.32, xanchor="center", x=0.5),
        updatemenus=[
            # 0: Commodity dropdown
            dict(
                type="dropdown", direction="down",
                x=0.0, xanchor="left", y=1.32, yanchor="top",
                buttons=[_commodity_button(c) for c in commodities_in_order],
                showactive=True,
                pad=dict(t=4, l=4, r=4, b=4),
            ),
            # 1: Vs (futures reference) dropdown
            dict(
                type="dropdown", direction="down",
                x=0.16, xanchor="left", y=1.32, yanchor="top",
                buttons=_vs_buttons(default_commodity),
                showactive=True,
                pad=dict(t=4, l=4, r=4, b=4),
            ),
            # 2: Praça dropdown
            dict(
                type="dropdown", direction="down",
                x=0.30, xanchor="left", y=1.32, yanchor="top",
                buttons=_praca_buttons(default_pair.label),
                showactive=True,
                pad=dict(t=4, l=4, r=4, b=4),
            ),
        ],
        annotations=[
            # 0: commodity banner (live-updates with dropdowns)
            dict(
                text=_banner(default_pair.label, default_loc),
                x=0.5, xref="paper", y=1.16, yref="paper",
                xanchor="center", yanchor="bottom",
                showarrow=False, align="center",
            ),
            # 1-3: dropdown labels
            dict(text="<b>Commodity:</b>", x=0.0, xref="paper", y=1.36, yref="paper",
                 showarrow=False, xanchor="left", font=dict(size=11)),
            dict(text="<b>Vs:</b>", x=0.16, xref="paper", y=1.36, yref="paper",
                 showarrow=False, xanchor="left", font=dict(size=11)),
            dict(text="<b>Praça:</b>", x=0.30, xref="paper", y=1.36, yref="paper",
                 showarrow=False, xanchor="left", font=dict(size=11)),
        ],
        template="plotly_white",
        height=720,
        margin=dict(t=140, l=70, r=30, b=80),
    )
    return fig
