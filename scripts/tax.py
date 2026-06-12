"""
Veda - capital-gains tax awareness and optimization.

Reads the transaction ledger and reports the book's Indian capital-gains tax
position three ways:
  1. Realized this financial year, and under which rule (the holding clock and
     the short-term / long-term split decide the rate).
  2. Unrealized in each open lot, with how many days until it turns long-term.
  3. What moves would lower the tax out-go: harvest a loss against a realized
     gain, or wait for a lot to cross the long-term clock.

The user is an Indian resident, so BOTH the India sleeve and the US sleeve are
taxed under Indian rules. See internal/tax-schema.md for the full contract and
internal/tax-rules.yaml for the dated rates and clocks.

Two views of cost basis are produced. The headline matches each sell to the
oldest open lot first (FIFO, the usual Indian demat default). A cross-check
matches each sell to the specific lot its ledger line names. Where they differ,
the report says so.

This module is awareness, not filing. It is not a chartered accountant. The
rates are sourced (see tax-rules.yaml) but not CA-signed-off; verify before
acting or filing. No LLM does the arithmetic (SKILL.md Hard Rule #8) - every
number below comes from this script.

The arithmetic core (build_report) takes prices, the exchange rate, and the
parsed rules as plain arguments, so tests feed fixed numbers and never touch
the network. Only the command-line run fetches from yfinance.

Examples (from a terminal in the Veda-advisor folder):

    python scripts/tax.py
    python scripts/tax.py --as-of 2026-06-11 --fy 2026-2027
    python scripts/tax.py --slab-rate 0.30      # to tax US short-term gains

Exit codes:
    0 - report written
    1 - could not compute (bad ledger, empty ledger); reason on stderr
    2 - ledger file missing
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

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
DEFAULT_OUT = REPO_ROOT / "tax" / "tax-report.json"
DEFAULT_RULES = REPO_ROOT / "internal" / "tax-rules.yaml"

STALENESS_DAYS = 7        # A price older than this, for the date asked, is stale.
EPSILON = 1e-9            # Shares or rupees at or below this are treated as zero.

# The four rate buckets a disposal can land in. The sleeve sets the rate; the
# short-term / long-term character sets both the rate and the set-off rules.
BUCKETS = ("india_short_term", "india_long_term", "foreign_short_term", "foreign_long_term")

# Set-off matrix (Income Tax Act Section 74) - fixed law, not a tunable rate:
#   a short-term loss offsets short-term AND long-term gains;
#   a long-term loss offsets long-term gains only;
#   a gain is never carried forward - it is taxed in the year it is booked.
# Within a financial year and across carried-forward losses, this engine offsets
# the highest-taxed gain first, which is the tax-minimizing order the Act allows.


# --- reading the rules table -----------------------------------------------

def load_rules(path: Path = DEFAULT_RULES) -> dict:
    """Read internal/tax-rules.yaml with a small stdlib parser (no PyYAML).

    Shape: top-level blocks (india_listed_equity, foreign_equity_resident,
    general), each followed by indented `key: value` lines. Matches the
    portability discipline of scripts/validate_assumptions.py.
    """
    rules: dict[str, dict] = {}
    current: Optional[dict] = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw.startswith((" ", "\t")):          # a top-level block header
            key = raw.split(":", 1)[0].strip()
            current = {}
            rules[key] = current
            continue
        if current is None or ":" not in raw:
            continue
        key, value = raw.strip().split(":", 1)
        current[key.strip()] = _parse_scalar(value.strip())
    return rules


def _parse_scalar(text: str):
    """Turn a YAML scalar into int / float / bool / None / str."""
    if len(text) >= 2 and text[0] in ("'", '"') and text[-1] == text[0]:
        return text[1:-1]
    if "#" in text:                                   # drop an inline comment
        text = text.split("#", 1)[0].strip()
    lowered = text.lower()
    if lowered in ("null", "~", ""):
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return text


# --- date and financial-year helpers ---------------------------------------

def _to_date(day: str) -> date:
    year, month, dom = (int(part) for part in day.split("-"))
    return date(year, month, dom)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def _add_months(start: date, months: int) -> date:
    """Add whole calendar months, clamping the day to the month's length."""
    index = start.month - 1 + months
    year = start.year + index // 12
    month = index % 12 + 1
    return date(year, month, min(start.day, _days_in_month(year, month)))


