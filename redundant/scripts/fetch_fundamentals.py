"""
Veda - fundamentals + valuation fetcher.

Fetches quarterly financials and computes archetype-specific valuation zones.
Called by the fundamentals-fetcher subagent (see internal/agents/fundamentals-fetcher.md).

Data sources:
  - US equities: yfinance (quarterly_income_stmt, quarterly_balance_sheet,
    quarterly_cash_flow, stock.info)
  - India equities: Screener.in HTML scrape (#quarters section) + Chart API

Zone computation (mirrors StockClarity's valuation_fetcher.py):
  - GROWTH (profitable): PEG size-tiered thresholds
  - GROWTH (unprofitable): P/S percentile
  - INCOME_VALUE: PE percentile + PEG override guard
  - TURNAROUND: EV/EBITDA percentile
  - CYCLICAL: EV/EBITDA percentile (inverted for commodity)
  - Banks/NBFCs: P/B percentile (overrides archetype)

Output: JSON to stdout per the contract in fundamentals-fetcher.md.

Usage:
    python scripts/fetch_fundamentals.py \\
        --ticker NVDA \\
        --market US \\
        --archetype GROWTH \\
        --archetype-secondary CYCLICAL \\  # optional; emits a parallel `secondary:` block
        --sector "Semiconductors" \\
        --sector-kind OTHER \\
        --history-quarters 12

Exit codes:
    0 - success or partial success (check JSON `errors` array)
    1 - complete failure; JSON with `errors` field
    2 - bad usage (argparse)

Requires ``yfinance`` and ``requests`` to be installed (see requirements.txt).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Shared with the core scripts: market detection, sector classification, and
# Screener.in HTTP settings. This file is quarantined in redundant/scripts/, so
# reach up to the core scripts/ dir (repo_root/scripts) for _common.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from _common import (  # noqa: E402
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    SCREENER_CHART_HEADERS,
    SCREENER_HEADERS,
    SCREENER_REQUEST_DELAY,
    classify_sector_kind,  # re-exported for callers; not used directly here
    detect_market,
    is_banking_sector,
)

# Silence noisy loggers
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.WARNING)


# =============================================================================
# Constants — mirrored from StockClarity's valuation_fetcher.py
# (Screener HTTP settings, retry knobs, sector keyword lists, and
# is_banking_sector live in scripts/_common.py.)
# =============================================================================

# Size tier thresholds (native currency: INR for India, USD for US)
# INR thresholds: MEGA > ₹10 lakh Cr, LARGE > ₹50K Cr, MID > ₹10K Cr
# USD thresholds: MEGA > $200B, LARGE > $10B, MID > $2B
_SIZE_TIERS_INR = [
    ("MEGA", 10_000_000_000_000),
    ("LARGE", 500_000_000_000),
    ("MID", 100_000_000_000),
    ("SMALL", 0),
]

_SIZE_TIERS_USD = [
    ("MEGA", 200_000_000_000),
    ("LARGE", 10_000_000_000),
    ("MID", 2_000_000_000),
    ("SMALL", 0),
]

# PEG thresholds for GROWTH archetype (profitable)
# PEG = current/trailing PE / future earnings growth pct. E.g., PE=50, growth=25% → PEG = 2.0
_PEG_THRESHOLDS = {
    "MEGA": (0.8, 1.5),   # (CHEAP_below, EXPENSIVE_above)
    "LARGE": (1.0, 2.0),
    "MID": (1.2, 2.5),
    "SMALL": (1.5, 3.0),
}

# INCOME_VALUE PEG override thresholds (tighter than GROWTH)
_INCOME_VALUE_PEG_THRESHOLDS = {
    "MEGA": (1.2, 3.0),   # (override EXPENSIVE→FAIR if PEG ≤, override CHEAP→FAIR if PEG >)
    "LARGE": (1.5, 3.0),
    "MID": (1.8, 3.5),
    "SMALL": (2.0, 4.0),
}

# PE absolute cap: above this, force EXPENSIVE regardless of PEG
PE_ABSOLUTE_CAP = 150


# =============================================================================
# Helper functions
# =============================================================================

def compute_size_tier(market_cap: Optional[float], is_indian: bool) -> str:
    """Determine the market-cap size tier for a company."""
    if market_cap is None or market_cap <= 0:
        return "SMALL"
    tiers = _SIZE_TIERS_INR if is_indian else _SIZE_TIERS_USD
    for tier_name, threshold in tiers:
        if market_cap > threshold:
            return tier_name
    return "SMALL"


def determine_primary_metric(
    archetype: str,
    sector: Optional[str],
    sector_kind: Optional[str],
    has_positive_pe: bool,
) -> str:
    """Determine the primary valuation metric for a company.

    Logic (all Python, no LLM):
      1. Banks/NBFCs (sector match) → PB, regardless of archetype
      2. GROWTH + negative/no earnings → PS
      3. GROWTH + positive earnings → PEG (PE is the basis)
      4. INCOME_VALUE → PE
      5. TURNAROUND → EV_EBITDA
      6. CYCLICAL → EV_EBITDA
      7. Default → PE
    """
    if is_banking_sector(sector, sector_kind):
        return "PB"
    if archetype == "GROWTH":
        return "PEG" if has_positive_pe else "PS"
    if archetype == "INCOME_VALUE":
        return "PE"
    if archetype in ("TURNAROUND", "CYCLICAL"):
        return "EV_EBITDA"
    return "PE"


def compute_percentiles(values: List[float]) -> Tuple[float, float]:
    """Compute 25th and 75th percentiles using linear interpolation."""
    if len(values) < 4:
        raise ValueError(f"Need at least 4 values for percentiles, got {len(values)}")
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    # 25th percentile
    k25 = (n - 1) * 0.25
    f25 = int(k25)
    c25 = min(f25 + 1, n - 1)
    p25 = sorted_vals[f25] + (k25 - f25) * (sorted_vals[c25] - sorted_vals[f25])
    # 75th percentile
    k75 = (n - 1) * 0.75
    f75 = int(k75)
    c75 = min(f75 + 1, n - 1)
    p75 = sorted_vals[f75] + (k75 - f75) * (sorted_vals[c75] - sorted_vals[f75])
    return round(p25, 2), round(p75, 2)


def quarter_from_date(date_str: str) -> str:
    """Convert ISO date to quarter label. '2026-03-31' -> '2026-Q1'."""
    dt = datetime.fromisoformat(date_str)
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def safe_round(val: Optional[float], decimals: int = 2) -> Optional[float]:
    """Round a value if not None, preserving None."""
    return round(val, decimals) if val is not None else None


def safe_float(val: Any) -> Optional[float]:
    """Convert to float, returning None on failure or NaN."""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (ValueError, TypeError):
        return None


def to_millions(val: Optional[float]) -> Optional[float]:
    """Convert raw value to millions."""
    if val is None:
        return None
    return round(val / 1_000_000, 2)


# =============================================================================
# US Fetcher (yfinance)
# =============================================================================

def fetch_us_fundamentals(
    ticker: str,
    history_quarters: int,
) -> Tuple[List[Dict], Dict, List[Dict], List[str]]:
    """Fetch quarterly fundamentals for a US stock from yfinance.

    Returns:
        (quarters_list, valuation_dict, annuals_list, errors_list)
    """
    import yfinance as yf

    errors: List[str] = []
    quarters: List[Dict] = []
    annuals: List[Dict] = []

    try:
        with contextlib.redirect_stderr(io.StringIO()):
            stock = yf.Ticker(ticker)
            info = stock.info or {}
    except Exception as exc:
        return [], {}, [], [f"Failed to fetch info for {ticker}: {exc}"]

    # === Current valuation ratios ===
    current_pe = safe_float(info.get("trailingPE"))
    current_forward_pe = safe_float(info.get("forwardPE"))
    current_pb = safe_float(info.get("priceToBook"))
    current_ps = safe_float(info.get("priceToSalesTrailing12Months"))
    current_ev_ebitda = safe_float(info.get("enterpriseToEbitda"))
    market_cap = safe_float(info.get("marketCap"))
    dividend_yield = safe_float(info.get("dividendYield"))
    provider_peg = safe_float(info.get("pegRatio"))
    if provider_peg is None:
        provider_peg = safe_float(info.get("trailingPegRatio"))
    earnings_growth = _to_pct(safe_float(info.get("earningsGrowth")))
    revenue_growth = _to_pct(safe_float(info.get("revenueGrowth")))

    # Filter out negative values
    if current_pe is not None and current_pe <= 0:
        current_pe = None
    if current_forward_pe is not None and current_forward_pe <= 0:
        current_forward_pe = None
    if current_pb is not None and current_pb <= 0:
        current_pb = None
    if current_ps is not None and current_ps <= 0:
        current_ps = None
    if current_ev_ebitda is not None and current_ev_ebitda <= 0:
        current_ev_ebitda = None
    if provider_peg is not None and provider_peg <= 0:
        provider_peg = None

    inferred_forward_growth_pct = None
    if current_forward_pe is not None and provider_peg is not None:
        # Yahoo's PEG is provider-specific and appears tied to forward PE.
        # Veda's Lynch-style methodology is current/trailing PE divided by
        # future growth, so infer the growth denominator and recompute PEG
        # later from current_pe.
        inferred_forward_growth_pct = current_forward_pe / provider_peg

    # Veda-methodology PEG: trailing PE divided by inferred forward growth
    # (Lynch convention). Mirrors the capped-growth math in _compute_peg_zone
    # so the default multiples line matches the verdict produced with --archetype.
    current_peg = None
    if current_pe is not None and inferred_forward_growth_pct is not None and inferred_forward_growth_pct > 0:
        capped_growth = min(inferred_forward_growth_pct, 100.0)
        current_peg = current_pe / capped_growth

    # Manual EV/EBITDA computation if yfinance didn't return it
    if current_ev_ebitda is None and market_cap and market_cap > 0:
        ebitda_raw = safe_float(info.get("ebitda"))
        ev_raw = safe_float(info.get("enterpriseValue"))
        if ebitda_raw and ebitda_raw > 0 and ev_raw and ev_raw > 0:
            current_ev_ebitda = round(ev_raw / ebitda_raw, 2)

    valuation = {
        "current_pe": safe_round(current_pe),
        "current_forward_pe": safe_round(current_forward_pe),
        "current_pb": safe_round(current_pb),
        "current_ps": safe_round(current_ps),
        "current_ev_ebitda": safe_round(current_ev_ebitda),
        "current_dividend_yield_pct": safe_round(_normalize_yf_dividend_yield_pct(dividend_yield)),
        "current_peg": safe_round(current_peg),
        "current_peg_source": (
            "trailingPE / inferred_forward_growth_pct (capped at 100%)"
            if current_peg is not None else None
        ),
        "provider_peg": safe_round(provider_peg),
        "provider_peg_source": "yfinance.info.pegRatio" if provider_peg is not None else None,
        "inferred_forward_growth_pct": safe_round(inferred_forward_growth_pct),
        "inferred_forward_growth_source": (
            "yfinance.info.forwardPE / yfinance.info.pegRatio"
            if inferred_forward_growth_pct is not None else None
        ),
        "yfinance_earnings_growth_pct": safe_round(earnings_growth),
        "yfinance_revenue_growth_pct": safe_round(revenue_growth),
        "market_cap": market_cap,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "yfinance",
    }

    # === Quarterly income statement ===
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            income_stmt = stock.quarterly_income_stmt
    except Exception as exc:
        errors.append(f"Income statement fetch failed: {exc}")
        income_stmt = None

    # === Quarterly balance sheet ===
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            balance_sheet = stock.quarterly_balance_sheet
    except Exception as exc:
        errors.append(f"Balance sheet fetch failed: {exc}")
        balance_sheet = None

    # === Quarterly cash flow ===
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            cash_flow = stock.quarterly_cash_flow
    except Exception as exc:
        errors.append(f"Cash flow fetch failed: {exc}")
        cash_flow = None

    # Build quarters list
    if income_stmt is not None and not income_stmt.empty:
        # Columns are quarter-end dates, rows are line items
        for col_date in income_stmt.columns[:history_quarters]:
            try:
                quarter_end_dt = col_date.to_pydatetime()
                quarter_end = quarter_end_dt.strftime("%Y-%m-%d")
                period = quarter_from_date(quarter_end)

                q_data: Dict[str, Any] = {
                    "period": period,
                    "as_of": quarter_end,
                    "source": "yfinance",
                }

                # Income statement fields
                q_data["revenue_mm"] = to_millions(_get_yf_metric(
                    income_stmt, col_date, ["Total Revenue", "Revenue", "Net Sales"]
                ))
                q_data["gross_profit_mm"] = to_millions(_get_yf_metric(
                    income_stmt, col_date, ["Gross Profit"]
                ))
                q_data["operating_expenses_mm"] = to_millions(_get_yf_metric(
                    income_stmt, col_date, ["Total Operating Expenses", "Operating Expense"]
                ))
                q_data["operating_income_mm"] = to_millions(_get_yf_metric(
                    income_stmt, col_date, ["Operating Income", "EBIT"]
                ))
                q_data["net_income_mm"] = to_millions(_get_yf_metric(
                    income_stmt, col_date, ["Net Income", "Net Income Common Stockholders"]
                ))
                q_data["eps_diluted"] = safe_round(_get_yf_metric(
                    income_stmt, col_date, ["Diluted EPS", "Basic EPS"]
                ))

                # Diluted shares
                shares = _get_yf_metric(
                    income_stmt, col_date, ["Diluted Average Shares", "Basic Average Shares"]
                )
                q_data["diluted_shares_mm"] = to_millions(shares)

                # Cash flow fields (if available)
                if cash_flow is not None and not cash_flow.empty and col_date in cash_flow.columns:
                    ocf = _get_yf_metric(
                        cash_flow, col_date, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]
                    )
                    capex = _get_yf_metric(
                        cash_flow, col_date, ["Capital Expenditure", "Purchase Of PPE"]
                    )
                    q_data["operating_cash_flow_mm"] = to_millions(ocf)
                    if capex is not None:
                        # CapEx is typically negative in yfinance; preserve sign
                        q_data["capex_mm"] = to_millions(capex)
                        if ocf is not None:
                            q_data["free_cash_flow_mm"] = to_millions(ocf + capex)

                # Balance sheet fields (if available)
                if balance_sheet is not None and not balance_sheet.empty and col_date in balance_sheet.columns:
                    q_data["cash_and_equivalents_mm"] = to_millions(_get_yf_metric(
                        balance_sheet, col_date, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"]
                    ))
                    q_data["total_debt_mm"] = to_millions(_get_yf_metric(
                        balance_sheet, col_date, ["Total Debt", "Long Term Debt"]
                    ))
                    q_data["total_equity_mm"] = to_millions(_get_yf_metric(
                        balance_sheet, col_date, ["Stockholders Equity", "Total Equity Gross Minority Interest"]
                    ))

                # Remove None values to keep output clean
                q_data = {k: v for k, v in q_data.items() if v is not None}
                quarters.append(q_data)

            except Exception as exc:
                errors.append(f"Failed to parse quarter {col_date}: {exc}")

    # Sort quarters oldest first
    quarters.sort(key=lambda q: q.get("as_of", ""))

    # === Historical PE for percentile computation ===
    # Compute 10-year monthly PE history from prices + TTM EPS
    historical_pe = _compute_historical_pe(stock, errors)
    valuation["historical_pe"] = historical_pe

    # === Monthly price history (10y) ===
    prices = fetch_us_prices(stock, errors)

    # === Annual statements (5y) ===
    annuals, annual_errors = fetch_us_annuals(stock, history_years=5)
    errors.extend(annual_errors)

    return quarters, valuation, annuals, prices, errors


def _get_yf_metric(df, col_date, label_variants: List[str]) -> Optional[float]:
    """Extract a metric from yfinance DataFrame, trying multiple label variants."""
    for label in label_variants:
        if label in df.index:
            try:
                val = df.loc[label, col_date]
                return safe_float(val)
            except (ValueError, TypeError, KeyError):
                continue
    return None


def _to_pct(value: Optional[float]) -> Optional[float]:
    """Convert yfinance growth ratios like 0.234 to percentage points."""
    if value is None:
        return None
    return value * 100 if abs(value) <= 1 else value


def _normalize_yf_dividend_yield_pct(value: Optional[float]) -> Optional[float]:
    """Normalize yfinance dividendYield to percentage points.

    yfinance can return dividendYield either as 0.0088 (ratio) or 0.88
    (percentage points), depending on ticker/source path.
    """
    if value is None or value <= 0:
        return None
    return value * 100 if value <= 0.2 else value


def _compute_historical_pe(stock, errors: List[str]) -> List[Dict[str, Any]]:
    """Compute 10-year monthly PE history from prices and TTM EPS.

    Returns a list of `{"date": "YYYY-MM-DD", "pe": float}` records,
    oldest first. yfinance's `quarterly_income_stmt` typically carries ~5y
    of quarterly EPS, so the earliest PE points will be sparse — that's
    expected and the orchestrator should treat short series accordingly.
    """
    historical_pe: List[Dict[str, Any]] = []

    try:
        with contextlib.redirect_stderr(io.StringIO()):
            # 10 years of monthly prices
            hist = stock.history(period="10y", interval="1mo")
            income_stmt = stock.quarterly_income_stmt
    except Exception as exc:
        errors.append(f"Historical PE computation failed: {exc}")
        return []

    if hist is None or hist.empty or income_stmt is None or income_stmt.empty:
        return []

    # Extract quarterly EPS
    quarterly_eps: List[Tuple[datetime, float]] = []
    for label in ["Diluted EPS", "Basic EPS"]:
        if label in income_stmt.index:
            row = income_stmt.loc[label]
            for col_date, value in row.items():
                val = safe_float(value)
                if val is not None and val > 0:
                    dt = col_date.to_pydatetime()
                    if dt.tzinfo is not None:
                        dt = dt.replace(tzinfo=None)
                    quarterly_eps.append((dt, val))
            if quarterly_eps:
                break

    if len(quarterly_eps) < 4:
        return []

    quarterly_eps.sort(key=lambda x: x[0])

    # Compute PE for each month-end
    for idx, row in hist.iterrows():
        try:
            close_price = float(row["Close"])
            if close_price <= 0:
                continue

            # Get TTM EPS as of this date
            price_date = idx.to_pydatetime()
            if price_date.tzinfo is not None:
                price_date = price_date.replace(tzinfo=None)

            # Find quarters reported on or before price_date
            preceding = [eps for dt, eps in quarterly_eps if dt <= price_date]
            if len(preceding) < 4:
                continue

            ttm_eps = sum(preceding[-4:])
            if ttm_eps > 0:
                pe = round(close_price / ttm_eps, 2)
                if 0 < pe < 500:  # Sanity bound
                    historical_pe.append({
                        "date": price_date.strftime("%Y-%m-%d"),
                        "pe": pe,
                    })
        except Exception:
            continue

    return historical_pe


def fetch_us_prices(stock, errors: List[str]) -> List[Dict[str, Any]]:
    """Fetch 10y monthly close prices via yfinance.

    Returns a list of `{"date": "YYYY-MM-DD", "close": float}` records,
    oldest first. Close prices are split- and dividend-adjusted by yfinance
    by default.
    """
    prices: List[Dict[str, Any]] = []
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            hist = stock.history(period="10y", interval="1mo")
    except Exception as exc:
        errors.append(f"US monthly price fetch failed: {exc}")
        return []

    if hist is None or hist.empty:
        return []

    for idx, row in hist.iterrows():
        try:
            close_price = float(row["Close"])
            if close_price <= 0:
                continue
            dt = idx.to_pydatetime()
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            prices.append({
                "date": dt.strftime("%Y-%m-%d"),
                "close": round(close_price, 2),
            })
        except Exception:
            continue

    return prices


# =============================================================================
# India Fetcher (Screener.in)
# =============================================================================

def fetch_india_fundamentals(
    ticker: str,
    history_quarters: int,
) -> Tuple[List[Dict], Dict, List[Dict], List[str]]:
    """Fetch quarterly fundamentals for an Indian stock from Screener.in.

    Returns:
        (quarters_list, valuation_dict, annuals_list, errors_list)
    """
    import requests

    errors: List[str] = []
    quarters: List[Dict] = []
    annuals: List[Dict] = []
    valuation: Dict[str, Any] = {}

    # Normalize ticker: remove .NS/.BO suffix if present
    symbol = ticker.upper().replace(".NS", "").replace(".BO", "")

    # Try consolidated first, then standalone
    html = None
    session = requests.Session()
    session.headers.update(SCREENER_HEADERS)

    for slug in ["consolidated/", ""]:
        url = f"https://www.screener.in/company/{symbol}/{slug}"
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = session.get(url, timeout=15, allow_redirects=True)
                if resp.status_code == 200 and len(resp.text) > 5000:
                    # Liveness check passed; now verify the #quarters section
                    # actually contains tabular data. Standalone-only filers
                    # (e.g., Wonderla) return HTTP 200 with an empty #quarters
                    # table on the /consolidated/ URL — fall through to the
                    # standalone slug rather than accept the skeleton page.
                    # We require >= 4 dated <th>/<td> cells inside the section
                    # (the parser's own header-detection threshold). A loose
                    # body-wide date check would false-match Screener's
                    # "Upcoming result date: <DD MMM YYYY>" badge that sits
                    # in the section even when the table is empty.
                    sect_match = re.search(
                        r'<section[^>]*id="quarters"[^>]*>(.*?)</section>',
                        resp.text,
                        re.DOTALL,
                    )
                    if sect_match:
                        date_cells = re.findall(
                            r'<t[dh][^>]*>\s*'
                            r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
                            r'\s+\d{4}\s*</t[dh]>',
                            sect_match.group(1),
                        )
                        if len(date_cells) >= 4:
                            html = resp.text
                            break
                    # Empty quarters section — try next slug
                    break
                elif resp.status_code == 429:
                    time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                elif resp.status_code == 404:
                    break  # Try next slug
            except requests.RequestException as exc:
                if attempt == MAX_RETRIES:
                    errors.append(f"Screener page fetch failed: {exc}")
        if html:
            break

    if not html:
        return [], {}, [], [], errors if errors else [f"No data found for {symbol} on Screener.in"]

    # Parse quarterly P&L from #quarters section
    quarters, parse_errors = _parse_screener_quarters(html, history_quarters)
    errors.extend(parse_errors)

    # Parse current-snapshot fields from the page itself (Stock P/E, BVPS,
    # Market Cap, Dividend Yield) — the chart API alone does not surface
    # these, and using it as the only source has masked silent fetch
    # failures in the past.
    top_ratios = _parse_screener_top_ratios(html)

    # Parse latest balance-sheet column (annual + interim) for Borrowings,
    # Reserves, Equity Capital, and Cash (when broken out). Used both as a
    # snapshot attached to the latest quarter AND as input to EV/EBITDA.
    bs_snapshot = _parse_screener_balance_sheet(html)

    # Fetch valuation chart data (PE history → percentile basis) and the
    # 10y monthly price series. Done in a single helper because both endpoints
    # need the resolved Screener company_id.
    time.sleep(SCREENER_REQUEST_DELAY)
    valuation, prices, val_errors = _fetch_screener_valuation(symbol, session)
    errors.extend(val_errors)

    # Merge top-ratios into the valuation block. Page-scraped values are
    # authoritative for the current-snapshot metrics; chart-API values
    # remain the source for `historical_pe`.
    if "current_pe" in top_ratios:
        valuation["current_pe"] = top_ratios["current_pe"]
    if "current_pb" in top_ratios:
        valuation["current_pb"] = top_ratios["current_pb"]
    if "current_dividend_yield_pct" in top_ratios:
        valuation["current_dividend_yield_pct"] = top_ratios["current_dividend_yield_pct"]
    # Convert market cap from Crores to native rupees for the size-tier
    # threshold table (which expects rupees, e.g. ₹10 lakh-Cr = 10e12).
    if "market_cap_cr" in top_ratios:
        valuation["market_cap"] = top_ratios["market_cap_cr"] * 1e7

    # Derive current_ps. Screener.in does not publish P/S on either the
    # page top-ratios block or the chart API (StockClarity confirms the
    # same), so we compute it from market cap ÷ TTM revenue using data
    # we already have. 1 Cr = 10 MM, so PS = (market_cap_cr × 10) ÷ Σ4Q revenue_mm.
    if quarters and "market_cap_cr" in top_ratios and "current_ps" not in valuation:
        last4 = quarters[-4:] if len(quarters) >= 4 else []
        rev_vals = [q.get("revenue_mm") for q in last4]
        if last4 and all(v is not None and v > 0 for v in rev_vals):
            ttm_rev_mm = sum(rev_vals)
            mc_mm = top_ratios["market_cap_cr"] * 10
            valuation["current_ps"] = round(mc_mm / ttm_rev_mm, 2)

    # Attach balance-sheet snapshot to the latest quarter (annual cadence;
    # we are explicit about that via a warning, not by silently propagating
    # stale numbers across all quarters).
    if quarters and bs_snapshot:
        latest = quarters[-1]
        if "total_debt_cr" in bs_snapshot:
            latest["total_debt_mm"] = round(bs_snapshot["total_debt_cr"] * 10, 2)
        if "total_equity_cr" in bs_snapshot:
            latest["total_equity_mm"] = round(bs_snapshot["total_equity_cr"] * 10, 2)
        if "cash_and_equivalents_cr" in bs_snapshot:
            latest["cash_and_equivalents_mm"] = round(
                bs_snapshot["cash_and_equivalents_cr"] * 10, 2
            )
        # Diluted-share approximation: shares = equity_capital / face_value.
        # Equity Capital is reported in Crores of Rupees; Face Value is in
        # Rupees per share; result is in Crores of shares → ×10 → millions.
        face_val = top_ratios.get("face_value")
        eq_cap = bs_snapshot.get("equity_capital_cr")
        if face_val and face_val > 0 and eq_cap and eq_cap > 0:
            latest["diluted_shares_mm"] = round((eq_cap / face_val) * 10, 2)
        bs_label = bs_snapshot.get("as_of_label")
        if bs_label:
            errors.append(
                f"Balance-sheet fields on latest quarter are from Screener "
                f"snapshot column '{bs_label}' (annual+interim cadence), "
                f"not the quarter close itself."
            )

    # Compute EV/EBITDA when components are available.
    # EBITDA = TTM Operating Profit (Screener's `Operating Profit` row is
    # pre-D&A; verified by the identity Sales − Expenses → Operating Profit
    # while Depreciation appears as a separate line below it).
    # EV = Market Cap + Total Debt − Cash. Cash defaults to 0 with a warning
    # when Screener does not break out a `Cash & Bank` row.
    if quarters and "market_cap_cr" in top_ratios:
        last4 = quarters[-4:] if len(quarters) >= 4 else []
        ttm_op_mm_vals = [q.get("operating_income_mm") for q in last4]
        if last4 and all(v is not None for v in ttm_op_mm_vals):
            ttm_ebitda_mm = sum(ttm_op_mm_vals)
            mc_mm = top_ratios["market_cap_cr"] * 10  # Cr → MM
            debt_mm = (bs_snapshot.get("total_debt_cr") or 0) * 10
            cash_cr = bs_snapshot.get("cash_and_equivalents_cr")
            if cash_cr is None:
                errors.append(
                    "Cash & Bank row not broken out by Screener for this "
                    "ticker; EV/EBITDA computed assuming cash=0."
                )
                cash_mm = 0.0
            else:
                cash_mm = cash_cr * 10
            ev_mm = mc_mm + debt_mm - cash_mm
            if ttm_ebitda_mm > 0:
                valuation["current_ev_ebitda"] = round(ev_mm / ttm_ebitda_mm, 2)
            else:
                errors.append(
                    "Trailing-4Q EBITDA is non-positive — EV/EBITDA not meaningful."
                )

    # Derive current_peg for India. Screener.in does not publish PEG and does
    # not surface forward PE / forward growth, so unlike the US path (which
    # uses yfinance forwardPE / pegRatio) we fall back to trailing-4Q YoY
    # net-income growth. Mirrors the capped-growth math in _compute_peg_zone
    # so the multiples line stays consistent with the GROWTH verdict.
    current_pe_in = valuation.get("current_pe")
    if current_pe_in is not None and current_pe_in > 0 and quarters:
        trailing_growth_in = _compute_trailing_growth(quarters)
        if trailing_growth_in is not None and trailing_growth_in > 0:
            capped_growth_in = min(trailing_growth_in, 100.0)
            valuation["current_peg"] = round(current_pe_in / capped_growth_in, 2)
            valuation["current_peg_source"] = (
                "current_pe / trailing_growth_pct (capped at 100%)"
            )

    # Document fields that Screener.in genuinely does not provide so the
    # orchestrator's confidence-flagging is informed by data, not guesswork.
    errors.append(
        "Screener.in does not provide quarterly cash-flow, capex, "
        "free-cash-flow, gross-profit, or diluted-share-count fields; "
        "those quarters are recorded with the four required P&L lines only."
    )

    # === Annual statements (5y) from #profit-loss / #balance-sheet / #cash-flow ===
    annuals, annual_errors = fetch_india_annuals(html)
    errors.extend(annual_errors)

    return quarters, valuation, annuals, prices, errors


def _parse_screener_quarters(html: str, limit: int) -> Tuple[List[Dict], List[str]]:
    """Parse quarterly P&L data from Screener.in HTML #quarters section."""
    errors: List[str] = []
    quarters: List[Dict] = []

    qr_match = re.search(r'<section[^>]*id="quarters"[^>]*>(.*?)</section>', html, re.DOTALL)
    if not qr_match:
        return [], ["No #quarters section found"]

    qr_section = qr_match.group(1)

    # Detect currency unit
    currency = "INR"  # Will note if in Crores or Lakhs
    unit_multiplier = 1.0  # Crores -> Crores (report as-is since India reports in Cr)
    if re.search(r'Lakhs?', qr_section, re.IGNORECASE):
        unit_multiplier = 0.01  # Lakhs to Crores

    # Extract rows
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', qr_section, re.DOTALL)
    parsed_rows: Dict[str, List[Optional[float]]] = {}
    quarter_headers: List[str] = []

    for row_html in rows:
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.DOTALL)
        clean: List[str] = []
        for c in cells:
            txt = re.sub(r'<[^>]+>', '', c).strip()
            txt = txt.replace('\n', '').replace('\r', '').replace('&nbsp;', '').replace(',', '').strip()
            clean.append(txt)

        if not clean:
            continue

        # Detect quarter headers
        if not quarter_headers:
            date_cells = [
                c for c in clean[1:]
                if c and re.match(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}', c)
            ]
            if len(date_cells) >= 4:
                quarter_headers = date_cells
                continue

        label = clean[0].rstrip('+').strip()
        if not label:
            continue

        # Map Screener labels to our schema
        label_map = {
            "Sales": "revenue",
            "Revenue": "revenue",
            "Operating Profit": "operating_income",
            "Financing Profit": "operating_income",
            "Depreciation": "depreciation",
            "Net Profit": "net_income",
            "EPS in Rs": "eps",
        }

        if label in label_map:
            key = label_map[label]
            values: List[Optional[float]] = []
            for v in clean[1:]:
                v = v.replace('%', '').strip()
                try:
                    values.append(float(v) * unit_multiplier)
                except (ValueError, TypeError):
                    values.append(None)
            parsed_rows[key] = values

    if not quarter_headers:
        return [], ["Could not parse quarter headers"]

    # Build quarters list. Screener serves columns OLDEST-FIRST and may include
    # one extra interim/preliminary column beyond `limit`. We want the most
    # recent `limit` quarters; iterate from the tail of the column list, not
    # the head — otherwise we silently drop the latest reporting period.
    total_cols = len(quarter_headers)
    start_idx = max(0, total_cols - limit)
    for i in range(start_idx, total_cols):
        label = quarter_headers[i]
        quarter_end = _quarter_label_to_date(label)
        if not quarter_end:
            continue

        q_data: Dict[str, Any] = {
            "period": quarter_from_date(quarter_end),
            "as_of": quarter_end,
            "source": "screener.in",
        }

        # Map to contract field names (values are in Crores, convert to MM)
        # 1 Crore = 10 million, so Crores * 10 = MM
        if "revenue" in parsed_rows and i < len(parsed_rows["revenue"]):
            val = parsed_rows["revenue"][i]
            if val is not None:
                q_data["revenue_mm"] = round(val * 10, 2)

        if "operating_income" in parsed_rows and i < len(parsed_rows["operating_income"]):
            val = parsed_rows["operating_income"][i]
            if val is not None:
                q_data["operating_income_mm"] = round(val * 10, 2)

        if "net_income" in parsed_rows and i < len(parsed_rows["net_income"]):
            val = parsed_rows["net_income"][i]
            if val is not None:
                q_data["net_income_mm"] = round(val * 10, 2)

        if "depreciation" in parsed_rows and i < len(parsed_rows["depreciation"]):
            val = parsed_rows["depreciation"][i]
            if val is not None:
                q_data["depreciation_mm"] = round(val * 10, 2)

        if "eps" in parsed_rows and i < len(parsed_rows["eps"]):
            val = parsed_rows["eps"][i]
            if val is not None:
                q_data["eps_diluted"] = round(val, 2)

        quarters.append(q_data)

    # Sort oldest first
    quarters.sort(key=lambda q: q.get("as_of", ""))

    return quarters, errors


