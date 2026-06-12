"""
Veda - review past decisions against today's prices.

Reads the decision logs the pipeline writes and prints a plain scoreboard so
you can see, at a glance, how each past call has aged:

  1. For every per-ticker decision file (holdings/<slug>/decisions/*.md): the
     date, ticker, action, the price recorded when the decision was made, the
     price today, the percent change since, and how many days have passed.
  2. For journal entries that did not write a per-ticker file (portfolio-wide
     reviews, sell screens): the date and the headline, listed without a price
     check.

This is facts only. It does NOT judge whether a thesis played out or whether a
kill criterion fired - that reading is the framework/judgment step the chat
pipeline does, and the planned decision-reviewer subagent will formalise. This
command just lays out the scoreboard the judgment is made against.

The core (build_review) takes the parsed decisions and a price lookup as plain
arguments, so tests feed fixed numbers and never touch the network. Only the
command-line run fetches today's prices from yfinance.

Examples (from a terminal in the Veda-advisor folder):

    python scripts/review_decisions.py
    python scripts/review_decisions.py --as-of 2026-06-11

Exit codes:
    0 - report printed (including the "nothing to review yet" case)
    1 - could not read the inputs
    2 - holdings folder missing
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from concentration import read_meta, _normalise_market

# Force UTF-8 stdout so non-Latin characters (e.g., ₹ in journal headlines)
# don't crash the script on Windows consoles that default to cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOLDINGS = REPO_ROOT / "holdings"
DEFAULT_JOURNAL = REPO_ROOT / "journal.md"

# A decision file is named YYYY-MM-DD-<action>.md, with an optional numeric
# suffix when two decisions share a day (e.g. 2026-04-23-hold-2.md).
DECISION_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-zA-Z]+)(?:-\d+)?\.md$")

# The price the decision was made at, taken from the decision file. Two real
# formats exist: the hand-written "- Current price: 456.00 (...)" line and the
# canonical decision-block field current_price: "INR 527.40 (...)" / "$875 ...".
# So accept a space or underscore in the key, an optional quote, and an optional
# currency symbol or 2-4 letter code before the number (which may carry commas).
PRICE_LINE = re.compile(
    r"current[ _]price:\s*[\"']?\s*[$\u20b9\u20ac\u00a3]?\s*(?:[A-Za-z]{2,4}\s+)?"
    r"([0-9][0-9,]*\.?[0-9]*)",
    re.IGNORECASE,
)

# A journal heading looks like:  ## 2026-05-23 — NTPC — HOLD; ...
# The separator is an em dash in practice; accept en dash and hyphen too.
JOURNAL_HEADING = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s+[\u2014\u2013-]\s+(.+)$")
HEADING_SEPARATOR = re.compile(r"\s+[\u2014\u2013-]\s+")


@dataclass
class Decision:
    """One per-ticker decision read from a decisions/*.md file."""
    date: str                    # YYYY-MM-DD, from the file name
    slug: str                    # holding folder name, e.g. "ntpc"
    ticker: str                  # bare symbol, e.g. "NTPC"
    market: str                  # "india" or "us"
    action: str                  # buy / add / trim / sell / hold
    price_then: Optional[float]  # price recorded in the file, or None


@dataclass
class Row:
    """One line of the price-check table."""
    date: str
    ticker: str
    action: str
    price_then: Optional[float]
    price_now: Optional[float]
    change_pct: Optional[float]
    days_held: int


# --- parsing helpers (no files, easy to test) ------------------------------

def parse_decision_name(name: str) -> Optional[tuple[str, str]]:
    """Return (date, action) from a decision file name, or None if it does
    not match the YYYY-MM-DD-<action>.md shape."""
    match = DECISION_NAME.match(name)
    if not match:
        return None
    return match.group(1), match.group(2).lower()


def parse_price_then(text: str) -> Optional[float]:
    """Return the decision-time price from the file body, or None if absent."""
    match = PRICE_LINE.search(text)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def ticker_for(fields: dict, slug: str) -> str:
    """Bare symbol for the holding: the _meta.yaml ticker, else the slug with
    any .NS / .BO marker dropped, upper-cased."""
    ticker = fields.get("ticker", "").strip().upper()
    if ticker:
        return ticker
    base = re.sub(r"-(ns|bo)$", "", slug.lower())
    return base.upper()


def market_for(fields: dict, slug: str) -> str:
    """"india" or "us" for the holding: the _meta.yaml market, else inferred
    from a .NS / .BO style slug suffix, else "us"."""
    raw = fields.get("market", "").strip()
    if raw:
        return _normalise_market(raw)
    low = slug.lower()
    if low.endswith("-ns") or low.endswith("-bo"):
        return "india"
    return "us"


def read_journal_headings(text: str) -> list[tuple[str, str, str]]:
    """Return (date, token, headline) for each decision heading in journal.md.

    token is the first field after the date (a ticker like NTPC, or a label
    like "PORTFOLIO REVIEW"); headline is the full text after the date.
    """
    headings: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        match = JOURNAL_HEADING.match(line)
        if not match:
            continue
        entry_date = match.group(1)
        rest = match.group(2).strip()
        token = HEADING_SEPARATOR.split(rest, maxsplit=1)[0].strip()
        headings.append((entry_date, token, rest))
    return headings


def journal_only(
    headings: list[tuple[str, str, str]],
    decisions: list[Decision],
) -> list[tuple[str, str]]:
    """Journal headings that have no matching per-ticker decision file.

    A heading is matched (and dropped) when a decision shares its date and that
    decision's ticker appears as a whole word in the heading. This handles both
    heading styles seen in practice: "NTPC — HOLD ..." (ticker as its own field)
    and "HOLD WONDERLA (...)" (ticker embedded in the text). Everything else -
    portfolio reviews, sell screens - is returned as (date, headline).
    """
    tickers_by_date: dict[str, list[str]] = {}
    for item in decisions:
        tickers_by_date.setdefault(item.date, []).append(item.ticker)
    out: list[tuple[str, str]] = []
    for entry_date, _token, headline in headings:
        upper_headline = headline.upper()
        covered = any(
            re.search(rf"\b{re.escape(ticker.upper())}\b", upper_headline)
            for ticker in tickers_by_date.get(entry_date, [])
        )
        if covered:
            continue
        out.append((entry_date, headline))
    return out


# --- reading the decision files --------------------------------------------

def find_decisions(holdings_dir: Path) -> list[Decision]:
    """Scan holdings/<slug>/decisions/*.md and read each into a Decision."""
    decisions: list[Decision] = []
    if not holdings_dir.exists():
        return decisions
    for meta_path in sorted(holdings_dir.glob("*/_meta.yaml")):
        slug = meta_path.parent.name
        fields = read_meta(meta_path)
        ticker = ticker_for(fields, slug)
        market = market_for(fields, slug)
        decisions_dir = meta_path.parent / "decisions"
        if not decisions_dir.exists():
            continue
        for decision_file in sorted(decisions_dir.glob("*.md")):
            parsed = parse_decision_name(decision_file.name)
            if not parsed:
                continue
            entry_date, action = parsed
            price_then = parse_price_then(decision_file.read_text(encoding="utf-8"))
            decisions.append(
                Decision(entry_date, slug, ticker, market, action, price_then)
            )
    return decisions