def _is_long_term(acquired: str, sold_on: str, months: int) -> bool:
    """Long-term when held strictly more than `months` months."""
    return _to_date(sold_on) > _add_months(_to_date(acquired), months)


def _first_long_term_date(acquired: str, months: int) -> date:
    """The first date on which a sale would count as long-term."""
    return _add_months(_to_date(acquired), months) + timedelta(days=1)


def financial_year(day: str) -> str:
    """The Indian financial year (1 April - 31 March) a date falls in, like 2026-2027."""
    moment = _to_date(day)
    start = moment.year if moment.month >= 4 else moment.year - 1
    return f"{start}-{start + 1}"


def _id_number(tx: dict) -> int:
    tx_id = tx.get("id", "")
    if tx_id.startswith("tx-"):
        try:
            return int(tx_id[3:])
        except ValueError:
            return 0
    return 0


def _term(bucket: str) -> str:
    return "short_term" if bucket.endswith("short_term") else "long_term"


def _bucket(market: str, long_term: bool) -> str:
    sleeve = "india" if market == "india" else "foreign"
    return f"{sleeve}_{'long_term' if long_term else 'short_term'}"


def _regime(rules: dict, market: str) -> dict:
    return rules["india_listed_equity"] if market == "india" else rules["foreign_equity_resident"]


def _bucket_rate(bucket: str, rules: dict, slab_rate: Optional[float]) -> Optional[float]:
    """The tax rate for a bucket. Foreign short-term is the slab rate (may be None)."""
    if bucket == "india_short_term":
        return rules["india_listed_equity"]["short_term_rate"]
    if bucket == "india_long_term":
        return rules["india_listed_equity"]["long_term_rate"]
    if bucket == "foreign_long_term":
        return rules["foreign_equity_resident"]["long_term_rate"]
    return slab_rate          # foreign_short_term, taxed at the user's income slab


# --- replaying the ledger into tax lots and disposals ----------------------

def replay_lots(
    transactions: list[dict],
    as_of: str,
    long_term_months_for: Callable[[str], int],
    match: str = "fifo",
) -> tuple[list[dict], list[dict], list[str]]:
    """Replay buys / sells / splits / bonuses into realized disposals + open lots.

    match="fifo" draws the oldest open lot first (the headline view).
    match="named" draws the lot whose id the sell names (the cross-check).

    Returns (disposals, open_lots, notes). Each disposal is one matched chunk
    with its acquired date, sold date, shares, native cost and proceeds, the
    native gain, and whether it is long-term. Cash and dividends do not affect
    cost basis, so they are ignored here.
    """
    books: dict[tuple[str, str], list[dict]] = {}
    disposals: list[dict] = []
    notes: list[str] = []
    bonus_events = 0

    ordered = sorted(
        (tx for tx in transactions if tx["date"] <= as_of),
        key=lambda tx: (tx["date"], _id_number(tx)),
    )
    for tx in ordered:
        kind = tx["type"]
        if kind == "buy":
            key = (tx["market"], tx["ticker"])
            shares = float(tx["shares"])
            total_cost = shares * float(tx["price"]) + float(tx.get("fees", 0.0))
            books.setdefault(key, []).append({
                "lot_id": tx.get("lot_id", ""),
                "market": tx["market"],
                "ticker": tx["ticker"],
                "currency": tx.get("currency", "INR"),
                "acquired": tx["date"],
                "shares": shares,
                "cost_per_share": total_cost / shares if shares else 0.0,
                "origin": "buy",
            })
        elif kind == "sell":
            key = (tx["market"], tx["ticker"])
            lots = books.get(key, [])
            quantity = float(tx["shares"])
            if quantity <= EPSILON:
                continue
            proceeds_per_share = (quantity * float(tx["price"]) - float(tx.get("fees", 0.0))) / quantity
            months = long_term_months_for(tx["market"])
            for lot, taken in _pick_lots(lots, quantity, tx.get("lot_id"), match):
                disposals.append({
                    "market": tx["market"],
                    "ticker": tx["ticker"],
                    "currency": tx.get("currency", "INR"),
                    "sold_on": tx["date"],
                    "acquired": lot["acquired"],
                    "shares": taken,
                    "proceeds_native": taken * proceeds_per_share,
                    "cost_native": taken * lot["cost_per_share"],
                    "gain_native": taken * (proceeds_per_share - lot["cost_per_share"]),
                    "long_term": _is_long_term(lot["acquired"], tx["date"], months),
                })
                lot["shares"] -= taken
            books[key] = [lot for lot in lots if lot["shares"] > EPSILON]
        elif kind == "split":
            factor = split_factor(tx["ratio"])
            for lot in books.get((tx["market"], tx["ticker"]), []):
                lot["shares"] *= factor               # total cost unchanged, date kept
                lot["cost_per_share"] /= factor
        elif kind == "bonus":
            key = (tx["market"], tx["ticker"])
            held = sum(lot["shares"] for lot in books.get(key, []))
            extra = held * (bonus_factor(tx["ratio"]) - 1.0)
            if extra > EPSILON:
                books.setdefault(key, []).append({
                    "lot_id": f"{tx['ticker'].lower()}-bonus-{tx['date']}",
                    "market": tx["market"],
                    "ticker": tx["ticker"],
                    "currency": tx.get("currency", "INR"),
                    "acquired": tx["date"],            # holding clock starts at allotment
                    "shares": extra,
                    "cost_per_share": 0.0,             # nil cost, Section 55(2)(aa)
                    "origin": "bonus",
                })
                bonus_events += 1

    if bonus_events:
        notes.append(
            f"{bonus_events} bonus event(s): bonus shares are treated as nil cost with the "
            "holding clock starting at allotment (Section 55(2)(aa)). Verify with a CA."
        )
    open_lots = [lot for lots in books.values() for lot in lots if lot["shares"] > EPSILON]
    return disposals, open_lots, notes


