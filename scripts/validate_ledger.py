"""
Veda - ledger validator.

Checks the whole transaction ledger against the rules in
internal/ledger-schema.md. Use it before trusting the file for any NAV or
performance number.

It confirms, for every line:
  - the line is valid JSON,
  - type, market, and currency hold allowed values,
  - date is a real date in YYYY-MM-DD form,
  - each type has the fields it needs,
  - shares, price, and amount are greater than 0; fees is 0 or more,
  - ratio is two whole numbers greater than 0, like 2:1.

And across the file:
  - every id is unique,
  - every buy lot_id is unique,
  - every sell names a lot_id that an earlier buy created.

Pure stdlib. Reuses the single-transaction checks from ledger.py.

Usage:

    python scripts/validate_ledger.py
    python scripts/validate_ledger.py --file ledger/transactions.jsonl

Exit codes:
    0 - valid
    1 - validation failed; reasons printed to stderr
    2 - file missing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ledger import DEFAULT_LEDGER, check_one, load


def validate(path: Path) -> list[str]:
    """Return a list of problems with the whole file. Empty list if valid."""
    transactions = load(path)
    problems = []

    seen_ids = set()
    buy_lots = set()

    for position, tx in enumerate(transactions, start=1):
        where = f"transaction {position}"
        tx_id = tx.get("id")
        if tx_id:
            where = f"{where} ({tx_id})"

        for problem in check_one(tx):
            problems.append(f"{where}: {problem}")

        if tx_id in seen_ids:
            problems.append(f"{where}: id is used more than once")
        seen_ids.add(tx_id)

        if tx.get("type") == "buy":
            lot_id = tx.get("lot_id")
            if lot_id in buy_lots:
                problems.append(f"{where}: lot_id '{lot_id}' is used by another buy")
            if lot_id:
                buy_lots.add(lot_id)

    # A sell can only sell from a lot some earlier buy created. Checked after
    # the loop so order within the file does not matter for this rule.
    for position, tx in enumerate(transactions, start=1):
        if tx.get("type") == "sell":
            lot_id = tx.get("lot_id")
            if lot_id and lot_id not in buy_lots:
                tx_id = tx.get("id") or f"transaction {position}"
                problems.append(
                    f"{tx_id}: sell names lot_id '{lot_id}', "
                    f"but no buy created that lot"
                )

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the Veda transaction ledger.")
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_LEDGER,
        help="ledger file path (default: ledger/transactions.jsonl)",
    )
    args = parser.parse_args(argv)

    if not args.file.exists():
        print(f"ledger file not found: {args.file}", file=sys.stderr)
        return 2

    try:
        problems = validate(args.file)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1

    if problems:
        print(f"{len(problems)} problem(s) found:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print("ledger is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
