"""On-read derived views.

Per holdings-schema.md: derived ratios (OPM%, FCF, gross margin) and the
portfolio-wide upcoming-events roll-up are NOT persisted — they are computed
on read. This module is the single home for those computations so the readers
stay shape-pure and the templates stay logic-free.

No file I/O lives here. No persistence. All inputs are dicts/lists from
``readers.py``; all outputs are plain dicts/lists for the templates.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from . import readers


# ---------------------------------------------------------------------------
# Fundamentals — derived per-quarter ratios
# ---------------------------------------------------------------------------

def derive_fundamentals_rows(
    fundamentals: Optional[dict[str, Any]],
    max_quarters: int = 8,
) -> list[dict[str, Any]]:
    """Return the most-recent ``max_quarters`` quarters as a row dict each.

    Adds derived columns:
      gross_margin_pct  -- gross_profit / revenue * 100   (when both present)
      opm_pct           -- operating_income / revenue * 100  (when both present)
      net_margin_pct    -- net_income / revenue * 100     (when both present)
      fcf_mm            -- echoed straight from free_cash_flow_mm if present;
                           else operating_cash_flow_mm + capex_mm when both
                           are present (capex carried with its sign per schema).

    The schema is explicit that derived ratios are not stored. We compute on
    read here, leave them absent (key omitted) when inputs are missing, and
    never silently substitute zero.
    """
    if not fundamentals:
        return []
    quarters = fundamentals.get("quarters") or []
    if not isinstance(quarters, list):
        return []
    # Newest first. The on-disk convention is ascending; reverse for display.
    rows: list[dict[str, Any]] = []
    for q in reversed(quarters[-max_quarters:]):
        if not isinstance(q, dict):
            continue
        out: dict[str, Any] = dict(q)
        rev = q.get("revenue_mm")
        gp = q.get("gross_profit_mm")
        oi = q.get("operating_income_mm")
        ni = q.get("net_income_mm")
        ocf = q.get("operating_cash_flow_mm")
        capex = q.get("capex_mm")
        fcf = q.get("free_cash_flow_mm")

        if isinstance(rev, (int, float)) and rev:
            if isinstance(gp, (int, float)):
                out["gross_margin_pct"] = round(gp / rev * 100.0, 2)
            if isinstance(oi, (int, float)):
                out["opm_pct"] = round(oi / rev * 100.0, 2)
            if isinstance(ni, (int, float)):
                out["net_margin_pct"] = round(ni / rev * 100.0, 2)
        if isinstance(fcf, (int, float)):
            out["fcf_mm"] = fcf
        elif isinstance(ocf, (int, float)) and isinstance(capex, (int, float)):
            out["fcf_mm"] = ocf + capex
        rows.append(out)
    return rows


def derive_fundamentals_series(
    rows: list[dict[str, Any]],
    key: str,
) -> list[Optional[float]]:
    """Pull a numeric series out of the derived-rows table for sparklines.

    Returns oldest-first so the sparkline reads left-to-right as time forward.
    """
    series: list[Optional[float]] = []
    for r in reversed(rows):
        v = r.get(key)
        series.append(float(v) if isinstance(v, (int, float)) else None)
    return series


# ---------------------------------------------------------------------------
# Sparkline SVG (inline, no JS, no chart lib)
# ---------------------------------------------------------------------------

def sparkline_svg(
    values: list[Optional[float]],
    width: int = 120,
    height: int = 28,
    pad: int = 2,
) -> str:
    """Return an inline SVG sparkline string for the given series.

    None values create gaps (no line segment). All values equal -> flat line
    in the vertical centre. An empty/all-None series returns an empty string
    so the template can branch on truthiness.
    """
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return ""
    n = len(values)
    if n == 1:
        # A single point degenerates; render a dot.
        cx = width / 2
        cy = height / 2
        return (
            f'<svg class="spark" viewBox="0 0 {width} {height}" '
            f'preserveAspectRatio="none" aria-hidden="true">'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2"/></svg>'
        )
    lo = min(nums)
    hi = max(nums)
    span = hi - lo or 1.0
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad
    points: list[tuple[float, Optional[float]]] = []
    for i, v in enumerate(values):
        x = pad + (i / (n - 1)) * inner_w
        if isinstance(v, (int, float)):
            y = pad + inner_h - ((v - lo) / span) * inner_h
            points.append((x, y))
        else:
            points.append((x, None))

    # Build polyline segments separated by None gaps.
    segments: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    for x, y in points:
        if y is None:
            if cur:
                segments.append(cur)
                cur = []
        else:
            cur.append((x, y))
    if cur:
        segments.append(cur)

    paths = []
    for seg in segments:
        if len(seg) == 1:
            x, y = seg[0]
            paths.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.5"/>')
        else:
            d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}"
                         for i, (x, y) in enumerate(seg))
            paths.append(f'<path d="{d}" fill="none" stroke-width="1.5"/>')
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" aria-hidden="true">'
        + "".join(paths) + "</svg>"
    )


# ---------------------------------------------------------------------------
# Assumptions cross-quarter view
# ---------------------------------------------------------------------------

def derive_assumptions_view(
    assumptions: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Shape assumptions.yaml for the per-position page.

    Returns:
      {
        keys: ["A1", "A2", "A3", "A4"],
        rows: [
          {
            key, text, category, quarterly_checkpoint, transcript_checkpoint,
            thesis_horizon_target, checkpoint_metric_source,
            grades_by_quarter: [
              { period, graded_on, source,
                quarterly: {grade, strength, note} | None,
                transcript: ... | None,
                horizon: ... | None }
            ],
            transcript_pending: bool   # quarterly graded but transcript missing
                                       # for the latest quarter (matches the
                                       # holdings-schema "transcript-gap" rule).
          },
          ...
        ],
        latest_period: str | None,
      }

    Returns None when the file is absent.
    """
    if not assumptions:
        return None
    asmap = assumptions.get("assumptions") or {}
    if not isinstance(asmap, dict):
        return None
    quarters = assumptions.get("quarters") or []
    if not isinstance(quarters, list):
        quarters = []

    keys = sorted(asmap.keys())
    latest_period = quarters[-1].get("period") if quarters else None

    rows = []
    for k in keys:
        a = asmap.get(k) or {}
        if not isinstance(a, dict):
            continue
        per_quarter = []
        latest_quarterly_present = False
        latest_transcript_present = False
        has_transcript_anchor = bool(a.get("transcript_checkpoint"))
        for q in quarters:
            if not isinstance(q, dict):
                continue
            grades = (q.get("grades") or {}).get(k) or {}
            entry = {
                "period": q.get("period"),
                "graded_on": q.get("graded_on"),
                "source": q.get("source"),
                "quarterly": grades.get("quarterly"),
                "transcript": grades.get("transcript"),
                "horizon": grades.get("horizon"),
            }
            per_quarter.append(entry)
            if q.get("period") == latest_period:
                latest_quarterly_present = bool(entry["quarterly"])
                latest_transcript_present = bool(entry["transcript"])

        transcript_pending = (
            has_transcript_anchor
            and latest_period is not None
            and latest_quarterly_present
            and not latest_transcript_present
        )
        rows.append(
            {
                "key": k,
                "text": a.get("text"),
                "category": a.get("category"),
                "quarterly_checkpoint": a.get("quarterly_checkpoint"),
                "transcript_checkpoint": a.get("transcript_checkpoint"),
                "thesis_horizon_target": a.get("thesis_horizon_target"),
                "checkpoint_metric_source": a.get("checkpoint_metric_source"),
                "grades_by_quarter": per_quarter,
                "transcript_pending": transcript_pending,
            }
        )

    return {"keys": keys, "rows": rows, "latest_period": latest_period}


