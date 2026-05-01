"""
Veda — calendar fetcher and normalizer.

Fetches forward-looking scheduled events for two scopes:

  Mode `position`: per-ticker corporate calendar — earnings dates, ex-dividend,
  splits. Sources: yfinance (US + India .NS suffix), Screener.in (India primary).

  Mode `global`: portfolio-wide macro calendar — FOMC meetings (US central bank).
  v1 auto-fetch is FOMC only; BLS US CPI, RBI MPC, MoSPI India CPI are v2 work
  (BLS blocks bots; RBI/MoSPI need brittle targeted parsing). Users supply v2
  events via the calendar-tracker subagent's `pasted_dates` channel.

Called by the calendar-tracker subagent (see internal/agents/calendar-tracker.md)
via the `Bash` tool. The subagent does NOT speak HTTP, scrape HTML, or call
yfinance directly; those messy parts live here.

Same pattern as scripts/fetch_news.py / fetch_disclosures.py / fetch_fundamentals.py:
Bash-invoked, JSON to stdout, exit codes documented.

Usage:
    # Position mode (US):
    python scripts/fetch_calendar.py \\
        --mode position --ticker MSFT --market US --lookforward-days 180

    # Position mode (India):
    python scripts/fetch_calendar.py \\
        --mode position --ticker NTPC --market India \\
        --bse-code 532555 --nse-symbol NTPC --lookforward-days 180

    # Global mode (US + India):
    python scripts/fetch_calendar.py \\
        --mode global --regions US,IN --lookforward-days 180

Exit codes:
    0 - success or partial success (check JSON `errors` and per-source `endpoint_errors`)
    1 - complete failure (no events returned across all sources, AND at least one error)
    2 - bad usage (argparse)

Requires `requests`, `beautifulsoup4`, `yfinance`. See requirements.txt.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
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
        "events": [],
    }), file=sys.stdout)
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print(json.dumps({
        "errors": ["beautifulsoup4 not installed. Run: pip install -r requirements.txt"],
        "events": [],
    }), file=sys.stdout)
    sys.exit(1)


# =============================================================================
# Endpoint configuration
# =============================================================================

# --- yfinance ---
# Used for: US position (Earnings Date, Ex-Dividend Date), India position via
# .NS suffix (Ex-Dividend Date — Indian Earnings Date is often empty).

# --- Screener.in ---
# Used for: India position (next quarterly results date scraped from the
# company page). Same HTTP pattern as scripts/fetch_fundamentals.py.
SCREENER_BASE = "https://www.screener.in"
SCREENER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

# --- federalreserve.gov FOMC schedule ---
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FED_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

# --- v2 deferred sources (documented; not fetched in v1) ---
V2_DEFERRED_SOURCES = {
    "us_cpi_schedule": {
        "url": "https://www.bls.gov/schedule/news_release/cpi.htm",
        "reason": "BLS blocks bot User-Agents (HTTP 403) even with full browser headers",
    },
    "rbi_mpc_schedule": {
        "url": "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx",
        "reason": "RBI MPC schedule buried in dated press releases; brittle targeted parsing",
    },
    "in_cpi_schedule": {
        "url": "https://www.mospi.gov.in/release-calendar",
        "reason": "MoSPI calendar page format varies; brittle parsing",
    },
}

DEFAULT_REQUEST_TIMEOUT_S = 20
DEFAULT_MAX_RETRIES = 3


# =============================================================================
# Normalized event record
# =============================================================================

@dataclass
class CalendarEvent:
    """One scheduled event. Field shape mirrors calendar.yaml row schema."""
    event: str
    date: str  # ISO YYYY-MM-DD
    source: str  # e.g., "calendar-tracker (auto): yfinance"
    # Optional fields per the calendar.yaml schema (all None when absent):
    time: Optional[str] = None
    note: Optional[str] = None
    # Position-specific optional fields:
    dividend_per_share: Optional[float] = None
    record_date: Optional[str] = None
    ratio: Optional[str] = None
    # Global-specific required fields (None for position events):
    region: Optional[str] = None
    category: Optional[str] = None


@dataclass
class FetchResult:
    """Per-source result."""
    events: List[CalendarEvent] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    source: str = ""  # e.g., "yfinance_MSFT", "fomc_schedule"
    raw_count: int = 0


# =============================================================================
# HTTP session builder
# =============================================================================

def _build_session(headers: Dict[str, str]) -> requests.Session:
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
# Date helpers
# =============================================================================

def _to_iso(d: Any) -> Optional[str]:
    """Coerce a date / datetime / string into ISO YYYY-MM-DD."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, date):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, str):
        # Try common formats
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(d.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


# =============================================================================
# Position mode — yfinance fetcher (US + India .NS)
# =============================================================================

def fetch_yfinance_calendar(
    ticker: str,
    market: str,
    today: datetime,
    lookforward_days: int,
) -> FetchResult:
    """Fetch upcoming events from yfinance Ticker.calendar.

    Returns earnings date, ex-dividend, dividend payment date when available
    and within the lookforward window. Estimates (Earnings High/Low/Average,
    Revenue High/Low/Average) are dropped per Hard Rule #8.
    """
    yf_ticker = ticker if market == "US" else f"{ticker}.NS"
    result = FetchResult(source=f"yfinance_{yf_ticker}")

    try:
        import yfinance as yf
    except ImportError:
        result.errors.append("yfinance not installed")
        return result

    try:
        t = yf.Ticker(yf_ticker)
        cal = t.calendar  # dict
    except Exception as exc:
        result.errors.append(f"yfinance lookup failed for {yf_ticker}: {exc}")
        return result

    if not isinstance(cal, dict) or not cal:
        # yfinance returned empty or unexpected shape — common for India
        result.errors.append(f"yfinance returned empty calendar for {yf_ticker}")
        return result

    cutoff = (today + timedelta(days=lookforward_days)).date()

    # Earnings Date may be a single date or a list of dates
    earnings = cal.get("Earnings Date")
    if earnings:
        dates = earnings if isinstance(earnings, list) else [earnings]
        for ed in dates:
            iso = _to_iso(ed)
            if iso:
                d_obj = datetime.strptime(iso, "%Y-%m-%d").date()
                if today.date() <= d_obj <= cutoff:
                    result.raw_count += 1
                    # Determine quarter label from date (calendar quarter)
                    quarter = (d_obj.month - 1) // 3 + 1
                    label = f"Q{quarter} {d_obj.year} earnings"
                    result.events.append(CalendarEvent(
                        event=label,
                        date=iso,
                        source=f"calendar-tracker (auto): yfinance",
                    ))

    # Ex-Dividend Date
    ex_div = cal.get("Ex-Dividend Date")
    iso = _to_iso(ex_div)
    if iso:
        d_obj = datetime.strptime(iso, "%Y-%m-%d").date()
        if today.date() <= d_obj <= cutoff:
            result.raw_count += 1
            event = CalendarEvent(
                event="Ex-dividend",
                date=iso,
                source=f"calendar-tracker (auto): yfinance",
            )
            # Also capture dividend payment date if separately listed
            div_pay = _to_iso(cal.get("Dividend Date"))
            if div_pay and div_pay != iso:
                event.note = f"dividend payment date: {div_pay}"
            result.events.append(event)

    return result


# =============================================================================
# Position mode — Screener.in fetcher (India)
# =============================================================================

def fetch_screener_calendar(
    ticker: str,
    bse_code: str,
    nse_symbol: str,
    today: datetime,
    lookforward_days: int,
) -> FetchResult:
    """Fetch the next quarterly results date for an Indian ticker via Screener.in.

    Screener publishes a `result_date` near the company's #quarters section
    (e.g., "Results: 24 May 2026"). We scrape the company page and look for
    that pattern. Best-effort — Screener does not always populate next-result
    dates ahead of the announcement.
    """
    result = FetchResult(source=f"screener_{ticker}")

    # Resolve company URL: try nse_symbol > bse_code > ticker
    candidates = [nse_symbol, bse_code, ticker]
    candidates = [c for c in candidates if c and c.strip()]
    if not candidates:
        result.errors.append("Screener: no symbol/code provided")
        return result

    session = _build_session(SCREENER_HEADERS)
    page_url = None
    page_text = None

    for candidate in candidates:
        # Try /company/<symbol>/ or /company/<bsecode>/
        url = f"{SCREENER_BASE}/company/{candidate}/"
        try:
            r = session.get(url, timeout=DEFAULT_REQUEST_TIMEOUT_S)
            if r.status_code == 200 and len(r.text) > 5000:
                page_url = url
                page_text = r.text
                break
        except requests.exceptions.RequestException:
            continue

    if not page_text:
        result.errors.append(
            f"Screener: company page not resolvable for any of {candidates}"
        )
        return result

    # Look for upcoming-results text. Screener's pattern is usually:
    #   "Result Date: 24 May 2026" or "Quarterly results scheduled for ..."
    # Conservative: only match explicit future-date patterns near the word
    # "Result", "result", or "Quarter".
    soup = BeautifulSoup(page_text, "html.parser")
    text = soup.get_text(" ", strip=True)
    cutoff = (today + timedelta(days=lookforward_days)).date()

    # Pattern 1: "<Day> <Month> <YYYY>" within ~50 chars of "result"
    pattern = re.compile(
        r"results?\s+(?:date|on|scheduled\s+for|to\s+be\s+announced)\s*[:\-]?\s*"
        r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})",
        re.IGNORECASE,
    )
    months = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    }

    for m in pattern.finditer(text):
        try:
            d_obj = date(int(m.group(3)), months[m.group(2).lower()], int(m.group(1)))
        except (ValueError, KeyError):
            continue
        if today.date() <= d_obj <= cutoff:
            result.raw_count += 1
            quarter = (d_obj.month - 1) // 3 + 1
            label = f"Q{quarter} {d_obj.year} earnings"
            result.events.append(CalendarEvent(
                event=label,
                date=d_obj.strftime("%Y-%m-%d"),
                source=f"calendar-tracker (auto): screener.in",
                note=f"page: {page_url}",
            ))
            break  # Take the first (earliest) match only

    if result.raw_count == 0:
        # Not an error per se — Screener may not have published the next
        # date yet. Caller should not treat as failure.
        pass

    return result