# --- the scoreboard core (pure: facts in, facts out) -----------------------

def build_review(
    decisions: list[Decision],
    price_now_by_slug: dict[str, float],
    as_of: date,
) -> list[Row]:
    """Turn decisions plus a current-price lookup into scoreboard rows."""
    rows: list[Row] = []
    for item in decisions:
        price_now = price_now_by_slug.get(item.slug)
        change_pct = None
        if item.price_then and price_now is not None:
            change_pct = (price_now - item.price_then) / item.price_then * 100.0
        days_held = (as_of - date.fromisoformat(item.date)).days
        rows.append(
            Row(
                date=item.date,
                ticker=item.ticker,
                action=item.action,
                price_then=item.price_then,
                price_now=price_now,
                change_pct=change_pct,
                days_held=days_held,
            )
        )
    rows.sort(key=lambda row: (row.date, row.ticker))
    return rows


# --- formatting ------------------------------------------------------------

def _price_text(value: Optional[float]) -> str:
    return f"{value:.2f}" if value is not None else "n/a"


def _change_text(value: Optional[float]) -> str:
    return f"{value:+.1f}%" if value is not None else "n/a"


def format_report(
    rows: list[Row],
    journal_rows: list[tuple[str, str]],
    as_of: date,
) -> str:
    """Build the printable report. Facts only; no verdicts."""
    lines: list[str] = [f"Decision review as of {as_of.isoformat()}", ""]

    if rows:
        lines.append("With a price check:")
        header = f"{'Date':<12}{'Ticker':<10}{'Action':<8}{'Price then':>12}{'Price now':>12}{'Change':>10}{'Days':>6}"
        lines.append(header)
        for row in rows:
            lines.append(
                f"{row.date:<12}{row.ticker:<10}{row.action:<8}"
                f"{_price_text(row.price_then):>12}{_price_text(row.price_now):>12}"
                f"{_change_text(row.change_pct):>10}{row.days_held:>6}"
            )
    else:
        lines.append("With a price check: none yet.")

    lines.append("")

    if journal_rows:
        lines.append("Journal entries without a price check:")
        for entry_date, headline in journal_rows:
            lines.append(f"{entry_date:<12}{headline}")
    else:
        lines.append("Journal entries without a price check: none.")

    return "\n".join(lines)