def _pick_lots(lots: list[dict], quantity: float, named_id, match: str) -> list[tuple[dict, float]]:
    """Choose which lots a sell draws from, returning [(lot, shares_taken), ...].

    fifo draws the oldest lot first. named draws the lot whose id matches first,
    then falls back to oldest-first for any shortfall (a stable sort keeps the
    remaining lots in acquisition order).
    """
    if match == "named" and named_id:
        order = sorted(lots, key=lambda lot: lot["lot_id"] != named_id)
    else:
        order = lots                                   # already oldest-first
    picks: list[tuple[dict, float]] = []
    remaining = quantity
    for lot in order:
        if remaining <= EPSILON:
            break
        take = min(lot["shares"], remaining)
        if take > EPSILON:
            picks.append((lot, take))
            remaining -= take
    return picks


def _price_disposals_in_inr(disposals: list[dict], fx: Series) -> tuple[list[dict], int]:
    """Add cost_inr / proceeds_inr / gain_inr / bucket to each disposal.

    India is already in rupees. For US disposals the cost is converted at the
    buy-date rate and the proceeds at the sell-date rate - the documented
    convention, pending CA confirmation. Returns (disposals, max_fx_age).
    """
    ages = [0]
    for item in disposals:
        if item["market"] == "us":
            buy_rate, buy_age = fx.as_of(item["acquired"])
            sell_rate, sell_age = fx.as_of(item["sold_on"])
            ages += [buy_age, sell_age]
            item["cost_inr"] = item["cost_native"] * buy_rate
            item["proceeds_inr"] = item["proceeds_native"] * sell_rate
        else:
            item["cost_inr"] = item["cost_native"]
            item["proceeds_inr"] = item["proceeds_native"]
        item["gain_inr"] = item["proceeds_inr"] - item["cost_inr"]
        item["bucket"] = _bucket(item["market"], item["long_term"])
    return disposals, max(ages)


# --- realized gains: set-off and carry-forward across financial years -------

def _net_by_financial_year(disposals: list[dict]) -> dict[str, dict[str, float]]:
    """{financial_year: {bucket: net_gain_inr}}, netting gains and losses per bucket."""
    by_year: dict[str, dict[str, float]] = {}
    for item in disposals:
        year = financial_year(item["sold_on"])
        buckets = by_year.setdefault(year, {})
        buckets[item["bucket"]] = buckets.get(item["bucket"], 0.0) + item["gain_inr"]
    return by_year


def _short_term_gain_order(slab_rate: Optional[float]) -> list[str]:
    """Gains a short-term loss may offset, highest tax first (so the saving is biggest).

    Long-term gains come foreign-first so the India long-term exemption is
    preserved for last.
    """
    if slab_rate is not None and slab_rate > 0.20:
        short = ["foreign_short_term", "india_short_term"]
    else:
        short = ["india_short_term", "foreign_short_term"]
    return short + ["foreign_long_term", "india_long_term"]