# =============================================================================
# Global mode — FOMC schedule scraper (federalreserve.gov)
# =============================================================================

def fetch_fomc_schedule(today: datetime, lookforward_days: int) -> FetchResult:
    """Fetch upcoming FOMC meeting dates from federalreserve.gov.

    Strategy: walk H4 headers like '2026 FOMC Meetings'. The H4 is wrapped in
    its own container div with no inline siblings — the actual meeting divs
    are the **PARENT div's** next-siblings, each holding text like
    'January 27-28 ...'. We stop walking when we hit the next year's panel
    (identified by another H4 with year text).

    For each match like 'June 16-17', use the FIRST day of the range as the
    canonical event date — the meeting starts then; the rate decision is
    announced on day 2. Day-1 is the conservative choice for a calendar
    nudge so the user has 1 day of pre-meeting heads-up.
    """
    result = FetchResult(source="fomc_schedule")

    session = _build_session(FED_HEADERS)
    try:
        r = session.get(FOMC_URL, timeout=DEFAULT_REQUEST_TIMEOUT_S)
        r.raise_for_status()
    except requests.exceptions.RequestException as exc:
        result.errors.append(f"FOMC fetch failed: {exc}")
        return result

    soup = BeautifulSoup(r.text, "html.parser")
    cutoff = (today + timedelta(days=lookforward_days)).date()

    months = {
        "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
        "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
    }
    year_re = re.compile(r"(20\d{2})\s+FOMC\s+Meetings", re.IGNORECASE)
    range_re = re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})[-\u2013](\d{1,2})"
    )
    seen: set = set()  # (year, month, day1) — dedup across H4 siblings

    for header in soup.find_all(["h4", "h3"]):
        header_text = header.get_text(" ", strip=True)
        ym = year_re.search(header_text)
        if not ym:
            continue
        year = int(ym.group(1))

        # The H4 lives inside a small container div with no inline siblings.
        # The meeting divs are the PARENT div's next-siblings. Walk until we
        # encounter another year's header (or end of container).
        container = header.parent if header.parent else header
        for sib in container.find_next_siblings():
            sub_header = sib.find(["h4", "h3"]) if hasattr(sib, "find") else None
            if sub_header:
                sub_ym = year_re.search(sub_header.get_text(" ", strip=True))
                if sub_ym and int(sub_ym.group(1)) != year:
                    break
            sib_text = sib.get_text(" ", strip=True)
            for m in range_re.finditer(sib_text):
                month_name, day1, _day2 = m.group(1), int(m.group(2)), int(m.group(3))
                month_num = months.get(month_name)
                if not month_num:
                    continue
                key = (year, month_num, day1)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    d_obj = date(year, month_num, day1)
                except ValueError:
                    continue
                if today.date() <= d_obj <= cutoff:
                    result.raw_count += 1
                    result.events.append(CalendarEvent(
                        event="FOMC rate decision",
                        date=d_obj.strftime("%Y-%m-%d"),
                        source="calendar-tracker (auto): fomc_schedule",
                        region="US",
                        category="central_bank",
                        note="meeting day 1 of 2; rate decision announced day 2",
                    ))

    return result