# --- network fetch layer (only used by the command-line run) ---------------

def _fetch_latest_price(market: str, ticker: str) -> Optional[float]:
    """Latest close for one holding. India tries .NS then .BO, like nav.py."""
    import yfinance as yf

    symbols = [ticker] if market == "us" else [ticker + ".NS", ticker + ".BO"]
    for symbol in symbols:
        try:
            data = yf.Ticker(symbol).history(period="5d", auto_adjust=True)
        except Exception:
            data = None
        if data is not None and not data.empty:
            return float(data["Close"].iloc[-1])
    return None


def fetch_prices(
    decisions: list[Decision],
    fetch: Callable[[str, str], Optional[float]] = _fetch_latest_price,
) -> dict[str, float]:
    """Current price per holding slug. One fetch per slug; misses are skipped."""
    prices: dict[str, float] = {}
    for item in decisions:
        if item.slug in prices:
            continue
        price = fetch(item.market, item.ticker)
        if price is not None:
            prices[item.slug] = price
    return prices


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Review past decisions against today's prices."
    )
    parser.add_argument(
        "--holdings", type=Path, default=DEFAULT_HOLDINGS, help="holdings folder"
    )
    parser.add_argument(
        "--journal", type=Path, default=DEFAULT_JOURNAL, help="journal.md file"
    )
    parser.add_argument(
        "--as-of",
        default=date.today().isoformat(),
        help="date to measure against (YYYY-MM-DD); defaults to today",
    )
    args = parser.parse_args(argv)

    if not args.holdings.exists():
        print(f"holdings folder not found: {args.holdings}", file=sys.stderr)
        return 2

    try:
        as_of = date.fromisoformat(args.as_of)
    except ValueError:
        print(f"bad --as-of date: {args.as_of}", file=sys.stderr)
        return 1

    try:
        decisions = find_decisions(args.holdings)
        headings = (
            read_journal_headings(args.journal.read_text(encoding="utf-8"))
            if args.journal.exists()
            else []
        )
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 1

    prices = fetch_prices(decisions)
    rows = build_review(decisions, prices, as_of)
    journal_rows = journal_only(headings, decisions)
    print(format_report(rows, journal_rows, as_of))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
