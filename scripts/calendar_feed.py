"""
Veda - live calendar feed for the advisor.

Fetches upcoming scheduled events (earnings, ex-dividend, splits, AGM) for one
name or a batch, on top of scripts/fetch_calendar.py (yfinance for both markets,
Screener.in + BSE corporate-actions for India). Every read is stamped with an
`as_of` date (Hard Rule #9: no stale market data).

Why live, not from the research packet: a calendar date is a re-fetchable FACT,
so the advisor fetches it fresh rather than inheriting a date frozen at the last
publish -- and a live fetch covers every name, including the held names the
research house does not cover (which a packet never carries).

Read-only w.r.t. the book. The only thing written is a held name's own
`clients/<client>/holdings/<slug>/calendar.yaml`, and only when that workspace
already exists -- a name with no workspace (a covered idea, a watchlist row) is
fetched live and not cached, so nothing gets scaffolded prematurely.

This module is imported by the single-company detail view and the cross-book
events digest; it also runs standalone:

    python scripts/calendar_feed.py --client default --ticker MSFT --market us
    python scripts/calendar_feed.py --client default --ticker ASTRAMICRO --market india

Exit codes:
    0 - events printed (an empty calendar is still success)
    1 - the fetch failed for the name
    2 - bad usage (argparse)
"""
from __future__ import annotations

import argparse
import concurrent.futures
import logging
import sys
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

import yaml  # integration script (reads/writes workspace YAML), like research_feed.py

from _common import client_root, slugify
from fetch_calendar import fetch_position, _dedup_events

# Force UTF-8 stdout so em-dashes / rupee signs don't mangle on Windows consoles
# that default to cp1252 (house idiom, see review_decisions.py).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# yfinance logs an HTTP 404 for every unknown ticker straight to its logger; that
# noise would clutter the digest. Silence it -- a name that returns nothing is
# already captured in its result's `errors` and reported as "no data".
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# How far forward to look, and how long a cached read stays fresh. Scheduled
# dates move slowly (an earnings date is set weeks ahead), so a same-day cache
# is fresh enough and keeps a 30-name digest from re-fetching all day.
LOOKFORWARD_DAYS = 180
MAX_WORKERS = 8

# Accept both the advisor's internal encoding ("us" / "india") and the research
# manifest's ("US" / "IN"); map either to what fetch_calendar.py expects.
_MARKET_TO_FETCHER = {
    "us": "US", "usa": "US", "united states": "US", "nasdaq": "US", "nyse": "US",
    "india": "India", "in": "India", "ind": "India", "nse": "India", "bse": "India",
}


def _fetcher_market(raw) -> str | None:
    return _MARKET_TO_FETCHER.get(str(raw or "").strip().lower())


def _today() -> date:
    return datetime.now(timezone.utc).date()


# --- the cache lives in the held name's own workspace ----------------------

def _workspace_calendar(client: str, slug: str) -> Path:
    return client_root(client) / "holdings" / slug / "calendar.yaml"


