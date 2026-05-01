"""
Veda — disclosure fetcher and normalizer.

Fetches unscheduled material announcements from primary regulator APIs, parses
them, normalizes to a single JSON envelope, and applies a routine-disclosure
filter (StockClarity-ported, 12 SEBI patterns) plus light future-event
extraction.

Sources (all source-tier 1 — primary regulator filings):
  - United States: SEC EDGAR submissions API, filtered to Form 8-K
  - India:         BSE Corporate Announcements API
  - India:         NSE Corporate Announcements API

Called by the disclosure-fetcher subagent (see internal/agents/disclosure-fetcher.md)
via the `Bash` tool. The subagent does NOT speak HTTP, parse JSON, resolve CIKs,
or apply the routine-regex filter; those messy parts live here.

Why a helper script (not LLM-inline parsing):
  - SEC submissions JSON has parallel-array structure (form[i] / filingDate[i] /
    accessionNumber[i] / items[i]) that requires zip-style iteration; brittle in
    LLM context.
  - BSE/NSE need browser-spoofed headers and (for NSE) cookie priming.
  - CIK resolution from sec.gov/files/company_tickers.json should be cached
    in-process per session, not re-fetched per ticker.
  - The 12-pattern routine-regex filter must be applied identically every time.
  - Future-event extraction is conservative regex matching; LLM extraction would
    introduce hallucinated dates that corrupt calendar.yaml.

Same pattern as scripts/fetch_news.py and scripts/fetch_fundamentals.py:
Bash-invoked, JSON to stdout, exit codes documented.

Usage:
    # US 8-K — CIK provided:
    python scripts/fetch_disclosures.py \\
        --market US --ticker MSFT --cik 0000789019 --since 2026-01-30

    # US 8-K — CIK auto-resolved from sec.gov/files/company_tickers.json:
    python scripts/fetch_disclosures.py \\
        --market US --ticker MSFT --since 2026-01-30

    # India — fetch both BSE and NSE in one invocation (preferred when both
    # codes are available; helper dedups across sources):
    python scripts/fetch_disclosures.py \\
        --market India --ticker RELIANCE \\
        --bse-code 500325 --nse-symbol RELIANCE \\
        --since 2026-01-30

    # India — single source (when only one code is available):
    python scripts/fetch_disclosures.py \\
        --market India --ticker NTPC --nse-symbol NTPC \\
        --since 2026-01-30

Exit codes:
    0 - success or partial success (check JSON `errors` array)
    1 - complete failure (no items returned across all sources, or fatal error)
    2 - bad usage (argparse)

Requires `requests` (see requirements.txt). No third-party HTML parser needed
for the v1 path — SEC/BSE/NSE all return structured JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

# Force UTF-8 stdout so non-Latin characters in Indian press headlines do not
# crash the script on Windows consoles that default to cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print(json.dumps({
        "errors": ["requests not installed. Run: pip install -r requirements.txt"],
        "results": [],
    }), file=sys.stdout)
    sys.exit(1)


# =============================================================================
# Endpoint configuration
# =============================================================================

# --- SEC EDGAR ---
# Per SEC fair-access policy: ≤ 10 req/s and identifying User-Agent required.
# We use ≤ 2 req/s in practice with backoff, which is conservative.
SEC_TICKER_TO_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_FILING_INDEX_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count=40"
)
# An 8-K's primary document URL (used as source_url):
#   https://www.sec.gov/Archives/edgar/data/{cik_no_zero_pad}/{accession_no_dashes}/{primary_document}
# The filing-index page is:
#   https://www.sec.gov/Archives/edgar/data/{cik_no_zero_pad}/{accession_no_dashes}/{accession_with_dashes}-index.htm
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
SEC_HEADERS = {
    # SEC requires identification per their fair-use policy:
    # https://www.sec.gov/os/accessing-edgar-data
    # Format requested: "Sample Company Name AdminContact@<domain>.com"
    # We use a stable placeholder. Users self-hosting Veda are encouraged to
    # replace this with their own contact (the SEC tracks per-UA traffic).
    "User-Agent": "Veda Advisor disclosure-fetcher contact@veda-advisor.com",
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json,text/html,*/*",
}

# --- BSE Corporate Announcements (StockClarity-ported, see disclosure_scraper.py) ---
BSE_CORPORATE_ANNOUNCEMENTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_CORPORATE_ANNOUNCEMENTS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.bseindia.com/",
    "Referer": "https://www.bseindia.com/",
}

# --- NSE Corporate Announcements (StockClarity-ported, see disclosure_scraper.py) ---
NSE_BASE_URL = "https://www.nseindia.com/"
NSE_CORPORATE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"
NSE_CORPORATE_ANNOUNCEMENTS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",  # NOT brotli — StockClarity confirmed brotli breaks NSE
    "Referer": "https://www.nseindia.com/",
}

# --- Shared HTTP config ---
DEFAULT_REQUEST_TIMEOUT_S = 20
DEFAULT_MAX_RETRIES = 3
RATE_LIMIT_DELAY_S = 0.5  # between paginated BSE requests


# =============================================================================
# Routine-disclosure regex filter (StockClarity-ported, verbatim)
# =============================================================================
#
# Source: StockClarity src/workflow/disclosure_fetcher.py _IGNORED_DISCLOSURE_PATTERNS
# Each pattern documented with StockClarity's production-log evidence.
# These are India-specific (BSE/NSE) by origin; do NOT apply to SEC 8-K.

_ROUTINE_PATTERNS_INDIA = [
    # Original StockClarity 8 — routine SEBI compliance items, all 100% LLM-rejected
    r"Certificate under SEBI .*\(Depositories and Participants\)",
    r"Regulation 74\(5\)",
    r"Closure of Trading Window",
    r"Loss of Share Certificate",
    r"Issue of Duplicate Share Certificate",
    r"Investor Complaints",
    r"Statement of Investor Complaints",
    r"Compliance Certificate",
    # Added by StockClarity Mar 2026 from 7-day production log analysis:
    r"Analysts/Institutional Investor Meet/Con\.?\s*Call Updates?",  # 30 rej, 0 acc
    r"Shareholders meeting",  # AGM/EGM SCHEDULE notices, not OUTCOME (7 rej, 0 acc)
    r"Copy of Newspaper Publication",  # newspaper ad copies (5 rej, 0 acc)
    r"ESOP/ESOS/ESPS",  # routine employee stock option grants (5 rej, 0 acc)
]

_ROUTINE_REGEXES_INDIA = [re.compile(p, re.IGNORECASE) for p in _ROUTINE_PATTERNS_INDIA]


def _is_routine_india(headline: str, category: str) -> bool:
    """True iff the headline OR category matches a routine-disclosure pattern.

    Mirror of StockClarity's _is_ignored_disclosure(). India-only.
    """
    for r in _ROUTINE_REGEXES_INDIA:
        if headline and r.search(headline):
            return True
        if category and r.search(category):
            return True
    return False


# =============================================================================
# Future-event regex extraction (conservative; calendar.yaml is downstream)
# =============================================================================
#
# We deliberately keep the regex set small and high-precision. False positives
# would corrupt calendar.yaml; false negatives are recoverable (the user can
# manually add the event, or the calendar-tracker subagent will pick it up
# when it ships). We do NOT extract dates from generic "soon" / "in the coming
# weeks" prose — only explicit dates.
#
# Date format support:
#   - DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY (Indian convention)
#   - DD Month YYYY, DD-Mon-YYYY (BSE/NSE common)
#   - Month DD, YYYY (US convention, for SEC)
#   - YYYY-MM-DD (ISO; rare in filings but present in some)
# Each captured to ISO YYYY-MM-DD.

_MONTH_NAMES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _normalize_date_iso(day: int, month: int, year: int) -> Optional[str]:
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _try_parse_date_anywhere(text: str) -> Optional[str]:
    """Find the first plausible date in `text` and return ISO YYYY-MM-DD.

    Returns None if no date pattern matches.
    """
    if not text:
        return None

    # Pattern 1: DD-MM-YYYY / DD/MM/YYYY / DD.MM.YYYY (Indian convention; day first)
    m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Disambiguate DD-MM vs MM-DD: if first num > 12 it's DD-MM
        if d > 12 and mo <= 12:
            return _normalize_date_iso(d, mo, y)
        # If both ≤12 we assume DD-MM (Indian convention; SEC filings rarely
        # use this format anyway — they use Month DD, YYYY)
        return _normalize_date_iso(d, mo, y) or _normalize_date_iso(mo, d, y)

    # Pattern 2: DD Month YYYY, e.g., "15 May 2026" or "15-May-2026"
    m = re.search(r"\b(\d{1,2})[-\s]+([A-Za-z]{3,9})[-\s,]+(\d{4})\b", text)
    if m:
        d = int(m.group(1))
        mo = _MONTH_NAMES.get(m.group(2).lower())
        y = int(m.group(3))
        if mo:
            return _normalize_date_iso(d, mo, y)

    # Pattern 3: Month DD, YYYY, e.g., "May 15, 2026" (US convention)
    m = re.search(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b", text)
    if m:
        mo = _MONTH_NAMES.get(m.group(1).lower())
        d = int(m.group(2))
        y = int(m.group(3))
        if mo:
            return _normalize_date_iso(d, mo, y)

    # Pattern 4: YYYY-MM-DD (ISO)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _normalize_date_iso(d, mo, y)

    return None


# Future-event types mapped to phrasing patterns. Each pattern matches the
# announcement type; date extraction is then run on the **headline only**
# (not the summary), within a window of ~140 chars around the type-match.
#
# Headline-only extraction is conservative on purpose. Searching the summary
# would catch cases like "Board Meeting Outcome ... record date 2026-06-15"
# and produce a false-positive board_meeting on the record date. Headlines
# of future-event filings on BSE/NSE always carry the date in-line
# (e.g., "Board Meeting Intimation - 15-05-2026"); past-event filings carry
# either no date or a past date the today-or-later filter drops.
#
# False positives corrupt calendar.yaml; false negatives are recoverable
# (calendar-tracker will pick up the event when it ships, or the user can
# enter it manually).
_FUTURE_EVENT_TYPES: List[Tuple[str, re.Pattern]] = [
    ("board_meeting", re.compile(r"board\s+meeting", re.IGNORECASE)),
    ("agm", re.compile(r"\bAGM\b|annual\s+general\s+meeting", re.IGNORECASE)),
    ("egm", re.compile(r"\bEGM\b|extraordinary\s+general\s+meeting", re.IGNORECASE)),
    ("record_date", re.compile(r"record\s+date", re.IGNORECASE)),
    ("ex_dividend", re.compile(r"ex-?dividend\s+date|ex-?date", re.IGNORECASE)),
    ("rights_issue", re.compile(r"rights\s+issue", re.IGNORECASE)),
]


def _extract_future_event(
    headline: str,
    summary: str,  # noqa: ARG001 — kept for signature stability; intentionally unused
    today: datetime,
) -> Optional[Dict[str, str]]:
    """Conservative regex extraction of a *dated future scheduled event*.

    Searches the **headline only** (summary is intentionally ignored to avoid
    false positives like "Board Meeting Outcome ... record date 2026-06-15"
    producing a future board_meeting event on the record date).

    Returns None if no dated future event found. False positives corrupt
    calendar.yaml — when in doubt, return None.
    """
    if not headline:
        return None

    for event_type, type_re in _FUTURE_EVENT_TYPES:
        m = type_re.search(headline)
        if not m:
            continue
        # Date-search window: ±140 chars around the type-match within the
        # headline (covers "Board Meeting on May 15, 2026" and "Board Meeting
        # Intimation - 15-05-2026").
        start = max(0, m.start() - 140)
        end = min(len(headline), m.end() + 140)
        window = headline[start:end]
        iso = _try_parse_date_anywhere(window)
        if not iso:
            continue
        try:
            event_dt = datetime.strptime(iso, "%Y-%m-%d")
        except ValueError:
            continue
        # Future-event filter: the date must be today or later. A board
        # meeting that already happened isn't a calendar entry — it would be
        # the disclosure itself.
        if event_dt.date() < today.date():
            continue
        return {
            "date": iso,
            "type": event_type,
            "headline": headline[:120].strip(),
        }

    return None


# =============================================================================
# Normalized disclosure record
# =============================================================================

@dataclass
class DisclosureItem:
    """Normalized disclosure record — the unit of the JSON envelope's `items` list.

    Field shape mirrors disclosures[] in the disclosure-fetcher subagent contract.
    """
    id: str
    date: str  # ISO YYYY-MM-DD
    exchange: str  # SEC | BSE | NSE
    form_or_category: str
    items: List[str] = field(default_factory=list)  # 8-K Item codes; [] for India
    subcategory: Optional[str] = None  # BSE only
    headline: str = ""
    summary: str = ""
    source_url: str = ""
    attachment_url: Optional[str] = None
    routine: bool = False
    future_event: Optional[Dict[str, str]] = None


@dataclass
class FetchResult:
    """Per-source result from one fetch call."""
    items: List[DisclosureItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    raw_count: int = 0
    routine_filtered: int = 0
    source: str = ""  # sec_edgar_8k | bse_announcements | nse_announcements


# =============================================================================
# HTTP session builder
# =============================================================================

def _build_session(headers: Dict[str, str]) -> requests.Session:
    """Build a session with retry on 429/5xx."""
    session = requests.Session()
    retry = Retry(
        total=DEFAULT_MAX_RETRIES,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(headers)
    return session


# =============================================================================
# CIK resolution (US)
# =============================================================================
#
# Cached in-process: SEC's company_tickers.json is ~1MB, ~10000 entries; one
# fetch per script invocation. The script is short-lived (single subagent
# call); re-running the script is fine.

_CIK_CACHE: Optional[Dict[str, str]] = None


def _normalize_ticker_for_sec(ticker: str) -> str:
    """SEC uses hyphens for share classes (BRK-B); some platforms use dots (BRK.B)."""
    return ticker.upper().replace(".", "-")


def _resolve_cik(ticker: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve ticker to (CIK_zero_padded, error_or_None).

    On cache miss, fetches sec.gov/files/company_tickers.json once.
    """
    global _CIK_CACHE
    if _CIK_CACHE is None:
        try:
            session = _build_session(SEC_HEADERS)
            resp = session.get(SEC_TICKER_TO_CIK_URL, timeout=DEFAULT_REQUEST_TIMEOUT_S)
            resp.raise_for_status()
            data = resp.json()
            _CIK_CACHE = {}
            for entry in data.values():
                t = str(entry.get("ticker", "")).upper()
                cik = entry.get("cik_str")
                if t and cik is not None:
                    _CIK_CACHE[t] = str(cik).zfill(10)
        except Exception as exc:
            return None, f"SEC ticker→CIK lookup failed: {exc}"

    normalized = _normalize_ticker_for_sec(ticker)
    cik = _CIK_CACHE.get(normalized)
    if cik is None:
        return None, f"Ticker {ticker!r} not found in SEC company_tickers.json"
    return cik, None


