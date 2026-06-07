"""
Veda - concentration and caps view.

Turns the transaction ledger into a snapshot of where the book is concentrated
today and checks each position against the limits in user-config/caps.json.

See internal/concentration-schema.md for the full contract.

Every weight is a fraction of the total book value (all holdings plus all
cash). The view checks three things: single-name weight, sector weight, and
market (india / us) weight. A breach reports how far over the cap a position
is, and a number to act on.

The arithmetic core (build_report) takes prices, the exchange rate, the sector
map, and the caps as plain arguments, so tests feed fixed numbers and never
touch the network. Only the command-line run fetches from yfinance.

Examples (from a terminal in the Veda-advisor folder):

    python scripts/concentration.py
    python scripts/concentration.py --file ledger/transactions.jsonl
    python scripts/concentration.py --as-of 2026-03-31

Exit codes:
    0 - snapshot written (whether or not any cap is breached)
    1 - could not compute (bad ledger, missing prices); reason on stderr
    2 - ledger file missing
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from ledger import DEFAULT_LEDGER, load
from nav import (
    FX_TICKER,
    Series,
    _closes_for_holding,
    _fetch_closes,
    bonus_factor,
    split_factor,
)

# Repo root is the parent of scripts/.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CAPS = REPO_ROOT / "user-config" / "caps.json"
DEFAULT_HOLDINGS = REPO_ROOT / "holdings"
DEFAULT_OUT = REPO_ROOT / "concentration" / "snapshot.json"

STALENESS_DAYS = 7        # A price older than this, for the snapshot date, is stale.
EPSILON = 1e-9            # Shares at or below this are treated as a closed position.


# --- reading the sector map and the caps -----------------------------------

def read_meta(path: Path) -> dict[str, str]:
    """Read a flat `key: value` _meta.yaml into a dict of strings.

    Only top-level scalar lines are read; that is all this view needs
    (ticker, market, sector). Surrounding single or double quotes are
    stripped. Nested lines (indented) and comments are ignored.
    """
    fields: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[0] in (" ", "\t"):       # indented: a nested line, not needed here
            continue
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
            value = value[1:-1]
        fields[key.strip()] = value
    return fields


def _normalise_market(market: str) -> str:
    """Map a _meta.yaml market to the ledger's spelling."""
    lowered = market.strip().lower()
    if lowered in ("in", "india"):
        return "india"
    if lowered in ("us", "usa"):
        return "us"
    return lowered


def build_sector_map(holdings_dir: Path) -> dict[tuple[str, str], str]:
    """Scan holdings/*/_meta.yaml and map (market, ticker) -> sector.

    A _meta.yaml missing any of ticker, market, or sector is skipped; the
    holding then shows up as a data gap when the ledger holds it.
    """
    sectors: dict[tuple[str, str], str] = {}
    if not holdings_dir.exists():
        return sectors
    for meta_path in sorted(holdings_dir.glob("*/_meta.yaml")):
        fields = read_meta(meta_path)
        ticker = fields.get("ticker", "").strip().upper()
        market = fields.get("market", "").strip()
        sector = fields.get("sector", "").strip()
        if not ticker or not market or not sector:
            continue
        sectors[(_normalise_market(market), ticker)] = sector
    return sectors


# Older caps.json files used terse field names. These are still read and mapped
# to the current friendlier names so an existing file keeps working unchanged.
_LEGACY_CAP_KEYS = {
    "single_name": "max_per_stock",
    "market": "max_per_country",
    "sector": "max_per_sector",
    "rebalance_band": "ignore_drift_below",
    "targets": "target_weights",
}


def load_caps(path: Path) -> dict:
    """Read user-config/caps.json. Missing countries / sectors mean no cap there.

    The field names are plain-language: max_per_stock, max_per_country,
    max_per_sector, ignore_drift_below, target_weights. Older files that used the
    terse names (single_name / market / sector / rebalance_band / targets) are
    read and mapped onto the current names automatically.
    """
    caps = json.loads(path.read_text(encoding="utf-8"))
    for old, new in _LEGACY_CAP_KEYS.items():
        if old in caps and new not in caps:
            caps[new] = caps.pop(old)
    caps.setdefault("max_per_stock", None)
    caps.setdefault("max_per_country", {})
    caps.setdefault("max_per_sector", {})
    return caps


# --- replaying the ledger into current positions ---------------------------

