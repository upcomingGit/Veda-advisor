"""
Veda — ownership/insider fetcher and normalizer.

Fetches insider transactions, promoter pledging, and shareholding-pattern data
for a held position from primary regulator/data feeds, normalizes to a single
JSON envelope, and emits to stdout.

Channels (selected via --channels):

  insiders     Insider transaction ledger
                  US: SEC EDGAR submissions JSON -> per-filing index.json ->
                      raw Form 4 XML (namespace-stripped) -> lot aggregation
                      by (insider, P/S code) per accession -> value-threshold
                      filter. ($500K buy / $2M sell — ported from StockClarity
                      verbatim.)
                      Note: Form 4 URLs use the FILER (insider) CIK from the
                      first 10 digits of the accession number, NOT the issuer
                      CIK that submissions JSON is keyed on. Form 4 is filed
                      by the individual reporting owner.
                  India: NSE PIT API single-call all-trades-in-window flow ->
                         5-filter pipeline (Equity Shares only / Buy or Sell /
                         Market Purchase or Market Sale / non-zero value /
                         value threshold ₹1 Cr buy / ₹5 Cr sell).
                         Also ported from StockClarity verbatim.
                         NSE PIT captures trades from ALL exchanges
                         (NSE, BSE, MSEI) — single source of truth.

  shareholding Quarterly shareholding pattern snapshot
                  US: yfinance Ticker.major_holders ->
                      insider_pct, institutional_pct, retail_pct.
                  India: NSE corp-shp master endpoint -> promoter_pct,
                         public_pct (master endpoint surfaces only
                         promoter+public aggregates; FII/DII split lives in
                         per-filing XBRL document and is parked for v2 — emits
                         fii_pct: null, dii_pct: null explicitly so the
                         orchestrator can distinguish "missing" from
                         "forgotten"). Up to 8 quarters of history captured
                         via parsed_rows[1:MAX_SHAREHOLDING_HISTORY_QUARTERS].
                         BSE shareholding-pattern fallback when NSE corp-shp
                         returns no rows or fails.
                         Pledging on India is NOT auto-fetched in v1 (lives
                         on a separate NSE corporate-pledge endpoint and is
                         parked for v2; subagent contract returns
                         pledging_status: not_fetched_v1).

US pledging is "applicable: false" by design. There is no SEC structured-feed
equivalent — pledging is disclosed only in DEF 14A footnotes / 10-K Item 12,
which require NLP. The opt-in `pasted_pledging` channel in the subagent
(see internal/agents/ownership-tracker.md Rule 7) is the v1 US-pledging path;
the helper does not auto-fetch.

Why a helper script (not LLM-inline parsing):
  - NSE PIT requires homepage->cookie bootstrap with `Accept-Encoding: gzip,
    deflate` (NOT brotli — brotli breaks the response per StockClarity).
  - SEC EDGAR Form 4 returns lots that must be aggregated per
    (insider, P/S code) per filing; LLM lot-summing is error-prone.
  - 5-filter pipeline (India) and value+price filter (US) must be applied
    identically every time; deterministic code beats LLM filter prose.
  - yfinance Ticker.major_holders returns a small DataFrame whose columns
    have shifted across yfinance versions; the helper canonicalizes.
  - CIK resolution from sec.gov/files/company_tickers.json should be cached
    in-process per session, not re-fetched per ticker.

Same pattern as scripts/fetch_disclosures.py / fetch_calendar.py /
fetch_fundamentals.py / fetch_news.py: Bash-invoked, JSON to stdout,
exit codes documented.

Usage:
    # US, all channels:
    python scripts/fetch_ownership.py \\
        --market US --ticker MSFT --cik 0000789019 \\
        --channels insiders,shareholding --insiders-since 2026-01-30

    # US, CIK auto-resolved:
    python scripts/fetch_ownership.py \\
        --market US --ticker MSFT \\
        --channels insiders,shareholding --insiders-since 2026-01-30

    # India, all channels (nse-symbol REQUIRED):
    python scripts/fetch_ownership.py \\
        --market India --ticker NTPC \\
        --bse-code 532555 --nse-symbol NTPC \\
        --channels insiders,shareholding --insiders-since 2026-01-30

    # India, insiders only:
    python scripts/fetch_ownership.py \\
        --market India --ticker NTPC --nse-symbol NTPC \\
        --channels insiders --insiders-since 2026-01-30

    # With existing-yaml dedup (helper drops fetched txns whose id already
    # exists in the file):
    python scripts/fetch_ownership.py \\
        --market US --ticker MSFT --cik 0000789019 \\
        --channels insiders --insiders-since 2026-01-30 \\
        --existing-insiders holdings/msft/insiders.yaml

Exit codes:
    0 - success or partial success (check JSON `errors` array)
    1 - complete failure (no items returned across all channels, AND at least
        one error)
    2 - bad usage (argparse)

Requires `requests` and `yfinance`. See requirements.txt.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

# Force UTF-8 stdout on Windows consoles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print(json.dumps({
        "errors": ["requests not installed. Run: pip install -r requirements.txt"],
        "transactions": [],
        "shareholding": None,
        "search_log": [],
    }), file=sys.stdout)
    sys.exit(1)

# yfinance is optional at import time — only required for `--market US
# --channels shareholding`. We defer the ImportError until that path runs so
# that India-only invocations succeed in environments without yfinance.
_yf_module = None
_yf_import_error: Optional[str] = None
try:
    import yfinance as yf
    _yf_module = yf
except ImportError as exc:
    _yf_import_error = f"yfinance not installed: {exc}. Run: pip install -r requirements.txt"


# =============================================================================
# Hard-coded thresholds — ported from StockClarity verbatim
# =============================================================================
# See StockClarity config/signal_sources.yaml lines 282-310 for the matching
# config block. We use exactly StockClarity's documented production thresholds.

MIN_BUY_VALUE_INR = 10_000_000      # ₹1 Cr
MIN_SELL_VALUE_INR = 50_000_000     # ₹5 Cr
MIN_BUY_VALUE_USD = 500_000          # $500K
MIN_SELL_VALUE_USD = 2_000_000       # $2M

# Hard cap on transactions[] list per Rule 8 of the contract.
MAX_TRANSACTIONS_PER_TICKER = 50

# Hard cap on shareholding history[] per Rule 9 of the contract.
MAX_SHAREHOLDING_HISTORY_QUARTERS = 8


# =============================================================================
# Endpoint configuration
# =============================================================================

# --- SEC EDGAR (US insider via Form 4) ---
# We use the SEC submissions JSON endpoint (same one disclosure-fetcher uses)
# rather than the legacy browse-edgar Atom feed. The submissions endpoint is
# faster, reliably reachable, and returns parallel arrays we can iterate by
# index. The Atom feed is Cloudflare-protected and times out from many envs.
SEC_TICKER_TO_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
SEC_HEADERS = {
    # Per SEC fair-access policy:
    # https://www.sec.gov/os/accessing-edgar-data
    # Format: "Sample Company Name AdminContact@<domain>.com"
    # Same UA used by scripts/fetch_disclosures.py for consistency.
    "User-Agent": "Veda Advisor disclosure-fetcher contact@veda-advisor.com",
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/atom+xml,application/json,text/html,*/*",
}

# --- NSE (India insider + shareholding) ---
# Ported from StockClarity src/workflow/signal_source_insider_india.py:
NSE_HOMEPAGE = "https://www.nseindia.com"
NSE_PIT_URL = "https://www.nseindia.com/api/corporates-pit"
NSE_CORP_SHP_URL = "https://www.nseindia.com/api/corporate-share-holdings-master"
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    # CRITICAL: do NOT include 'br' (brotli) — causes garbled output with the
    # requests library. StockClarity flagged this explicitly.
    "Accept-Encoding": "gzip, deflate",
    "Referer": (
        "https://www.nseindia.com/companies-listing/"
        "corporate-filings-insider-trading"
    ),
}
NSE_WARMUP_URLS = [
    "https://www.nseindia.com",
    "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading",
]

# --- BSE (India shareholding fallback) ---
# Used only when NSE corp-shp returns no rows. BSE's shareholding API:
BSE_CORP_SHP_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/Trades/w?Type=ShareHolding&Flag=N&scripcode={code}"
)
BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.bseindia.com/",
    "Referer": "https://www.bseindia.com/",
}

# --- Shared HTTP config ---
DEFAULT_REQUEST_TIMEOUT_S = 30
DEFAULT_MAX_RETRIES = 3
SEC_REQUEST_DELAY_S = 0.20    # SEC fair-use: <= 10 req/s; we use 5 req/s
NSE_BOOTSTRAP_MAX_ATTEMPTS = 3
NSE_API_MAX_ATTEMPTS = 3


# =============================================================================
# Safe value parsing — ported from StockClarity verbatim
# =============================================================================

def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely parse a value to float.

    Handles `'-'`, `'Nil'`, `None`, empty strings, and comma-formatted
    numbers — all observed in NSE PIT and SEC Form 4 responses.
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).strip()
    if val_str in ("-", "Nil", "", "None", "NA", "N/A"):
        return default
    try:
        return float(val_str.replace(",", ""))
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    """Safely parse a value to int."""
    return int(_safe_float(val, default=float(default)))


def _slug(name: str) -> str:
    """Lowercase + spaces->hyphens + strip non-alnum-hyphen.

    Used for transaction `id` generation (Rule 5 of contract).
    """
    s = (name or "unknown").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "unknown"


# =============================================================================
# CIK resolution (US) — ported from scripts/fetch_disclosures.py
# =============================================================================

_cik_cache: Optional[Dict[str, str]] = None


def _resolve_cik(ticker: str) -> Optional[str]:
    """Resolve a ticker to a 10-digit zero-padded CIK via sec.gov/files/company_tickers.json.

    Cached in-process for the session.
    """
    global _cik_cache
    if _cik_cache is None:
        try:
            resp = requests.get(
                SEC_TICKER_TO_CIK_URL,
                headers=SEC_HEADERS,
                timeout=DEFAULT_REQUEST_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json()
            _cik_cache = {
                row["ticker"].upper(): str(row["cik_str"]).zfill(10)
                for row in data.values()
            }
        except Exception:
            _cik_cache = {}
            return None
    return _cik_cache.get(ticker.upper())


# =============================================================================
# NSE session bootstrap — ported from StockClarity verbatim
# =============================================================================

def _create_nse_session() -> requests.Session:
    """Create a requests session with NSE cookies.

    NSE blocks raw API calls — must hit the homepage first to acquire session
    cookies (`_abck`, `ak_bmsc`, `bm_sz`), then use those cookies for
    subsequent API calls.
    """
    last_statuses: List[str] = []

    for attempt in range(1, NSE_BOOTSTRAP_MAX_ATTEMPTS + 1):
        session = requests.Session()
        session.headers.update(NSE_HEADERS)

        warmup_ok = False
        for url in NSE_WARMUP_URLS:
            try:
                resp = session.get(url, timeout=10)
                last_statuses.append(f"{url}={resp.status_code}")
                if resp.status_code == 200:
                    warmup_ok = True
            except Exception as exc:
                last_statuses.append(f"{url}=EXC:{type(exc).__name__}")

        if warmup_ok:
            # Brief jitter before API call to avoid immediate 403.
            time.sleep(0.8 + random.random() * 0.6)
            return session

        if attempt < NSE_BOOTSTRAP_MAX_ATTEMPTS:
            time.sleep(1.2 * attempt)

    raise RuntimeError(
        "NSE bootstrap failed: " + " | ".join(last_statuses[-len(NSE_WARMUP_URLS):])
    )


# =============================================================================
# US insiders — SEC EDGAR Form 4 (via submissions JSON)
# =============================================================================
# We use the SEC submissions JSON endpoint (same one disclosure-fetcher uses)
# rather than the legacy browse-edgar Atom feed. Submissions JSON is faster
# and reliably reachable; the Atom feed is Cloudflare-protected and times
# out from many environments. The submissions endpoint returns parallel
# arrays (form[i] / filingDate[i] / accessionNumber[i] / primaryDocument[i])
# we iterate by index. For Form 4, the primary document IS the XML — no
# index-page scrape needed. Filter pipeline (transactionCode P/S, non-zero
# price/shares, value threshold) and lot aggregation are ported from
# StockClarity verbatim.

def _fetch_form4_filings_from_submissions(
    cik: str,
    since_iso: str,
) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """Fetch Form 4 filings from SEC submissions JSON since ``since_iso``.

    Returns (filings, error). filings is a list of dicts with:
        accession_number, accession_no_dashes, filing_date,
        primary_document, cik_no_pad, xml_url.
    """
    url = SEC_SUBMISSIONS_URL.format(cik=cik)
    try:
        resp = requests.get(
            url, headers=SEC_HEADERS, timeout=DEFAULT_REQUEST_TIMEOUT_S
        )
        time.sleep(SEC_REQUEST_DELAY_S)
    except Exception as exc:
        return [], f"SEC submissions fetch failed: {exc}"

    if resp.status_code != 200:
        return [], f"SEC submissions returned status {resp.status_code}"

    try:
        data = resp.json()
    except ValueError as exc:
        return [], f"SEC submissions JSON decode failed: {exc}"

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_documents = recent.get("primaryDocument", [])

    n = min(
        len(forms), len(filing_dates), len(accession_numbers),
        len(primary_documents),
    )
    cik_no_pad = str(int(cik))  # archive URLs use unpadded CIK

    try:
        cutoff = datetime.strptime(since_iso, "%Y-%m-%d").date()
    except ValueError:
        cutoff = date.today() - timedelta(days=90)

    filings: List[Dict[str, str]] = []
    for i in range(n):
        form = (forms[i] or "").strip()
        if form != "4":
            continue
        filing_date_str = (filing_dates[i] or "").strip()
        try:
            filing_dt = datetime.strptime(filing_date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if filing_dt < cutoff:
            # Submissions are date-descending; once below cutoff we can stop.
            break

        accession = (accession_numbers[i] or "").strip()
        primary_doc = (primary_documents[i] or "").strip()
        if not accession or not primary_doc:
            continue
        accession_no_dashes = accession.replace("-", "")

        # Form 4 is filed by the individual insider, not the issuer. The
        # filing's archive URL uses the FILER (insider) CIK — encoded as the
        # first 10 digits of the accession number — not the issuer CIK we
        # passed in. (Disclosure-fetcher uses the issuer CIK because Form
        # 8-K is filed by the company itself; Form 4 is filed by the
        # reporting owner.) Strip leading zeros for the archive URL path.
        try:
            filer_cik_no_pad = str(int(accession.split("-")[0]))
        except (ValueError, IndexError):
            continue

        # The primary document for Form 4 is the XML itself.
        xml_url = (
            f"{SEC_ARCHIVES_BASE}/{filer_cik_no_pad}/{accession_no_dashes}/"
            f"{primary_doc}"
        )
        filings.append({
            "accession_number": accession,
            "accession_no_dashes": accession_no_dashes,
            "filing_date": filing_date_str,
            "primary_document": primary_doc,
            "filer_cik_no_pad": filer_cik_no_pad,
            "issuer_cik_no_pad": cik_no_pad,
            "xml_url": xml_url,
        })
    return filings, None


def _derive_designation(root: ET.Element) -> str:
    """Derive a human-readable designation from Form 4 owner relationship.

    Priority: officerTitle > Director > 10% Owner > "Insider".
    """
    is_director = (root.findtext(".//isDirector") or "").strip() == "1"
    is_officer = (root.findtext(".//isOfficer") or "").strip() == "1"
    is_ten_pct = (root.findtext(".//isTenPercentOwner") or "").strip() == "1"
    officer_title = (root.findtext(".//officerTitle") or "").strip()

    parts: List[str] = []
    if is_officer and officer_title:
        parts.append(officer_title)
    elif is_officer:
        parts.append("Officer")
    if is_director:
        parts.append("Director")
    if is_ten_pct:
        parts.append("10% Owner")
    return ", ".join(parts) if parts else "Insider"


def _find_form4_xml_url(
    filer_cik_no_pad: str,
    accession_no_dashes: str,
) -> Optional[str]:
    """Locate the raw Form 4 XML inside a filing's archive directory.

    Form 4's ``primaryDocument`` from the submissions JSON is usually the
    HTML wrapper. The actual ownership XML lives alongside it. We use the
    filing's ``index.json`` to enumerate files and pick the first ``.xml``
    that is not an XSL transform.
    """
    index_url = (
        f"{SEC_ARCHIVES_BASE}/{filer_cik_no_pad}/{accession_no_dashes}/"
        f"index.json"
    )
    try:
        resp = requests.get(
            index_url, headers=SEC_HEADERS, timeout=DEFAULT_REQUEST_TIMEOUT_S
        )
        time.sleep(SEC_REQUEST_DELAY_S)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None

    items = data.get("directory", {}).get("item", [])
    for entry in items:
        name = (entry.get("name") or "").strip()
        if not name.lower().endswith(".xml"):
            continue
        # Skip XSL stylesheets (e.g., xslF345X05/edgardoc.xml).
        lower = name.lower()
        if "xsl" in lower or "/" in name:
            continue
        return (
            f"{SEC_ARCHIVES_BASE}/{filer_cik_no_pad}/"
            f"{accession_no_dashes}/{name}"
        )
    return None


def _parse_form4_xml(xml_url: str, filing_date: str) -> List[Dict[str, Any]]:
    """Parse a Form 4 XML and extract non-derivative P/S transactions.

    Returns a list of lot dicts (one per individual lot — caller aggregates).
    """
    try:
        resp = requests.get(
            xml_url, headers=SEC_HEADERS, timeout=DEFAULT_REQUEST_TIMEOUT_S
        )
        time.sleep(SEC_REQUEST_DELAY_S)
    except Exception:
        return []
    if resp.status_code != 200:
        return []

    # Some Form 4 primary documents are HTML wrappers, not raw XML. Skip if so.
    text = resp.text
    if "<ownershipDocument" not in text and "<?xml" not in text[:200]:
        return []

    # Strip the default XML namespace so simple XPath like
    # ``.//rptOwnerName`` matches. Form 4 declares
    # ``xmlns="http://www.sec.gov/edgar/ownership/0202"`` (or 0306) on the
    # root, which would otherwise force every findall/findtext to use
    # Clark-notation prefixes.
    text = re.sub(r'\s+xmlns="[^"]+"', "", text, count=1)

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    insider_name = (root.findtext(".//rptOwnerName") or "Unknown").strip()
    designation = _derive_designation(root)

    lots: List[Dict[str, Any]] = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        code = (txn.findtext(".//transactionCode") or "").strip()
        if code not in ("P", "S"):
            continue
        shares = _safe_float(txn.findtext(".//transactionShares/value"))
        price = _safe_float(txn.findtext(".//transactionPricePerShare/value"))
        txn_date_str = (
            txn.findtext(".//transactionDate/value") or ""
        ).strip()
        if price <= 0 or shares <= 0:
            continue
        lots.append({
            "insider_name": insider_name,
            "designation": designation,
            "transaction_code": code,
            "shares": shares,
            "price": price,
            "total_value": shares * price,
            "transaction_date": txn_date_str,
            "filing_date": filing_date,
        })
    return lots


def _aggregate_form4_lots(
    lots: List[Dict[str, Any]],
    accession_number: str,
) -> List[Dict[str, Any]]:
    """Aggregate lots from a single filing by (insider_name, transaction_code).

    EDGAR reports multiple lots per filing (e.g., 7 sale lots at slightly
    different prices for the same insider on the same day). We sum shares,
    compute weighted-average price, and sum value per (insider, direction).
    """
    if not lots:
        return []

    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for lot in lots:
        key = (lot["insider_name"], lot["transaction_code"])
        groups[key].append(lot)

    aggregated: List[Dict[str, Any]] = []
    for (insider_name, code), grp in groups.items():
        total_shares = sum(l["shares"] for l in grp)
        total_value = sum(l["total_value"] for l in grp)
        wavg_price = total_value / total_shares if total_shares > 0 else 0.0
        first = grp[0]
        aggregated.append({
            "insider_name": insider_name,
            "designation": first["designation"],
            "transaction_code": code,
            "shares": total_shares,
            "price": round(wavg_price, 2),
            "total_value": total_value,
            "transaction_date": first["transaction_date"],
            "filing_date": first["filing_date"],
            "lot_count": len(grp),
            "accession_number": accession_number,
        })
    return aggregated


def _form4_to_transaction(agg: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    """Map an aggregated Form 4 row to the insiders.yaml transaction shape."""
    direction = "buy" if agg["transaction_code"] == "P" else "sell"
    txn_date = agg.get("transaction_date") or agg.get("filing_date") or ""
    person_slug = _slug(agg["insider_name"])
    direction_code = agg["transaction_code"]  # "P" or "S"
    txn_id = f"{agg['accession_number']}-{person_slug}-{direction_code}"

    note_parts: List[str] = []
    if agg.get("lot_count", 1) > 1:
        note_parts.append(f"aggregated from {agg['lot_count']} lots")

    out: Dict[str, Any] = {
        "id": txn_id,
        "date": txn_date or None,
        "person": agg["insider_name"],
        "role": agg["designation"],
        "type": direction,
        "shares": int(agg["shares"]),
        "price": float(agg["price"]),
        "value_mm": round(agg["total_value"] / 1_000_000, 4),  # USD millions
        "currency": "USD",
        "source": "SEC Form 4",
        "source_url": (
            f"https://www.sec.gov/cgi-bin/browse-edgar"
            f"?action=getcompany&CIK={ticker}"
            f"&type=4&dateb=&owner=include&count=40"
        ),
        "accession_number": agg["accession_number"],
    }
    if note_parts:
        out["note"] = "; ".join(note_parts)
    return out


def _us_insider_passes_threshold(agg: Dict[str, Any]) -> bool:
    """US value-threshold filter: $500K buy / $2M sell."""
    val = agg["total_value"]
    if agg["transaction_code"] == "P":
        return val >= MIN_BUY_VALUE_USD
    return val >= MIN_SELL_VALUE_USD


def fetch_us_insiders(
    ticker: str,
    cik: str,
    since_iso: str,
    search_log: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Fetch and normalize US insider trades from SEC Form 4.

    Returns (transactions, raw_count, kept_count).
    raw_count = aggregated rows BEFORE threshold filter.
    kept_count = rows AFTER threshold filter.
    """
    filings, err = _fetch_form4_filings_from_submissions(cik, since_iso)
    if err:
        search_log.append({
            "operation": "helper_invocation",
            "source": "sec_form4",
            "result": "failed",
            "detail": err,
        })
        return [], 0, 0

    if not filings:
        search_log.append({
            "operation": "helper_invocation",
            "source": "sec_form4",
            "result": "miss",
            "detail": f"no Form 4 filings since {since_iso}",
            "helper_summary": {
                "items_raw": 0,
                "items_after_filter": 0,
                "items_after_dedup": 0,
                "endpoint_errors": [],
            },
        })
        return [], 0, 0

    all_aggregated: List[Dict[str, Any]] = []
    endpoint_errors: List[str] = []

    for filing in filings:
        # Form 4 primary_document is typically the HTML wrapper. Scrape the
        # filing's index page to find the raw .xml file (skip XSL transforms).
        xml_url = _find_form4_xml_url(
            filing["filer_cik_no_pad"],
            filing["accession_no_dashes"],
        )
        if not xml_url:
            endpoint_errors.append(
                f"no XML link in {filing['accession_number']}"
            )
            continue
        lots = _parse_form4_xml(xml_url, filing["filing_date"])
        if not lots:
            endpoint_errors.append(
                f"no parseable lots in {filing['accession_number']}"
            )
            continue
        agg = _aggregate_form4_lots(lots, filing["accession_number"])
        all_aggregated.extend(agg)

    raw_count = len(all_aggregated)
    kept = [a for a in all_aggregated if _us_insider_passes_threshold(a)]
    kept_count = len(kept)
    transactions = [_form4_to_transaction(a, ticker) for a in kept]

    search_log.append({
        "operation": "helper_invocation",
        "source": "sec_form4",
        "result": f"hit_{kept_count}" if kept_count > 0 else "miss",
        "helper_summary": {
            "items_raw": raw_count,
            "items_after_filter": kept_count,
            "items_after_dedup": kept_count,  # dedup applied later vs existing
            "endpoint_errors": endpoint_errors,
        },
    })
    return transactions, raw_count, kept_count