# =============================================================================
# SEC EDGAR — 8-K fetcher
# =============================================================================

def fetch_sec_8k(
    ticker: str,
    cik: str,
    since: datetime,
    today: datetime,
) -> FetchResult:
    """Fetch 8-K filings for a US ticker since `since`.

    Uses the SEC submissions JSON endpoint and filters to Form 8-K within the
    date range. Each filing produces one DisclosureItem.
    """
    result = FetchResult(source="sec_edgar_8k")

    # Different host than the static archives endpoint, so use a fresh session.
    session = _build_session(SEC_HEADERS)
    url = SEC_SUBMISSIONS_URL.format(cik=cik)

    try:
        resp = session.get(url, timeout=DEFAULT_REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            result.errors.append(f"SEC EDGAR rate-limited (429) for CIK {cik}")
        else:
            result.errors.append(f"SEC EDGAR HTTP error for CIK {cik}: {exc}")
        return result
    except requests.exceptions.RequestException as exc:
        result.errors.append(f"SEC EDGAR request failed for CIK {cik}: {exc}")
        return result
    except json.JSONDecodeError as exc:
        result.errors.append(f"SEC EDGAR JSON decode error for CIK {cik}: {exc}")
        return result

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_documents = recent.get("primaryDocument", [])
    items_csv = recent.get("items", [])
    primary_doc_descriptions = recent.get("primaryDocDescription", [])

    n = min(len(forms), len(filing_dates), len(accession_numbers), len(primary_documents))
    cik_no_pad = str(int(cik))  # SEC archive URLs use the CIK without zero-padding

    for i in range(n):
        form = (forms[i] or "").strip()
        if form != "8-K":
            continue

        filing_date_str = (filing_dates[i] or "").strip()
        try:
            filing_dt = datetime.strptime(filing_date_str, "%Y-%m-%d")
        except ValueError:
            continue
        if filing_dt < since:
            # SEC submissions are date-descending; once below `since` we can stop.
            break
        if filing_dt > today:
            continue

        result.raw_count += 1

        accession = accession_numbers[i].strip()
        accession_no_dashes = accession.replace("-", "")
        primary_doc = (primary_documents[i] or "").strip()
        items_field = (items_csv[i] if i < len(items_csv) else "") or ""
        item_codes = [s.strip() for s in items_field.split(",") if s.strip()]
        primary_doc_desc = (primary_doc_descriptions[i] if i < len(primary_doc_descriptions) else "") or ""

        # source_url: filing index page (HTML, human-readable directory of the filing)
        source_url = (
            f"{SEC_ARCHIVES_BASE}/{cik_no_pad}/{accession_no_dashes}/"
            f"{accession}-index.htm"
        )
        # attachment_url: the primary document itself (the actual 8-K HTML)
        attachment_url = (
            f"{SEC_ARCHIVES_BASE}/{cik_no_pad}/{accession_no_dashes}/{primary_doc}"
            if primary_doc
            else None
        )

        # Headline derivation: the SEC submissions API does not carry an inline
        # 8-K title — we synthesize one from items + primaryDocDescription.
        # Item-code descriptions (per SEC):
        item_label = _summarize_8k_items(item_codes)
        if primary_doc_desc and primary_doc_desc.upper() != "8-K":
            headline = f"8-K: {item_label} — {primary_doc_desc}".strip(" —")
        else:
            headline = f"8-K: {item_label}" if item_label else "8-K filing"
        headline = headline[:200]

        # Summary: at this stage we do not have the body. The subagent may use
        # WebFetch on Item 2.02 / 5.02 cases per its Rule 11; for the helper we
        # leave summary minimal but informative.
        summary_parts = []
        if item_label:
            summary_parts.append(f"Items filed: {item_label}.")
        if primary_doc_desc:
            summary_parts.append(f"Primary document: {primary_doc_desc}.")
        summary = " ".join(summary_parts)[:300]

        # Future-event extraction on the headline + summary. SEC 8-K dated
        # future events are rare (most 8-Ks are about already-occurred events)
        # but Item 5.07 (shareholder votes) and 8.01 sometimes carry them.
        future_event = _extract_future_event(headline, summary, today)

        item = DisclosureItem(
            id=f"{filing_date_str}-SEC-{accession}",
            date=filing_date_str,
            exchange="SEC",
            form_or_category="8-K",
            items=item_codes,
            subcategory=None,
            headline=headline,
            summary=summary,
            source_url=source_url,
            attachment_url=attachment_url,
            routine=False,  # SEC 8-K is not subject to the India routine filter
            future_event=future_event,
        )
        result.items.append(item)

    return result


def _summarize_8k_items(item_codes: List[str]) -> str:
    """Render a comma-joined human-readable list of 8-K Item codes.

    Per SEC 8-K Item code descriptions (Form 8-K General Instructions):
      Item 1.01 — Entry into a Material Definitive Agreement
      Item 1.02 — Termination of a Material Definitive Agreement
      Item 1.03 — Bankruptcy or Receivership
      Item 2.01 — Completion of Acquisition or Disposition of Assets
      Item 2.02 — Results of Operations and Financial Condition
      Item 2.03 — Creation of a Direct Financial Obligation
      Item 2.04 — Triggering Events That Accelerate or Increase a Direct Financial Obligation
      Item 2.05 — Costs Associated with Exit or Disposal Activities
      Item 2.06 — Material Impairments
      Item 3.01 — Notice of Delisting or Failure to Satisfy a Continued Listing Rule
      Item 3.02 — Unregistered Sales of Equity Securities
      Item 3.03 — Material Modification to Rights of Security Holders
      Item 4.01 — Changes in Registrant's Certifying Accountant
      Item 4.02 — Non-Reliance on Previously Issued Financial Statements
      Item 5.01 — Changes in Control of Registrant
      Item 5.02 — Departure of Directors or Certain Officers; Appointment
      Item 5.03 — Amendments to Articles of Incorporation or Bylaws
      Item 5.07 — Submission of Matters to a Vote of Security Holders
      Item 7.01 — Regulation FD Disclosure
      Item 8.01 — Other Events
      Item 9.01 — Financial Statements and Exhibits
    """
    if not item_codes:
        return ""
    descriptions = {
        "1.01": "material agreement",
        "1.02": "termination of agreement",
        "1.03": "bankruptcy",
        "2.01": "acquisition/disposition",
        "2.02": "results of operations",
        "2.03": "direct financial obligation",
        "2.04": "triggering event on obligation",
        "2.05": "exit/disposal costs",
        "2.06": "material impairment",
        "3.01": "delisting notice",
        "3.02": "unregistered equity sales",
        "3.03": "material modification of rights",
        "4.01": "auditor change",
        "4.02": "non-reliance on prior statements",
        "5.01": "change in control",
        "5.02": "officer/director departure or appointment",
        "5.03": "amendment to articles/bylaws",
        "5.07": "shareholder vote",
        "7.01": "Regulation FD disclosure",
        "8.01": "other events",
        "9.01": "financial statements and exhibits",
    }
    pieces = []
    for code in item_codes:
        desc = descriptions.get(code)
        pieces.append(f"Item {code} ({desc})" if desc else f"Item {code}")
    return ", ".join(pieces)


# =============================================================================
# BSE — Corporate Announcements (StockClarity-ported)
# =============================================================================

def fetch_bse(
    scrip_code: str,
    since: datetime,
    today: datetime,
) -> FetchResult:
    """Fetch BSE corporate announcements. Ported from StockClarity disclosure_scraper.py."""
    result = FetchResult(source="bse_announcements")

    if not scrip_code or not scrip_code.strip().isdigit():
        result.errors.append(
            f"BSE scrip code must be numeric; got {scrip_code!r}"
        )
        return result

    session = _build_session(BSE_CORPORATE_ANNOUNCEMENTS_HEADERS)
    from_ymd = since.strftime("%Y%m%d")
    to_ymd = today.strftime("%Y%m%d")
    page = 1
    all_rows: List[Dict[str, Any]] = []

    while True:
        params = {
            "pageno": page,
            "strCat": "-1",
            "subcategory": "-1",
            "strPrevDate": from_ymd,
            "strToDate": to_ymd,
            "strSearch": "P",
            "strscrip": scrip_code,
            "strType": "C",
        }
        try:
            resp = session.get(
                BSE_CORPORATE_ANNOUNCEMENTS_URL,
                params=params,
                timeout=DEFAULT_REQUEST_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as exc:
            result.errors.append(f"BSE request failed (page {page}): {exc}")
            break
        except json.JSONDecodeError as exc:
            result.errors.append(f"BSE JSON decode error (page {page}): {exc}")
            break

        rows = data.get("Table", []) or []
        if not rows:
            break
        all_rows.extend(rows)
        time.sleep(RATE_LIMIT_DELAY_S)

        meta = (data.get("Table1", []) or [{}])[0]
        total = int(meta.get("ROWCNT", 0)) if meta.get("ROWCNT") else 0
        if total and len(all_rows) >= total:
            break
        page += 1

    # Normalize each row.
    for row in all_rows:
        result.raw_count += 1
        headline = (row.get("HEADLINE") or "").strip()
        category = (row.get("CATEGORYNAME") or "").strip()
        subcategory = (row.get("SUBCATNAME") or "").strip() or None
        content = (row.get("MORE") or "").strip()
        attachment_url = row.get("NSURL") or None
        news_id = str(row.get("NEWSID") or "").strip()
        date_str = (row.get("NEWS_DT") or "").strip()
        date_iso = _bse_date_to_iso(date_str)

        if _is_routine_india(headline, category):
            result.routine_filtered += 1
            continue

        source_url = attachment_url or f"disclosure://bse/{news_id}"
        summary = (content or category or "")[:300]

        future_event = _extract_future_event(headline, content, today)

        item = DisclosureItem(
            id=f"{date_iso}-BSE-{news_id}" if date_iso else f"BSE-{news_id}",
            date=date_iso or "",
            exchange="BSE",
            form_or_category=category,
            items=[],
            subcategory=subcategory,
            headline=headline[:200],
            summary=summary,
            source_url=source_url,
            attachment_url=attachment_url,
            routine=False,
            future_event=future_event,
        )
        result.items.append(item)

    return result


def _bse_date_to_iso(date_str: str) -> Optional[str]:
    """BSE date format: 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD'."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# =============================================================================
# NSE — Corporate Announcements (StockClarity-ported)
# =============================================================================

def fetch_nse(
    symbol: str,
    since: datetime,
    today: datetime,
) -> FetchResult:
    """Fetch NSE corporate announcements. Ported from StockClarity disclosure_scraper.py.

    NSE requires session cookie priming (visit the homepage first). Known to
    rate-limit aggressively (403 / 429); failures return empty rather than
    raising — the orchestrator can retry on a subsequent invocation.
    """
    result = FetchResult(source="nse_announcements")

    if not symbol or not symbol.strip():
        result.errors.append("NSE symbol required")
        return result

    session = _build_session(NSE_CORPORATE_ANNOUNCEMENTS_HEADERS)

    # Cookie priming (StockClarity pattern)
    try:
        session.get(NSE_BASE_URL, timeout=DEFAULT_REQUEST_TIMEOUT_S)
    except requests.exceptions.RequestException as exc:
        result.errors.append(f"NSE cookie priming failed: {exc}")
        return result

    params = {
        "index": "equities",
        "from_date": since.strftime("%d-%m-%Y"),
        "to_date": today.strftime("%d-%m-%Y"),
        "symbol": symbol.upper().strip(),
    }

    try:
        resp = session.get(
            NSE_CORPORATE_ANNOUNCEMENTS_URL,
            params=params,
            timeout=DEFAULT_REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code in (403, 429):
            result.errors.append(f"NSE rate-limited ({exc.response.status_code}) for {symbol}")
        else:
            result.errors.append(f"NSE HTTP error for {symbol}: {exc}")
        return result
    except requests.exceptions.RequestException as exc:
        result.errors.append(f"NSE request failed for {symbol}: {exc}")
        return result
    except json.JSONDecodeError as exc:
        result.errors.append(f"NSE JSON decode error for {symbol}: {exc}")
        return result

    raw = data if isinstance(data, list) else []

    for row in raw:
        result.raw_count += 1
        headline = (row.get("desc") or "").strip()
        category = (row.get("desc") or "").strip()  # NSE conflates desc/headline
        content = (row.get("attchmntText") or "").strip()
        attachment_url = row.get("attchmntFile") or None
        seq_id = str(row.get("seq_id") or "").strip()
        date_str = (row.get("an_dt") or "").strip()
        date_iso = _nse_date_to_iso(date_str)

        # Server-side date filtering can be loose; double-check.
        if date_iso:
            try:
                d = datetime.strptime(date_iso, "%Y-%m-%d")
                if d < since or d > today:
                    continue
            except ValueError:
                pass

        if _is_routine_india(headline, category):
            result.routine_filtered += 1
            continue

        source_url = attachment_url or f"disclosure://nse/{seq_id}"
        summary = (content or category or "")[:300]

        future_event = _extract_future_event(headline, content, today)

        item = DisclosureItem(
            id=f"{date_iso}-NSE-{seq_id}" if date_iso else f"NSE-{seq_id}",
            date=date_iso or "",
            exchange="NSE",
            form_or_category=category,
            items=[],
            subcategory=None,
            headline=headline[:200],
            summary=summary,
            source_url=source_url,
            attachment_url=attachment_url,
            routine=False,
            future_event=future_event,
        )
        result.items.append(item)

    return result


def _nse_date_to_iso(date_str: str) -> Optional[str]:
    """NSE date format: '02-Dec-2025 18:01:12'."""
    if not date_str:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# =============================================================================
# Cross-source dedup (BSE + NSE)
# =============================================================================
#
# When both BSE and NSE return announcements for the same ticker on the same
# day, many filings appear on both exchanges (the company files once, both
# exchanges publish). We dedup by (date, headline-prefix) match where the
# headline-prefix is the first 60 chars normalized.

def _norm_headline_for_dedup(headline: str) -> str:
    """Lowercase, strip non-alnum, take prefix."""
    s = re.sub(r"[^a-z0-9]+", "", headline.lower())
    return s[:60]


def _dedup_cross_source(items: List[DisclosureItem]) -> Tuple[List[DisclosureItem], int]:
    """Dedup BSE/NSE items reporting the same filing.

    Strategy: bucket by (date, normalized headline prefix). When >1 item per
    bucket, keep BSE preferentially (BSE is the older exchange and tends to
    have more reliable category metadata; NSE often conflates category+headline
    into a single field). Returns (deduped_list, dropped_count).
    """
    if not items:
        return items, 0

    by_key: Dict[Tuple[str, str], List[DisclosureItem]] = {}
    for it in items:
        key = (it.date, _norm_headline_for_dedup(it.headline))
        by_key.setdefault(key, []).append(it)

    kept: List[DisclosureItem] = []
    dropped = 0
    for key, group in by_key.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        # Multiple items match — prefer BSE.
        bse = [g for g in group if g.exchange == "BSE"]
        if bse:
            kept.append(bse[0])
            dropped += len(group) - 1
        else:
            kept.append(group[0])
            dropped += len(group) - 1

    return kept, dropped


# =============================================================================
# Argparse
# =============================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch unscheduled material disclosures for a single ticker. "
                    "Outputs JSON envelope to stdout. See module docstring for full usage."
    )
    p.add_argument("--market", required=True, choices=["US", "India"],
                   help="US (SEC EDGAR 8-K) or India (BSE + NSE)")
    p.add_argument("--ticker", required=True, help="Ticker symbol; used in id and logs")
    p.add_argument("--cik", default="",
                   help="SEC CIK (US only). If omitted, helper resolves from sec.gov/files/company_tickers.json")
    p.add_argument("--bse-code", default="", help="BSE scrip code (India only). Numeric.")
    p.add_argument("--nse-symbol", default="", help="NSE trading symbol (India only). Alphanumeric.")
    p.add_argument("--since", required=True,
                   help="Lower bound on filing date, YYYY-MM-DD (inclusive)")
    p.add_argument("--today", default="",
                   help="Override 'today' for testing, YYYY-MM-DD. Defaults to system date.")
    return p.parse_args()


# =============================================================================
# Main
# =============================================================================

def main() -> int:
    args = parse_args()

    # Date inputs
    try:
        since_dt = datetime.strptime(args.since, "%Y-%m-%d")
    except ValueError as exc:
        print(json.dumps({
            "errors": [f"Bad --since: {exc}"],
            "results": [],
        }), file=sys.stdout)
        return 2

    if args.today:
        try:
            today_dt = datetime.strptime(args.today, "%Y-%m-%d")
        except ValueError as exc:
            print(json.dumps({
                "errors": [f"Bad --today: {exc}"],
                "results": [],
            }), file=sys.stdout)
            return 2
    else:
        today_dt = datetime.now(timezone.utc).replace(tzinfo=None)

    if since_dt > today_dt:
        print(json.dumps({
            "errors": [f"--since {args.since} is after today {today_dt.strftime('%Y-%m-%d')}"],
            "results": [],
        }), file=sys.stdout)
        return 2

    all_results: List[FetchResult] = []
    resolved_cik: Optional[str] = None

    if args.market == "US":
        # CIK resolution
        cik = args.cik.strip()
        if not cik:
            cik, err = _resolve_cik(args.ticker)
            if cik is None:
                print(json.dumps({
                    "errors": [err or f"CIK resolution failed for {args.ticker}"],
                    "results": [],
                    "resolved_cik": None,
                }), file=sys.stdout)
                return 1
            resolved_cik = cik
        else:
            cik = cik.zfill(10)

        result = fetch_sec_8k(args.ticker, cik, since_dt, today_dt)
        all_results.append(result)

    else:  # India
        bse = args.bse_code.strip()
        nse = args.nse_symbol.strip()
        if not bse and not nse:
            print(json.dumps({
                "errors": ["At least one of --bse-code or --nse-symbol required for India"],
                "results": [],
            }), file=sys.stdout)
            return 2

        if bse:
            all_results.append(fetch_bse(bse, since_dt, today_dt))
        if nse:
            all_results.append(fetch_nse(nse, since_dt, today_dt))

    # Cross-source dedup (only meaningful for India when both BSE+NSE returned items)
    flat_items: List[DisclosureItem] = []
    for r in all_results:
        flat_items.extend(r.items)
    deduped, dropped_dedup = _dedup_cross_source(flat_items)

    # Sort by date descending
    deduped.sort(key=lambda it: it.date or "", reverse=True)

    # Build envelope
    envelope: Dict[str, Any] = {
        "ticker": args.ticker,
        "market": args.market,
        "since": args.since,
        "today": today_dt.strftime("%Y-%m-%d"),
        "results": [
            {
                "source": r.source,
                "raw_count": r.raw_count,
                "items_after_routine_filter": r.raw_count - r.routine_filtered,
                "routine_filtered": r.routine_filtered,
                "endpoint_errors": r.errors,
            }
            for r in all_results
        ],
        "items_after_dedup": len(deduped),
        "items_dropped_in_cross_source_dedup": dropped_dedup,
        "items": [asdict(it) for it in deduped],
        "resolved_cik": resolved_cik,
        "errors": [e for r in all_results for e in r.errors],
    }

    # Exit code:
    #   0 = success, even if some sources failed (partial)
    #   1 = total failure (no items returned across all sources AND no rows
    #       at all from any endpoint, AND at least one endpoint errored)
    if not deduped and any(r.errors for r in all_results) and all(r.raw_count == 0 for r in all_results):
        print(json.dumps(envelope, indent=2, ensure_ascii=False), file=sys.stdout)
        return 1

    print(json.dumps(envelope, indent=2, ensure_ascii=False), file=sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