def _apply_loss(amount: float, order: list[str], gains: dict[str, float], log: list[dict], loss_term: str) -> float:
    """Reduce gains in `order` by up to `amount`. Returns the leftover loss."""
    for bucket in order:
        if amount <= EPSILON:
            break
        available = gains.get(bucket, 0.0)
        if available <= EPSILON:
            continue
        used = min(amount, available)
        gains[bucket] = available - used
        amount -= used
        log.append({"loss_term": loss_term, "reduced_bucket": bucket, "amount_inr": round(used, 2)})
    return amount


def _tax_on_gains(gains: dict[str, float], rules: dict, slab_rate: Optional[float]) -> tuple[float, float]:
    """Tax in rupees on positive gains per bucket, applying the India long-term
    exemption. Returns (tax_inr, foreign_short_term_gain_with_unknown_slab_inr).
    """
    tax = 0.0
    unknown_slab_gain = 0.0
    for bucket, gain in gains.items():
        if gain <= EPSILON:
            continue
        if bucket == "india_long_term":
            exemption = rules["india_listed_equity"]["long_term_exemption_inr"]
            tax += max(0.0, gain - exemption) * rules["india_listed_equity"]["long_term_rate"]
        elif bucket == "india_short_term":
            tax += gain * rules["india_listed_equity"]["short_term_rate"]
        elif bucket == "foreign_long_term":
            tax += gain * rules["foreign_equity_resident"]["long_term_rate"]
        else:                                          # foreign_short_term, at slab
            if slab_rate is None:
                unknown_slab_gain += gain
            else:
                tax += gain * slab_rate
    return tax, unknown_slab_gain


def _run_one_year(
    buckets: dict[str, float],
    carried_short_loss: float,
    carried_long_loss: float,
    rules: dict,
    slab_rate: Optional[float],
) -> dict:
    """Set off losses against gains for one financial year and compute the tax."""
    gains = {bucket: value for bucket, value in buckets.items() if value > EPSILON}
    current_short_loss = -sum(min(0.0, v) for b, v in buckets.items() if _term(b) == "short_term")
    current_long_loss = -sum(min(0.0, v) for b, v in buckets.items() if _term(b) == "long_term")

    short_loss = current_short_loss + carried_short_loss
    long_loss = current_long_loss + carried_long_loss

    gross_tax, _ = _tax_on_gains(gains, rules, slab_rate)

    remaining = dict(gains)
    log: list[dict] = []
    long_loss = _apply_loss(long_loss, ["foreign_long_term", "india_long_term"], remaining, log, "long_term")
    short_loss = _apply_loss(short_loss, _short_term_gain_order(slab_rate), remaining, log, "short_term")

    net_tax, unknown_slab_gain = _tax_on_gains(remaining, rules, slab_rate)

    return {
        "buckets": {bucket: round(value, 2) for bucket, value in buckets.items()},
        "carried_in": {
            "short_term_loss": round(carried_short_loss, 2),
            "long_term_loss": round(carried_long_loss, 2),
        },
        "set_offs": log,
        "taxable_gain": {bucket: round(value, 2) for bucket, value in remaining.items() if value > EPSILON},
        "_taxable_gain_raw": {bucket: value for bucket, value in remaining.items() if value > EPSILON},
        "tax_inr": round(net_tax, 2),
        "tax_saved_by_set_off_inr": round(gross_tax - net_tax, 2),
        "foreign_short_term_gain_unknown_slab_inr": round(unknown_slab_gain, 2),
        "carried_forward": {
            "short_term_loss": round(short_loss, 2),
            "long_term_loss": round(long_loss, 2),
        },
        "long_term_exemption_inr": rules["india_listed_equity"]["long_term_exemption_inr"],
    }


def _realized_for_year(disposals: list[dict], rules: dict, slab_rate: Optional[float], target_year: str) -> dict:
    """Walk financial years in order, carrying losses forward, and return the
    target year's result (with carried-in losses from every earlier year).
    """
    by_year = _net_by_financial_year(disposals)
    carried_short = 0.0
    carried_long = 0.0
    result = None
    for year in sorted(set(by_year) | {target_year}):
        if year > target_year:
            break
        result = _run_one_year(by_year.get(year, {}), carried_short, carried_long, rules, slab_rate)
        carried_short = result["carried_forward"]["short_term_loss"]
        carried_long = result["carried_forward"]["long_term_loss"]
    result["financial_year"] = target_year
    return result