# =============================================================================
# India insiders — NSE PIT API (ported from StockClarity verbatim)
# =============================================================================

# Filter constants — ported from StockClarity src/workflow/signal_source_insider_india.py:
_NSE_PIT_VALID_SEC_TYPES = {"Equity Shares"}
_NSE_PIT_VALID_TXN_TYPES = {"Buy", "Sell"}
_NSE_PIT_VALID_BUY_MODES = {"Market Purchase"}
_NSE_PIT_VALID_SELL_MODES = {"Market Sale"}


def _nse_pit_passes_filters(trade: dict) -> bool:
    """5-filter pipeline ported verbatim from StockClarity.

    1. secType == "Equity Shares" — exclude ADR/GDR/FCCB
    2. tdpTransactionType in (Buy, Sell) — exclude Pledge variants
    3. acqMode in (Market Purchase / Market Sale) — exclude ESOP, Off Market,
       Gift, Inter-se-Transfer, Conversion, Preferential
    4. secVal > 0 — exclude zero-value transfers
    5. Value threshold: ≥₹1 Cr buy / ≥₹5 Cr sell
    """
    sec_type = trade.get("secType", "")
    txn_type = trade.get("tdpTransactionType", "")
    acq_mode = trade.get("acqMode", "")
    sec_val = _safe_float(trade.get("secVal"))

    if sec_type not in _NSE_PIT_VALID_SEC_TYPES:
        return False
    if txn_type not in _NSE_PIT_VALID_TXN_TYPES:
        return False
    if txn_type == "Buy" and acq_mode not in _NSE_PIT_VALID_BUY_MODES:
        return False
    if txn_type == "Sell" and acq_mode not in _NSE_PIT_VALID_SELL_MODES:
        return False
    if sec_val <= 0:
        return False
    if txn_type == "Buy" and sec_val < MIN_BUY_VALUE_INR:
        return False
    if txn_type == "Sell" and sec_val < MIN_SELL_VALUE_INR:
        return False
    return True