def _read_yaml(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _write_calendar(path: Path, as_of: str, upcoming: list, prior: dict | None) -> None:
    """Write as_of + upcoming to a held name's calendar.yaml, preserving any
    existing `past` block (the forward fetch never fills the past)."""
    out: dict = {"as_of": as_of, "upcoming": upcoming}
    if prior and prior.get("past"):
        out["past"] = prior["past"]
    path.write_text(
        yaml.safe_dump(out, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


# --- the fetch (pure: one name in, an event list out) ----------------------

def fetch_events(ticker: str, market: str, *, lookforward_days: int = LOOKFORWARD_DAYS,
                 today: date | None = None) -> dict:
    """Fetch upcoming events for one name. No cache, no write.

    Returns {as_of, upcoming: [event dicts], errors: [...]}. `upcoming` is
    date-sorted and de-duplicated across sources.
    """
    today = today or _today()
    fetch_market = _fetcher_market(market)
    if not fetch_market:
        return {"as_of": today.isoformat(), "upcoming": [],
                "errors": [f"unknown market: {market!r}"]}
    today_dt = datetime(today.year, today.month, today.day)
    tkr = ticker.strip().upper()
    results = fetch_position(
        tkr, fetch_market, today_dt, lookforward_days,
        nse_symbol=tkr if fetch_market == "India" else "",
    )
    events = _dedup_events([e for r in results for e in r.events])
    events.sort(key=lambda e: e.date or "")
    upcoming = [{k: v for k, v in asdict(e).items() if v is not None} for e in events]
    errors = [e for r in results for e in r.errors]
    return {"as_of": today.isoformat(), "upcoming": upcoming, "errors": errors}


# --- cache-aware single name -----------------------------------------------

def get_calendar(client: str, slug: str, ticker: str, market: str, *,
                 lookforward_days: int = LOOKFORWARD_DAYS, refresh: bool = False,
                 today: date | None = None) -> dict:
    """Upcoming events for one name, cache-aware.

    Reuses a held name's `calendar.yaml` when its `as_of` is today (unless
    `refresh`); otherwise fetches live. Writes the fetch back only when the
    name already has a workspace (never scaffolds one for a covered idea or a
    watchlist row). Returns {as_of, upcoming, cached, errors}.
    """
    today = today or _today()
    path = _workspace_calendar(client, slug)
    prior = _read_yaml(path)
    has_workspace = path.parent.is_dir()

    if prior and not refresh and prior.get("as_of") == today.isoformat():
        return {"as_of": prior.get("as_of"), "upcoming": prior.get("upcoming") or [],
                "cached": True, "errors": []}

    fetched = fetch_events(ticker, market, lookforward_days=lookforward_days, today=today)
    if has_workspace:
        _write_calendar(path, fetched["as_of"], fetched["upcoming"], prior)
    return {**fetched, "cached": False}


# --- parallel fan-out for the events digest --------------------------------

def get_many(client: str, names: list[dict], *, lookforward_days: int = LOOKFORWARD_DAYS,
             refresh: bool = False, max_workers: int = MAX_WORKERS,
             today: date | None = None) -> dict:
    """Cache-aware calendars for many names, fetched in parallel.

    `names`: [{"slug", "ticker", "market"}, ...]. Returns {slug: get_calendar(...)}.
    One slow or failing name never takes the digest down -- it comes back with an
    empty `upcoming` and an error note. Bounded worker pool so a 50-name book does
    not open 50 sockets at once.
    """
    today = today or _today()
    todo = [n for n in names if n.get("slug") and n.get("ticker") and n.get("market")]
    out: dict[str, dict] = {}
    if not todo:
        return out
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_slug = {
            pool.submit(get_calendar, client, n["slug"], n["ticker"], n["market"],
                        lookforward_days=lookforward_days, refresh=refresh, today=today): n["slug"]
            for n in todo
        }
        for future in concurrent.futures.as_completed(future_to_slug):
            slug = future_to_slug[future]
            try:
                out[slug] = future.result()
            except Exception as exc:  # a single name must not sink the whole digest
                out[slug] = {"as_of": today.isoformat(), "upcoming": [],
                             "cached": False, "errors": [f"fetch failed: {exc}"]}
    return out


# --- CLI (one name) --------------------------------------------------------

def _format_one(name: str, market: str, cal: dict, lookforward_days: int) -> str:
    lines = [f"{name} [{market}] - upcoming events (as of {cal.get('as_of')}"
             + (", cached" if cal.get("cached") else "") + "):"]
    upcoming = cal.get("upcoming") or []
    if not upcoming:
        lines.append(f"  no upcoming events in the next {lookforward_days} days")
    for ev in upcoming:
        src = str(ev.get("source") or "").split(":")[-1].strip() or "source n/a"
        tail = f"  ({src})"
        note = ev.get("note")
        lines.append(f"  {ev.get('date')}  {ev.get('event')}{tail}"
                     + (f"  - {note}" if note else ""))
    errs = cal.get("errors") or []
    if errs and not upcoming:
        lines.append("  note: every source came back empty or errored "
                     "(common for Indian names between results)")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Fetch upcoming scheduled events for one name (earnings, "
                    "ex-dividend, splits, AGM). Live fetch, as_of-stamped.")
    p.add_argument("--client", default="default", help="Active client (default: default).")
    p.add_argument("--ticker", required=True, help="Ticker symbol.")
    p.add_argument("--market", required=True, help="us / india (or US / IN).")
    p.add_argument("--slug", default="", help="Workspace slug (default: slugify(ticker)).")
    p.add_argument("--lookforward-days", type=int, default=LOOKFORWARD_DAYS)
    p.add_argument("--refresh", action="store_true", help="Ignore any same-day cache.")
    args = p.parse_args()

    if not _fetcher_market(args.market):
        print(f"unknown market: {args.market!r} (use us / india)", file=sys.stderr)
        return 2

    slug = args.slug or slugify(args.ticker)
    cal = get_calendar(args.client, slug, args.ticker, args.market,
                       lookforward_days=args.lookforward_days, refresh=args.refresh)
    print(_format_one(args.ticker.upper(), args.market.lower(), cal, args.lookforward_days))
    return 0 if not (cal.get("errors") and not cal.get("upcoming")) else 1


if __name__ == "__main__":
    sys.exit(main())