def current_positions(
    transactions: list[dict],
    as_of: str,
) -> tuple[dict[tuple[str, str], float], dict[str, float]]:
    """Replay the ledger up to as_of into shares held and cash by currency.

    Returns ({(market, ticker): shares}, {currency: cash}). Shares of a name
    are aggregated across lots. Splits and bonuses rescale the held shares of
    the named holding, using the same factors as the NAV pipeline.
    """
    positions: dict[tuple[str, str], float] = {}
    cash = {"INR": 0.0, "USD": 0.0}

    ordered = sorted(
        (tx for tx in transactions if tx["date"] <= as_of),
        key=lambda tx: (tx["date"], _id_number(tx)),
    )
    for tx in ordered:
        kind = tx["type"]
        currency = tx.get("currency", "INR")
        if kind == "cash_in":
            cash[currency] += tx["amount"]
        elif kind == "cash_out":
            cash[currency] -= tx["amount"]
        elif kind == "dividend":
            cash[currency] += tx["amount"]
        elif kind == "buy":
            key = (tx["market"], tx["ticker"])
            positions[key] = positions.get(key, 0.0) + float(tx["shares"])
            cash[currency] -= tx["shares"] * tx["price"] + tx.get("fees", 0.0)
        elif kind == "sell":
            key = (tx["market"], tx["ticker"])
            positions[key] = positions.get(key, 0.0) - float(tx["shares"])
            cash[currency] += tx["shares"] * tx["price"] - tx.get("fees", 0.0)
        elif kind in ("split", "bonus"):
            key = (tx["market"], tx["ticker"])
            if key in positions:
                factor = split_factor(tx["ratio"]) if kind == "split" else bonus_factor(tx["ratio"])
                positions[key] *= factor

    return positions, cash


def _id_number(tx: dict) -> int:
    tx_id = tx.get("id", "")
    if tx_id.startswith("tx-"):
        try:
            return int(tx_id[3:])
        except ValueError:
            return 0
    return 0


# --- the arithmetic core ---------------------------------------------------

def build_report(
    transactions: list[dict],
    prices: dict[tuple[str, str], Series],
    fx: Series,
    sector_map: dict[tuple[str, str], str],
    caps: dict,
    as_of: str,
    staleness_days: int = STALENESS_DAYS,
) -> dict:
    """Build the concentration snapshot. Pure: every number comes from the arguments.

    prices is keyed by (market, ticker). fx is a Series of USD->INR. sector_map
    maps (market, ticker) -> sector. caps is the parsed caps file.
    """
    positions, cash = current_positions(transactions, as_of)
    rate, fx_age = fx.as_of(as_of)
    ages = [fx_age]

    # Value each open position in rupees.
    names: list[dict] = []
    data_gaps: list[str] = []
    for (market, ticker), shares in positions.items():
        if shares <= EPSILON:
            continue
        series = prices.get((market, ticker))
        if series is None:
            raise LookupError(f"no price for {ticker} ({market})")
        price, age = series.as_of(as_of)
        ages.append(age)
        value_inr = shares * price * rate if market == "us" else shares * price
        sector = sector_map.get((market, ticker), "unknown")
        if sector == "unknown":
            data_gaps.append(f"{ticker} ({market}): no sector in _meta.yaml")
        names.append({
            "ticker": ticker,
            "market": market,
            "sector": sector,
            "shares": round(shares, 4),
            "price": round(price, 4),
            "value_inr": value_inr,
        })

    cash_inr = cash["INR"] + cash["USD"] * rate
    holdings_inr = sum(item["value_inr"] for item in names)
    book = holdings_inr + cash_inr

    single_cap = caps.get("max_per_stock")
    for item in names:
        weight = item["value_inr"] / book if book > EPSILON else 0.0
        item["weight"] = weight
        item["cap"] = single_cap
        breach = single_cap is not None and weight > single_cap
        item["breach"] = breach
        if breach:
            trim_inr = item["value_inr"] - single_cap * book
            item["trim_inr"] = round(trim_inr, 2)
            item["trim_shares"] = round(trim_inr / (item["price"] * (rate if item["market"] == "us" else 1.0)), 4)
        else:
            item["trim_inr"] = 0.0
            item["trim_shares"] = 0.0
        item["value_inr"] = round(item["value_inr"], 2)
        item["weight"] = round(weight, 4)

    names.sort(key=lambda item: item["weight"], reverse=True)

    sectors = _rollup(
        names, book, key="sector",
        cap_for=lambda name: _sector_cap(caps, name),
    )
    markets = _rollup(
        names, book, key="market",
        cap_for=lambda name: caps.get("max_per_country", {}).get(name),
    )

    return {
        "as_of": as_of,
        "book_value_inr": round(book, 2),
        "holdings_value_inr": round(holdings_inr, 2),
        "cash_value_inr": round(cash_inr, 2),
        "cash_weight": round(cash_inr / book, 4) if book > EPSILON else 0.0,
        "stale": any(age > staleness_days for age in ages),
        "names": names,
        "sectors": sectors,
        "markets": markets,
        "data_gaps": data_gaps,
    }


def _sector_cap(caps: dict, sector: str):
    """A sector's own cap, or the default, or None. Unknown is never capped."""
    if sector == "unknown":
        return None
    sector_caps = caps.get("max_per_sector", {})
    if sector in sector_caps:
        return sector_caps[sector]
    return sector_caps.get("default")


