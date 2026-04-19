"""
import_portfolio.py — Convert a broker CSV export into Veda's portfolio.md format.

Usage:
    python import_portfolio.py <broker> <input.csv> [--out portfolio.md]

Supported brokers (v0.1):
    zerodha     — Zerodha Kite "Holdings" CSV export
    generic     — Any CSV with columns: ticker, name, shares, avg_cost, current_price [optional: sector]

Adding a new broker:
    Add a function `parse_<broker>(rows) -> list[Position]` that returns a list of Position dicts,
    then register it in BROKER_PARSERS. See parse_zerodha for the reference implementation.

Output:
    A portfolio.md file with a structured holdings table, cash line, and watchlist stub.
    Does NOT fetch live prices. Current prices come from the CSV (which is usually end-of-day).
    The "as of" date defaults to today — edit it in the generated file if the export is older.

Privacy:
    portfolio.md is gitignored by default (see repo .gitignore). Never commit it.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class Position:
    ticker: str
    name: str
    shares: float
    avg_cost: float
    current_price: float
    current_value: float = 0.0
    sector: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.current_value:
            self.current_value = round(self.shares * self.current_price, 2)


# -----------------------------------------------------------------------------
# Broker parsers
# -----------------------------------------------------------------------------
# Each parser receives a list of dict rows (from csv.DictReader) and returns
# a list of Position objects. Parsers should be tolerant of column name
# variations within a broker's format (e.g., "Avg. cost" vs "Average price").


def _get(row: dict, *keys: str) -> str:
    """Return the first non-empty value among the given column keys (case-insensitive)."""
    lower = {k.lower().strip(): v for k, v in row.items()}
    for key in keys:
        v = lower.get(key.lower().strip())
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return ""


def _to_float(s: str) -> float:
    """Parse a numeric string that may contain commas or currency symbols."""
    if not s:
        return 0.0
    cleaned = s.replace(",", "").replace("₹", "").replace("$", "").replace("€", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_zerodha(rows: list[dict]) -> list[Position]:
    """
    Parse a Zerodha Kite Holdings CSV.

    Expected columns (Zerodha has renamed these over time; we accept several):
        Instrument | Symbol | Tradingsymbol
        Qty.       | Quantity
        Avg. cost  | Avg cost | Average price
        LTP        | Last traded price | Current price
        Cur. val   | Current value
        Sector     (optional; not always present)
    """
    positions: list[Position] = []
    for row in rows:
        ticker = _get(row, "Instrument", "Symbol", "Tradingsymbol")
        if not ticker:
            continue  # skip totals/blank rows
        shares = _to_float(_get(row, "Qty.", "Quantity"))
        if shares <= 0:
            continue
        avg_cost = _to_float(_get(row, "Avg. cost", "Avg cost", "Average price"))
        current_price = _to_float(_get(row, "LTP", "Last traded price", "Current price"))
        current_value = _to_float(_get(row, "Cur. val", "Current value"))
        sector = _get(row, "Sector")
        positions.append(
            Position(
                ticker=ticker,
                name=ticker,  # Zerodha Kite exports usually don't include company name separately
                shares=shares,
                avg_cost=avg_cost,
                current_price=current_price,
                current_value=current_value or round(shares * current_price, 2),
                sector=sector,
            )
        )
    return positions


def parse_generic(rows: list[dict]) -> list[Position]:
    """
    Parse a generic CSV with flexible columns:
        ticker (required)
        name (optional; defaults to ticker)
        shares | quantity | qty (required)
        avg_cost | cost_basis | average_price (required)
        current_price | price | ltp (required)
        sector (optional)
    """
    positions: list[Position] = []
    for row in rows:
        ticker = _get(row, "ticker", "symbol")
        if not ticker:
            continue
        shares = _to_float(_get(row, "shares", "quantity", "qty"))
        if shares <= 0:
            continue
        positions.append(
            Position(
                ticker=ticker,
                name=_get(row, "name") or ticker,
                shares=shares,
                avg_cost=_to_float(_get(row, "avg_cost", "cost_basis", "average_price")),
                current_price=_to_float(_get(row, "current_price", "price", "ltp")),
                sector=_get(row, "sector"),
            )
        )
    return positions


BROKER_PARSERS = {
    "zerodha": parse_zerodha,
    "generic": parse_generic,
}


# -----------------------------------------------------------------------------
# Markdown writer
# -----------------------------------------------------------------------------


def render_markdown(positions: list[Position], as_of: str) -> str:
    """Produce the portfolio.md content from a list of positions."""
    total_value = sum(p.current_value for p in positions)

    header = [
        "# Portfolio",
        "",
        f"**As of:** {as_of}",
        "",
        "<!--",
        "This file was auto-generated by scripts/import_portfolio.py.",
        "Edit freely. Veda re-reads this file on every portfolio-level question.",
        "Keep it up to date: re-run the importer after trades, or edit the table by hand.",
        "",
        "This file is gitignored by default. Do not commit it.",
        "-->",
        "",
        "## Holdings",
        "",
        "| ticker | name | shares | avg_cost | current_price | current_value | sector | thesis | tags |",
        "|---|---|---:|---:|---:|---:|---|---|---|",
    ]

    rows: list[str] = []
    for p in sorted(positions, key=lambda x: x.current_value, reverse=True):
        rows.append(
            f"| {p.ticker} | {p.name} | {p.shares:g} | {p.avg_cost:,.2f} "
            f"| {p.current_price:,.2f} | {p.current_value:,.2f} | {p.sector or '-'} | _(add thesis)_ | _(core/tactical/speculation)_ |"
        )

    footer = [
        "",
        f"**Total holdings value:** {total_value:,.2f}",
        "**Cash:** _(update manually)_",
        "",
        "## Watchlist / open orders",
        "",
        "- _(tickers you're tracking but don't own yet, with trigger conditions)_",
        "",
        "## Sector caps (optional)",
        "",
        "- _(e.g., Semiconductors <= 30%, Financials <= 25%)_",
        "",
        "## Notes",
        "",
        "- _(anything Veda should know about the portfolio as a whole: tax lots, wash-sale windows, upcoming rebalance dates)_",
    ]

    return "\n".join(header + rows + footer) + "\n"


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert a broker CSV export into Veda's portfolio.md format.",
    )
    parser.add_argument(
        "broker",
        choices=sorted(BROKER_PARSERS.keys()),
        help="Broker format. Use 'generic' for any CSV with ticker/shares/avg_cost/current_price columns.",
    )
    parser.add_argument("csv_path", type=Path, help="Path to the broker CSV export.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("portfolio.md"),
        help="Output markdown path. Default: portfolio.md in the current directory.",
    )
    parser.add_argument(
        "--as-of",
        default=date.today().isoformat(),
        help="'As of' date written into the file header. Default: today.",
    )

    args = parser.parse_args()

    if not args.csv_path.exists():
        print(f"Error: CSV file not found: {args.csv_path}", file=sys.stderr)
        return 2

    with args.csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    if not rows:
        print(f"Error: CSV file is empty or has no data rows: {args.csv_path}", file=sys.stderr)
        return 2

    positions = BROKER_PARSERS[args.broker](rows)
    if not positions:
        print(
            f"Warning: no positions parsed from {args.csv_path}. "
            f"Check the column names match the '{args.broker}' format. "
            f"See the docstrings in import_portfolio.py for expected columns.",
            file=sys.stderr,
        )
        return 1

    content = render_markdown(positions, as_of=args.as_of)
    args.out.write_text(content, encoding="utf-8")
    print(f"Wrote {len(positions)} position(s) to {args.out}")
    print(
        "\nNext steps:\n"
        "  1. Add your cash balance and any sector caps at the bottom of the file.\n"
        "  2. Leave 'thesis' and 'tags' blank. Veda will ask for those lazily\n"
        "     when you question a specific holding, and write the answers back here.\n"
        "  3. Confirm portfolio.md is gitignored: `git check-ignore -v portfolio.md`"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
