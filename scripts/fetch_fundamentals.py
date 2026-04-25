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
from typing import Any, Dict, List, Optional, Tuple

# Silence noisy loggers
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.WARNING)


# =============================================================================
# Constants — mirrored from StockClarity's valuation_fetcher.py
# =============================================================================

# Banking / NBFC sector keywords — force PB as primary metric
BANKING_SECTOR_KEYWORDS = [
    "banking", "bank", "nbfc", "financial services",
    "housing finance", "microfinance",
]

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
# PEG = PE / (earnings_growth_pct). E.g., PE=50, growth=25% → PEG = 50/25 = 2.0
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

# Screener.in HTTP settings
SCREENER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.screener.in/",
}

SCREENER_CHART_HEADERS = {
    "User-Agent": SCREENER_HEADERS["User-Agent"],
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.screener.in/",
}

# Retry settings
MAX_RETRIES = 2
RETRY_BASE_DELAY = 2.0
SCREENER_REQUEST_DELAY = 2.0  # Rate limiting between Screener calls


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


def is_banking_sector(sector: Optional[str], sector_kind: Optional[str]) -> bool:
    """Check if sector indicates a bank/NBFC (forces P/B metric)."""
    if sector_kind and sector_kind.upper() == "CREDIT":
        return True
    if sector:
        sector_lower = sector.lower()
        return any(kw in sector_lower for kw in BANKING_SECTOR_KEYWORDS)
    return False


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
) -> Tuple[List[Dict], Dict, List[str]]:
    """Fetch quarterly fundamentals for a US stock from yfinance.

    Returns:
        (quarters_list, valuation_dict, errors_list)
    """
    import yfinance as yf

    errors: List[str] = []
    quarters: List[Dict] = []

    try:
        with contextlib.redirect_stderr(io.StringIO()):
            stock = yf.Ticker(ticker)
            info = stock.info or {}
    except Exception as exc:
        return [], {}, [f"Failed to fetch info for {ticker}: {exc}"]

    # === Current valuation ratios ===
    current_pe = safe_float(info.get("trailingPE"))
    current_pb = safe_float(info.get("priceToBook"))
    current_ps = safe_float(info.get("priceToSalesTrailing12Months"))
    current_ev_ebitda = safe_float(info.get("enterpriseToEbitda"))
    market_cap = safe_float(info.get("marketCap"))
    dividend_yield = safe_float(info.get("dividendYield"))

    # Filter out negative values
    if current_pe is not None and current_pe <= 0:
        current_pe = None
    if current_pb is not None and current_pb <= 0:
        current_pb = None
    if current_ps is not None and current_ps <= 0:
        current_ps = None
    if current_ev_ebitda is not None and current_ev_ebitda <= 0:
        current_ev_ebitda = None

    # Manual EV/EBITDA computation if yfinance didn't return it
    if current_ev_ebitda is None and market_cap and market_cap > 0:
        ebitda_raw = safe_float(info.get("ebitda"))
        ev_raw = safe_float(info.get("enterpriseValue"))
        if ebitda_raw and ebitda_raw > 0 and ev_raw and ev_raw > 0:
            current_ev_ebitda = round(ev_raw / ebitda_raw, 2)

    valuation = {
        "current_pe": safe_round(current_pe),
        "current_pb": safe_round(current_pb),
        "current_ps": safe_round(current_ps),
        "current_ev_ebitda": safe_round(current_ev_ebitda),
        "current_dividend_yield_pct": safe_round(dividend_yield * 100 if dividend_yield else None),
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
    # Compute 5-year PE history from monthly prices + TTM EPS
    historical_pe = _compute_historical_pe(stock, errors)
    valuation["historical_pe"] = historical_pe

    return quarters, valuation, errors


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


def _compute_historical_pe(stock, errors: List[str]) -> List[float]:
    """Compute 5-year monthly PE history from prices and TTM EPS."""
    historical_pe: List[float] = []

    try:
        with contextlib.redirect_stderr(io.StringIO()):
            # 5 years of monthly prices
            hist = stock.history(period="5y", interval="1mo")
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
                    historical_pe.append(pe)
        except Exception:
            continue

    return historical_pe


# =============================================================================
# India Fetcher (Screener.in)
# =============================================================================

def fetch_india_fundamentals(
    ticker: str,
    history_quarters: int,
) -> Tuple[List[Dict], Dict, List[str]]:
    """Fetch quarterly fundamentals for an Indian stock from Screener.in.

    Returns:
        (quarters_list, valuation_dict, errors_list)
    """
    import requests

    errors: List[str] = []
    quarters: List[Dict] = []
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
                    html = resp.text
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
        return [], {}, errors if errors else [f"No data found for {symbol} on Screener.in"]

    # Parse quarterly P&L from #quarters section
    quarters, parse_errors = _parse_screener_quarters(html, history_quarters)
    errors.extend(parse_errors)

    # Fetch valuation chart data (PE)
    time.sleep(SCREENER_REQUEST_DELAY)
    valuation, val_errors = _fetch_screener_valuation(symbol, session)
    errors.extend(val_errors)

    return quarters, valuation, errors


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

    # Build quarters list
    num_quarters = min(len(quarter_headers), limit)
    for i in range(num_quarters):
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


def _fetch_screener_valuation(symbol: str, session) -> Tuple[Dict, List[str]]:
    """Fetch current valuation metrics from Screener.in Chart API."""
    import requests

    errors: List[str] = []
    valuation: Dict[str, Any] = {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "screener.in",
    }

    # We need to find the screener_company_id from the HTML or search API
    # For simplicity, fetch current PE from the chart API using the symbol
    # The chart API needs a numeric company_id, which we'd normally get from the HTML

    # Try to extract company_id from a search
    try:
        search_url = f"https://www.screener.in/api/company/search/?q={symbol}"
        headers = SCREENER_CHART_HEADERS.copy()
        resp = session.get(search_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            results = resp.json()
            if results and len(results) > 0:
                company_id = results[0].get("id")
                if company_id:
                    time.sleep(SCREENER_REQUEST_DELAY)
                    pe_data, hist_pe = _fetch_screener_pe_history(company_id, session)
                    valuation.update(pe_data)
                    valuation["historical_pe"] = hist_pe
    except Exception as exc:
        errors.append(f"Screener valuation fetch failed: {exc}")

    return valuation, errors


def _fetch_screener_pe_history(company_id: int, session) -> Tuple[Dict, List[float]]:
    """Fetch PE history from Screener.in Chart API."""
    result: Dict[str, Any] = {}
    historical_pe: List[float] = []

    try:
        url = f"https://www.screener.in/api/company/{company_id}/chart/"
        params = {"q": "Price+to+Earning-Median+PE", "days": 1825, "consolidated": "true"}
        resp = session.get(url, params=params, headers=SCREENER_CHART_HEADERS, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            for ds in data.get("datasets", []):
                metric = ds.get("metric", "").lower()
                values = ds.get("values", [])

                if "price to earning" in metric:
                    for entry in values:
                        if len(entry) >= 2 and entry[1] is not None:
                            val = safe_float(entry[1])
                            if val and val > 0:
                                historical_pe.append(val)
                    # Latest value
                    if historical_pe:
                        result["current_pe"] = historical_pe[-1]
    except Exception:
        pass

    return result, historical_pe


# =============================================================================
# Zone Computation
# =============================================================================

def compute_zone(
    archetype: str,
    sector: Optional[str],
    sector_kind: Optional[str],
    valuation: Dict[str, Any],
    quarters: List[Dict],
    is_indian: bool,
) -> Dict[str, Any]:
    """Compute the valuation zone based on archetype.

    Returns the valuation block with zone, thresholds, etc.
    """
    current_pe = valuation.get("current_pe")
    current_pb = valuation.get("current_pb")
    current_ps = valuation.get("current_ps")
    current_ev_ebitda = valuation.get("current_ev_ebitda")
    market_cap = valuation.get("market_cap")
    historical_pe = valuation.get("historical_pe", [])

    has_positive_pe = current_pe is not None and current_pe > 0

    # Determine primary metric
    primary_metric = determine_primary_metric(archetype, sector, sector_kind, has_positive_pe)

    result: Dict[str, Any] = {
        "primary_metric": primary_metric,
        "current_pe": safe_round(current_pe),
        "current_pb": safe_round(current_pb),
        "current_ps": safe_round(current_ps),
        "current_ev_ebitda": safe_round(current_ev_ebitda),
        "current_dividend_yield_pct": valuation.get("current_dividend_yield_pct"),
        "as_of": valuation.get("as_of"),
        "source": valuation.get("source"),
    }

    size_tier = compute_size_tier(market_cap, is_indian)
    result["size_tier"] = size_tier

    # Compute trailing earnings growth from quarters
    trailing_growth = _compute_trailing_growth(quarters)
    result["trailing_growth_pct"] = safe_round(trailing_growth)

    # === Zone computation by primary metric ===

    if primary_metric == "PEG":
        # GROWTH archetype with positive PE
        zone, thresholds, peg = _compute_peg_zone(
            current_pe, trailing_growth, size_tier
        )
        result["zone"] = zone
        result["zone_thresholds"] = thresholds
        result["peg"] = peg
        result["primary_metric_value"] = peg
        result["inverted"] = False

    elif primary_metric == "PE":
        # INCOME_VALUE or default
        zone, thresholds, percentile_basis = _compute_percentile_zone(
            current_pe, historical_pe, "PE"
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
# Main
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch quarterly fundamentals and compute valuation zone.",
    )
    parser.add_argument("--ticker", required=True, help="Stock ticker (e.g., NVDA, RELIANCE.NS)")
    parser.add_argument("--market", required=True, choices=["US", "IN"], help="Market: US or IN")
    parser.add_argument("--archetype", required=True, choices=["GROWTH", "INCOME_VALUE", "TURNAROUND", "CYCLICAL"])
    parser.add_argument("--sector", default="", help="Sector name (optional)")
    parser.add_argument("--sector-kind", default="", choices=["COMMODITY", "CREDIT", "OTHER", ""], help="Sector kind (optional)")
    parser.add_argument("--history-quarters", type=int, default=12, help="Number of quarters to fetch")

    args = parser.parse_args()

    is_indian = args.market == "IN"

    # Fetch fundamentals
    if is_indian:
        quarters, valuation, errors = fetch_india_fundamentals(args.ticker, args.history_quarters)
        currency = "INR"
        source = "screener.in"
    else:
        quarters, valuation, errors = fetch_us_fundamentals(args.ticker, args.history_quarters)
        currency = "USD"
        source = "yfinance"

    # Compute zone
    zone_result = compute_zone(
        archetype=args.archetype,
        sector=args.sector if args.sector else None,
        sector_kind=args.sector_kind if args.sector_kind else None,
        valuation=valuation,
        quarters=quarters,
        is_indian=is_indian,
    )

    # Remove internal fields from zone_result
    zone_result.pop("historical_pe", None)

    # Build output
    as_of = quarters[-1]["as_of"] if quarters else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "as_of": as_of,
        "currency": currency,
        "quarters": quarters,
        "valuation": zone_result,
    }

    if errors:
        output["errors"] = errors

    # Output JSON
    print(json.dumps(output, indent=2))

    # Exit code: 0 if we got some data, 1 if total failure
    if not quarters and not zone_result.get("zone"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
