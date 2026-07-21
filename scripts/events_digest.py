"""
Veda - upcoming-events digest ("what's coming up for everything I track").

Builds one date-sorted calendar across the client's whole tracked universe:
every name they HOLD, every name on their WATCHLIST, and every name the research
house COVERS or actively TRACKS (even if not yet held or watchlisted). Each row
is tagged with three independent axes: research coverage, research tracking and
book relationship. Tracking-only names remain not assessed.

Calendars are fetched live (Hard Rule #9) and in parallel (calendar_feed), so a
30-name book resolves in about the time of its slowest single name, not the sum.
Read-only w.r.t. the book; the only writes are the per-name calendar caches in
held names' own workspaces (via calendar_feed).

    python scripts/events_digest.py --client default
    python scripts/events_digest.py --client default --refresh --lookforward-days 90

Exit codes:
    0 - digest printed (an empty window is still success)
    1 - could not read the research feed
    2 - bad usage (argparse)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _common import slugify
from research_feed import (
    DEFAULT_RESEARCH_CONFIG,
    FeedError,
    has_active_coverage,
    has_ended_coverage,
    load_feed,
)
from calendar_feed import LOOKFORWARD_DAYS, get_many

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_MARKET_LABEL = {"india": "IN", "us": "US"}
_REL_LABEL = {"HELD": "held", "WATCHLIST": "watchlist", "NEW_IDEA": "research idea",
              "PRIVATE": "private"}


def build_universe(rows: list[dict], held: set, watched: set) -> dict:
    """The universe keyed by (market, ticker): every covered or actively tracked
    listed name, plus every held and watchlisted name. Feed rows win the
    slug/name; unlisted names are dropped because there is no calendar ticker."""
    universe: dict[tuple, dict] = {}
    for row in rows:
        complete = has_active_coverage(row)
        globally_tracked = bool((row.get("tracking") or {}).get("globally_tracked"))
        ticker = row.get("ticker")
        if not ticker:  # private / unlisted - no calendar to fetch
            continue
        key = (row["market"], ticker)
        if not complete and not globally_tracked and key not in held and key not in watched:
            continue
        universe[key] = {"slug": row["slug"], "ticker": ticker, "market": row["market"],
                         "name": row.get("name") or row["slug"], "covered": complete,
                         "research_status": row.get("research_status"),
                         "coverage_ended": has_ended_coverage(row),
                         "research_tracked": globally_tracked,
                         "relation": row.get("relation")}
    for market, ticker in held:
        key = (market, ticker)
        if key not in universe:
            universe[key] = {"slug": slugify(ticker), "ticker": ticker, "market": market,
                             "name": ticker, "covered": False, "relation": "HELD"}
    for market, ticker in watched:
        key = (market, ticker)
        if key not in universe:
            universe[key] = {"slug": slugify(ticker), "ticker": ticker, "market": market,
                             "name": ticker, "covered": False, "relation": "WATCHLIST"}
    return universe


def _tag(item: dict) -> str:
    if item["covered"]:
        cover = "covered"
    elif item.get("coverage_ended"):
        cover = "research-tracked, coverage ended" if item.get("research_tracked") else "coverage ended"
    elif item.get("research_tracked"):
        cover = "research-tracked, not assessed"
    else:
        cover = "uncovered"
    rel = _REL_LABEL.get(item["relation"], str(item["relation"]).lower())
    return f"{cover}, {rel}"


def _company_label(item: dict) -> str:
    market = _MARKET_LABEL.get(item.get("market"), (item.get("market") or "?").upper())
    return f"{item['name']} ({item['ticker']}, {market})"


def build_digest(universe: dict, calendars: dict, as_of: str,
                 lookforward_days: int) -> str:
    """A date-sorted timeline across the universe, plus the names with nothing
    scheduled and a one-line summary."""
    timeline: list[tuple] = []
    empty: list[str] = []
    errored: list[str] = []
    for item in universe.values():
        cal = calendars.get(item["slug"]) or {}
        upcoming = cal.get("upcoming") or []
        if not upcoming:
            (errored if cal.get("errors") else empty).append(item["ticker"])
            continue
        for ev in upcoming:
            timeline.append((ev.get("date") or "9999", item, ev))
    timeline.sort(key=lambda r: (r[0], r[1]["ticker"]))

    n = len(universe)
    held = sum(1 for i in universe.values() if i["relation"] == "HELD")
    watch = sum(1 for i in universe.values() if i["relation"] == "WATCHLIST")
    covered = sum(1 for i in universe.values() if i["covered"])
    pending = sum(1 for i in universe.values() if i.get("research_tracked") and not i["covered"])
    lines = [f"Upcoming events - everything you track (as of {as_of}).",
             f"Scope: held + watchlist + research-covered/tracked ({n} names: "
             f"{held} held, {watch} watchlisted, {covered} covered, "
             f"{pending} research-tracked without active coverage).", ""]

    if timeline:
        for date_s, item, ev in timeline:
            note = ev.get("note")
            lines.append(f"  {date_s}  {_company_label(item):<34}  {ev.get('event')}"
                         f"   [{_tag(item)}]" + (f"  - {note}" if note else ""))
    else:
        lines.append(f"  No scheduled events across your tracked names in the next "
                     f"{lookforward_days} days.")

    if empty:
        lines += ["", f"No scheduled events ({len(empty)}): " + ", ".join(sorted(empty))]
    if errored:
        lines += [f"No data returned ({len(errored)}; often Indian names between results): "
                  + ", ".join(sorted(errored))]
    lines += ["", f"Summary: {len(timeline)} events across {n} tracked names in the next "
              f"{lookforward_days} days."]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(
        description="A date-sorted calendar across every name you hold, watch, or "
                    "the research house covers or actively tracks. Live fetch, status-tagged.")
    p.add_argument("--client", default="default", help="Active client (default: default).")
    p.add_argument("--research-path", default=None, help="Override the research repo path.")
    p.add_argument("--config", type=Path, default=DEFAULT_RESEARCH_CONFIG)
    p.add_argument("--lookforward-days", type=int, default=LOOKFORWARD_DAYS)
    p.add_argument("--refresh", action="store_true", help="Ignore same-day caches.")
    args = p.parse_args()

    try:
        rows, held, watched, _updated, _research = load_feed(
            args.client, args.config, args.research_path)
    except FeedError as error:
        print(str(error), file=sys.stderr)
        return 1

    universe = build_universe(rows, held, watched)
    if not universe:
        print(f"No tracked names for client '{args.client}' "
              "(no holdings, no watchlist, no covered or research-tracked names).")
        return 0

    calendars = get_many(args.client, list(universe.values()),
                         lookforward_days=args.lookforward_days, refresh=args.refresh)
    as_of = next((c.get("as_of") for c in calendars.values() if c.get("as_of")), "n/a")
    print(build_digest(universe, calendars, as_of, args.lookforward_days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
