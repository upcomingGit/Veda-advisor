"""
Veda - NAV and performance pipeline.

Turns the transaction ledger into the track record: a month-end series of the
book's value per unit, in rupees, next to a blended price-return benchmark
(Nifty 50 for the India sleeve, S&P 500 for the US sleeve).

See internal/nav-schema.md for the full contract and the worked example.

The book is run like a mutual fund. Money in buys units at the current NAV per
unit; money out sells units. The NAV per unit moves only with investment
performance, so it is comparable to an index. The starting NAV is 100, so the
NAV per unit is also a growth-of-100 line.

The arithmetic core (compute_nav_series) takes prices and the exchange rate as
plain lookups, so tests feed fixed numbers and never touch the network. Only
the command-line run fetches from yfinance.

Examples (from a terminal in the Veda-advisor folder):

    python scripts/nav.py
    python scripts/nav.py --file ledger/transactions.jsonl --out nav/nav-series.jsonl

Exit codes:
    0 - series written
    1 - could not compute (bad ledger, missing prices); reason on stderr
    2 - ledger file missing
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

from ledger import load
from _common import client_root

# Default output for the default client (clients/default/nav/...). A specific
# client's files are resolved from --client in main().
DEFAULT_OUT = client_root() / "nav" / "nav-series.jsonl"

STARTING_NAV = 100.0      # NAV per unit at inception (rupees).
STALENESS_DAYS = 7        # A price older than this, for the date asked, is stale.

NIFTY_TICKER = "^NSEI"
SP500_TICKER = "^GSPC"
FX_TICKER = "USDINR=X"


class Series:
    """A dated series of numbers with an as-of lookup.

    as_of(day) returns the value from the last date on or before day, together
    with how many days old that value is. Weekends and holidays resolve to the
    previous trading day.
    """

    def __init__(self, points: list[tuple[str, float]]):
        ordered = sorted(points, key=lambda item: item[0])
        self._days = [day for day, _ in ordered]
        self._values = [value for _, value in ordered]

    def as_of(self, day: str) -> tuple[float, int]:
        spot = bisect.bisect_right(self._days, day) - 1
        if spot < 0:
            raise LookupError(f"no value on or before {day}")
        value = self._values[spot]
        age = _days_between(self._days[spot], day)
        return value, age


def _days_between(earlier: str, later: str) -> int:
    return (_to_date(later) - _to_date(earlier)).days


def _to_date(day: str) -> date:
    year, month, dom = (int(part) for part in day.split("-"))
    return date(year, month, dom)


def split_factor(ratio: str) -> float:
    """Share multiplier for a split. Ratio a:b means b old shares become a new."""
    left, right = (int(part) for part in ratio.split(":"))
    return left / right


def bonus_factor(ratio: str) -> float:
    """Share multiplier for a bonus. Ratio a:b means a free shares for every b held."""
    left, right = (int(part) for part in ratio.split(":"))
    return 1.0 + left / right


def compute_nav_series(
    transactions: list[dict],
    prices: dict[tuple[str, str], Series],
    fx: Series,
    nifty: Series,
    sp500: Series,
    valuation_dates: list[str],
    staleness_days: int = STALENESS_DAYS,
    starting_nav: float = STARTING_NAV,
) -> list[dict]:
    """Build the NAV series. Pure: every number comes from the arguments.

    prices is keyed by (market, ticker), both as stored in the ledger.
    fx, nifty, and sp500 are Series. valuation_dates are the rows to report.
    """
    lots: dict[str, dict] = {}        # lot_id -> {ticker, market, currency, shares}
    cash = {"INR": 0.0, "USD": 0.0}
    units = 0.0

    def price_of(market: str, ticker: str, day: str) -> tuple[float, int]:
        series = prices.get((market, ticker))
        if series is None:
            raise LookupError(f"no price history for {ticker} ({market})")
        return series.as_of(day)

    def value_book(day: str) -> dict:
        """Value the whole book in rupees as of day."""
        rate, fx_age = fx.as_of(day)
        ages = [fx_age]
        india_inr = 0.0
        us_inr = 0.0
        for lot in lots.values():
            if lot["shares"] <= 1e-9:
                continue
            price, age = price_of(lot["market"], lot["ticker"], day)
            ages.append(age)
            if lot["market"] == "india":
                india_inr += lot["shares"] * price
            else:
                us_inr += lot["shares"] * price * rate
        cash_inr = cash["INR"] + cash["USD"] * rate
        return {
            "india_value_inr": india_inr,
            "us_value_inr": us_inr,
            "cash_value_inr": cash_inr,
            "book_value_inr": india_inr + us_inr + cash_inr,
            "stale": any(age > staleness_days for age in ages),
        }

    def to_inr(amount: float, currency: str, day: str) -> float:
        if currency == "INR":
            return amount
        rate, _ = fx.as_of(day)
        return amount * rate

    snapshots: dict[str, dict] = {}
    targets = sorted(set(valuation_dates))
    target_index = 0

    ordered = sorted(transactions, key=lambda tx: (tx["date"], _id_number(tx)))

    for tx in ordered:
        day = tx["date"]
        while target_index < len(targets) and targets[target_index] < day:
            snapshots[targets[target_index]] = _row(targets[target_index], units, value_book)
            target_index += 1

        kind = tx["type"]
        if kind == "cash_in":
            amount_inr = to_inr(tx["amount"], tx["currency"], day)
            if units <= 1e-9:
                nav = starting_nav
            else:
                nav = value_book(day)["book_value_inr"] / units
            units += amount_inr / nav
            cash[tx["currency"]] += tx["amount"]
        elif kind == "cash_out":
            amount_inr = to_inr(tx["amount"], tx["currency"], day)
            nav = value_book(day)["book_value_inr"] / units
            units -= amount_inr / nav
            cash[tx["currency"]] -= tx["amount"]
        elif kind == "buy":
            cash[tx["currency"]] -= tx["shares"] * tx["price"] + tx.get("fees", 0.0)
            lots[tx["lot_id"]] = {
                "ticker": tx["ticker"],
                "market": tx["market"],
                "currency": tx["currency"],
                "shares": float(tx["shares"]),
            }
        elif kind == "sell":
            lot = lots.get(tx["lot_id"])
            if lot is None:
                raise ValueError(f"sell {tx.get('id')} names unknown lot {tx['lot_id']}")
            lot["shares"] -= tx["shares"]
            cash[tx["currency"]] += tx["shares"] * tx["price"] - tx.get("fees", 0.0)
        elif kind == "dividend":
            cash[tx["currency"]] += tx["amount"]
        elif kind in ("split", "bonus"):
            factor = split_factor(tx["ratio"]) if kind == "split" else bonus_factor(tx["ratio"])
            for lot in lots.values():
                if lot["ticker"] == tx["ticker"] and lot["market"] == tx["market"]:
                    lot["shares"] *= factor

    while target_index < len(targets):
        snapshots[targets[target_index]] = _row(targets[target_index], units, value_book)
        target_index += 1

    rows = [snapshots[day] for day in targets]
    _add_benchmark(rows, fx, nifty, sp500)
    return rows


def _row(day: str, units: float, value_book: Callable[[str], dict]) -> dict:
    book = value_book(day)
    nav = book["book_value_inr"] / units if units > 1e-9 else 0.0
    return {
        "date": day,
        "units": round(units, 4),
        "nav_per_unit": round(nav, 2),
        "book_value_inr": round(book["book_value_inr"], 2),
        "india_value_inr": round(book["india_value_inr"], 2),
        "us_value_inr": round(book["us_value_inr"], 2),
        "cash_value_inr": round(book["cash_value_inr"], 2),
        "stale": book["stale"],
        # carried, then replaced with a rounded number by _add_benchmark
        "benchmark_indexed": None,
    }


def _add_benchmark(rows: list[dict], fx: Series, nifty: Series, sp500: Series) -> None:
    """Fill benchmark_indexed: 100 at the first row, grown by the blended return."""
    if not rows:
        return
    rows[0]["benchmark_indexed"] = 100.0
    indexed = 100.0
    for past, now in zip(rows, rows[1:]):
        india = past["india_value_inr"]
        us = past["us_value_inr"]
        invested = india + us
        if invested <= 1e-9:
            blended = 0.0
        else:
            nifty_return = _ratio(nifty.as_of(now["date"])[0], nifty.as_of(past["date"])[0])
            sp_inr_now = sp500.as_of(now["date"])[0] * fx.as_of(now["date"])[0]
            sp_inr_past = sp500.as_of(past["date"])[0] * fx.as_of(past["date"])[0]
            sp_return = _ratio(sp_inr_now, sp_inr_past)
            blended = (india / invested) * nifty_return + (us / invested) * sp_return
        indexed *= 1.0 + blended
        now["benchmark_indexed"] = round(indexed, 2)
    rows[0]["benchmark_indexed"] = round(rows[0]["benchmark_indexed"], 2)


def _ratio(now: float, past: float) -> float:
    return now / past - 1.0


def _id_number(tx: dict) -> int:
    tx_id = tx.get("id", "")
    if tx_id.startswith("tx-"):
        try:
            return int(tx_id[3:])
        except ValueError:
            return 0
    return 0


def monthly_valuation_dates(inception: str, today: str) -> list[str]:
    """Inception, then every month-end after it up to last month, then today."""
    dates = [inception]
    start = _to_date(inception)
    end = _to_date(today)
    year, month = start.year, start.month
    while True:
        month_end = _month_end(year, month)
        if month_end >= end:
            break
        if month_end > start:
            dates.append(month_end.isoformat())
        month += 1
        if month > 12:
            month = 1
            year += 1
    dates.append(today)
    return sorted(set(dates))


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


# --- network fetch layer (only used by the command-line run) ---------------

def _fetch_closes(yf_ticker: str) -> list[tuple[str, float]]:
    import yfinance as yf

    data = yf.Ticker(yf_ticker).history(period="max", auto_adjust=True)
    if data is None or data.empty:
        return []
    points = []
    for stamp, row in data.iterrows():
        points.append((stamp.strftime("%Y-%m-%d"), float(row["Close"])))
    return points


def _build_price_book(transactions: list[dict]) -> dict[tuple[str, str], Series]:
    held = {(tx["market"], tx["ticker"]) for tx in transactions if tx.get("ticker")}
    book: dict[tuple[str, str], Series] = {}
    for market, ticker in sorted(held):
        points = _closes_for_holding(market, ticker)
        if not points:
            raise LookupError(f"no price history found for {ticker} ({market})")
        book[(market, ticker)] = Series(points)
    return book


def _closes_for_holding(market: str, ticker: str) -> list[tuple[str, float]]:
    if market == "us":
        return _fetch_closes(ticker)
    for suffix in (".NS", ".BO"):
        points = _fetch_closes(ticker + suffix)
        if points:
            return points
    return []


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Veda NAV series.")
    parser.add_argument("--client", default="default", help="which client's book (default: default)")
    parser.add_argument("--file", type=Path, default=None, help="ledger file")
    parser.add_argument("--out", type=Path, default=None, help="series output file")
    args = parser.parse_args(argv)

    root = client_root(args.client)
    ledger_file = args.file or (root / "ledger" / "transactions.jsonl")
    out_file = args.out or (root / "nav" / "nav-series.jsonl")

    if not ledger_file.exists():
        print(f"ledger file not found: {ledger_file}", file=sys.stderr)
        return 2

    try:
        transactions = load(ledger_file)
        if not transactions:
            print("ledger is empty; nothing to value", file=sys.stderr)
            return 1
        inception = min(tx["date"] for tx in transactions)
        today = date.today().isoformat()
        valuation_dates = monthly_valuation_dates(inception, today)

        prices = _build_price_book(transactions)
        fx = Series(_fetch_closes(FX_TICKER))
        nifty = Series(_fetch_closes(NIFTY_TICKER))
        sp500 = Series(_fetch_closes(SP500_TICKER))

        rows = compute_nav_series(transactions, prices, fx, nifty, sp500, valuation_dates)
    except (ValueError, LookupError) as error:
        print(str(error), file=sys.stderr)
        return 1

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    latest = rows[-1]
    print(f"wrote {len(rows)} rows to {out_file}")
    print(
        f"latest {latest['date']}: NAV/unit {latest['nav_per_unit']} "
        f"vs benchmark {latest['benchmark_indexed']} (both started at 100)"
    )
    if any(row["stale"] for row in rows):
        print("warning: some rows used stale prices", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