def _quarter_label_to_date(label: str) -> Optional[str]:
    """Convert 'Mar 2026' to '2026-03-31'."""
    month_map = {
        "jan": (1, 31), "feb": (2, 28), "mar": (3, 31), "apr": (4, 30),
        "may": (5, 31), "jun": (6, 30), "jul": (7, 31), "aug": (8, 31),
        "sep": (9, 30), "oct": (10, 31), "nov": (11, 30), "dec": (12, 31),
    }
    m = re.match(r"([A-Za-z]{3})\s+(\d{4})", label.strip())
    if not m:
        return None
    month_str, year_str = m.groups()
    month_info = month_map.get(month_str.lower())
    if not month_info:
        return None
    month, day = month_info
    year = int(year_str)
    # Handle Feb in leap years
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        day = 29
    return f"{year}-{month:02d}-{day:02d}"


def _parse_screener_top_ratios(html: str) -> Dict[str, Optional[float]]:
    """Extract current valuation snapshot from Screener.in `<ul id="top-ratios">`.

    Returns a dict with whichever of these keys could be parsed:

      - ``current_price``           — INR per share (e.g. 530.0)
      - ``market_cap_cr``           — INR Crores (e.g. 3360.0)
      - ``current_pe``              — trailing-12M P/E (e.g. 40.5)
      - ``book_value_per_share``    — INR per share (e.g. 278.0)
      - ``current_pb``              — derived: current_price / book_value_per_share
      - ``current_dividend_yield_pct`` — percentage (e.g. 0.38)
      - ``face_value``              — INR per share (e.g. 10.0)

    Schema is stable across all Indian listings on Screener (verified for
    Wonderla, NTPC, Reliance, Pidilite, HDFC Bank). Missing keys are simply
    omitted; callers must handle absence.
    """

    out: Dict[str, Optional[float]] = {}
    block = re.search(r'<ul[^>]*id="top-ratios"[^>]*>(.*?)</ul>', html, re.DOTALL)
    if not block:
        return out

    items = re.findall(r'<li[^>]*>(.*?)</li>', block.group(1), re.DOTALL)
    label_map = {
        "Market Cap": "market_cap_cr",
        "Current Price": "current_price",
        "Stock P/E": "current_pe",
        "Book Value": "book_value_per_share",
        "Dividend Yield": "current_dividend_yield_pct",
        "Face Value": "face_value",
    }

    for item in items:
        name_m = re.search(r'<span[^>]*class="name"[^>]*>(.*?)</span>', item, re.DOTALL)
        num_m = re.search(r'<span[^>]*class="number"[^>]*>(.*?)</span>', item, re.DOTALL)
        if not name_m or not num_m:
            continue
        label = re.sub(r'<[^>]+>', '', name_m.group(1)).strip()
        raw = re.sub(r'<[^>]+>', '', num_m.group(1)).strip()
        # Indian number format: "3,87,285" → 387285 ; "3,360" → 3360
        cleaned = raw.replace(",", "").strip()
        try:
            value = float(cleaned)
        except ValueError:
            continue
        key = label_map.get(label)
        if key:
            out[key] = value

    # Derive P/B from price and book-value-per-share
    cp, bvps = out.get("current_price"), out.get("book_value_per_share")
    if cp is not None and bvps is not None and bvps > 0:
        out["current_pb"] = round(cp / bvps, 4)

    return out


