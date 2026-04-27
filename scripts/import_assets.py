"""
import_assets.py — Convert a broker CSV export into the equities-holdings
section of Veda's assets.md file.

Usage:
    python import_assets.py <broker> <input.csv> [--out assets.md]

Supported brokers (v0.1):
    zerodha     — Zerodha Kite "Holdings" CSV export
    generic     — Any CSV with columns: ticker, name, shares, avg_cost, current_price [optional: sector]

Adding a new broker:
    Add a function `parse_<broker>(rows) -> list[Position]` that returns a list of Position dicts,
    then register it in BROKER_PARSERS. See parse_zerodha for the reference implementation.

Output:
    An assets.md file with:
      - A top `dynamic:` YAML block populated with TBD_fetch / null stubs. Veda fills
        these (fx_rates, concentration_snapshot, capital_split_current,
        forced_concentration_snapshot, totals) on the first session after import,
        using scripts/calc.py per Hard Rule #8. See internal/assets-schema.md.
      - A `## Holdings (equities)` table populated from the CSV. Per-position
        thesis content is NOT written into this table — it lives in
        holdings/<slug>/thesis.md and is captured lazily per SKILL.md Stage 1.5.
      - Empty `## Cash & equivalents` and `## Liabilities (loans)` placeholders.

    Does NOT fetch live prices. Current prices come from the CSV (which is usually end-of-day).
    The "as of" date defaults to today — edit it in the generated file if the export is older.

Privacy:
    assets.md is gitignored by default (see repo .gitignore). Never commit it.
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
    """Produce the assets.md content from a list of positions."""
    total_value = sum(p.current_value for p in positions)

    header = [
        "# Assets",
        "",
        f"**As of:** {as_of}",
        "",
        "<!--",
        "This file was auto-generated by scripts/import_assets.py.",
        "Edit freely. Veda re-reads this file on every portfolio-level question.",
        "Keep it up to date: re-run the importer after trades, or edit tables by hand.",
        "",
        "The `dynamic:` block below is populated with stubs. Veda will fill these",
        "fields via scripts/calc.py on the next session (FX, snapshot, totals,",
        "capital split, forced-concentration snapshot). See internal/assets-schema.md.",
        "",
        "This file is gitignored by default. Do not commit it.",
        "-->",
        "",
        "```yaml",
        "dynamic:",
        "  fx_rates: {}   # TBD: paste scripts/fetch_quote.py fx --pair <from>_<to> output here",
        "  concentration_snapshot:",
        "    style: TBD_fetch",
        "    position_count: TBD_fetch",
        "    largest_position_pct: TBD_fetch",
        "    largest_position_ticker: TBD_fetch",
        "  capital_split_current:",
        "    core_long_term: TBD_fetch",
        "    tactical: TBD_fetch",
        "    short_term_trades: TBD_fetch",
        "    speculation: TBD_fetch",
        "  forced_concentration_snapshot: []",
        "  totals: {}",
        "```",
        "",
        "## Holdings (equities)",
        "",
        "| ticker | name | shares | avg_cost | current_price | current_value | sector | tags |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]

    rows: list[str] = []
    for p in sorted(positions, key=lambda x: x.current_value, reverse=True):
        rows.append(
            f"| {p.ticker} | {p.name} | {p.shares:g} | {p.avg_cost:,.2f} "
            f"| {p.current_price:,.2f} | {p.current_value:,.2f} | {p.sector or '-'} | _(core/tactical/speculation)_ |"
        )

    footer = [
        "",
        f"**Total holdings value:** {total_value:,.2f}",
        "",
        "## Cash & equivalents",
        "",
        "_(not yet captured — add savings accounts, current accounts, liquid funds, money-market balances, sweep-in FDs here. One row per account.)_",
        "",
        "| account | institution | currency | balance | as_of | notes |",
        "|---|---|---|---:|---|---|",
        "",
        "## Fixed deposits & bonds",
        "",
        "_(not yet captured — add bank FDs, corporate FDs, RBI bonds, SGBs held as debt, G-secs, and debt mutual-fund holdings here.)_",
        "",
        "| instrument | institution | currency | principal | rate_pct | start_date | maturity_date | auto_renew | current_value | notes |",
        "|---|---|---|---:|---:|---|---|---|---:|---|",
        "",
        "## Retirement & tax-advantaged accounts",
        "",
        "_(not yet captured — add PPF, EPF, NPS, Sukanya Samriddhi (IN); 401(k), IRA, HSA (US); ISA, SIPP (UK). Access-age constraints mean these do NOT count toward `dynamic.totals.grand_total_<base_ccy>` unless the user explicitly authorises inclusion.)_",
        "",
        "| account_type | scheme | institution | currency | contribution_total | current_value | vesting_or_lock_until | annual_contribution | employer_match_pct | notes |",
        "|---|---|---|---|---:|---:|---|---:|---:|---|",
        "",
        "## Unvested equity grants (stock options, RSUs, ESPP)",
        "",
        "_(not yet captured — add unvested RSU tranches, stock options with strike + expiry, ESPP lookbacks. Unvested grants are contingent claims: they do NOT enter `dynamic.totals` or `dynamic.concentration_snapshot.position_count`, but they DO inform `dynamic.forced_concentration_snapshot` forward projections.)_",
        "",
        "| grant_type | ticker | grant_date | shares_granted | shares_vested | shares_unvested | strike_or_fmv | vesting_schedule | next_vest_date | next_vest_shares | expiry | notes |",
        "|---|---|---|---:|---:|---:|---:|---|---|---:|---|---|",
        "",
        "## Precious metals",
        "",
        "_(not yet captured — add physical gold/silver, sovereign gold bonds, gold ETFs, digital-gold platform balances. Keep physical and paper forms in separate rows so the liquidity flag is honest.)_",
        "",
        "| form | metal | weight_grams | purity | currency | current_value | source_of_valuation | storage | notes |",
        "|---|---|---:|---|---|---:|---|---|---|",
        "",
        "## Real estate",
        "",
        "_(not yet captured — one row per property: owner-occupied, rental, land, inherited-awaiting-partition. Owner-occupied is recorded but NOT funded against in equity sizing. Any row with `outstanding_loan > 0` must have a matching row in Liabilities with `secured_against` pointing back to the property.)_",
        "",
        "| property_type | location | ownership_pct | use | currency | purchase_price | purchase_date | current_value | valuation_source | outstanding_loan | monthly_income | notes |",
        "|---|---|---:|---|---|---:|---|---:|---|---:|---:|---|",
        "",
        "## Other assets (loans given, private holdings, alternatives)",
        "",
        "_(not yet captured — money lent to family/friends, informal business loans given out, private-company equity, angel cheques, unlisted-company ESOPs, art, collectibles, off-exchange crypto. Anything that is an asset but does not fit the rows above.)_",
        "",
        "| asset | category | currency | principal_or_cost | current_value | valuation_date | expected_return | liquidity | counterparty | notes |",
        "|---|---|---|---:|---:|---|---|---|---|---|",
        "",
        "## Liabilities (loans taken)",
        "",
        "_(not yet captured — mortgages, auto loans, personal loans, education loans, revolving credit-card balances, loan-against-securities, margin balances.)_",
        "",
        "| loan_type | lender | currency | principal | outstanding_balance | rate_pct | rate_type | emi | tenure_months_remaining | secured_against | start_date | notes |",
        "|---|---|---|---:|---:|---:|---|---:|---:|---|---|---|",
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
        description="Convert a broker CSV export into Veda's assets.md format.",
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
        default=Path("assets.md"),
        help="Output markdown path. Default: assets.md in the current directory.",
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
            f"See the docstrings in import_assets.py for expected columns.",
            file=sys.stderr,
        )
        return 1

    content = render_markdown(positions, as_of=args.as_of)
    args.out.write_text(content, encoding="utf-8")
    print(f"Wrote {len(positions)} position(s) to {args.out}")
    print(
        "\nNext steps:\n"
        "  1. Add your cash balance and any sector caps at the bottom of the file.\n"
        "  2. Per-position thesis content is captured lazily in\n"
        "     holdings/<slug>/thesis.md the first time you ask Veda about that\n"
        "     ticker (SKILL.md Stage 1.5). Do not pre-fill it here.\n"
        "  3. Confirm assets.md is gitignored: `git check-ignore -v assets.md`"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