# ---------------------------------------------------------------------------
# Calendar — per-position upcoming + portfolio-wide roll-up
# ---------------------------------------------------------------------------

def _coerce_date(v: Any) -> Optional[date]:
    """PyYAML may return a date, a datetime, or a string. Coerce uniformly."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return datetime.strptime(v.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def derive_calendar_split(
    calendar: Optional[dict[str, Any]],
    today: Optional[date] = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return ``{"upcoming": [...], "past": [...]}`` from a calendar.yaml dict.

    Re-classifies each row by date: anything with a date < today moves to past,
    everything else stays in upcoming. Handles either ``upcoming:`` / ``past:``
    blocks, or a single ``events:`` list.
    """
    today = today or date.today()
    bag: list[dict[str, Any]] = []
    if calendar:
        for src in ("upcoming", "past", "events"):
            block = calendar.get(src)
            if isinstance(block, list):
                bag.extend(b for b in block if isinstance(b, dict))
    upcoming: list[dict[str, Any]] = []
    past: list[dict[str, Any]] = []
    for row in bag:
        d = _coerce_date(row.get("date"))
        out = dict(row)
        out["_date"] = d
        if d is None:
            # Dateless rows go to upcoming; the user can fix.
            upcoming.append(out)
        elif d >= today:
            upcoming.append(out)
        else:
            past.append(out)
    upcoming.sort(key=lambda r: r["_date"] or date.max)
    past.sort(key=lambda r: r["_date"] or date.min, reverse=True)
    return {"upcoming": upcoming, "past": past}