# --- unrealized lots and the optimization view -----------------------------

def _unrealized_rows(
    open_lots: list[dict],
    prices: dict[tuple[str, str], Series],
    fx: Series,
    long_term_months_for: Callable[[str], int],
    as_of: str,
) -> tuple[list[dict], list[str], int]:
    """One row per open lot: current value, unrealized gain in rupees, whether a
    sale today is long-term, and days until it turns long-term.
    """
    rows: list[dict] = []
    gaps: list[str] = []
    ages = [0]
    for lot in open_lots:
        series = prices.get((lot["market"], lot["ticker"]))
        if series is None:
            gaps.append(f"{lot['ticker']} ({lot['market']}): no current price")
            continue
        price, age = series.as_of(as_of)
        ages.append(age)
        months = long_term_months_for(lot["market"])
        long_now = _is_long_term(lot["acquired"], as_of, months)
        days_to_long = 0 if long_now else max(0, (_first_long_term_date(lot["acquired"], months) - _to_date(as_of)).days)
        if lot["market"] == "us":
            buy_rate, buy_age = fx.as_of(lot["acquired"])
            now_rate, now_age = fx.as_of(as_of)
            ages += [buy_age, now_age]
            cost_inr = lot["cost_per_share"] * lot["shares"] * buy_rate
            value_inr = lot["shares"] * price * now_rate
        else:
            cost_inr = lot["cost_per_share"] * lot["shares"]
            value_inr = lot["shares"] * price
        rows.append({
            "market": lot["market"],
            "ticker": lot["ticker"],
            "acquired": lot["acquired"],
            "origin": lot["origin"],
            "shares": round(lot["shares"], 4),
            "cost_inr": round(cost_inr, 2),
            "value_inr": round(value_inr, 2),
            "gain_inr": round(value_inr - cost_inr, 2),
            "long_term": long_now,
            "days_to_long_term": days_to_long,
            "bucket": _bucket(lot["market"], long_now),
        })
    return rows, gaps, max(ages)


def _offsettable_order(loss_term: str, slab_rate: Optional[float]) -> list[str]:
    """Which gain buckets a loss of this term may offset, best-saving first."""
    if loss_term == "short_term":
        return _short_term_gain_order(slab_rate)
    return ["foreign_long_term", "india_long_term"]


def _optimize(realized: dict, unrealized_rows: list[dict], rules: dict, slab_rate: Optional[float]) -> dict:
    """Build the advice view: which losses to harvest, which lots to hold for the
    long-term rate, and how much room is left under the India long-term exemption.
    """
    exemption = rules["india_listed_equity"]["long_term_exemption_inr"]

    # Gains that actually incur tax this year (after set-off, after the exemption).
    taxable_pool: dict[str, float] = {}
    for bucket, gain in realized.get("_taxable_gain_raw", {}).items():
        amount = max(0.0, gain - exemption) if bucket == "india_long_term" else gain
        if amount > EPSILON:
            taxable_pool[bucket] = amount

    harvest: list[dict] = []
    for lot in sorted((r for r in unrealized_rows if r["gain_inr"] < -EPSILON), key=lambda r: r["gain_inr"]):
        loss = -lot["gain_inr"]
        remaining = loss
        saved = 0.0
        offsets: list[dict] = []
        for bucket in _offsettable_order(_term(lot["bucket"]), slab_rate):
            if remaining <= EPSILON:
                break
            available = taxable_pool.get(bucket, 0.0)
            if available <= EPSILON:
                continue
            used = min(remaining, available)
            rate = _bucket_rate(bucket, rules, slab_rate)
            if rate is None:                           # foreign short-term, slab unknown
                offsets.append({"bucket": bucket, "amount_inr": round(used, 2), "rate": "your slab"})
            else:
                saved += used * rate
                offsets.append({"bucket": bucket, "amount_inr": round(used, 2), "rate": rate})
            taxable_pool[bucket] = available - used
            remaining -= used
        harvest.append({
            "ticker": lot["ticker"],
            "market": lot["market"],
            "bookable_loss_inr": round(loss, 2),
            "loss_term": _term(lot["bucket"]),
            "offsets": offsets,
            "tax_saved_inr": round(saved, 2),
        })
    harvest.sort(key=lambda item: item["tax_saved_inr"], reverse=True)

    wait: list[dict] = []
    for lot in unrealized_rows:
        if lot["gain_inr"] <= EPSILON or lot["long_term"] or not (0 < lot["days_to_long_term"] <= 90):
            continue
        gain = lot["gain_inr"]
        long_rate = _regime(rules, lot["market"])["long_term_rate"]
        tax_long = gain * long_rate
        if lot["market"] == "india":
            tax_now: Optional[float] = gain * rules["india_listed_equity"]["short_term_rate"]
        else:
            tax_now = None if slab_rate is None else gain * slab_rate
        wait.append({
            "ticker": lot["ticker"],
            "market": lot["market"],
            "days_to_long_term": lot["days_to_long_term"],
            "gain_inr": round(gain, 2),
            "tax_if_sold_now_inr": None if tax_now is None else round(tax_now, 2),
            "tax_if_long_term_inr": round(tax_long, 2),
            "saving_inr": None if tax_now is None else round(tax_now - tax_long, 2),
        })
    wait.sort(key=lambda item: (item["saving_inr"] is not None, item["saving_inr"] or 0.0), reverse=True)

    india_long_gain = realized.get("_taxable_gain_raw", {}).get("india_long_term", 0.0)
    headroom = max(0.0, exemption - india_long_gain)

    return {
        "harvest": harvest,
        "wait_for_long_term": wait,
        "india_long_term_exemption_headroom_inr": round(headroom, 2),
    }