def _parse_screener_balance_sheet(html: str) -> Dict[str, Optional[float]]:
    """Extract latest-column balance-sheet snapshot from Screener `#balance-sheet`.

    Screener serves the balance-sheet section annual + (optionally) one trailing
    interim column. We always read the right-most column. Returns a dict with:

      - ``total_debt_cr``       — `Borrowings` row, INR Crores
      - ``total_equity_cr``     — `Equity Capital` + `Reserves`, INR Crores
      - ``equity_capital_cr``   — face-value share capital, INR Crores
      - ``cash_and_equivalents_cr`` — only when a `Cash & Bank` row is present
                                     (some companies don't break it out)
      - ``as_of_label``         — the right-most column header string
                                  (e.g. "Sep 2025" or "Mar 2025")

    Missing rows are omitted. Cash is genuinely unavailable on many Indian
    listings (e.g. Wonderla); callers must treat absence as "unknown",
    not zero.
    """

    out: Dict[str, Any] = {}
    sect = re.search(r'<section[^>]*id="balance-sheet"[^>]*>(.*?)</section>', html, re.DOTALL)
    if not sect:
        return out

    qr_section = sect.group(1)
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', qr_section, re.DOTALL)
    if not rows:
        return out

    label_map = {
        "Borrowings": "total_debt_cr",
        "Equity Capital": "equity_capital_cr",
        "Reserves": "reserves_cr",
        "Cash & Bank": "cash_and_equivalents_cr",
        "Cash and Bank": "cash_and_equivalents_cr",  # rare alt spelling
    }

    last_col_index: Optional[int] = None

    for row_html in rows:
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.DOTALL)
        clean = [
            re.sub(r'<[^>]+>', '', c).replace('\n', '').replace('\r', '')
                .replace('&nbsp;', '').replace(',', '').strip()
            for c in cells
        ]
        if not clean:
            continue

        # First non-empty row should be the thead (date columns)
        if last_col_index is None:
            date_cells = [
                idx for idx, c in enumerate(clean[1:], start=1)
                if c and re.match(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}', c)
            ]
            if len(date_cells) >= 4:
                last_col_index = date_cells[-1]
                out["as_of_label"] = clean[last_col_index]
            continue

        label = clean[0].rstrip('+').strip()
        if not label or last_col_index is None or last_col_index >= len(clean):
            continue
        key = label_map.get(label)
        if not key:
            continue
        try:
            out[key] = float(clean[last_col_index])
        except (ValueError, TypeError):
            pass

    # Derived: total_equity_cr = equity_capital + reserves (Indian convention)
    eq_cap = out.get("equity_capital_cr")
    reserves = out.get("reserves_cr")
    if eq_cap is not None and reserves is not None:
        out["total_equity_cr"] = round(eq_cap + reserves, 2)

    return out