def derive_portfolio_calendar(
    holdings_dir: Path,
    slugs: list[str],
    window_days: int,
    today: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Merge every workspace's calendar.yaml upcoming events.

    Tags each row with its source slug. Sorted by date, filtered to the next
    ``window_days``. Rows with no date are excluded from the cross-position
    view (they are still visible on the per-position page).
    """
    today = today or date.today()
    horizon = today + timedelta(days=window_days)
    out: list[dict[str, Any]] = []
    for slug in slugs:
        cal = readers.read_calendar(holdings_dir / slug)
        split = derive_calendar_split(cal, today=today)
        for row in split["upcoming"]:
            d = row.get("_date")
            if d is None or d > horizon:
                continue
            row["_slug"] = slug
            out.append(row)
    out.sort(key=lambda r: r["_date"])
    return out


def derive_portfolio_calendar_month(
    events: list[dict[str, Any]],
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Return a compact current-month calendar grid for the overview page."""
    today = today or date.today()
    first = today.replace(day=1)
    if first.month == 12:
        next_month = first.replace(year=first.year + 1, month=1)
    else:
        next_month = first.replace(month=first.month + 1)
    days_in_month = (next_month - first).days
    event_dates: dict[date, list[dict[str, Any]]] = {}
    for event in events:
        event_date = event.get("_date")
        if isinstance(event_date, date) and event_date.month == first.month:
            event_dates.setdefault(event_date, []).append(event)

    cells: list[dict[str, Any]] = []
    for _ in range(first.weekday()):
        cells.append({"day": "", "date": None, "events": [], "is_today": False})
    for day in range(1, days_in_month + 1):
        current = first.replace(day=day)
        cells.append(
            {
                "day": day,
                "date": current,
                "events": event_dates.get(current, []),
                "is_today": current == today,
            }
        )
    while len(cells) % 7:
        cells.append({"day": "", "date": None, "events": [], "is_today": False})
    weeks = [cells[i:i + 7] for i in range(0, len(cells), 7)]
    return {
        "month_label": today.strftime("%B %Y"),
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "weeks": weeks,
    }


def derive_overview_summary(assets: readers.AssetsView) -> dict[str, Any]:
    """Compute overview-only portfolio summaries from assets.md."""
    totals = assets.dynamic.get("totals") or {}
    fx_rates = assets.dynamic.get("fx_rates") or {}
    usd_inr = _safe_float((fx_rates.get("usd_inr") or {}).get("rate"))

    rows_by_ccy = assets.holdings_by_currency
    country_order = [("INR", "India"), ("USD", "US")]
    countries: list[dict[str, Any]] = []
    total_positions = sum(len(rows) for rows in rows_by_ccy.values())

    for ccy, label in country_order:
        rows = rows_by_ccy.get(ccy, [])
        current_key = "india_total_inr" if ccy == "INR" else "us_all_total_inr"
        weight_key = "india_weight_pct" if ccy == "INR" else None
        if ccy == "USD" and totals.get("us_all_total_inr") is not None:
            weight_pct = _pct(totals.get("us_all_total_inr"), totals.get("grand_total_inr"))
        else:
            weight_pct = _safe_float(totals.get(weight_key)) if weight_key else None
        return_view = _derive_return_view(rows)
        countries.append(
            {
                "currency": ccy,
                "label": label,
                "count": len(rows),
                "value_inr": _safe_float(totals.get(current_key)),
                "weight_pct": weight_pct,
                **return_view,
            }
        )

    largest = _derive_largest_position(rows_by_ccy, totals, usd_inr)
    cash = _derive_cash_split(assets.cash_rows)
    holdings_total_inr = _safe_float(totals.get("grand_total_inr"))
    cash_total_inr = _safe_float(totals.get("cash_total_inr"))
    if holdings_total_inr is not None and cash_total_inr is not None:
        holdings_total_inr -= cash_total_inr

    return {
        "total_positions": total_positions,
        "holdings_total_inr": holdings_total_inr,
        "countries": countries,
        "largest": largest,
        "cash": cash,
    }


def _safe_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _pct(part: Any, whole: Any) -> Optional[float]:
    part_num = _safe_float(part)
    whole_num = _safe_float(whole)
    if part_num is None or not whole_num:
        return None
    return round(part_num / whole_num * 100.0, 2)


def _derive_return_view(rows: list[readers.HoldingRow]) -> dict[str, Any]:
    cost_basis = 0.0
    current_value = 0.0
    covered = 0
    missing: list[str] = []
    for row in rows:
        if row.shares is None or row.avg_cost is None or row.current_value is None:
            missing.append(row.ticker)
            continue
        cost_basis += row.shares * row.avg_cost
        current_value += row.current_value
        covered += 1
    return_pct = None
    if cost_basis:
        return_pct = round((current_value - cost_basis) / cost_basis * 100.0, 1)
    return {
        "return_pct": return_pct,
        "return_coverage": covered,
        "return_missing": missing,
    }


def _derive_largest_position(
    rows_by_ccy: dict[str, list[readers.HoldingRow]],
    totals: dict[str, Any],
    usd_inr: Optional[float],
) -> dict[str, Any] | None:
    grand_total_inr = _safe_float(totals.get("grand_total_inr"))
    best: dict[str, Any] | None = None
    for ccy, rows in rows_by_ccy.items():
        for row in rows:
            if row.current_value is None:
                continue
            value_inr = row.current_value
            if ccy == "USD":
                if usd_inr is None:
                    continue
                value_inr = row.current_value * usd_inr
            candidate = {
                "ticker": row.ticker,
                "name": row.name,
                "currency": ccy,
                "value_native": row.current_value,
                "value_inr": value_inr,
                "weight_pct": _pct(value_inr, grand_total_inr),
            }
            if best is None or value_inr > best["value_inr"]:
                best = candidate
    return best


def _derive_cash_split(cash_rows: list[dict[str, str]]) -> dict[str, Any]:
    by_currency: dict[str, dict[str, Any]] = {
        "INR": {"label": "India cash", "currency": "INR", "balance": 0.0, "accounts": []},
        "USD": {"label": "US cash", "currency": "USD", "balance": 0.0, "accounts": []},
    }
    for row in cash_rows:
        currency = (row.get("currency") or "").upper()
        if currency not in by_currency:
            by_currency[currency] = {
                "label": f"{currency} cash",
                "currency": currency,
                "balance": 0.0,
                "accounts": [],
            }
        balance = _safe_float(row.get("balance"))
        if balance is not None:
            by_currency[currency]["balance"] += balance
        by_currency[currency]["accounts"].append(row)
    return {"by_currency": [by_currency[k] for k in sorted(by_currency.keys())]}


# ---------------------------------------------------------------------------
# Holdings overview enrichment
# ---------------------------------------------------------------------------

def slug_for_ticker(ticker: str, registry: list[readers.RegistryRow]) -> Optional[str]:
    """Best-effort ticker -> slug.

    Strategy:
      1. Exact instance_key match (lowercased).
      2. instrument_class == 'equity' and display_name's first word matches the ticker.

    Returns None when nothing matches; the dashboard then renders the row with
    no /position/<slug> link, as designed.
    """
    if not ticker:
        return None
    key = ticker.lower().replace(".", "").replace("-", "").replace("_", "")
    by_key = {r.instance_key.lower(): r.instance_key for r in registry}
    if key in by_key:
        return by_key[key]
    # Some Indian tickers (e.g. HBLENGINE) match an instance_key directly.
    if ticker.lower() in by_key:
        return by_key[ticker.lower()]
    return None