def _flag_pre_effective(transactions: list[dict], rules: dict, as_of: str, notes: list[str]) -> None:
    """Note any sale dated before a regime's rates take effect (we do not guess older rates)."""
    effective = {
        "india": rules["india_listed_equity"]["effective_from"],
        "us": rules["foreign_equity_resident"]["effective_from"],
    }
    flagged: set[str] = set()
    for tx in transactions:
        if tx.get("type") != "sell" or tx["date"] > as_of:
            continue
        start = effective.get(tx["market"])
        if start and str(tx["date"]) < str(start) and tx["market"] not in flagged:
            flagged.add(tx["market"])
            notes.append(
                f"A {tx['market']} sale is dated before {start}, when the encoded rules take "
                "effect. Its rate is not in tax-rules.yaml - add the earlier regime or verify with a CA."
            )


# --- the arithmetic core ---------------------------------------------------

def build_report(
    transactions: list[dict],
    prices: dict[tuple[str, str], Series],
    fx: Series,
    rules: dict,
    as_of: str,
    target_year: Optional[str] = None,
    slab_rate: Optional[float] = None,
    staleness_days: int = STALENESS_DAYS,
) -> dict:
    """Build the tax report. Pure: every number comes from the arguments.

    prices is keyed by (market, ticker). fx is a Series of USD->INR. rules is
    the parsed tax-rules.yaml. target_year is the financial year to report (like
    "2026-2027"); it defaults to the year `as_of` falls in. slab_rate is the
    user's marginal income-tax rate, needed only to tax US short-term gains.
    """
    def long_term_months_for(market: str) -> int:
        return int(_regime(rules, market)["long_term_months"])

    year = target_year or financial_year(as_of)
    notes: list[str] = []
    _flag_pre_effective(transactions, rules, as_of, notes)

    # Headline: first-in first-out matching.
    fifo_disposals, open_lots, replay_notes = replay_lots(transactions, as_of, long_term_months_for, "fifo")
    notes += replay_notes
    fifo_disposals, fx_age_realized = _price_disposals_in_inr(fifo_disposals, fx)
    realized = _realized_for_year(fifo_disposals, rules, slab_rate, year)

    # Cross-check: match each sell to the lot its ledger line names.
    named_disposals, _, _ = replay_lots(transactions, as_of, long_term_months_for, "named")
    named_disposals, _ = _price_disposals_in_inr(named_disposals, fx)
    realized_named = _realized_for_year(named_disposals, rules, slab_rate, year)
    cross_check = {
        "fifo_tax_inr": realized["tax_inr"],
        "named_lot_tax_inr": realized_named["tax_inr"],
        "agree": abs(realized["tax_inr"] - realized_named["tax_inr"]) < 0.01,
    }

    unrealized_rows, price_gaps, fx_age_unrealized = _unrealized_rows(
        open_lots, prices, fx, long_term_months_for, as_of
    )
    optimization = _optimize(realized, unrealized_rows, rules, slab_rate)

    target_disposals = [
        {
            "market": d["market"], "ticker": d["ticker"], "sold_on": d["sold_on"],
            "acquired": d["acquired"], "shares": round(d["shares"], 4),
            "cost_inr": round(d["cost_inr"], 2), "proceeds_inr": round(d["proceeds_inr"], 2),
            "gain_inr": round(d["gain_inr"], 2), "long_term": d["long_term"], "bucket": d["bucket"],
        }
        for d in fifo_disposals if financial_year(d["sold_on"]) == year
    ]
    realized = {key: value for key, value in realized.items() if key != "_taxable_gain_raw"}
    realized["disposals"] = target_disposals

    stale = max(fx_age_realized, fx_age_unrealized) > staleness_days

    return {
        "as_of": as_of,
        "financial_year": year,
        "ca_note": (
            "Awareness, not advice from a chartered accountant. Rates are sourced "
            "(internal/tax-rules.yaml) but not CA-signed-off; verify before acting or filing."
        ),
        "fx_note": (
            "US gains converted with cost at the buy-date rate and proceeds at the sell-date "
            "rate. Confirm the rule with a CA."
        ),
        "headline_basis": "FIFO (oldest lot first)",
        "realized": realized,
        "cross_check": cross_check,
        "unrealized": unrealized_rows,
        "optimization": optimization,
        "stale": stale,
        "data_gaps": price_gaps,
        "notes": notes,
    }