def _fetch_screener_valuation(symbol: str, session) -> Tuple[Dict, List[Dict[str, Any]], List[str]]:
    """Fetch current valuation metrics + monthly price history from Screener.in Chart API."""
    import requests

    errors: List[str] = []
    prices: List[Dict[str, Any]] = []
    valuation: Dict[str, Any] = {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "screener.in",
    }

    # We need to find the screener_company_id from the HTML or search API
    # For simplicity, fetch current PE from the chart API using the symbol
    # The chart API needs a numeric company_id, which we'd normally get from the HTML

    # Resolve Screener company_id via search API, preferring an exact slug
    # match (StockClarity pattern: /api/company/search/?q= returns entries
    # with url="/company/SLUG/" where SLUG is usually the NSE symbol).
    try:
        search_url = f"https://www.screener.in/api/company/search/?q={symbol}"
        headers = SCREENER_CHART_HEADERS.copy()
        resp = session.get(search_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            results = resp.json() or []
            company_id = None
            sym_u = symbol.upper()
            for entry in results:
                parts = [p for p in entry.get("url", "").strip("/").split("/") if p]
                if len(parts) >= 2 and parts[1].upper() == sym_u:
                    company_id = entry.get("id")
                    break
            if company_id is None and results:
                company_id = results[0].get("id")
            if company_id:
                time.sleep(SCREENER_REQUEST_DELAY)
                pe_data, hist_pe = _fetch_screener_pe_history(company_id, session)
                valuation.update(pe_data)
                valuation["historical_pe"] = hist_pe
                time.sleep(SCREENER_REQUEST_DELAY)
                prices = _fetch_screener_prices(company_id, session, errors)
    except Exception as exc:
        errors.append(f"Screener valuation fetch failed: {exc}")

    return valuation, prices, errors


def _fetch_screener_chart_series(
    company_id: int,
    session,
    metric_query: str,
    metric_match,
    errors: Optional[List[str]] = None,
) -> Tuple[List[Tuple[str, float]], Optional[str]]:
    """Hit Screener's chart API with consolidated→standalone fallback.

    Returns `(values, basis)`. `values` is `[(date_str, float), ...]` in the
    order Screener returns them (oldest-first). `basis` is
    ``"consolidated"`` / ``"standalone"`` / ``None``.

    `metric_match` is a predicate taking the lowercased Screener metric
    string. Used because Screener labels PE as ``"Price to Earning-Median PE"``
    (substring match) but Price as exactly ``"Price"`` (equality).

    Pass `errors` to surface request-level failures; omit to swallow them
    (the PE-history path is opportunistic and a miss simply yields no
    historical_pe).

    NOTE: ``requests`` will URL-encode ``metric_query``. Pass literal spaces;
    they encode to ``+``, which is what the chart API expects. Sending ``+``
    directly encodes to ``%2B`` and returns HTTP 404.
    """
    url = f"https://www.screener.in/api/company/{company_id}/chart/"
    for consolidated in (True, False):
        try:
            # 3650 days ≈ 10y; Screener returns whatever history it has.
            params = {"q": metric_query, "days": 3650}
            if consolidated:
                params["consolidated"] = "true"
            resp = session.get(url, params=params, headers=SCREENER_CHART_HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            for ds in (resp.json() or {}).get("datasets", []):
                if not metric_match(ds.get("metric", "").lower()):
                    continue
                values: List[Tuple[str, float]] = []
                for entry in ds.get("values", []):
                    if len(entry) >= 2 and entry[0] and entry[1] is not None:
                        v = safe_float(entry[1])
                        if v and v > 0:
                            values.append((str(entry[0]), v))
                if values:
                    return values, ("consolidated" if consolidated else "standalone")
            if consolidated:
                time.sleep(SCREENER_REQUEST_DELAY)
        except Exception as exc:
            if errors is not None:
                errors.append(f"Screener chart fetch failed for '{metric_query}': {exc}")
            continue
    return [], None


def _fetch_screener_pe_history(company_id: int, session) -> Tuple[Dict, List[Dict[str, Any]]]:
    """Fetch 10y PE history from Screener.in Chart API.

    Returns `(metadata_dict, [{"date": "YYYY-MM-DD", "pe": float}, ...])`,
    oldest first. The metadata dict carries ``current_pe`` (last point) and
    ``historical_pe_basis`` (consolidated/standalone) when data is found.

    Small/mid-cap Indian companies with no subsidiaries (e.g., Wonderla)
    only publish standalone numbers, so the consolidated endpoint returns
    200 with zero data points; the standalone fallback then yields the
    full series.
    """
    values, basis = _fetch_screener_chart_series(
        company_id, session,
        metric_query="Price to Earning-Median PE",
        metric_match=lambda m: "price to earning" in m,
    )
    historical_pe = [{"date": d, "pe": v} for d, v in values]
    if not historical_pe:
        return {}, []
    return (
        {"current_pe": historical_pe[-1]["pe"], "historical_pe_basis": basis},
        historical_pe,
    )


def _fetch_screener_prices(company_id: int, session, errors: List[str]) -> List[Dict[str, Any]]:
    """Fetch 10y monthly price history from Screener.in Chart API.

    Returns `[{"date": "YYYY-MM-DD", "close": float}, ...]`, oldest first,
    down-sampled to one observation per month (the last close in each
    YYYY-MM bucket). Matches the US side's monthly cadence and keeps the
    persisted file under a few hundred KB per holding.
    """
    values, _ = _fetch_screener_chart_series(
        company_id, session,
        metric_query="Price",
        metric_match=lambda m: m == "price",
        errors=errors,
    )
    if not values:
        return []
    by_month: Dict[str, Dict[str, Any]] = {}
    for date_str, val in values:
        by_month[date_str[:7]] = {"date": date_str, "close": round(val, 2)}
    return sorted(by_month.values(), key=lambda r: r["date"])


# =============================================================================
# Zone Computation
# =============================================================================

def compute_zone(
    archetype: Optional[str],
    sector: Optional[str],
    sector_kind: Optional[str],
    valuation: Dict[str, Any],
    quarters: List[Dict],
    is_indian: bool,
) -> Dict[str, Any]:
    """Build the valuation block.

    When `archetype` is provided, the returned block includes zone fields
    (zone, zone_thresholds, primary_metric, primary_metric_value, etc.)
    layered on top of the always-present multiples base.

    When `archetype` is None or empty, only the multiples base is returned
    (no verdict line, no single "zone" call).
    """
    current_pe = valuation.get("current_pe")
    current_forward_pe = valuation.get("current_forward_pe")
    current_pb = valuation.get("current_pb")
    current_ps = valuation.get("current_ps")
    current_ev_ebitda = valuation.get("current_ev_ebitda")
    provider_peg = valuation.get("provider_peg")
    inferred_forward_growth = valuation.get("inferred_forward_growth_pct")
    market_cap = valuation.get("market_cap")
    historical_pe = valuation.get("historical_pe", [])

    has_positive_pe = current_pe is not None and current_pe > 0

    # === Multiples base (always emitted, archetype-independent) ===
    result: Dict[str, Any] = {
        "current_pe": safe_round(current_pe),
        "current_forward_pe": safe_round(current_forward_pe),
        "current_pb": safe_round(current_pb),
        "current_ps": safe_round(current_ps),
        "current_ev_ebitda": safe_round(current_ev_ebitda),
        "current_dividend_yield_pct": valuation.get("current_dividend_yield_pct"),
        "current_peg": valuation.get("current_peg"),
        "current_peg_source": valuation.get("current_peg_source"),
        "provider_peg": valuation.get("provider_peg"),
        "provider_peg_source": valuation.get("provider_peg_source"),
        "inferred_forward_growth_pct": valuation.get("inferred_forward_growth_pct"),
        "inferred_forward_growth_source": valuation.get("inferred_forward_growth_source"),
        "yfinance_earnings_growth_pct": valuation.get("yfinance_earnings_growth_pct"),
        "yfinance_revenue_growth_pct": valuation.get("yfinance_revenue_growth_pct"),
        "market_cap": market_cap,
        "as_of": valuation.get("as_of"),
        "source": valuation.get("source"),
    }

    size_tier = compute_size_tier(market_cap, is_indian)
    result["size_tier"] = size_tier

    # Compute trailing earnings growth from quarters
    trailing_growth = _compute_trailing_growth(quarters)
    result["trailing_growth_pct"] = safe_round(trailing_growth)

    # Historical-PE percentile context (always useful, no archetype needed).
    # `historical_pe` is now List[Dict[date, pe]]; extract floats for the
    # sort-based percentile math. See § "PE history shape" in the contract.
    historical_pe_floats = [
        rec["pe"] for rec in historical_pe
        if isinstance(rec, dict) and isinstance(rec.get("pe"), (int, float)) and rec["pe"] > 0
    ]
    if historical_pe_floats and current_pe is not None and current_pe > 0:
        sorted_hist = sorted(historical_pe_floats)
        below = sum(1 for x in sorted_hist if x < current_pe)
        result["current_pe_percentile"] = safe_round(
            100.0 * below / len(sorted_hist), decimals=0,
        )
        result["historical_pe_median"] = safe_round(
            sorted_hist[len(sorted_hist) // 2]
        )
        # Carry the consolidated/standalone basis through so the human
        # renderer can label which Screener report set we drew from.
        if valuation.get("historical_pe_basis"):
            result["historical_pe_basis"] = valuation["historical_pe_basis"]
        result["historical_pe_n"] = len(sorted_hist)
        result["historical_pe_min"] = safe_round(sorted_hist[0])
        result["historical_pe_max"] = safe_round(sorted_hist[-1])

    # No archetype: return multiples only, no verdict line.
    if not archetype:
        return result

    # === Archetype-specific zone verdict layered on top of the multiples base ===
    result["archetype"] = archetype

    # Determine primary metric
    primary_metric = determine_primary_metric(archetype, sector, sector_kind, has_positive_pe)
    result["primary_metric"] = primary_metric
    # === Zone computation by primary metric ===
    # When the primary metric VALUE is unavailable (e.g., EV/EBITDA could not
    # be derived because the source omits Cash & Bank or trailing-4Q EBITDA
    # was negative), we surface that explicitly with `zone: null` rather than
    # silently returning FAIR. This lets the orchestrator distinguish "data
    # places this in the FAIR band" from "could not compute".
    primary_value_map = {
        "PEG": current_pe,
        "PE": current_pe,
        "PS": current_ps,
        "EV_EBITDA": current_ev_ebitda,
        "PB": current_pb,
    }
    if primary_value_map.get(primary_metric) is None:
        result["zone"] = None
        result["zone_thresholds"] = None
        result["percentile_basis"] = None
        result["primary_metric_value"] = None
        result["inverted"] = False
        return result

    if primary_metric == "PEG":
        # GROWTH archetype with positive PE
        if inferred_forward_growth is not None and inferred_forward_growth > 0:
            zone, thresholds, peg = _compute_peg_zone(
                current_pe, inferred_forward_growth, size_tier
            )
            result["peg_source"] = "current_pe / inferred_forward_growth_pct"
        else:
            zone, thresholds, peg = _compute_peg_zone(
                current_pe, trailing_growth, size_tier
            )
            result["peg_source"] = "derived_from_trailing_growth" if peg is not None else None
        result["zone"] = zone
        result["zone_thresholds"] = thresholds
        result["peg"] = peg
        result["primary_metric_value"] = peg
        result["inverted"] = False

    elif primary_metric == "PE":
        # INCOME_VALUE or default. Reuse `historical_pe_floats` extracted
        # earlier for the percentile-context block — same source list, same
        # filter (pe > 0).
        zone, thresholds, percentile_basis = _compute_percentile_zone(
            current_pe, historical_pe_floats, "PE"
        )
        # Apply INCOME_VALUE PEG override if applicable
        if archetype == "INCOME_VALUE" and zone != "FAIR":
            zone, override_info = _apply_income_value_peg_override(
                zone, current_pe, trailing_growth, size_tier
            )
            if override_info:
                result["peg"] = override_info.get("peg")

        result["zone"] = zone
        result["zone_thresholds"] = thresholds
        result["percentile_basis"] = percentile_basis
        result["primary_metric_value"] = current_pe
        result["inverted"] = False

    elif primary_metric == "PS":
        # GROWTH unprofitable
        zone, thresholds, percentile_basis = _compute_percentile_zone(
            current_ps, [], "PS"  # No historical PS available
        )
        result["zone"] = zone
        result["zone_thresholds"] = thresholds
        result["percentile_basis"] = percentile_basis
        result["primary_metric_value"] = current_ps
        result["inverted"] = False

    elif primary_metric == "EV_EBITDA":
        # TURNAROUND or CYCLICAL
        zone, thresholds, percentile_basis = _compute_percentile_zone(
            current_ev_ebitda, [], "EV_EBITDA"  # No historical EV/EBITDA available
        )
        # Invert for commodity cyclicals
        inverted = sector_kind and sector_kind.upper() == "COMMODITY"
        if inverted and zone in ("CHEAP", "EXPENSIVE"):
            zone = "EXPENSIVE" if zone == "CHEAP" else "CHEAP"

        result["zone"] = zone
        result["zone_thresholds"] = thresholds
        result["percentile_basis"] = percentile_basis
        result["primary_metric_value"] = current_ev_ebitda
        result["inverted"] = inverted

    elif primary_metric == "PB":
        # Banks/NBFCs
        zone, thresholds, percentile_basis = _compute_percentile_zone(
            current_pb, [], "PB"  # No historical PB available
        )
        result["zone"] = zone
        result["zone_thresholds"] = thresholds
        result["percentile_basis"] = percentile_basis
        result["primary_metric_value"] = current_pb
        result["inverted"] = False

    else:
        result["zone"] = "FAIR"
        result["zone_thresholds"] = None
        result["inverted"] = False

    return result


def _compute_trailing_growth(quarters: List[Dict]) -> Optional[float]:
    """Compute trailing 4Q average YoY earnings growth from quarters data."""
    if len(quarters) < 5:
        return None

    # Need at least 5 quarters for YoY comparison (Q vs Q-4)
    net_incomes = []
    for q in quarters:
        ni = q.get("net_income_mm")
        if ni is not None:
            net_incomes.append(ni)
        else:
            net_incomes.append(None)

    # Compute YoY growth rates
    growth_rates = []
    for i in range(4, len(net_incomes)):
        current = net_incomes[i]
        prior = net_incomes[i - 4]
        if current is not None and prior is not None and prior > 0:
            growth = (current - prior) / prior
            growth_rates.append(growth)

    if not growth_rates:
        return None

    # Average of growth rates, as percentage
    avg_growth = sum(growth_rates) / len(growth_rates)
    return round(avg_growth * 100, 2)


def _compute_peg_zone(
    current_pe: Optional[float],
    trailing_growth_pct: Optional[float],
    size_tier: str,
) -> Tuple[str, Dict, Optional[float]]:
    """Compute PEG-based zone for GROWTH archetype."""
    peg_cheap, peg_expensive = _PEG_THRESHOLDS.get(size_tier, (1.0, 2.0))
    thresholds = {"cheap_below": peg_cheap, "expensive_above": peg_expensive}

    if current_pe is None or current_pe <= 0:
        return "FAIR", thresholds, None

    # PE cap guardrail
    if current_pe > PE_ABSOLUTE_CAP:
        return "EXPENSIVE", thresholds, None

    if trailing_growth_pct is None or trailing_growth_pct <= 0:
        return "FAIR", thresholds, None

    # Cap growth at 100%
    capped_growth = min(trailing_growth_pct, 100.0)

    # PEG = PE / growth_pct
    peg = round(current_pe / capped_growth, 2)

    if peg < peg_cheap:
        zone = "CHEAP"
    elif peg > peg_expensive:
        zone = "EXPENSIVE"
    else:
        zone = "FAIR"

    return zone, thresholds, peg


def _compute_percentile_zone(
    current_value: Optional[float],
    historical_values: List[float],
    metric_name: str,
) -> Tuple[str, Optional[Dict], Optional[Dict]]:
    """Compute percentile-based zone from historical data."""
    if current_value is None:
        return "FAIR", None, None

    if len(historical_values) < 20:
        # Insufficient history — use reasonable defaults by metric
        defaults = {
            "PE": (15.0, 25.0),
            "PB": (1.0, 2.5),
            "PS": (5.0, 15.0),
            "EV_EBITDA": (8.0, 14.0),
        }
        cheap, expensive = defaults.get(metric_name, (10.0, 20.0))
        thresholds = {"cheap_below": cheap, "expensive_above": expensive}

        if current_value < cheap:
            zone = "CHEAP"
        elif current_value > expensive:
            zone = "EXPENSIVE"
        else:
            zone = "FAIR"

        return zone, thresholds, None  # No percentile_basis available

    # Compute percentiles
    try:
        p25, p75 = compute_percentiles(historical_values)
    except ValueError:
        return "FAIR", None, None

    thresholds = {"cheap_below": p25, "expensive_above": p75}
    percentile_basis = {
        "p25": p25,
        "p75": p75,
        "sector_median": None,  # Not available without database
        "history_years": 5,
    }

    # Zone rules (without sector median check)
    if current_value > p75:
        zone = "EXPENSIVE"
    elif current_value < p25:
        zone = "CHEAP"
    else:
        zone = "FAIR"

    return zone, thresholds, percentile_basis


def _apply_income_value_peg_override(
    percentile_zone: str,
    current_pe: Optional[float],
    trailing_growth_pct: Optional[float],
    size_tier: str,
) -> Tuple[str, Optional[Dict]]:
    """Apply PEG override guard for INCOME_VALUE companies."""
    if current_pe is None or current_pe <= 0:
        return percentile_zone, None

    if trailing_growth_pct is None or trailing_growth_pct <= 0:
        return percentile_zone, None

    capped_growth = min(trailing_growth_pct, 100.0)
    peg = round(current_pe / capped_growth, 2)

    exp_threshold, cheap_threshold = _INCOME_VALUE_PEG_THRESHOLDS.get(size_tier, (1.5, 3.0))

    if percentile_zone == "EXPENSIVE" and peg <= exp_threshold:
        return "FAIR", {"peg": peg, "override": "EXPENSIVE->FAIR"}

    if percentile_zone == "CHEAP" and peg > cheap_threshold:
        return "FAIR", {"peg": peg, "override": "CHEAP->FAIR"}

    return percentile_zone, {"peg": peg}


# =============================================================================
# Slice 1: Annual Statements (5y) — US and India
# =============================================================================

def fetch_us_annuals(stock, history_years: int = 5) -> Tuple[List[Dict], List[str]]:
    """Fetch annual P&L + BS + CF for a US stock via yfinance.

    yfinance exposes annual statements as `income_stmt`, `balance_sheet`,
    `cashflow` (the unprefixed properties; the `quarterly_*` variants are
    already used for `quarters[]`). Returns a list of annual records,
    oldest first; each carries the same `*_mm` keys as `quarters[]` plus
    `fy_end` and `fiscal_year`.
    """
    errors: List[str] = []
    annuals: List[Dict] = []

    try:
        with contextlib.redirect_stderr(io.StringIO()):
            income_stmt = stock.income_stmt
            balance_sheet = stock.balance_sheet
            cash_flow = stock.cashflow
    except Exception as exc:
        return [], [f"Annual statements fetch failed: {exc}"]

    if income_stmt is None or income_stmt.empty:
        return [], ["Annual income statement not returned by yfinance"]

    for col_date in income_stmt.columns[:history_years]:
        try:
            fy_end_dt = col_date.to_pydatetime()
            fy_end = fy_end_dt.strftime("%Y-%m-%d")
            a: Dict[str, Any] = {
                "fy_end": fy_end,
                "fiscal_year": fy_end_dt.year,
                "source": "yfinance",
            }

            a["revenue_mm"] = to_millions(_get_yf_metric(
                income_stmt, col_date, ["Total Revenue", "Revenue", "Net Sales"]
            ))
            a["gross_profit_mm"] = to_millions(_get_yf_metric(
                income_stmt, col_date, ["Gross Profit"]
            ))
            a["operating_income_mm"] = to_millions(_get_yf_metric(
                income_stmt, col_date, ["Operating Income", "EBIT"]
            ))
            a["net_income_mm"] = to_millions(_get_yf_metric(
                income_stmt, col_date, ["Net Income", "Net Income Common Stockholders"]
            ))
            a["eps_diluted"] = safe_round(_get_yf_metric(
                income_stmt, col_date, ["Diluted EPS", "Basic EPS"]
            ))

            if cash_flow is not None and not cash_flow.empty and col_date in cash_flow.columns:
                ocf = _get_yf_metric(
                    cash_flow, col_date,
                    ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
                )
                capex = _get_yf_metric(
                    cash_flow, col_date, ["Capital Expenditure", "Purchase Of PPE"]
                )
                a["operating_cash_flow_mm"] = to_millions(ocf)
                if capex is not None:
                    a["capex_mm"] = to_millions(capex)
                    if ocf is not None:
                        a["free_cash_flow_mm"] = to_millions(ocf + capex)

            if balance_sheet is not None and not balance_sheet.empty and col_date in balance_sheet.columns:
                a["cash_and_equivalents_mm"] = to_millions(_get_yf_metric(
                    balance_sheet, col_date,
                    ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
                ))
                a["total_debt_mm"] = to_millions(_get_yf_metric(
                    balance_sheet, col_date, ["Total Debt", "Long Term Debt"]
                ))
                a["total_equity_mm"] = to_millions(_get_yf_metric(
                    balance_sheet, col_date,
                    ["Stockholders Equity", "Total Equity Gross Minority Interest"],
                ))
                a["total_assets_mm"] = to_millions(_get_yf_metric(
                    balance_sheet, col_date, ["Total Assets"]
                ))

            a = {k: v for k, v in a.items() if v is not None}
            annuals.append(a)
        except Exception as exc:
            errors.append(f"Annual parse failed for {col_date}: {exc}")

    annuals.sort(key=lambda x: x.get("fy_end", ""))
    return annuals, errors


def fetch_india_annuals(html: str) -> Tuple[List[Dict], List[str]]:
    """Parse annual P&L + BS + CF from Screener.in HTML sections.

    Screener exposes three annual sections — `#profit-loss`, `#balance-sheet`,
    `#cash-flow` — with FY-end column headers like "Mar 2024". This function
    parses all three and merges them by FY-end into a single per-year record.
    Records are returned oldest first.

    Cash & Bank is not always broken out (some listings only report total
    current assets); when absent, the field is simply omitted.
    """
    errors: List[str] = []
    by_fy: Dict[str, Dict[str, Any]] = {}

    sections = {
        "profit-loss": {
            "Sales": "revenue_cr",
            "Revenue": "revenue_cr",
            "Operating Profit": "operating_income_cr",
            "Financing Profit": "operating_income_cr",
            "Depreciation": "depreciation_cr",
            "Net Profit": "net_income_cr",
            "EPS in Rs": "eps",
        },
        "balance-sheet": {
            "Equity Capital": "equity_capital_cr",
            "Reserves": "reserves_cr",
            "Borrowings": "total_debt_cr",
            "Cash & Bank": "cash_and_equivalents_cr",
            "Cash and Bank": "cash_and_equivalents_cr",
            "Total Assets": "total_assets_cr",
        },
        "cash-flow": {
            "Cash from Operating Activity": "operating_cash_flow_cr",
            "Cash from Investing Activity": "investing_cash_flow_cr",
            "Cash from Financing Activity": "financing_cash_flow_cr",
            "Net Cash Flow": "net_cash_flow_cr",
        },
    }

    for section_id, label_map in sections.items():
        sect_match = re.search(
            rf'<section[^>]*id="{section_id}"[^>]*>(.*?)</section>',
            html,
            re.DOTALL,
        )
        if not sect_match:
            errors.append(f"Screener section #{section_id} not found")
            continue

        sect = sect_match.group(1)
        unit_multiplier = 1.0
        if re.search(r"Lakhs?", sect, re.IGNORECASE):
            unit_multiplier = 0.01

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", sect, re.DOTALL)
        headers: List[str] = []

        for row_html in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.DOTALL)
            clean = [
                re.sub(r"<[^>]+>", "", c)
                    .replace("\n", "").replace("\r", "")
                    .replace("&nbsp;", "").replace(",", "").strip()
                for c in cells
            ]
            if not clean:
                continue

            if not headers:
                date_cells = [
                    c for c in clean[1:]
                    if c and re.match(
                        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}",
                        c,
                    )
                ]
                if len(date_cells) >= 3:
                    headers = date_cells
                    continue

            if not headers:
                continue

            label = clean[0].rstrip("+").strip()
            field = label_map.get(label)
            if not field:
                continue

            values = clean[1:1 + len(headers)]
            for i, raw in enumerate(values):
                raw_clean = raw.replace("%", "").strip()
                try:
                    val = float(raw_clean) * unit_multiplier
                except (ValueError, TypeError):
                    continue
                fy_end = _quarter_label_to_date(headers[i])
                if not fy_end:
                    continue
                rec = by_fy.setdefault(
                    fy_end, {"fy_end": fy_end, "source": "screener.in"}
                )
                rec[field] = val

    annuals: List[Dict] = []
    cr_to_mm = {
        "revenue_cr": "revenue_mm",
        "operating_income_cr": "operating_income_mm",
        "depreciation_cr": "depreciation_mm",
        "net_income_cr": "net_income_mm",
        "total_debt_cr": "total_debt_mm",
        "cash_and_equivalents_cr": "cash_and_equivalents_mm",
        "total_assets_cr": "total_assets_mm",
        "operating_cash_flow_cr": "operating_cash_flow_mm",
        "investing_cash_flow_cr": "investing_cash_flow_mm",
        "financing_cash_flow_cr": "financing_cash_flow_mm",
        "net_cash_flow_cr": "net_cash_flow_mm",
    }
    for fy_end, rec in sorted(by_fy.items()):
        out: Dict[str, Any] = {
            "fy_end": fy_end,
            "fiscal_year": int(fy_end[:4]),
            "source": rec.get("source", "screener.in"),
        }
        for cr_key, mm_key in cr_to_mm.items():
            if cr_key in rec:
                out[mm_key] = round(rec[cr_key] * 10, 2)
        if "eps" in rec:
            out["eps_diluted"] = round(rec["eps"], 2)
        eq_cap = rec.get("equity_capital_cr")
        reserves = rec.get("reserves_cr")
        if eq_cap is not None and reserves is not None:
            out["total_equity_mm"] = round((eq_cap + reserves) * 10, 2)
        if any(k in out for k in ("revenue_mm", "net_income_mm", "total_equity_mm")):
            annuals.append(out)

    return annuals, errors


# =============================================================================
# Slice 1: Derived Ratios
# =============================================================================

def compute_derived_ratios(
    quarters: List[Dict],
    annuals: List[Dict],
    valuation: Dict[str, Any],
    is_indian: bool,
) -> Dict[str, Any]:
    """Compute latest-period derived ratios from quarters + annuals + valuation.

    All inputs are already-fetched; no I/O. Mirrors Veda Hard Rule #8
    (no LLM arithmetic): every ratio is a pure Python derivation.

    Returned keys (each Optional[float]; omitted when inputs missing):
      - roe_ttm_pct        — TTM net_income / latest total_equity * 100
      - roce_ttm_pct       — TTM operating_income / (equity + debt) * 100
      - op_margin_pct      — latest-quarter operating_income / revenue * 100
      - net_margin_pct     — latest-quarter net_income / revenue * 100
      - debt_to_equity     — latest total_debt / latest total_equity
      - fcf_yield_pct      — TTM FCF / market_cap * 100
      - basis_note         — short note about source of each number
    """
    ratios: Dict[str, Any] = {}
    if not quarters:
        return ratios

    last = quarters[-1]
    last4 = quarters[-4:] if len(quarters) >= 4 else []

    def _ttm_sum(field: str) -> Optional[float]:
        if not last4:
            return None
        vals = [q.get(field) for q in last4]
        if any(v is None for v in vals):
            return None
        return sum(vals)

    ttm_net_income = _ttm_sum("net_income_mm")
    ttm_operating = _ttm_sum("operating_income_mm")
    ttm_fcf = _ttm_sum("free_cash_flow_mm")

    # Latest BS snapshot: prefer last quarter; fall back to latest annual.
    latest_equity = last.get("total_equity_mm")
    latest_debt = last.get("total_debt_mm")
    if (latest_equity is None or latest_debt is None) and annuals:
        latest_annual = annuals[-1]
        if latest_equity is None:
            latest_equity = latest_annual.get("total_equity_mm")
        if latest_debt is None:
            latest_debt = latest_annual.get("total_debt_mm")

    market_cap = valuation.get("market_cap")  # native currency

    if ttm_net_income is not None and latest_equity is not None and latest_equity > 0:
        ratios["roe_ttm_pct"] = round(100.0 * ttm_net_income / latest_equity, 2)

    if (
        ttm_operating is not None
        and latest_equity is not None
        and latest_debt is not None
        and (latest_equity + latest_debt) > 0
    ):
        ratios["roce_ttm_pct"] = round(
            100.0 * ttm_operating / (latest_equity + latest_debt), 2
        )

    last_rev = last.get("revenue_mm")
    last_op = last.get("operating_income_mm")
    last_ni = last.get("net_income_mm")
    if last_rev is not None and last_rev > 0:
        if last_op is not None:
            ratios["op_margin_pct"] = round(100.0 * last_op / last_rev, 2)
        if last_ni is not None:
            ratios["net_margin_pct"] = round(100.0 * last_ni / last_rev, 2)

    if latest_debt is not None and latest_equity is not None and latest_equity > 0:
        ratios["debt_to_equity"] = round(latest_debt / latest_equity, 2)

    # FCF yield: native-currency consistent. market_cap is in raw native units
    # (USD or INR); FCF is in MM-native. Convert mc to MM then divide.
    if ttm_fcf is not None and market_cap and market_cap > 0:
        mc_mm = market_cap / 1_000_000
        if mc_mm > 0:
            ratios["fcf_yield_pct"] = round(100.0 * ttm_fcf / mc_mm, 2)

    if ratios:
        ratios["basis_note"] = (
            "Margins from latest quarter. ROE/ROCE: TTM 4Q numerator over "
            "latest balance-sheet denominator. FCF yield: TTM 4Q FCF over "
            "market cap (when FCF available; India Screener does not publish "
            "quarterly cash-flow, so India FCF yield is typically null)."
        )
    return ratios


# =============================================================================
# Main
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch quarterly fundamentals and compute valuation zone.",
    )
    parser.add_argument("--ticker", required=True, help="Stock ticker (e.g., NVDA, RELIANCE.NS)")
    parser.add_argument(
        "--market",
        choices=["US", "IN"],
        default="",
        help=(
            "Market: US or IN. If omitted, auto-detected from ticker suffix "
            "(.NS/.BO → IN; otherwise US)."
        ),
    )
    parser.add_argument(
        "--archetype",
        choices=["GROWTH", "INCOME_VALUE", "TURNAROUND", "CYCLICAL", ""],
        default="",
        help=(
            "Optional. When omitted, output is exploration-mode — all relevant "
            "multiples are emitted with no single zone verdict. When provided, "
            "a zone verdict is layered on top using the archetype's primary metric."
        ),
    )
    parser.add_argument(
        "--archetype-secondary",
        default="",
        choices=["GROWTH", "INCOME_VALUE", "TURNAROUND", "CYCLICAL", ""],
        help=(
            "Optional secondary archetype for composite positions. When set, "
            "the output adds a parallel `valuation.secondary` block computed "
            "against the same fundamentals using the secondary archetype's "
            "primary metric. Must differ from --archetype."
        ),
    )
    parser.add_argument("--sector", default="", help="Sector name (optional)")
    parser.add_argument("--sector-kind", default="", choices=["COMMODITY", "CREDIT", "OTHER", ""], help="Sector kind (optional)")
    parser.add_argument("--history-quarters", type=int, default=12, help="Number of quarters to fetch")

    args = parser.parse_args()

    # Auto-detect market from ticker suffix if not provided.
    if not args.market:
        args.market = detect_market(args.ticker)

    if args.archetype_secondary and args.archetype_secondary == args.archetype:
        parser.error(
            "--archetype-secondary must differ from --archetype (composite "
            "requires two distinct archetypes; omit --archetype-secondary for "
            "a monoline position)."
        )

    is_indian = args.market == "IN"

    # Fetch fundamentals
    if is_indian:
        quarters, valuation, annuals, prices, errors = fetch_india_fundamentals(args.ticker, args.history_quarters)
        currency = "INR"
        source = "screener.in"
    else:
        quarters, valuation, annuals, prices, errors = fetch_us_fundamentals(args.ticker, args.history_quarters)
        currency = "USD"
        source = "yfinance"

    # Bare-ticker IN fallback: if a US-routed bare ticker came back empty
    # (no quarters, no annuals, no usable multiples), the user likely typed
    # an Indian symbol bare (CDSL, HDFCBANK, TITAN). Try Screener.in with
    # .NS then .BO before giving up. Mirrors the same fallback in
    # fetch_company_info.py.
    resolved_ticker = None
    if not is_indian:
        has_any_multiple = any(
            valuation.get(k) is not None
            for k in ("current_pe", "current_pb", "current_ps", "current_ev_ebitda", "market_cap")
        )
        if not quarters and not annuals and not has_any_multiple:
            for suffix in (".NS", ".BO"):
                candidate = f"{args.ticker.upper()}{suffix}"
                in_q, in_v, in_a, in_p, in_e = fetch_india_fundamentals(candidate, args.history_quarters)
                if in_q or in_a or in_v.get("market_cap") is not None:
                    quarters, valuation, annuals, prices, errors = in_q, in_v, in_a, in_p, errors + in_e
                    currency = "INR"
                    source = "screener.in"
                    is_indian = True
                    args.market = "IN"
                    args.ticker = candidate
                    resolved_ticker = candidate
                    break

    # Capture dated PE history BEFORE compute_zone strips it off the
    # valuation block. The valuation block keeps only summary stats
    # (n / min / median / max / percentile); raw points live at top-level.
    pe_history = valuation.get("historical_pe", []) or []

    # Compute valuation block. When --archetype is empty, this returns the
    # multiples-only base (no verdict line). When set, the zone verdict is
    # layered on top.
    zone_result = compute_zone(
        archetype=args.archetype if args.archetype else None,
        sector=args.sector if args.sector else None,
        sector_kind=args.sector_kind if args.sector_kind else None,
        valuation=valuation,
        quarters=quarters,
        is_indian=is_indian,
    )

    # Composite: when --archetype-secondary is set, compute a parallel block
    # using the secondary archetype's primary-metric path. The banks override
    # (sector_kind=CREDIT or banking sector keyword) is intentionally NOT
    # applied to the secondary block: PB-override exists because banks have a
    # single business model (lending). When a non-bank sector carries a
    # secondary archetype, the secondary metric is the right lens for that
    # segment. See internal/holdings-schema.md § "Composite valuation —
    # `secondary:` block".
    if args.archetype and args.archetype_secondary:
        secondary_zone = compute_zone(
            archetype=args.archetype_secondary,
            sector=None,            # bypass banks override on the secondary block
            sector_kind=None,
            valuation=valuation,
            quarters=quarters,
            is_indian=is_indian,
        )
        secondary_zone["archetype"] = args.archetype_secondary
        zone_result["secondary"] = secondary_zone

    # Build output
    as_of = quarters[-1]["as_of"] if quarters else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Slice 1: derived ratios (pure computation; no I/O)
    derived_ratios = compute_derived_ratios(quarters, annuals, valuation, is_indian)

    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "as_of": as_of,
        "currency": currency,
        "quarters": quarters,
        "annuals": annuals,
        "valuation": zone_result,
        "derived_ratios": derived_ratios,
        "pe_history": pe_history,
        "prices": prices,
    }
    if resolved_ticker:
        output["resolved_ticker"] = resolved_ticker

    if errors:
        output["errors"] = errors

    # Output JSON
    print(json.dumps(output, indent=2))

    # Exit code: 0 if we got some data, 1 if total failure.
    # When no --archetype was passed there is no zone — success is
    # defined as having at least one current multiple.
    has_any_multiple = any(
        zone_result.get(k) is not None
        for k in ("current_pe", "current_pb", "current_ps", "current_ev_ebitda")
    )
    if not quarters and not zone_result.get("zone") and not has_any_multiple:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

