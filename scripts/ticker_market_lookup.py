"""Resolve a bare ticker symbol to its market ("us" / "india") and name.

Veda's data fetchers (`scripts/fetch_quote.py`, the calendar / news /
ownership scripts) need to know which market a ticker belongs to so they
can pick the right primitive -- Yahoo's spark endpoint for US batches,
Screener.in for Indian batches, etc. Asking the LLM to infer this on every
call is slow, costs tokens, and risks hallucination on ambiguous symbols
like INFY (NSE listing) vs INFY (NYSE ADR).

The lookup table lives in scripts/data/ticker_market.csv. Coverage is the
full active equity universe of both markets (~10k US tickers from SEC,
~2k India tickers from NSE archives). Regenerate it any time with:

    python scripts/refresh_ticker_market.py

Schema is `ticker,market,name`. The table holds BARE symbols only -- the
form a user actually types ("CDSL", not "CDSL.NS"). The `.NS` / `.BO`
suffix is a yfinance convention that no user sees in normal use. Suffixed
inputs are still accepted by the lookup -- they short-circuit to "india"
via a suffix rule without needing a table entry.

Collision policy (handled at refresh time): if a symbol exists on both
markets (e.g. "TCS" -- Tata Consultancy on NSE, Container Store on US),
the India entry wins because Veda's primary audience is Indian. Users
wanting the US ADR pass `--market us` at the call site, which bypasses
the table entirely.

Output contract (JSON on stdout):

    # --ticker mode
    {"ticker": "MSFT", "market": "us", "name": "Microsoft Corp.",
     "source": "bundled-table"}
    {"ticker": "CDSL.NS", "market": "india", "name": null,
     "source": "suffix-rule"}
    {"ticker": "ZZZ", "market": null, "name": null, "source": null,
     "error": "not in bundled table"}

    # --tickers mode
    {"results": [...per-ticker entries...],
     "by_market": {"us": [...], "india": [...], "unknown": [...]}}

Exit codes (CLI): 0 if every input ticker resolved; 1 if any did not.

Programmatic API:

    from scripts.ticker_market_lookup import (
        lookup_market, lookup_name, split_by_market,
    )

    lookup_market("MSFT")     # -> "us"
    lookup_market("CDSL")     # -> "india"
    lookup_market("CDSL.NS")  # -> "india"   (suffix rule)
    lookup_market("ZZZ")      # -> None

    lookup_name("MSFT")       # -> "Microsoft Corp."
    lookup_name("CDSL.NS")    # -> None   (suffix rule has no name; the
                              #            table is bare-symbol keyed)

    split_by_market(["MSFT", "CDSL", "ZZZ"])
    # -> {"us": ["MSFT"], "india": ["CDSL"], "unknown": ["ZZZ"]}
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Optional

# Source of truth for the curated mapping. Sits next to this file so the
# script + its data ship together.
_DATA_PATH = Path(__file__).parent / "data" / "ticker_market.csv"

# Suffixes that yfinance uses to disambiguate Indian listings. A user
# would not normally type these, but Veda's internal slugs and some
# external callers do. Treat them as a hard signal -- no table needed.
_INDIA_SUFFIXES = (".NS", ".BO")

# Allowed market values. Matches the --market flag on fetch_quote.py.
_VALID_MARKETS = {"us", "india"}


def _load_table() -> dict[str, tuple[str, str]]:
    """Read the CSV once and return ticker -> (market, name) map.

    Comments (lines starting with '#') and blank lines are ignored. The
    header row 'ticker,market,name' is also skipped. Any row with an
    invalid market value raises ValueError -- a typo in the CSV should
    fail loudly at import, not silently route a ticker to the wrong
    market. Uses csv.reader so company names containing commas (e.g.
    "Alphabet Inc., Class A") parse correctly.
    """
    table: dict[str, tuple[str, str]] = {}
    if not _DATA_PATH.exists():
        raise FileNotFoundError(
            f"ticker_market.csv not found at {_DATA_PATH}. "
            "Regenerate with: python scripts/refresh_ticker_market.py"
        )

    with _DATA_PATH.open("r", encoding="utf-8", newline="") as f:
        # Strip comment lines + blank lines before csv parsing.
        cleaned = [
            raw for raw in f
            if raw.strip() and not raw.lstrip().startswith("#")
        ]
    reader = csv.reader(cleaned)
    for lineno, row in enumerate(reader, start=1):
        if not row:
            continue
        # Skip the schema header.
        if [c.strip().lower() for c in row[:3]] == ["ticker", "market", "name"]:
            continue
        if len(row) < 3:
            raise ValueError(
                f"ticker_market.csv row {lineno}: expected 3 columns "
                f"(ticker,market,name), got {row!r}"
            )
        ticker = row[0].strip().upper()
        market = row[1].strip().lower()
        name = row[2].strip()
        if not ticker:
            continue
        if market not in _VALID_MARKETS:
            raise ValueError(
                f"ticker_market.csv row {lineno}: market must be one of "
                f"{sorted(_VALID_MARKETS)}, got {market!r} for {ticker}"
            )
        if ticker in table and table[ticker][0] != market:
            raise ValueError(
                f"ticker_market.csv row {lineno}: duplicate ticker "
                f"{ticker} with conflicting markets "
                f"({table[ticker][0]} vs {market})"
            )
        table[ticker] = (market, name)
    return table


# Loaded once at import. The CSV is ~12k rows / ~1 MB. Read once at
# startup is faster than re-parsing on every call and keeps lookups O(1).
_TABLE: dict[str, tuple[str, str]] = _load_table()


def lookup_market(ticker: str) -> Optional[str]:
    """Return "us", "india", or None for an unknown bare ticker.

    Suffixed inputs (CDSL.NS, TITANBIO.BO) short-circuit to "india" via
    the suffix rule; the bare-symbol table is not consulted in that case.
    """
    if not ticker:
        return None
    t = ticker.strip().upper()
    if t.endswith(_INDIA_SUFFIXES):
        return "india"
    entry = _TABLE.get(t)
    return entry[0] if entry else None


def lookup_name(ticker: str) -> Optional[str]:
    """Return the issuer name for a bare ticker, or None if not in the table.

    Suffixed inputs (CDSL.NS) return None -- the suffix rule resolves
    market but the table holds bare symbols only; pass the bare form
    (CDSL) if you want the name.
    """
    if not ticker:
        return None
    t = ticker.strip().upper()
    if t.endswith(_INDIA_SUFFIXES):
        return None
    entry = _TABLE.get(t)
    return entry[1] if entry else None


def split_by_market(tickers: list[str]) -> dict[str, list[str]]:
    """Group a ticker list into {"us": [...], "india": [...], "unknown": [...]}.

    Order within each market is preserved from the input.
    """
    buckets: dict[str, list[str]] = {"us": [], "india": [], "unknown": []}
    for t in tickers:
        market = lookup_market(t)
        if market is None:
            buckets["unknown"].append(t)
        else:
            buckets[market].append(t)
    return buckets


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_one(ticker: str) -> dict:
    """One-ticker resolution entry with explicit source attribution."""
    t = ticker.strip().upper()
    if not t:
        return {
            "ticker": ticker,
            "market": None,
            "name": None,
            "source": None,
            "error": "empty ticker",
        }
    if t.endswith(_INDIA_SUFFIXES):
        return {
            "ticker": t,
            "market": "india",
            "name": None,
            "source": "suffix-rule",
        }
    entry = _TABLE.get(t)
    if entry is None:
        return {
            "ticker": t,
            "market": None,
            "name": None,
            "source": None,
            "error": "not in bundled table",
        }
    market, name = entry
    return {
        "ticker": t,
        "market": market,
        "name": name,
        "source": "bundled-table",
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve bare ticker symbols to their market (us / india). "
            "Reads scripts/data/ticker_market.csv. Suffixed forms (.NS / "
            ".BO) route to india via the suffix rule. Unknown tickers "
            "exit with code 1."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ticker", help="A single ticker to resolve.")
    group.add_argument(
        "--tickers",
        nargs="+",
        help="One or more tickers to resolve. Output is grouped by market.",
    )
    args = parser.parse_args(argv)

    if args.ticker is not None:
        entry = _resolve_one(args.ticker)
        print(json.dumps(entry, indent=2, sort_keys=True))
        return 0 if entry.get("market") is not None else 1

    results = [_resolve_one(t) for t in args.tickers]
    buckets = {"us": [], "india": [], "unknown": []}
    for entry in results:
        market = entry.get("market") or "unknown"
        buckets[market].append(entry["ticker"])
    payload = {"results": results, "by_market": buckets}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not buckets["unknown"] else 1


if __name__ == "__main__":
    sys.exit(main())