# --- network fetch layer (only used by the command-line run) ---------------

def _build_price_book(transactions: list[dict]) -> dict[tuple[str, str], Series]:
    """Fetch daily closes for each held name. Missing histories are skipped and
    surface later as a data gap, so the report still runs.
    """
    held = {(tx["market"], tx["ticker"]) for tx in transactions if tx.get("ticker")}
    book: dict[tuple[str, str], Series] = {}
    for market, ticker in sorted(held):
        points = _closes_for_holding(market, ticker)
        if points:
            book[(market, ticker)] = Series(points)
    return book


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Veda capital-gains tax report.")
    parser.add_argument("--file", type=Path, default=DEFAULT_LEDGER, help="ledger file")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES, help="tax-rules.yaml")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="report output file")
    parser.add_argument("--as-of", dest="as_of", default=date.today().isoformat(), help="valuation date YYYY-MM-DD")
    parser.add_argument("--fy", dest="fy", default=None, help="financial year to report, like 2026-2027")
    parser.add_argument("--slab-rate", dest="slab_rate", type=float, default=None,
                        help="your marginal income-tax rate as a fraction (e.g. 0.30), to tax US short-term gains")
    args = parser.parse_args(argv)

    if not args.file.exists():
        print(f"ledger file not found: {args.file}", file=sys.stderr)
        return 2

    try:
        transactions = load(args.file)
        if not transactions:
            print("ledger is empty; there is no tax position to show yet", file=sys.stderr)
            return 1
        rules = load_rules(args.rules)
        prices = _build_price_book(transactions)
        fx = Series(_fetch_closes(FX_TICKER))
        report = build_report(transactions, prices, fx, rules, args.as_of, args.fy, args.slab_rate)
    except (ValueError, LookupError) as error:
        print(str(error), file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    realized = report["realized"]
    print(f"wrote tax report for FY {report['financial_year']} to {args.out}")
    print(
        f"realized tax (FIFO): Rs {realized['tax_inr']:.2f}; "
        f"set-off saved Rs {realized['tax_saved_by_set_off_inr']:.2f}; "
        f"carried forward: short-term loss Rs {realized['carried_forward']['short_term_loss']:.2f}, "
        f"long-term loss Rs {realized['carried_forward']['long_term_loss']:.2f}"
    )
    if not report["cross_check"]["agree"]:
        print(
            f"note: named-lot basis gives Rs {report['cross_check']['named_lot_tax_inr']:.2f} "
            f"vs FIFO Rs {report['cross_check']['fifo_tax_inr']:.2f}",
            file=sys.stderr,
        )
    if realized["foreign_short_term_gain_unknown_slab_inr"] > 0:
        print(
            f"note: Rs {realized['foreign_short_term_gain_unknown_slab_inr']:.2f} of US short-term gain "
            "is taxed at your slab rate; pass --slab-rate to include it",
            file=sys.stderr,
        )
    if report["data_gaps"]:
        print(f"data gaps: {len(report['data_gaps'])} name(s) without a current price", file=sys.stderr)
    if report["stale"]:
        print("warning: some prices or FX rates used were stale", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
