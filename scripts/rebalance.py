"""
Veda - rebalancing proposal.

Turns the transaction ledger and your target weights into a list of trades that
would move the book toward those targets. It proposes; it never places or stages
a trade. A person reads the proposal, edits it, and only then acts.

See internal/rebalance-schema.md for the full contract.

A target weight is the share of the whole book value (all holdings plus all
cash) you want a name to hold - the same denominator the caps use. For each held
name the proposal compares the current weight to the target, skips the name if
the gap is inside the no-trade band, and otherwise proposes a buy or a sell to
close the gap. India trades round to whole shares; US trades may be fractional.
A sell never exceeds the shares held. A held name with no target is a data gap,
never a trade.

The arithmetic core (build_proposal) takes prices, the exchange rate, the sector
map, and the caps as plain arguments, so tests feed fixed numbers and never
touch the network. Only the command-line run fetches from yfinance.

Examples (from a terminal in the Veda-advisor folder):

    python scripts/rebalance.py --setup     # friendly first-time rule setup
    python scripts/rebalance.py
    python scripts/rebalance.py --as-of 2026-03-31

Exit codes:
    0 - proposal written (whether or not any trade is proposed)
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
from nav import FX_TICKER, Series, _fetch_closes
from concentration import (
    EPSILON,
    STALENESS_DAYS,
    _closes_for_holding,
    build_price_book,
    build_sector_map,
    current_positions,
    load_caps,
)

# Repo root is the parent of scripts/.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CAPS = REPO_ROOT / "user-config" / "caps.json"
DEFAULT_HOLDINGS = REPO_ROOT / "holdings"
DEFAULT_OUT = REPO_ROOT / "rebalance" / "proposal.json"

TOLERANCE = 1e-9          # Small slack so a target exactly on a cap is not a breach.
ALLOCATION_TOLERANCE = 0.005   # Allow targets to sum within half a percent of 100%.

# Sensible starting rules for someone who has not set their own. Plain-language
# meaning is in run_setup() and internal/rebalance-schema.md.
DEFAULT_RULES = {
    "max_per_stock": 0.10,                          # most in any one stock
    "max_per_country": {"india": 0.70, "us": 0.50}, # most in Indian / US stocks
    "max_per_sector": {"default": 0.30},            # most in any one sector
    "ignore_drift_below": 0.02,                     # ignore differences smaller than this
}


# --- friendly guided setup -------------------------------------------------

def _parse_percent(text: str, default: float) -> float:
    """Read a percent the way a person would type it: 10, 10%, or 0.10.

    Blank input keeps the default. A number above 1 is read as a percent
    (10 -> 0.10); a number at or below 1 is read as a fraction already.
    """
    text = text.strip().rstrip("%").strip()
    if not text:
        return default
    value = float(text)
    if value < 0:
        raise ValueError("a percent cannot be negative")
    fraction = value / 100 if value > 1 else value
    if fraction > 1:
        raise ValueError("a percent cannot be more than 100")
    return round(fraction, 4)


def _ask_percent(prompt: str, default: float) -> float:
    """Ask one percent question, re-asking until the answer is valid."""
    while True:
        raw = input(f"{prompt}\n  [{default * 100:.0f}%]: ")
        try:
            return _parse_percent(raw, default)
        except ValueError as error:
            print(f"  (couldn't read that - {error}. try a number like 10)")


def run_setup(caps_path: Path) -> int:
    """Walk a brand-new user through their rebalance rules in plain language.

    Every question shows a default in brackets; pressing Enter keeps it. The
    user can also accept all defaults at once. Any target weights already in the
    file are preserved untouched. Writes user-config/caps.json and returns 0.
    """
    existing = json.loads(caps_path.read_text(encoding="utf-8")) if caps_path.exists() else {}

    print("Veda rebalance setup")
    print("--------------------")
    print("These rules decide when Veda suggests buying or selling to keep your")
    print("portfolio balanced. You can change them any time by running this again.")
    print()

    try:
        choice = input(
            "Set the rules yourself, or use sensible defaults?\n"
            "  Type 'setup' to choose, or press Enter to use defaults: "
        ).strip().lower()
    except EOFError:
        choice = ""

    rules = dict(DEFAULT_RULES)
    if choice in ("setup", "s", "yes", "y"):
        print("\nPress Enter on any question to keep the default in brackets.\n")
        try:
            rules["max_per_stock"] = _ask_percent(
                "1. Most in any one stock - the largest share a single stock may be.",
                DEFAULT_RULES["max_per_stock"],
            )
            rules["max_per_country"] = {
                "india": _ask_percent(
                    "2. Most in Indian stocks together.", DEFAULT_RULES["max_per_country"]["india"]
                ),
                "us": _ask_percent(
                    "3. Most in US stocks together.", DEFAULT_RULES["max_per_country"]["us"]
                ),
            }
            rules["max_per_sector"] = {
                "default": _ask_percent(
                    "4. Most in any one sector (banks, tech, and so on).",
                    DEFAULT_RULES["max_per_sector"]["default"],
                )
            }
            rules["ignore_drift_below"] = _ask_percent(
                "5. Ignore-small-differences band - we won't suggest a trade if a\n"
                "   stock is already within this much of its target. Stops churning\n"
                "   over tiny amounts.",
                DEFAULT_RULES["ignore_drift_below"],
            )
        except EOFError:
            print("\n(no input available - keeping defaults)")
            rules = dict(DEFAULT_RULES)
    else:
        print("\nUsing sensible defaults. You can fine-tune them later by running")
        print("  python scripts/rebalance.py --setup")

    # Keep any target weights the user already set; start empty otherwise.
    targets = existing.get("target_weights", existing.get("targets", {"india": {}, "us": {}}))

    caps = {}
    # Keep the _about header at the top of the file if it is already there.
    if existing.get("_about") is not None:
        caps["_about"] = existing["_about"]
    caps.update({
        "max_per_stock": rules["max_per_stock"],
        "max_per_country": rules["max_per_country"],
        "max_per_sector": rules["max_per_sector"],
        "ignore_drift_below": rules["ignore_drift_below"],
        "target_weights": targets,
    })

    caps_path.parent.mkdir(parents=True, exist_ok=True)
    caps_path.write_text(json.dumps(caps, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\nYour rebalance rules:")
    print(f"  Most in any one stock:   {caps['max_per_stock'] * 100:.0f}%")
    print(f"  Most in Indian stocks:   {caps['max_per_country']['india'] * 100:.0f}%")
    print(f"  Most in US stocks:       {caps['max_per_country']['us'] * 100:.0f}%")
    print(f"  Most in any one sector:  {caps['max_per_sector']['default'] * 100:.0f}%")
    print(f"  Ignore differences under {caps['ignore_drift_below'] * 100:.0f}%")
    print(f"\nSaved to {caps_path}")
    print("\nNext: pick a target weight for each stock you want to hold. Not sure what")
    print("the targets should be? That's exactly what Veda is for - ask it to help you")
    print("research a stock and decide how much to hold. You can also track stocks you")
    print("don't own yet in your watchlist (assets.md), then set targets for them when")
    print("you're ready. Once targets are set, run:")
    print("  python scripts/rebalance.py")
    print("to see suggested trades.")
    return 0


# --- reading targets and the band from the caps file -----------------------

def load_caps_with_targets(path: Path) -> dict:
    """Read user-config/caps.json and fill in the rebalancing defaults if absent."""
    caps = load_caps(path)
    caps.setdefault("target_weights", {})
    caps.setdefault("ignore_drift_below", 0.0)
    return caps


def normalise_targets(caps: dict) -> dict[tuple[str, str], float]:
    """Flatten the caps target_weights block into a map of (market, ticker) -> fraction.

    The target_weights block is grouped by market then ticker. Markets are
    lowercased and tickers uppercased so the keys match the held positions. The
    `cash` key is not a position and is read separately by cash_target_weight.
    """
    flat: dict[tuple[str, str], float] = {}
    for market, names in caps.get("target_weights", {}).items():
        if market.strip().lower() == "cash":
            continue
        normalised_market = market.strip().lower()
        for ticker, fraction in names.items():
            flat[(normalised_market, ticker.strip().upper())] = float(fraction)
    return flat


def cash_target_weight(caps: dict) -> Optional[float]:
    """The target weight set for cash, or None when no cash target is set.

    Cash is a target line like any stock: `target_weights.cash` is the share of
    the book you want to hold in cash. When it is unset, cash is whatever the
    stock trades leave over.
    """
    raw = caps.get("target_weights", {}).get("cash")
    return float(raw) if raw is not None else None


def add_watchlist_prices(prices: dict, caps: dict, positions: dict) -> None:
    """Fetch prices for target names that are not currently held (watchlist names).

    A target set for a stock you do not own yet should still produce a proposed
    buy. Held names are already priced by build_price_book; this fills in the
    rest. A ticker with no price history (a typo, or an untradeable symbol) is
    skipped quietly - the proposal lists it as an untracked target rather than
    failing the whole run.
    """
    held = {(market, ticker.upper()) for (market, ticker), shares in positions.items()
            if shares > EPSILON}
    for (market, ticker) in normalise_targets(caps):
        if (market, ticker) in held or (market, ticker) in prices:
            continue
        try:
            points = _closes_for_holding(market, ticker)
        except (LookupError, ValueError, OSError):
            points = None
        if points:
            prices[(market, ticker)] = Series(points)


# --- the arithmetic core ---------------------------------------------------

def build_proposal(
    transactions: list[dict],
    prices: dict[tuple[str, str], Series],
    fx: Series,
    sector_map: dict[tuple[str, str], str],
    caps: dict,
    as_of: str,
    staleness_days: int = STALENESS_DAYS,
) -> dict:
    """Build the rebalancing proposal. Pure: every number comes from the arguments.

    prices is keyed by (market, ticker) as stored in the ledger. fx is a Series
    of USD->INR. sector_map maps (market, ticker_upper) -> sector. caps is the
    parsed caps file, including the targets block and the no-trade band.
    """
    positions, cash = current_positions(transactions, as_of)
    rate, fx_age = fx.as_of(as_of)
    ages = [fx_age]
    targets = normalise_targets(caps)
    band = float(caps.get("ignore_drift_below", 0.0) or 0.0)

    # First pass: value each open position in rupees.
    names: list[dict] = []
    held_keys: set[tuple[str, str]] = set()
    for (market, ticker), shares in positions.items():
        if shares <= EPSILON:
            continue
        held_keys.add((market, ticker.upper()))
        series = prices.get((market, ticker))
        if series is None:
            raise LookupError(f"no price for {ticker} ({market})")
        price, age = series.as_of(as_of)
        ages.append(age)
        price_inr = price * rate if market == "us" else price
        names.append({
            "ticker": ticker.upper(),
            "market": market,
            "sector": sector_map.get((market, ticker.upper()), "unknown"),
            "shares": shares,
            "price": price,
            "price_inr": price_inr,
            "value_inr": shares * price_inr,
            "held": True,
        })

    # Watchlist names: a target was set for a stock you do not hold yet. Propose
    # opening the position. If there is no price for it (an untracked ticker),
    # list it as a note instead of crashing the run.
    untracked_targets: list[str] = []
    for (market, ticker) in sorted(targets):
        if (market, ticker) in held_keys:
            continue
        series = prices.get((market, ticker))
        if series is None:
            untracked_targets.append(
                f"{ticker} ({market}): target set but no price yet - track or research it first"
            )
            continue
        price, age = series.as_of(as_of)
        ages.append(age)
        price_inr = price * rate if market == "us" else price
        names.append({
            "ticker": ticker,
            "market": market,
            "sector": sector_map.get((market, ticker), "unknown"),
            "shares": 0.0,
            "price": price,
            "price_inr": price_inr,
            "value_inr": 0.0,
            "held": False,
        })

    cash_inr = cash["INR"] + cash["USD"] * rate
    holdings_inr = sum(item["value_inr"] for item in names)
    book = holdings_inr + cash_inr

    # Second pass: weight, target, and the trade that closes the gap.
    data_gaps: list[str] = []
    total_buy = 0.0
    total_sell = 0.0
    for item in names:
        weight = item["value_inr"] / book if book > EPSILON else 0.0
        item["weight"] = round(weight, 4)
        target = targets.get((item["market"], item["ticker"]))

        if target is None:
            item.update(target=None, target_weight=None, action="hold",
                        trade_shares=0.0, trade_inr=0.0, reason="not set in plan file")
            data_gaps.append(
                f"{item['ticker']} ({item['market']}): missing target weight in user-config/caps.json"
            )
            continue

        item["target"] = target
        item["target_weight"] = round(target, 4)

        if abs(target - weight) < band:
            item.update(action="hold", trade_shares=0.0, trade_inr=0.0, reason="within band")
            continue

        gap_value = target * book - item["value_inr"]      # signed: + buy, - sell
        raw_shares = gap_value / item["price_inr"]          # signed
        if item["market"] == "india":
            traded = float(round(raw_shares))               # whole shares only
        else:
            traded = round(raw_shares, 4)                   # fractional allowed
        if traded < 0 and -traded > item["shares"]:         # never sell more than held
            traded = -item["shares"]

        if abs(traded) <= EPSILON:
            item.update(action="hold", trade_shares=0.0, trade_inr=0.0,
                        reason="rounds to zero shares")
            continue

        trade_inr = traded * item["price_inr"]              # signed
        if traded > 0:
            reason = "below target" if item.get("held", True) else "new position - research first"
            item.update(action="buy", reason=reason)
            total_buy += trade_inr
        else:
            sell_all = abs(-traded - item["shares"]) <= EPSILON
            item.update(action="sell", reason="sell all" if sell_all else "above target")
            total_sell += -trade_inr
        item["trade_shares"] = round(abs(traded), 4)
        item["trade_inr"] = round(abs(trade_inr), 2)

    # Final tidy: round the display numbers and drop the working field.
    for item in names:
        item["value_inr"] = round(item["value_inr"], 2)
        item["price"] = round(item["price"], 4)
        item.pop("price_inr", None)

    net_cash_change = total_sell - total_buy
    resulting_cash = cash_inr + net_cash_change
    cash_warning = None
    if resulting_cash < -TOLERANCE:
        cash_warning = (
            f"the buys need INR {-resulting_cash:,.0f} more than the book holds; "
            "fund them or trim the buys"
        )

    # Cash is a target line like any stock. When a cash target is set, the stock
    # targets plus the cash target must sum to 100% of the book - otherwise some
    # of the book is unallocated (or over-allocated). Surface that as a warning.
    cash_target = cash_target_weight(caps)
    cash_now = cash_inr / book if book > EPSILON else 0.0
    allocation_warning = None
    if cash_target is not None:
        allocated = sum(targets.values()) + cash_target
        if abs(allocated - 1.0) > ALLOCATION_TOLERANCE:
            if allocated > 1.0:
                allocation_warning = (
                    f"your targets add up to {allocated * 100:.1f}% - more than 100%; "
                    "trim a target so your stocks plus cash sum to 100%"
                )
            else:
                allocation_warning = (
                    f"your targets add up to {allocated * 100:.1f}% - less than 100%; "
                    "raise a target so your stocks plus cash sum to 100%"
                )
        if abs(cash_now - cash_target) < band:
            cash_reason = "within band"
        elif cash_now > cash_target:
            cash_reason = "above target - deploy into stocks to reach it"
        else:
            cash_reason = "below target - raise cash to reach it"
    else:
        cash_reason = "no target set - cash is whatever the trades leave"

    cap_warnings = build_cap_warnings(names, caps)

    # Trades first, biggest by rupee value; then holds; then by current weight.
    names.sort(key=lambda item: (
        0 if item["action"] in ("buy", "sell") else 1,
        -(item["trade_inr"] or 0.0),
        -(item["weight"] or 0.0),
    ))

    return {
        "as_of": as_of,
        "book_value_inr": round(book, 2),
        "holdings_value_inr": round(holdings_inr, 2),
        "cash_value_inr": round(cash_inr, 2),
        "cash_weight": round(cash_inr / book, 4) if book > EPSILON else 0.0,
        "cash_target_weight": round(cash_target, 4) if cash_target is not None else None,
        "cash_reason": cash_reason,
        "rebalance_band": band,
        "stale": any(age > staleness_days for age in ages),
        "names": names,
        "totals": {
            "buy_inr": round(total_buy, 2),
            "sell_inr": round(total_sell, 2),
            "net_cash_change_inr": round(net_cash_change, 2),
            "resulting_cash_inr": round(resulting_cash, 2),
            "resulting_cash_weight": round(resulting_cash / book, 4) if book > EPSILON else 0.0,
        },
        "cap_warnings": cap_warnings,
        "cash_warning": cash_warning,
        "allocation_warning": allocation_warning,
        "data_gaps": data_gaps,
        "untracked_targets": untracked_targets,
        "scope_note": (
            "This rebalance covers the stocks you hold, plus any stock you have set a "
            "target for in user-config/caps.json (including watchlist names you want to "
            "start buying). It does not pick stocks for you - decide what to track and "
            "what the target should be with Veda first."
        ),
    }


def build_cap_warnings(names: list[dict], caps: dict) -> list[str]:
    """Flag any configured target that asks for more than a cap allows.

    Checks the single-name cap per held name, and the sector and market caps
    against the summed targets of the held names. Names with no target, and the
    unknown sector, are skipped: a missing target or sector is a data gap, not a
    cap breach.
    """
    warnings: list[str] = []
    single = caps.get("max_per_stock")
    sector_totals: dict[str, float] = {}
    market_totals: dict[str, float] = {}

    for item in names:
        target = item["target"]
        if target is None:
            continue
        if single is not None and target > single + TOLERANCE:
            warnings.append(
                f"{item['ticker']} target {target * 100:.1f}% is above "
                f"your per-stock limit of {single * 100:.0f}%"
            )
        if item["sector"] != "unknown":
            sector_totals[item["sector"]] = sector_totals.get(item["sector"], 0.0) + target
        market_totals[item["market"]] = market_totals.get(item["market"], 0.0) + target

    sector_caps = caps.get("max_per_sector", {})
    for sector, total in sector_totals.items():
        cap = sector_caps.get(sector, sector_caps.get("default"))
        if cap is not None and total > cap + TOLERANCE:
            warnings.append(
                f"sector {sector} targets sum to {total * 100:.1f}%, "
                f"above its cap {cap * 100:.0f}%"
            )

    market_caps = caps.get("max_per_country", {})
    for market, total in market_totals.items():
        cap = market_caps.get(market)
        if cap is not None and total > cap + TOLERANCE:
            warnings.append(
                f"market {market} targets sum to {total * 100:.1f}%, "
                f"above its cap {cap * 100:.0f}%"
            )

    return warnings


# --- readable report -------------------------------------------------------

def format_report(report: dict) -> str:
    """A plain-text table of the proposal for standard output."""
    lines: list[str] = []
    lines.append(f"Rebalancing proposal as of {report['as_of']}")
    if report["stale"]:
        lines.append("  WARNING: a price or the exchange rate is more than 7 days old.")
    lines.append(f"  Book value: INR {report['book_value_inr']:,.2f}")
    cash_target = report.get("cash_target_weight")
    cash_line = (
        f"  Holdings: INR {report['holdings_value_inr']:,.2f}   "
        f"Cash: INR {report['cash_value_inr']:,.2f} ({report['cash_weight'] * 100:.1f}%)"
    )
    if cash_target is not None:
        cash_line += f"  target {cash_target * 100:.1f}%"
    lines.append(cash_line)
    lines.append(f"  No-trade band: {report['rebalance_band'] * 100:.1f}% of book")

    lines.append("")
    lines.append("Proposed trades:")
    lines.append(
        f"  {'name':<10} {'market':<6} {'now':>7} {'target':>7} "
        f"{'action':<6} {'shares':>10} {'INR':>14}  reason"
    )
    for item in report["names"]:
        target = f"{item['target_weight'] * 100:.1f}%" if item["target_weight"] is not None else "-"
        shares = f"{item['trade_shares']:g}" if item["action"] != "hold" else "-"
        amount = f"{item['trade_inr']:,.0f}" if item["action"] != "hold" else "-"
        lines.append(
            f"  {item['ticker']:<10} {item['market']:<6} {item['weight'] * 100:6.1f}% "
            f"{target:>7} {item['action']:<6} {shares:>10} {amount:>14}  {item['reason']}"
        )
    # Cash is shown as its own line, a position like any other.
    cash_target_str = f"{cash_target * 100:.1f}%" if cash_target is not None else "-"
    lines.append(
        f"  {'CASH':<10} {'-':<6} {report['cash_weight'] * 100:6.1f}% "
        f"{cash_target_str:>7} {'-':<6} {'-':>10} {'-':>14}  {report['cash_reason']}"
    )

    totals = report["totals"]
    lines.append("")
    lines.append("Totals:")
    lines.append(f"  Buy:  INR {totals['buy_inr']:,.2f}")
    lines.append(f"  Sell: INR {totals['sell_inr']:,.2f}")
    lines.append(
        f"  Cash after: INR {totals['resulting_cash_inr']:,.2f} "
        f"({totals['resulting_cash_weight'] * 100:.1f}%)"
    )

    if report["cap_warnings"]:
        lines.append("")
        lines.append("Cap warnings (a target asks for more than a cap allows):")
        for warning in report["cap_warnings"]:
            lines.append(f"  {warning}")

    if report["cash_warning"]:
        lines.append("")
        lines.append(f"Cash warning: {report['cash_warning']}")

    if report.get("allocation_warning"):
        lines.append("")
        lines.append(f"Allocation warning: {report['allocation_warning']}")

    if report["data_gaps"]:
        lines.append("")
        lines.append("These stocks are in your portfolio but missing from user-config/caps.json:")
        lines.append("  add a target weight for each one")
        for gap in report["data_gaps"]:
            lines.append(f"  {gap}")

    if report.get("untracked_targets"):
        lines.append("")
        lines.append("Targets set for stocks you don't hold yet, but with no price found:")
        for note in report["untracked_targets"]:
            lines.append(f"  {note}")

    lines.append("")
    lines.append("Scope: we rebalance the stocks you hold, plus any stock you've set a target")
    lines.append("  for in user-config/caps.json - including watchlist names you want to start")
    lines.append("  buying. We don't pick stocks for you. To add a new name, ask Veda to help")
    lines.append("  research it and decide a target, then set that target here.")

    return "\n".join(lines)


# --- command-line run (the only part that fetches) -------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Veda rebalancing proposal.")
    parser.add_argument("--file", type=Path, default=DEFAULT_LEDGER, help="ledger file")
    parser.add_argument("--caps", type=Path, default=DEFAULT_CAPS, help="caps config file")
    parser.add_argument("--holdings", type=Path, default=DEFAULT_HOLDINGS, help="holdings folder")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="proposal output file")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="proposal date YYYY-MM-DD")
    parser.add_argument("--setup", action="store_true",
                        help="friendly guided setup of your rebalance rules, then exit")
    args = parser.parse_args(argv)

    if args.setup:
        return run_setup(args.caps)

    if not args.file.exists():
        print(f"ledger file not found: {args.file}", file=sys.stderr)
        return 2

    try:
        transactions = load(args.file)
        if not transactions:
            print("ledger is empty; nothing to rebalance", file=sys.stderr)
            return 1
        caps = load_caps_with_targets(args.caps)
        sector_map = build_sector_map(args.holdings)
        positions, _ = current_positions(transactions, args.as_of)
        prices = build_price_book(positions)
        add_watchlist_prices(prices, caps, positions)
        fx = Series(_fetch_closes(FX_TICKER))
        report = build_proposal(transactions, prices, fx, sector_map, caps, args.as_of)
    except (ValueError, LookupError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(format_report(report))
    print(f"\nwrote proposal to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
