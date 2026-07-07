"""
Veda - reconcile the ledger against assets.md.

assets.md is the file the chat trusts for what you hold today. The ledger
(ledger/transactions.jsonl) is the dated record the performance, concentration,
and rebalance modules read. The two can drift apart: a trade recorded in one
place but not the other, or a hand-edit to either file.

This check compares the two, name by name, and reports where they disagree. It
compares share counts only, not values, so it needs no prices and no network.

It changes nothing. It reads both files and prints a table.

This is the "reconcile on demand" guard: run it before trusting any number the
ledger-based modules print, and any time you want to know the two books match.

See internal/reconcile-schema.md for the full contract.

Examples (from a terminal in the Veda-advisor folder):

    python scripts/reconcile.py
    python scripts/reconcile.py --assets assets.md --file ledger/transactions.jsonl

Exit codes:
    0 - the two books agree (every name matches)
    1 - they disagree (at least one name differs, or is in only one book)
    2 - a file is missing
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from ledger import load
from concentration import current_positions
from _common import client_root


# Share counts equal within this are treated as the same (mutual-fund units can
# be fractional, so an exact-equality test would be too strict).
EPSILON = 1e-6

# Exchange suffixes that name the same stock as the bare ticker in the ledger.
TICKER_SUFFIXES = (".NS", ".BO", ".BSE", ".NSE")

# Currency word in an assets.md subsection header -> the ledger's market name.
CURRENCY_TO_MARKET = {"INR": "india", "USD": "us"}


def normalize_ticker(ticker: str) -> str:
    """Upper-case the ticker and drop a trailing exchange suffix.

    The ledger stores NTPC; assets.md may store NTPC or NTPC.NS. Both should
    compare as the same name.
    """
    cleaned = ticker.strip().upper()
    for suffix in TICKER_SUFFIXES:
        if cleaned.endswith(suffix):
            return cleaned[: -len(suffix)]
    return cleaned


def _rekey(positions: dict[tuple[str, str], float]) -> dict[tuple[str, str], float]:
    """Re-key a positions map through normalize_ticker and drop closed names.

    A name fully sold leaves a near-zero entry in the ledger replay; it is not a
    holding, so it is dropped before the comparison.
    """
    out: dict[tuple[str, str], float] = {}
    for (market, ticker), shares in positions.items():
        if abs(shares) < EPSILON:
            continue
        out[(market, normalize_ticker(ticker))] = shares
    return out


def compare_positions(
    ledger_positions: dict[tuple[str, str], float],
    assets_positions: dict[tuple[str, str], float],
    epsilon: float = EPSILON,
) -> list[dict]:
    """Compare two position maps and return one row per name.

    Both maps are keyed by (market, ticker) -> shares. Tickers are assumed to be
    already normalized. Each row has: market, ticker, ledger_shares,
    assets_shares (None where absent), and status, one of:
      - match           both books hold the same shares
      - mismatch        both books hold the name, different shares
      - in ledger only  the ledger holds it, assets.md does not
      - in assets only  assets.md holds it, the ledger does not
    Rows are sorted by market then ticker for a stable, readable table.
    """
    keys = set(ledger_positions) | set(assets_positions)
    rows: list[dict] = []
    for key in sorted(keys):
        market, ticker = key
        in_ledger = key in ledger_positions
        in_assets = key in assets_positions
        ledger_shares = ledger_positions.get(key)
        assets_shares = assets_positions.get(key)
        if in_ledger and in_assets:
            status = "match" if abs(ledger_shares - assets_shares) < epsilon else "mismatch"
        elif in_ledger:
            status = "in ledger only"
        else:
            status = "in assets only"
        rows.append(
            {
                "market": market,
                "ticker": ticker,
                "ledger_shares": ledger_shares,
                "assets_shares": assets_shares,
                "status": status,
            }
        )
    return rows


def read_assets_positions(path: Path) -> dict[tuple[str, str], float]:
    """Parse the holdings tables in assets.md into {(market, ticker): shares}.

    Reads the `## Holdings (equities)` section, walks its `### <Region> (<CCY>)`
    subsections to learn each row's market, and reads the ticker and shares
    columns of each table row. Stdlib only; no YAML or markdown library.
    """
    text = path.read_text(encoding="utf-8")
    positions: dict[tuple[str, str], float] = {}

    in_holdings = False
    market: str | None = None
    for raw in text.splitlines():
        line = raw.strip()

        # Section boundaries. Any new `## ` heading ends the holdings section.
        if line.startswith("## "):
            in_holdings = line.lower().startswith("## holdings")
            market = None
            continue
        if not in_holdings:
            continue

        # A `### India (INR)` style subsection names the market via its currency.
        if line.startswith("### "):
            market = _market_from_subsection(line)
            continue

        # Table rows start with a pipe. Skip the header and separator rows.
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        ticker_cell = cells[0]
        if ticker_cell.lower() in ("ticker", ""):
            continue
        if set(ticker_cell) <= set("-: "):  # separator row like |---|
            continue
        if market is None:
            continue
        shares = _to_float(cells[2])
        if shares is None:
            continue
        key = (market, normalize_ticker(ticker_cell))
        positions[key] = positions.get(key, 0.0) + shares

    return positions


def _market_from_subsection(line: str) -> str | None:
    """Read the market from a `### India (INR)` style subsection header."""
    match = re.search(r"\(([A-Za-z]{3})\)", line)
    if match:
        return CURRENCY_TO_MARKET.get(match.group(1).upper())
    return None


def _to_float(value: str) -> float | None:
    cleaned = value.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def format_report(rows: list[dict]) -> str:
    """Render the comparison as a readable table plus a one-line summary."""
    header = f"{'market':<7} {'ticker':<12} {'ledger':>12} {'assets.md':>12}  status"
    lines = [header, "-" * len(header)]
    for row in rows:
        ledger = "-" if row["ledger_shares"] is None else f"{row['ledger_shares']:.4f}"
        assets = "-" if row["assets_shares"] is None else f"{row['assets_shares']:.4f}"
        lines.append(
            f"{row['market']:<7} {row['ticker']:<12} {ledger:>12} {assets:>12}  {row['status']}"
        )

    disagreements = [r for r in rows if r["status"] != "match"]
    if not rows:
        lines.append("")
        lines.append("Both books are empty. Nothing to reconcile.")
    elif not disagreements:
        lines.append("")
        lines.append(f"The two books agree: {len(rows)} name(s) match.")
    else:
        lines.append("")
        lines.append(
            f"The two books disagree on {len(disagreements)} of {len(rows)} name(s). "
            "Record the missing trades, or fix whichever file is wrong."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile the ledger against assets.md (share counts only)."
    )
    parser.add_argument(
        "--client",
        default="default",
        help="which client's book to reconcile (default: default)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="ledger file (default: the client's ledger/transactions.jsonl)",
    )
    parser.add_argument(
        "--assets",
        type=Path,
        default=None,
        help="assets.md file (default: the client's assets.md)",
    )
    parser.add_argument(
        "--as-of",
        default=date.today().isoformat(),
        help="reconcile as of this date (default: today)",
    )
    args = parser.parse_args(argv)

    root = client_root(args.client)
    ledger_file = args.file or (root / "ledger" / "transactions.jsonl")
    assets_file = args.assets or (root / "assets.md")

    if not ledger_file.exists():
        print(f"Ledger file not found: {ledger_file}", file=sys.stderr)
        return 2
    if not assets_file.exists():
        print(f"Assets file not found: {assets_file}", file=sys.stderr)
        return 2

    transactions = load(ledger_file)
    ledger_raw, _cash = current_positions(transactions, args.as_of)
    ledger_positions = _rekey(ledger_raw)
    assets_positions = read_assets_positions(assets_file)

    rows = compare_positions(ledger_positions, assets_positions)
    print(format_report(rows))

    disagreements = [r for r in rows if r["status"] != "match"]
    return 1 if disagreements else 0


if __name__ == "__main__":
    raise SystemExit(main())
