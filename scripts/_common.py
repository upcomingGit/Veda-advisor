"""Shared constants and helpers for the Veda fetcher scripts.

Single source of truth for:
  - Market detection from ticker suffix.
  - Sector-kind keyword classification (CREDIT / OTHER) and the bank/NBFC
    override used by the archetype-driven valuation verdict.
  - Screener.in HTTP request settings.

If any of these drift across `fetch_company_info.py`, `fetch_fundamentals.py`,
or `fetch_calendar.py`, the same ticker will get classified differently in
different scripts. Keep one definition here; import everywhere else.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Market detection
# ---------------------------------------------------------------------------

def detect_market(ticker: str) -> str:
    """Return "IN" for .NS / .BO tickers, otherwise "US"."""
    upper = ticker.upper()
    if upper.endswith(".NS") or upper.endswith(".BO"):
        return "IN"
    return "US"


def slugify(ticker: str) -> str:
    """Canonical holdings-folder slug for a ticker.

    Indian-exchange suffixes (`.NS`, `.BO`, `.BOM`) are stripped before the
    dot-to-dash replacement so that a ticker called both as `RELIANCE` and
    `RELIANCE.NS` resolves to the same folder (`reliance`), not two distinct
    folders (`reliance` and `reliance-ns`). US tickers (no exchange suffix in
    this repo's convention) are unaffected: `BRK.B` -> `brk-b`. Ported from the
    research repo's canonical slugify so both sides derive identical slugs.
    """
    t = ticker.upper()
    for suffix in (".NS", ".BO", ".BOM"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    # Lowercase, then collapse any run of non-alphanumerics to a single hyphen.
    # For a normal ticker this maps "." -> "-" exactly (BRK.B -> brk-b); it also
    # keeps a name-based input (an unlisted company) folder-safe.
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


# ---------------------------------------------------------------------------
# Client roots (multi-client layout)
#
# Every client's personal files — profile.md, assets.md, journal.md, holdings/,
# holdings_registry.csv, ledger/ — live under clients/<client>/.
# A single-client user never names one: the default client is "default".
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent


def client_root(client: str = "default") -> Path:
    """Return the folder holding one client's personal files: clients/<client>/."""
    return _REPO_ROOT / "clients" / client


# ---------------------------------------------------------------------------
# Sector-kind classification (CREDIT / OTHER)
# Keyword list mirrors StockClarity's BANKING_SECTOR_KEYWORDS in
# src/helper_functions/valuation_fetcher.py — the canonical PB-override
# trigger. Keep this list identical to StockClarity's; drift means a stock
# classified CREDIT here might not trigger the PB-override there, or vice
# versa — silent and dangerous.
#
# Cyclicality / commodity-producer status is NOT carried by sector_kind —
# it is investor judgement set via thesis_archetype (CYCLICAL / TURNAROUND)
# in thesis.md, not provider metadata. _meta.yaml stays pure-facts.
# ---------------------------------------------------------------------------

CREDIT_KEYWORDS: tuple[str, ...] = (
    "bank", "nbfc", "financial services", "housing finance", "microfinance",
)

# Non-lender financials that ride the "financial services" umbrella but are
# NOT balance-sheet-funded credit businesses — exchanges, depositories,
# clearing corps, broking, asset managers, insurance, wealth/AMC. These
# get the standard P/E lens, not the book-value lens.
#
# NOTE: StockClarity's BANKING_SECTOR_KEYWORDS does not yet carry this
# exclusion layer, so a CDSL/BSE/MCX/HDFC AMC will currently classify as
# CREDIT there and OTHER here. Mirror this exclusion in StockClarity to
# restore parity.
CREDIT_EXCLUSION_KEYWORDS: tuple[str, ...] = (
    "depositor",          # depository, depositories
    "exchange",           # stock exchange
    "clearing",           # clearing corp / clearing house
    "broking", "broker",  # broking / broker-dealer
    "asset management",
    "wealth management",
    "investment management",
    "insurance",
    "intermediar",        # intermediaries
    "capital market",     # capital markets infra (MIIs)
)


def classify_sector_kind(sector: Optional[str], industry: Optional[str]) -> str:
    """Return CREDIT or OTHER based on sector + industry text.

    A position is CREDIT only if a lender keyword matches AND no
    non-lender-financial keyword matches (depository, exchange, broking,
    AMC, insurance, etc. all stay OTHER).
    """
    blob = " ".join(filter(None, [sector, industry])).lower()
    if not any(k in blob for k in CREDIT_KEYWORDS):
        return "OTHER"
    if any(x in blob for x in CREDIT_EXCLUSION_KEYWORDS):
        return "OTHER"
    return "CREDIT"


def is_banking_sector(sector: Optional[str], sector_kind: Optional[str]) -> bool:
    """True when the position should use PB as the primary valuation metric.

    Triggered by either:
      - sector_kind already classified as CREDIT (preferred path), or
      - sector text contains a CREDIT keyword (back-compat for callers
        that did not set sector_kind explicitly).
    """
    if sector_kind and sector_kind.upper() == "CREDIT":
        return True
    if sector:
        sector_lower = sector.lower()
        if any(x in sector_lower for x in CREDIT_EXCLUSION_KEYWORDS):
            return False
        return any(kw in sector_lower for kw in CREDIT_KEYWORDS)
    return False


# ---------------------------------------------------------------------------
# Screener.in HTTP settings
# Used by fetch_company_info.py and fetch_fundamentals.py for the company
# page scrape, and the chart-API variant for fetch_fundamentals.py.
# fetch_calendar.py uses the same base headers — see its own SCREENER_HEADERS
# which extends this dict.
# ---------------------------------------------------------------------------

_SCREENER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

SCREENER_HEADERS = {
    "User-Agent": _SCREENER_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.screener.in/",
}

SCREENER_CHART_HEADERS = {
    "User-Agent": _SCREENER_USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.screener.in/",
}

# Retry settings (used by the simple while-attempt-loop retries in the
# fundamentals + company-info fetchers; fetch_calendar.py uses urllib3's
# Retry adapter with its own DEFAULT_MAX_RETRIES and is intentionally
# left alone).
MAX_RETRIES = 2
RETRY_BASE_DELAY = 2.0
SCREENER_REQUEST_DELAY = 2.0  # rate-limit gap between sequential Screener calls