def _parse_nse_pit_date(trade: dict) -> Optional[str]:
    """Parse NSE PIT acqtoDt to ISO YYYY-MM-DD.

    Field format observed: "25-Feb-2026 00:00".
    """
    raw = trade.get("acqtoDt") or trade.get("acqfromDt") or ""
    if not raw or not isinstance(raw, str):
        return None
    try:
        date_str = raw.split(" ")[0] if " " in raw else raw
        return datetime.strptime(date_str, "%d-%b-%Y").date().isoformat()
    except (ValueError, AttributeError):
        return None


def _nse_pit_to_transaction(trade: dict) -> Dict[str, Any]:
    """Map an NSE PIT trade to the insiders.yaml transaction shape."""
    txn_type_raw = trade.get("tdpTransactionType", "")
    direction = "buy" if txn_type_raw == "Buy" else "sell"
    direction_code = "B" if direction == "buy" else "S"
    total_value = _safe_float(trade.get("secVal"))
    shares = _safe_int(trade.get("secAcq"))
    avg_price = round(total_value / shares, 2) if shares > 0 else 0.0
    person = (trade.get("acqName") or "Unknown").strip()
    role = (trade.get("personCategory") or "-").strip()
    txn_date = _parse_nse_pit_date(trade)
    person_slug = _slug(person)
    txn_id = (
        f"{txn_date or 'unknown'}-NSE-{person_slug}-{direction_code}-{shares}"
    )
    return {
        "id": txn_id,
        "date": txn_date,
        "person": person,
        "role": role,
        "type": direction,
        "shares": shares,
        "price": avg_price,
        "value_cr": round(total_value / 10_000_000, 4),  # INR crores
        "currency": "INR",
        "source": "NSE PIT",
    }