def _rollup(names: list[dict], book: float, key: str, cap_for) -> list[dict]:
    """Group name values by a key (sector or market) and check each group's cap."""
    totals: dict[str, float] = {}
    for item in names:
        # value_inr was rounded in place above; use it as the grouped value.
        totals[item[key]] = totals.get(item[key], 0.0) + item["value_inr"]

    groups: list[dict] = []
    for name, value in totals.items():
        weight = value / book if book > EPSILON else 0.0
        cap = cap_for(name)
        breach = cap is not None and weight > cap
        groups.append({
            key: name,
            "value_inr": round(value, 2),
            "weight": round(weight, 4),
            "cap": cap,
            "breach": breach,
            "overage_inr": round(value - cap * book, 2) if breach else 0.0,
        })
    groups.sort(key=lambda group: group["weight"], reverse=True)
    return groups


# --- readable report -------------------------------------------------------

def format_report(report: dict) -> str:
    """A plain-text table of the snapshot for standard output."""
    lines: list[str] = []
    lines.append(f"Concentration snapshot as of {report['as_of']}")
    if report["stale"]:
        lines.append("  WARNING: a price or the exchange rate is more than 7 days old.")
    lines.append(f"  Book value: INR {report['book_value_inr']:,.2f}")
    lines.append(
        f"  Holdings: INR {report['holdings_value_inr']:,.2f}   "
        f"Cash: INR {report['cash_value_inr']:,.2f} ({report['cash_weight'] * 100:.1f}%)"
    )

    lines.append("")
    lines.append("Names (by weight):")
    for item in report["names"]:
        mark = "  BREACH" if item["breach"] else ""
        line = (
            f"  {item['ticker']:<10} {item['market']:<6} {item['sector']:<16} "
            f"{item['weight'] * 100:6.2f}%"
        )
        if item["cap"] is not None:
            line += f"  cap {item['cap'] * 100:.0f}%"
        if item["breach"]:
            line += f"  trim INR {item['trim_inr']:,.0f} ({item['trim_shares']:g} sh)"
        lines.append(line + mark)

    lines.append("")
    lines.append("Sectors (by weight):")
    for group in report["sectors"]:
        _append_group(lines, group, "sector")

    lines.append("")
    lines.append("Markets (by weight):")
    for group in report["markets"]:
        _append_group(lines, group, "market")

    if report["data_gaps"]:
        lines.append("")
        lines.append("Data gaps (add ticker + sector to the holding's _meta.yaml):")
        for gap in report["data_gaps"]:
            lines.append(f"  {gap}")

    return "\n".join(lines)


def _append_group(lines: list[str], group: dict, key: str) -> None:
    mark = "  BREACH" if group["breach"] else ""
    line = f"  {group[key]:<16} {group['weight'] * 100:6.2f}%"
    if group["cap"] is not None:
        line += f"  cap {group['cap'] * 100:.0f}%"
    if group["breach"]:
        line += f"  over by INR {group['overage_inr']:,.0f}"
    lines.append(line + mark)


# --- network fetch layer (only used by the command-line run) ---------------

def build_price_book(
    positions: dict[tuple[str, str], float],
) -> dict[tuple[str, str], Series]:
    """Fetch a price history for each open position, keyed by (market, ticker)."""
    book: dict[tuple[str, str], Series] = {}
    for (market, ticker), shares in sorted(positions.items()):
        if shares <= EPSILON:
            continue
        points = _closes_for_holding(market, ticker)
        if not points:
            raise LookupError(f"no price history found for {ticker} ({market})")
        book[(market, ticker)] = Series(points)
    return book


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Veda concentration snapshot.")
    parser.add_argument("--file", type=Path, default=DEFAULT_LEDGER, help="ledger file")
    parser.add_argument("--caps", type=Path, default=DEFAULT_CAPS, help="caps config file")
    parser.add_argument("--holdings", type=Path, default=DEFAULT_HOLDINGS, help="holdings folder")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="snapshot output file")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="snapshot date YYYY-MM-DD")
    args = parser.parse_args(argv)

    if not args.file.exists():
        print(f"ledger file not found: {args.file}", file=sys.stderr)
        return 2

    try:
        transactions = load(args.file)
        if not transactions:
            print("ledger is empty; nothing to value", file=sys.stderr)
            return 1
        caps = load_caps(args.caps)
        sector_map = build_sector_map(args.holdings)
        positions, _ = current_positions(transactions, args.as_of)
        prices = build_price_book(positions)
        fx = Series(_fetch_closes(FX_TICKER))
        report = build_report(transactions, prices, fx, sector_map, caps, args.as_of)
    except (ValueError, LookupError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(format_report(report))
    print(f"\nwrote snapshot to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