# =============================================================================
# Argparse + main
# =============================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch scheduled calendar events for one position OR for "
                    "the portfolio's macro calendar. Outputs JSON envelope to "
                    "stdout. See module docstring for full usage."
    )
    p.add_argument("--mode", required=True, choices=["position", "global"])
    p.add_argument("--lookforward-days", type=int, default=180,
                   help="How many days forward to consider events for. Default 180.")
    # Position-mode args
    p.add_argument("--ticker", default="", help="Ticker symbol (position mode).")
    p.add_argument("--market", default="", choices=["", "US", "India"],
                   help="Market routing (position mode).")
    p.add_argument("--bse-code", default="", help="BSE scrip code (India position).")
    p.add_argument("--nse-symbol", default="", help="NSE trading symbol (India position).")
    # Global-mode args
    p.add_argument("--regions", default="US,IN",
                   help="Comma-separated regions for global mode. v1: US,IN.")
    # Test override
    p.add_argument("--today", default="",
                   help="Override 'today' for testing, YYYY-MM-DD.")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # today
    if args.today:
        try:
            today_dt = datetime.strptime(args.today, "%Y-%m-%d")
        except ValueError as exc:
            print(json.dumps({
                "errors": [f"Bad --today: {exc}"],
                "events": [],
            }), file=sys.stdout)
            return 2
    else:
        today_dt = datetime.now(timezone.utc).replace(tzinfo=None)

    all_results: List[FetchResult] = []
    deferred_v2: List[Dict[str, str]] = []

    if args.mode == "position":
        if not args.ticker:
            print(json.dumps({
                "errors": ["--ticker required for position mode"],
                "events": [],
            }), file=sys.stdout)
            return 2
        if args.market not in ("US", "India"):
            print(json.dumps({
                "errors": [f"--market must be US or India for position mode; got {args.market!r}"],
                "events": [],
            }), file=sys.stdout)
            return 2

        # yfinance is the primary for both US and India
        all_results.append(fetch_yfinance_calendar(
            args.ticker, args.market, today_dt, args.lookforward_days
        ))

        if args.market == "India":
            # Screener.in supplements (and is often the only earnings-date source for India)
            all_results.append(fetch_screener_calendar(
                args.ticker, args.bse_code, args.nse_symbol,
                today_dt, args.lookforward_days,
            ))

    else:  # global
        regions = [r.strip().upper() for r in args.regions.split(",") if r.strip()]
        valid_regions = {"US", "IN"}
        if not regions or not any(r in valid_regions for r in regions):
            print(json.dumps({
                "errors": [f"--regions must include US or IN; got {args.regions!r}"],
                "events": [],
            }), file=sys.stdout)
            return 2

        if "US" in regions:
            all_results.append(fetch_fomc_schedule(today_dt, args.lookforward_days))
            # Document BLS deferral
            deferred_v2.append({
                "source": "us_cpi_schedule",
                "url": V2_DEFERRED_SOURCES["us_cpi_schedule"]["url"],
                "reason": V2_DEFERRED_SOURCES["us_cpi_schedule"]["reason"],
            })

        if "IN" in regions:
            # No v1 auto-source for IN; document deferrals so the subagent can
            # surface them in search_log with result: deferred_v2
            deferred_v2.append({
                "source": "rbi_mpc_schedule",
                "url": V2_DEFERRED_SOURCES["rbi_mpc_schedule"]["url"],
                "reason": V2_DEFERRED_SOURCES["rbi_mpc_schedule"]["reason"],
            })
            deferred_v2.append({
                "source": "in_cpi_schedule",
                "url": V2_DEFERRED_SOURCES["in_cpi_schedule"]["url"],
                "reason": V2_DEFERRED_SOURCES["in_cpi_schedule"]["reason"],
            })

    # Flatten
    all_events: List[CalendarEvent] = []
    for r in all_results:
        all_events.extend(r.events)

    # Sort upcoming ascending by date
    all_events.sort(key=lambda e: e.date or "")

    envelope: Dict[str, Any] = {
        "mode": args.mode,
        "today": today_dt.strftime("%Y-%m-%d"),
        "lookforward_days": args.lookforward_days,
        "results": [
            {
                "source": r.source,
                "raw_count": r.raw_count,
                "endpoint_errors": r.errors,
            }
            for r in all_results
        ],
        "deferred_v2": deferred_v2,
        "events_total": len(all_events),
        "events": [
            {k: v for k, v in asdict(e).items() if v is not None}
            for e in all_events
        ],
        "errors": [e for r in all_results for e in r.errors],
    }

    # Exit code:
    #   0 = success or partial (some events returned, or no events but no errors)
    #   1 = total failure (no events AND every result had errors)
    if not all_events and all_results and all(r.errors for r in all_results):
        print(json.dumps(envelope, indent=2, ensure_ascii=False), file=sys.stdout)
        return 1

    print(json.dumps(envelope, indent=2, ensure_ascii=False), file=sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
