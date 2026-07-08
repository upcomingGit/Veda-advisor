"""
Veda - transaction ledger.

The ledger is the dated, append-only record of every money event in the
family book: shares bought and sold, cash in and out, dividends, splits, and
bonus shares. It is the source data the NAV and performance pipeline reads.

See internal/ledger-schema.md for the full contract.

This module does two things:
  - load every transaction back from the file, in order.
  - add one new transaction to the end of the file.

It does NOT compute profit, cost basis, or NAV. That is the next module.

Pure stdlib. The file is one JSON object per line (JSONL), append-only.

Examples (from a terminal in the Veda-advisor folder):

    python scripts/ledger.py add --type buy --date 2026-06-03 \
        --market india --currency INR --ticker NTPC --shares 100 --price 350

    python scripts/ledger.py add --type sell --date 2026-07-01 \
        --market india --currency INR --ticker NTPC --shares 40 --price 380 \
        --lot-id ntpc-2026-06-03-1

    python scripts/ledger.py add --type cash_in --date 2026-06-01 \
        --market india --currency INR --amount 500000

    python scripts/ledger.py list
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from _common import client_root, slugify


# Default ledger file for the default client (clients/default/ledger/...).
# A specific client's ledger is resolved from --client in main().
DEFAULT_LEDGER = client_root() / "ledger" / "transactions.jsonl"

VALID_TYPES = {"buy", "sell", "cash_in", "cash_out", "dividend", "split", "bonus"}
VALID_MARKETS = {"india", "us"}
VALID_CURRENCIES = {"INR", "USD"}

# Which fields each type needs. Common fields (id, date, type, market,
# currency) are checked separately for every type.
REQUIRED_BY_TYPE = {
    "buy": ["ticker", "shares", "price", "lot_id"],
    "sell": ["ticker", "shares", "price", "lot_id"],
    "cash_in": ["amount"],
    "cash_out": ["amount"],
    "dividend": ["ticker", "amount"],
    "split": ["ticker", "ratio"],
    "bonus": ["ticker", "ratio"],
}

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RATIO_PATTERN = re.compile(r"^\d+:\d+$")


def load(path: Path = DEFAULT_LEDGER) -> list[dict]:
    """Return every transaction in the file, in order. Empty list if no file."""
    if not path.exists():
        return []
    transactions = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text:
                continue
            try:
                transactions.append(json.loads(text))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"line {line_number} is not valid JSON: {error}"
                ) from error
    return transactions


def next_id(transactions: list[dict]) -> str:
    """Return the next transaction id, like tx-00001."""
    highest = 0
    for tx in transactions:
        tx_id = tx.get("id", "")
        if tx_id.startswith("tx-"):
            try:
                highest = max(highest, int(tx_id[3:]))
            except ValueError:
                continue
    return f"tx-{highest + 1:05d}"


def make_lot_id(ticker: str, day: str, transactions: list[dict]) -> str:
    """Build a lot id from ticker and date, like ntpc-2026-06-03-1.

    If a lot for the same ticker and date already exists, the trailing number
    goes up so each lot id is unique.
    """
    slug = slugify(ticker)
    prefix = f"{slug}-{day}-"
    used = 0
    for tx in transactions:
        existing = tx.get("lot_id", "")
        if existing.startswith(prefix):
            try:
                used = max(used, int(existing[len(prefix):]))
            except ValueError:
                continue
    return f"{prefix}{used + 1}"


def check_one(tx: dict) -> list[str]:
    """Return a list of problems with a single transaction. Empty list if fine."""
    problems = []

    tx_type = tx.get("type")
    if tx_type not in VALID_TYPES:
        problems.append(f"type '{tx_type}' is not one of {sorted(VALID_TYPES)}")
        return problems  # without a known type we cannot check the rest

    day = tx.get("date", "")
    if not DATE_PATTERN.match(day):
        problems.append(f"date '{day}' is not in YYYY-MM-DD form")
    else:
        try:
            year, month, dom = (int(part) for part in day.split("-"))
            date(year, month, dom)
        except ValueError:
            problems.append(f"date '{day}' is not a real date")

    if tx.get("market") not in VALID_MARKETS:
        problems.append(f"market '{tx.get('market')}' must be india or us")

    if tx.get("currency") not in VALID_CURRENCIES:
        problems.append(f"currency '{tx.get('currency')}' must be INR or USD")

    for field in REQUIRED_BY_TYPE[tx_type]:
        if tx.get(field) in (None, ""):
            problems.append(f"{tx_type} needs a {field}")

    for field in ("shares", "price", "amount"):
        if field in tx and tx[field] is not None:
            if not _is_number(tx[field]) or tx[field] <= 0:
                problems.append(f"{field} must be a number greater than 0")

    if "fees" in tx and tx["fees"] is not None:
        if not _is_number(tx["fees"]) or tx["fees"] < 0:
            problems.append("fees must be a number of 0 or more")

    if tx_type in ("split", "bonus"):
        ratio = tx.get("ratio", "")
        if not RATIO_PATTERN.match(str(ratio)):
            problems.append(f"ratio '{ratio}' must be two whole numbers, like 2:1")
        else:
            left, right = (int(part) for part in str(ratio).split(":"))
            if left <= 0 or right <= 0:
                problems.append(f"ratio '{ratio}' must use numbers greater than 0")

    return problems


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def add(tx: dict, path: Path = DEFAULT_LEDGER) -> dict:
    """Add one transaction to the end of the file.

    Sets the id. For a buy, sets the lot_id if one is not given. Checks the
    transaction before writing it. Returns the stored transaction.
    """
    transactions = load(path)

    stored = dict(tx)
    stored["id"] = next_id(transactions)

    if stored.get("type") == "buy" and not stored.get("lot_id"):
        stored["lot_id"] = make_lot_id(
            stored.get("ticker", ""), stored.get("date", ""), transactions
        )

    problems = check_one(stored)
    if problems:
        raise ValueError("cannot add transaction:\n  - " + "\n  - ".join(problems))

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(stored, ensure_ascii=False) + "\n")
    return stored


def _build_from_args(args: argparse.Namespace) -> dict:
    """Turn command-line arguments into a transaction, dropping empty fields."""
    fields = {
        "date": args.date,
        "type": args.type,
        "market": args.market,
        "currency": args.currency,
        "ticker": args.ticker,
        "shares": args.shares,
        "price": args.price,
        "fees": args.fees,
        "amount": args.amount,
        "lot_id": args.lot_id,
        "ratio": args.ratio,
        "note": args.note,
    }
    return {key: value for key, value in fields.items() if value is not None}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Veda transaction ledger.")
    parser.add_argument(
        "--client",
        default="default",
        help="which client's ledger to use (default: default)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="ledger file path (default: the client's ledger/transactions.jsonl)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add_parser = sub.add_parser("add", help="add one transaction")
    add_parser.add_argument("--type", required=True, choices=sorted(VALID_TYPES))
    add_parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    add_parser.add_argument("--market", required=True, choices=sorted(VALID_MARKETS))
    add_parser.add_argument("--currency", required=True, choices=sorted(VALID_CURRENCIES))
    add_parser.add_argument("--ticker")
    add_parser.add_argument("--shares", type=float)
    add_parser.add_argument("--price", type=float)
    add_parser.add_argument("--fees", type=float)
    add_parser.add_argument("--amount", type=float)
    add_parser.add_argument("--lot-id", dest="lot_id")
    add_parser.add_argument("--ratio", help="like 2:1, for split or bonus")
    add_parser.add_argument("--note")

    sub.add_parser("list", help="print every transaction in the file")

    args = parser.parse_args(argv)
    ledger_file = args.file or (client_root(args.client) / "ledger" / "transactions.jsonl")

    if args.command == "add":
        try:
            stored = add(_build_from_args(args), ledger_file)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(f"added {stored['id']}: {json.dumps(stored, ensure_ascii=False)}")
        return 0

    if args.command == "list":
        try:
            transactions = load(ledger_file)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        for tx in transactions:
            print(json.dumps(tx, ensure_ascii=False))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