def fetch_india_insiders(
    nse_symbol: str,
    since_iso: str,
    search_log: List[Dict[str, Any]],
    nse_session: Optional[requests.Session] = None,
) -> Tuple[List[Dict[str, Any]], int, int, Optional[requests.Session]]:
    """Fetch and normalize India insider trades from NSE PIT API.

    Single all-companies-in-window fetch, then matches to nse_symbol
    (StockClarity's documented optimization: ~150x fewer API calls than
    per-company queries).

    Returns (transactions, raw_count, kept_count, nse_session).
    The session is returned so the caller can reuse it for shareholding fetch.
    """
    if nse_session is None:
        try:
            nse_session = _create_nse_session()
        except Exception as exc:
            search_log.append({
                "operation": "helper_invocation",
                "source": "nse_pit",
                "result": "failed",
                "detail": f"NSE bootstrap failed: {exc}",
            })
            return [], 0, 0, None

    # Lookback window
    try:
        from_dt = datetime.strptime(since_iso, "%Y-%m-%d").date()
    except ValueError:
        from_dt = date.today() - timedelta(days=90)
    from_str = from_dt.strftime("%d-%m-%Y")
    to_str = date.today().strftime("%d-%m-%Y")

    params = {"index": "equities", "from_date": from_str, "to_date": to_str}

    last_error: Optional[str] = None
    trades: List[dict] = []
    for attempt in range(1, NSE_API_MAX_ATTEMPTS + 1):
        try:
            resp = nse_session.get(
                NSE_PIT_URL, params=params, timeout=DEFAULT_REQUEST_TIMEOUT_S
            )
            if resp.status_code == 200:
                trades = resp.json().get("data", [])
                break
            last_error = f"status {resp.status_code}"
            if resp.status_code in {401, 403, 429, 500, 502, 503, 504}:
                if attempt < NSE_API_MAX_ATTEMPTS:
                    time.sleep(1.0 * attempt)
                    nse_session = _create_nse_session()
                    continue
            break
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < NSE_API_MAX_ATTEMPTS:
                time.sleep(1.0 * attempt)
                try:
                    nse_session = _create_nse_session()
                except Exception:
                    pass
                continue

    if last_error and not trades:
        search_log.append({
            "operation": "helper_invocation",
            "source": "nse_pit",
            "result": "failed",
            "detail": last_error,
        })
        return [], 0, 0, nse_session

    # Filter to this ticker
    nse_upper = nse_symbol.strip().upper()
    matched = [
        t for t in trades
        if (t.get("symbol") or "").strip().upper() == nse_upper
    ]
    raw_count = len(matched)
    kept = [t for t in matched if _nse_pit_passes_filters(t)]
    kept_count = len(kept)
    transactions = [_nse_pit_to_transaction(t) for t in kept]

    search_log.append({
        "operation": "helper_invocation",
        "source": "nse_pit",
        "result": f"hit_{kept_count}" if kept_count > 0 else "miss",
        "helper_summary": {
            "items_raw": raw_count,
            "items_after_filter": kept_count,
            "items_after_dedup": kept_count,  # dedup applied later vs existing
            "endpoint_errors": [],
        },
    })
    return transactions, raw_count, kept_count, nse_session


# =============================================================================
# India shareholding + pledging — NSE corp-shp endpoint (fresh)
# =============================================================================

def _period_from_date(d: str) -> Optional[str]:
    """Convert YYYY-MM-DD to YYYY-Qn (calendar quarter)."""
    try:
        dt = datetime.strptime(d, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def fetch_india_shareholding(
    nse_symbol: str,
    bse_code: Optional[str],
    search_log: List[Dict[str, Any]],
    nse_session: Optional[requests.Session] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch quarterly shareholding pattern from NSE corp-shp.

    BSE fallback when NSE returns no rows. Returns the latest snapshot
    dict shaped per the helper-output schema, or None on full failure.

    Note on endpoint: the public NSE shareholding-pattern endpoint surfaces
    multiple sub-endpoints; we use `corporate-share-holdings-master` which
    returns the structured promoter/public/FII/DII shares plus the pledge
    column. The endpoint occasionally rotates path; failure surfaces the
    URL in `endpoint_errors` so the caller can update the constant.
    """
    if nse_session is None:
        try:
            nse_session = _create_nse_session()
        except Exception as exc:
            search_log.append({
                "operation": "helper_invocation",
                "source": "nse_corp_shp",
                "result": "failed",
                "detail": f"NSE bootstrap failed: {exc}",
            })
            return _fetch_bse_shareholding_fallback(bse_code, search_log)

    params = {"index": "equities", "symbol": nse_symbol.strip().upper()}

    last_error: Optional[str] = None
    payload: Optional[dict] = None
    for attempt in range(1, NSE_API_MAX_ATTEMPTS + 1):
        try:
            resp = nse_session.get(
                NSE_CORP_SHP_URL,
                params=params,
                timeout=DEFAULT_REQUEST_TIMEOUT_S,
            )
            if resp.status_code == 200:
                payload = resp.json()
                break
            last_error = f"status {resp.status_code}"
            if resp.status_code in {401, 403, 429, 500, 502, 503, 504}:
                if attempt < NSE_API_MAX_ATTEMPTS:
                    time.sleep(1.0 * attempt)
                    nse_session = _create_nse_session()
                    continue
            break
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < NSE_API_MAX_ATTEMPTS:
                time.sleep(1.0 * attempt)
                try:
                    nse_session = _create_nse_session()
                except Exception:
                    pass
                continue

    rows = []
    if isinstance(payload, dict):
        # Endpoint variants: 'data', 'shareholdingPatterns', or top-level list.
        if isinstance(payload.get("data"), list):
            rows = payload["data"]
        elif isinstance(payload.get("shareholdingPatterns"), list):
            rows = payload["shareholdingPatterns"]
    elif isinstance(payload, list):
        rows = payload

    if not rows:
        search_log.append({
            "operation": "helper_invocation",
            "source": "nse_corp_shp",
            "result": "miss" if not last_error else "failed",
            "detail": last_error or "NSE corp-shp returned no rows for symbol",
        })
        return _fetch_bse_shareholding_fallback(bse_code, search_log)

    # Parse the most recent row. NSE corp-shp returns the quarter-end
    # date in the `date` field (e.g. "31-MAR-2026"). The `submissionDate`
    # is the regulatory filing date; we use the quarter-end as as_of.
    def _row_date(r: dict) -> str:
        for k in ("date", "asOnDate", "as_on_date", "submissionDate"):
            v = r.get(k)
            if v:
                return str(v).strip()
        return ""

    # Sort by date descending
    parsed_rows: List[Tuple[str, dict]] = []
    for r in rows:
        d = _row_date(r)
        # Try to normalize to ISO. NSE uses "31-MAR-2026" with uppercase
        # month codes; %b is locale-sensitive on Windows so title-case the
        # token before parsing.
        iso = None
        token = d.split(" ")[0]
        normalized = token
        # Title-case month abbreviation: "31-MAR-2026" -> "31-Mar-2026".
        if "-" in token and len(token.split("-")) == 3:
            parts = token.split("-")
            if len(parts[1]) == 3 and parts[1].isalpha():
                parts[1] = parts[1].title()
                normalized = "-".join(parts)
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                iso = datetime.strptime(normalized, fmt).date().isoformat()
                break
            except (ValueError, AttributeError):
                continue
        parsed_rows.append((iso or d, r))
    parsed_rows.sort(key=lambda x: x[0], reverse=True)

    snapshot = _normalize_nse_corp_shp_row(parsed_rows[0][1], parsed_rows[0][0])
    if snapshot is None:
        search_log.append({
            "operation": "helper_invocation",
            "source": "nse_corp_shp",
            "result": "failed",
            "detail": "could not normalize NSE corp-shp row to schema",
        })
        return _fetch_bse_shareholding_fallback(bse_code, search_log)

    # Capture up to MAX_SHAREHOLDING_HISTORY_QUARTERS - 1 older quarters
    # as `history[]` (the latest snapshot occupies the top-level fields).
    history: List[Dict[str, Any]] = []
    for older_iso, older_row in parsed_rows[1:MAX_SHAREHOLDING_HISTORY_QUARTERS]:
        older = _normalize_nse_corp_shp_row(older_row, older_iso)
        if older is not None:
            history.append({
                "period": older["period"],
                "as_of": older["as_of"],
                "promoter_pct": older["promoter_pct"],
                "fii_pct": older["fii_pct"],
                "dii_pct": older["dii_pct"],
                "public_pct": older["public_pct"],
            })
    if history:
        snapshot["history"] = history

    search_log.append({
        "operation": "helper_invocation",
        "source": "nse_corp_shp",
        "result": "hit_1",
        "helper_summary": {
            "items_raw": len(rows),
            "items_after_filter": 1 + len(history),
            "items_after_dedup": 1 + len(history),
            "endpoint_errors": [],
        },
    })
    return snapshot


def _normalize_nse_corp_shp_row(
    row: dict,
    as_of_iso: str,
) -> Optional[Dict[str, Any]]:
    """Map an NSE corp-shp row to the shareholding.yaml snapshot shape.

    NSE corp-shp's master endpoint surfaces only the promoter and public
    aggregates per filing (`pr_and_prgrp`, `public_val`). The FII / DII
    breakdown is inside the linked XBRL file and is not parsed here —
    callers receive `fii_pct: None` and `dii_pct: None` for India and
    must populate those from a separate channel if needed.

    Pledge is also not in this endpoint; pledging belongs in insiders.yaml
    and is sourced from the corporate-pledge endpoint or pasted SAST text
    via the agent's `pasted_pledging` opt-in channel.
    """
    def _get_pct(*keys: str) -> Optional[float]:
        for k in keys:
            v = row.get(k)
            if v is None:
                continue
            f = _safe_float(v, default=-1.0)
            if f >= 0:
                return f
        return None

    promoter_pct = _get_pct("pr_and_prgrp", "promoterAndPromoterGroup")
    public_pct = _get_pct("public_val", "publicShareholding", "public")

    if promoter_pct is None and public_pct is None:
        return None

    period = _period_from_date(as_of_iso)
    return {
        "as_of": as_of_iso,
        "period": period,
        "source": "NSE shareholding pattern",
        "promoter_pct": promoter_pct,
        "fii_pct": None,
        "dii_pct": None,
        "public_pct": public_pct,
        "pledge_pct": None,
    }


def _fetch_bse_shareholding_fallback(
    bse_code: Optional[str],
    search_log: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """BSE fallback when NSE corp-shp returns no rows.

    Surfaces in search_log as `bse_shp_fallback`. Best-effort — BSE's
    public shareholding endpoint is less stable than NSE corp-shp and is
    used purely as a backup.
    """
    if not bse_code:
        search_log.append({
            "operation": "helper_invocation",
            "source": "bse_shp_fallback",
            "result": "miss",
            "detail": "no bse_code available for fallback",
        })
        return None

    url = BSE_CORP_SHP_URL.format(code=bse_code)
    try:
        resp = requests.get(
            url, headers=BSE_HEADERS, timeout=DEFAULT_REQUEST_TIMEOUT_S
        )
    except Exception as exc:
        search_log.append({
            "operation": "helper_invocation",
            "source": "bse_shp_fallback",
            "result": "failed",
            "detail": f"BSE fetch failed: {exc}",
        })
        return None

    if resp.status_code != 200:
        search_log.append({
            "operation": "helper_invocation",
            "source": "bse_shp_fallback",
            "result": "failed",
            "detail": f"BSE returned status {resp.status_code}",
        })
        return None

    try:
        payload = resp.json()
    except ValueError:
        search_log.append({
            "operation": "helper_invocation",
            "source": "bse_shp_fallback",
            "result": "failed",
            "detail": "BSE returned non-JSON response",
        })
        return None

    # BSE structure observed: top-level dict with 'Table' list of records,
    # each having QtrId / Promoter_Pct / FII_Pct / DII_Pct / Public_Pct
    # / Promoter_Pledged_Pct.
    rows = []
    if isinstance(payload, dict) and isinstance(payload.get("Table"), list):
        rows = payload["Table"]
    elif isinstance(payload, list):
        rows = payload
    if not rows:
        search_log.append({
            "operation": "helper_invocation",
            "source": "bse_shp_fallback",
            "result": "miss",
            "detail": "BSE returned no rows",
        })
        return None

    # Take first row (BSE typically returns most-recent first)
    row = rows[0]
    as_of = (
        row.get("QtrId") or row.get("Quarter") or row.get("AsOnDate") or ""
    )
    # BSE QtrId looks like "20260331" — convert to ISO if so.
    iso_as_of = as_of
    if isinstance(as_of, str) and re.match(r"^\d{8}$", as_of):
        try:
            iso_as_of = datetime.strptime(as_of, "%Y%m%d").date().isoformat()
        except ValueError:
            pass

    snapshot = {
        "as_of": iso_as_of,
        "period": _period_from_date(iso_as_of),
        "source": "BSE shareholding pattern (fallback)",
        "promoter_pct": _safe_float(
            row.get("Promoter_Pct") or row.get("PromoterPct"), default=-1.0
        ) or None,
        "fii_pct": _safe_float(
            row.get("FII_Pct") or row.get("FIIPct"), default=-1.0
        ) or None,
        "dii_pct": _safe_float(
            row.get("DII_Pct") or row.get("DIIPct"), default=-1.0
        ) or None,
        "public_pct": _safe_float(
            row.get("Public_Pct") or row.get("PublicPct"), default=-1.0
        ) or None,
        "pledge_pct": _safe_float(
            row.get("Promoter_Pledged_Pct") or row.get("PledgePct"),
            default=-1.0,
        ),
    }
    # Normalize -1.0 sentinels back to None
    for k in ("promoter_pct", "fii_pct", "dii_pct", "public_pct", "pledge_pct"):
        if snapshot[k] is not None and snapshot[k] < 0:
            snapshot[k] = None

    search_log.append({
        "operation": "helper_invocation",
        "source": "bse_shp_fallback",
        "result": "hit_1",
        "helper_summary": {
            "items_raw": len(rows),
            "items_after_filter": 1,
            "items_after_dedup": 1,
            "endpoint_errors": [],
        },
    })
    return snapshot


# =============================================================================
# US shareholding — yfinance major_holders (fresh)
# =============================================================================

def fetch_us_shareholding(
    ticker: str,
    search_log: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Fetch US shareholding split from yfinance major_holders.

    yfinance returns a small DataFrame whose row labels include:
        '% of Shares Held by All Insider'
        '% of Shares Held by Institutions'
        '% of Float Held by Institutions'
        'Number of Institutions Holding Shares'

    We extract insider_pct, institutional_pct, and derive retail_pct
    (capped at >= 0) as the residual.
    """
    if _yf_module is None:
        search_log.append({
            "operation": "helper_invocation",
            "source": "yfinance_major_holders",
            "result": "failed",
            "detail": _yf_import_error or "yfinance not available",
        })
        return None

    try:
        t = _yf_module.Ticker(ticker)
        mh = t.major_holders
    except Exception as exc:
        search_log.append({
            "operation": "helper_invocation",
            "source": "yfinance_major_holders",
            "result": "failed",
            "detail": f"yfinance error: {exc}",
        })
        return None

    if mh is None:
        search_log.append({
            "operation": "helper_invocation",
            "source": "yfinance_major_holders",
            "result": "miss",
            "detail": "yfinance returned no major_holders data",
        })
        return None

    # yfinance returns either a DataFrame with rows indexed by description
    # OR (older versions) a 2-column DataFrame with the description in col[1].
    insider_pct: Optional[float] = None
    institutional_pct: Optional[float] = None

    try:
        # Newer yfinance: DataFrame with index = description, single 'Value'
        # column holding fractional values (0.07 = 7%).
        if hasattr(mh, "index"):
            for idx_label in mh.index:
                label_str = str(idx_label).lower()
                value_col = mh.iloc[mh.index.get_loc(idx_label)]
                # value_col may be a Series (single Value column)
                if hasattr(value_col, "iloc") and len(value_col) >= 1:
                    v = value_col.iloc[0]
                else:
                    v = value_col
                v_num = _safe_float(v)
                if "insider" in label_str:
                    insider_pct = v_num
                elif "institution" in label_str and "float" not in label_str:
                    institutional_pct = v_num

        # Older yfinance: 2-column DataFrame, [percent, description]
        if (insider_pct is None and institutional_pct is None
                and hasattr(mh, "iloc")
                and mh.shape[1] >= 2):
            for i in range(min(mh.shape[0], 5)):
                row = mh.iloc[i]
                pct_raw = row.iloc[0]
                desc = str(row.iloc[1]).lower() if mh.shape[1] >= 2 else ""
                pct_str = str(pct_raw).replace("%", "")
                pct_val = _safe_float(pct_str)
                # Older versions returned percentages as e.g. "7.21%" strings
                # — convert to fractional 0.0721
                if pct_val > 1.0:
                    pct_val = pct_val / 100.0
                if "insider" in desc:
                    insider_pct = pct_val
                elif "institution" in desc and "float" not in desc:
                    institutional_pct = pct_val
    except Exception as exc:
        search_log.append({
            "operation": "helper_invocation",
            "source": "yfinance_major_holders",
            "result": "failed",
            "detail": f"yfinance major_holders parse error: {exc}",
        })
        return None

    # yfinance values are fractional (0.07 = 7%); convert to percentages.
    def _pct(v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        return round(v * 100.0, 2) if 0 <= v <= 1.0 else round(v, 2)

    insider_pct_pct = _pct(insider_pct)
    institutional_pct_pct = _pct(institutional_pct)

    if insider_pct_pct is None and institutional_pct_pct is None:
        search_log.append({
            "operation": "helper_invocation",
            "source": "yfinance_major_holders",
            "result": "miss",
            "detail": "could not extract insider/institutional from yfinance",
        })
        return None

    # Retail residual (best-effort; capped at >= 0)
    retail_pct: Optional[float] = None
    if (insider_pct_pct is not None
            and institutional_pct_pct is not None):
        retail_pct = round(
            max(0.0, 100.0 - insider_pct_pct - institutional_pct_pct), 2
        )

    today_iso = date.today().isoformat()
    snapshot = {
        "as_of": today_iso,
        "period": _period_from_date(today_iso),
        "source": "yfinance major_holders",
        "insider_pct": insider_pct_pct,
        "institutional_pct": institutional_pct_pct,
        "retail_pct": retail_pct,
    }
    search_log.append({
        "operation": "helper_invocation",
        "source": "yfinance_major_holders",
        "result": "hit_1",
    })
    return snapshot


# =============================================================================
# Existing-yaml dedup helpers
# =============================================================================

def _read_existing_ids(yaml_path: str) -> List[str]:
    """Read existing transaction `id` values from an insiders.yaml file.

    Lightweight regex (does not require PyYAML). Returns empty list if the
    file is missing or contains no `id:` entries.
    """
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    return re.findall(r"^\s*-?\s*id:\s*[\"']?([^\s\"'#]+)[\"']?\s*$",
                      text, re.MULTILINE)


# =============================================================================
# Argparse and main
# =============================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Veda ownership/insider fetcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--market", required=True, choices=["US", "India"],
        help="Market: US or India"
    )
    p.add_argument(
        "--ticker", required=True,
        help="Ticker symbol; used in transaction id and provenance"
    )
    p.add_argument(
        "--cik", default=None,
        help="(US only) SEC CIK; auto-resolved from sec.gov "
             "company_tickers.json if omitted"
    )
    p.add_argument(
        "--bse-code", default=None,
        help="(India) BSE scrip code; used as fallback for shareholding"
    )
    p.add_argument(
        "--nse-symbol", default=None,
        help="(India) NSE trading symbol; REQUIRED for India market"
    )
    p.add_argument(
        "--channels", required=True,
        help="Comma-separated list: insiders,shareholding"
    )
    p.add_argument(
        "--insiders-since", default=None,
        help="ISO date (YYYY-MM-DD) for insider lookback; defaults to "
             "today - 90 days"
    )
    p.add_argument(
        "--existing-insiders", default=None,
        help="Path to existing insiders.yaml; helper drops fetched txns "
             "whose id already exists"
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    channels = {c.strip() for c in args.channels.split(",") if c.strip()}
    valid_channels = {"insiders", "shareholding"}
    invalid = channels - valid_channels
    if invalid:
        print(json.dumps({
            "errors": [
                f"invalid channel(s): {sorted(invalid)}; "
                f"valid: {sorted(valid_channels)}"
            ],
            "transactions": [],
            "shareholding": None,
            "search_log": [],
        }), file=sys.stdout)
        return 2

    if args.market == "India" and not args.nse_symbol:
        print(json.dumps({
            "errors": [
                "--nse-symbol is required for --market India "
                "(both NSE PIT and NSE corp-shp key on it)"
            ],
            "transactions": [],
            "shareholding": None,
            "search_log": [],
        }), file=sys.stdout)
        return 2

    # CIK resolution for US
    cik = args.cik
    resolved_cik = None
    if args.market == "US":
        if not cik:
            cik = _resolve_cik(args.ticker)
            if cik:
                resolved_cik = cik
        else:
            cik = str(cik).zfill(10)
        if not cik:
            print(json.dumps({
                "errors": [f"could not resolve CIK for ticker {args.ticker}"],
                "transactions": [],
                "shareholding": None,
                "search_log": [],
            }), file=sys.stdout)
            return 1

    # Insider since
    if args.insiders_since:
        since_iso = args.insiders_since
    else:
        since_iso = (date.today() - timedelta(days=90)).isoformat()

    transactions: List[Dict[str, Any]] = []
    shareholding: Optional[Dict[str, Any]] = None
    search_log: List[Dict[str, Any]] = []
    errors: List[str] = []
    raw_count = 0
    kept_count = 0

    nse_session: Optional[requests.Session] = None

    # Insiders channel
    if "insiders" in channels:
        if args.market == "US":
            transactions, raw_count, kept_count = fetch_us_insiders(
                args.ticker, cik, since_iso, search_log
            )
        else:  # India
            transactions, raw_count, kept_count, nse_session = fetch_india_insiders(
                args.nse_symbol, since_iso, search_log
            )

    # Shareholding channel
    if "shareholding" in channels:
        if args.market == "US":
            shareholding = fetch_us_shareholding(args.ticker, search_log)
        else:  # India
            shareholding = fetch_india_shareholding(
                args.nse_symbol, args.bse_code, search_log, nse_session
            )

    # Dedup vs existing IDs (insiders only)
    added_count = len(transactions)
    if "insiders" in channels and args.existing_insiders:
        existing_ids = set(_read_existing_ids(args.existing_insiders))
        before = len(transactions)
        transactions = [t for t in transactions if t["id"] not in existing_ids]
        dedup_dropped = before - len(transactions)
        added_count = len(transactions)
        # Update the last insiders search_log entry's items_after_dedup
        for entry in reversed(search_log):
            if entry.get("source") in ("nse_pit", "sec_form4"):
                if "helper_summary" in entry:
                    entry["helper_summary"]["items_after_dedup"] = added_count
                break

    envelope = {
        "errors": errors,
        "ticker": args.ticker,
        "market": args.market,
        "channels_requested": sorted(channels),
        "transactions": transactions,
        "shareholding": shareholding,
        "search_log": search_log,
        "counts": {
            "transactions_fetched": raw_count,
            "transactions_kept": kept_count,
            "transactions_added": added_count,
        },
    }
    if resolved_cik:
        envelope["resolved_codes"] = {"cik": resolved_cik}

    # Determine exit code
    any_data = bool(transactions) or shareholding is not None
    any_error = any(
        e.get("result") == "failed" for e in search_log
    )
    print(json.dumps(envelope, ensure_ascii=False, indent=2), file=sys.stdout)
    if not any_data and any_error:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
