"""
Veda - portfolio formation.

Turns the research house's covered names into a proposed target-weight book:
which names to back now and how much, which to own but wait on, which to just
watch, and which to skip. It proposes; it never writes your book. A person reads
the proposal, adjusts it, and only then are the targets saved to assets.md.

For each covered name in the research feed (published/manifest.yaml) it reads
three things - the call (Invest / Watch / Avoid), the valuation zone (CHEAP /
FAIR / EXPENSIVE), and how the thesis assumptions are holding - and makes a
first read:

  - back now      : research says buy and the price is right.
  - own but wait  : research says buy, but wait for a better price (a dear zone,
                    or a note like "only on a sharp drop").
  - just watching : research says watch, not buy yet.
  - skip          : research says avoid.

For the names it would back (now or later), it sets a first-cut conviction -
high / medium / low, from how the assumptions are holding - and turns that into a
target weight, capped by your single-name limit (profile.md). The names to back
now get proposed targets (which ADD to your existing targets); the ones to wait
on are penciled onto the watchlist with a trigger.

Formation is book-aware: it reads your holdings and watchlist, tags each covered
name by how it relates to your book (a new idea, a name you hold, a name you
watch), flags a research Avoid on a name you hold as an exit to propose, and lists
the legacy holdings research does not cover (frozen at their weight, with a nudge
to commission research). The whole-book arithmetic - sector and country caps, and
the true cash-vs-buys math - still belongs to the rebalancer, which sees the weights.

This first read is a starting point, not the last word. The advisor reads the
fuller thesis and report and can override any name's size with --set, or drop a
name with --drop. The arithmetic stays in this script, never in the chat
(Hard Rule #8).

Examples (from a terminal in the Veda-advisor folder):

    python scripts/portfolio_formation.py --client default
    python scripts/portfolio_formation.py --client default --set BABA=8 --drop PARAS
    python scripts/portfolio_formation.py --client default --write-requests

Exit codes:
    0 - proposal printed
    1 - could not read (bad research path / manifest)
    2 - manifest not found
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml

from _common import client_root
from concentration import load_limits
from research_feed import DEFAULT_RESEARCH_CONFIG, FeedError, _norm_market, load_feed

# Force UTF-8 stdout so em-dashes / rupee signs in research text don't mangle on
# Windows consoles that default to cp1252 (house idiom, see review_decisions.py).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Conviction -> a starting target weight (percent), before the single-name cap.
# A focused ~12-name book: a few high-conviction names anchor it, the rest fill
# in. These are starting points; adjust any name with --set.
CONVICTION_WEIGHT = {"high": 12.0, "medium": 7.0, "low": 3.0}

# Words in the verdict / why that mean "buy, but not at this price" - wait for a
# better entry rather than buying now.
_WAIT_WORDS = ("drop", "de-rat", "derat", "pullback", "better entry", "cheaper", "correction")


# --- the first read (pure: one manifest entry in, a routing decision out) ---

def verdict_word(value) -> str:
    """The canonical first word of the My Call: Invest / Watch / Avoid (else '')."""
    if not value:
        return ""
    head = str(value).replace("\u2014", " ").replace("-", " ").split()
    return head[0].capitalize() if head else ""


def conviction_from_assumptions(row: dict) -> tuple[str, str]:
    """A first-cut conviction (high/medium/low) from how the assumptions hold.

    Returns (conviction, reason). Two or more weak assumptions caps it at low; a
    mostly-on-track thesis reads high; the middle reads medium.
    """
    assumptions = row.get("assumptions") or []
    total = len(assumptions)
    on_track = sum(1 for a in assumptions
                   if isinstance(a, dict) and "on-track" in str(a.get("status") or "").lower())
    weak = sum(1 for a in assumptions
               if isinstance(a, dict) and "weak" in str(a.get("status") or "").lower())
    if weak >= 2:
        conviction = "low"
    elif on_track >= 3:
        conviction = "high"
    elif on_track >= 2:
        conviction = "medium"
    else:
        conviction = "low"
    return conviction, f"{on_track} of {total} assumptions on-track" + (
        f", {weak} weak" if weak else "")


def first_cut(row: dict) -> tuple[str, str, str]:
    """A mechanical read of one covered name: (outcome, conviction, reason).

    outcome: back_now | own_but_wait | watching | skip.
    conviction is set only for back_now / own_but_wait (the names worth backing).
    A starting point the advisor can override.
    """
    if not row.get("listed", True) or not row.get("ticker"):
        return "watching", "", "unlisted - watch for a listing"
    verdict = verdict_word(row.get("value"))
    if verdict == "Avoid":
        return "skip", "", "research says avoid"
    if verdict != "Invest":
        return "watching", "", "research says watch, not buy yet"

    conviction, reason = conviction_from_assumptions(row)
    zone = str((row.get("valuation") or {}).get("zone") or "").upper()
    text = " ".join(filter(None, [
        str(row.get("value") or ""),
        str(row.get("why") or ""),
    ])).lower()
    if zone == "EXPENSIVE" or any(w in text for w in _WAIT_WORDS):
        return "own_but_wait", conviction, "buy, but wait for a better price; " + reason
    return "back_now", conviction, reason


# --- sizing (pure: entries + limits + overrides -> a proposal) --------------

def _row(row: dict, outcome: str, conviction: str, reason: str) -> dict:
    val = row.get("valuation") or {}
    return {
        "ticker": (row.get("ticker") or "").upper(),
        "market": _norm_market(row.get("market")) or (row.get("market") or "?"),
        "name": row.get("name") or row.get("slug"),
        "relation": row.get("relation"),
        "outcome": outcome,
        "conviction": conviction,
        "reason": reason,
        "verdict": row.get("value"),
        "zone": val.get("zone"),
        "why": row.get("why"),
        "target_pct": None,
        "capped": False,
    }


def build_proposal(rows: list[dict], limits: dict, overrides: dict,
                   drops: set) -> dict:
    """One proposal: covered names tagged with an outcome and (where backed) a
    target %, routed by how each relates to the book.

    Each backed name gets a conviction-based %, trimmed to the single-name cap
    (--set overrides). A research Avoid on a name you HOLD becomes an exit to
    propose (never a silent skip). The whole-book arithmetic - sector and country
    caps, and the true cash - stays with the rebalancer, which sees the holdings.
    """
    cap_pct = (limits.get("max_per_stock") or 1.0) * 100.0

    out: list[dict] = []
    for row in rows:
        ticker = (row.get("ticker") or "").upper()
        if ticker and ticker in drops:
            continue
        outcome, conviction, reason = first_cut(row)
        if outcome == "skip" and row.get("relation") == "HELD":
            outcome = "exit"
            reason = ("research now rates Avoid a name you hold - propose an exit, "
                      "tax-aware, never auto-sell")
        pr = _row(row, outcome, conviction, reason)
        if outcome in ("back_now", "own_but_wait"):
            base = overrides.get(ticker, CONVICTION_WEIGHT.get(conviction, 0.0))
            pr["capped"] = base > cap_pct
            pr["target_pct"] = round(min(base, cap_pct), 1)
        out.append(pr)

    back = [r for r in out if r["outcome"] == "back_now"]
    flags = [f"{r['ticker']} trimmed to the {cap_pct:.0f}% single-name cap"
             for r in out if r["capped"]]
    return {"rows": out, "back": back, "flags": flags, "cap_pct": cap_pct}


def legacy_holdings(rows: list[dict], held: set) -> list[tuple[str, str]]:
    """Held names research does not cover: (market, ticker) in the book but absent
    from the feed. Frozen at their current weight; each carries the research nudge."""
    covered = {(r.get("market"), (r.get("ticker") or "").upper())
               for r in rows if r.get("ticker")}
    return sorted(k for k in held if k not in covered)


def load_dry_powder_pct(client: str) -> float | None:
    """The client's dry-powder reserve target (percent of the book), from profile.md
    capital.dry_powder_pct. An AVERAGE target, not a hard floor -- spent on dip-triggers
    and rebuilt after. None when unset."""
    profile = client_root(client) / "profile.md"
    if not profile.exists():
        return None
    text = profile.read_text(encoding="utf-8")
    match = re.search(r"```yaml\n(.*?)```", text, re.DOTALL)
    try:
        data = yaml.safe_load(match.group(1) if match else text) or {}
    except yaml.YAMLError:
        return None
    capital = data.get("capital") if isinstance(data, dict) else None
    value = capital.get("dry_powder_pct") if isinstance(capital, dict) else None
    return float(value) if isinstance(value, (int, float)) else None


def coverage_requests(rows: list[dict], held: set, watched: set) -> tuple[list, list]:
    """The uncovered names the client holds or watches - the coverage the advisor would
    ask the research house to add. Returns (held_uncovered, watch_uncovered), each a
    sorted list of (market, ticker)."""
    covered = {(r.get("market"), (r.get("ticker") or "").upper())
               for r in rows if r.get("ticker")}
    held_unc = sorted(k for k in held if k not in covered)
    watch_unc = sorted(k for k in watched if k not in covered)
    return held_unc, watch_unc


def write_coverage_requests(client: str, held_unc: list, watch_unc: list) -> Path:
    """Write the plain-text coverage-request list to clients/<client>/research-requests.md -
    a human-readable to-do the research house reads to prioritise what to cover next."""
    path = client_root(client) / "research-requests.md"
    lines = [f"# Coverage requests - client '{client}' ({date.today().isoformat()})", "",
             "Names I hold or watch that research does not cover. Covering any of these lets",
             "the advisor judge it research-grade instead of a framework guess.", "",
             f"## Held ({len(held_unc)})",
             (", ".join(t for _m, t in held_unc) if held_unc else "(none)"), "",
             f"## Watchlist ({len(watch_unc)})",
             (", ".join(t for _m, t in watch_unc) if watch_unc else "(none)"), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def load_book_cash(client: str) -> tuple[float | None, float | None]:
    """Book total and total cash (INR) from assets.md > dynamic.totals, for the cash
    fit-check. (None, None) when unavailable - the check falls back to percents."""
    assets = client_root(client) / "assets.md"
    if not assets.exists():
        return None, None
    match = re.search(r"```yaml\n(.*?)```", assets.read_text(encoding="utf-8"), re.DOTALL)
    if not match:
        return None, None
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None, None
    totals = ((data.get("dynamic") or {}).get("totals")) or {}
    grand = totals.get("grand_total_inr")
    cash = sum(v for k, v in totals.items()
               if k.startswith("cash_") and k.endswith("_inr") and isinstance(v, (int, float)))
    grand = float(grand) if isinstance(grand, (int, float)) else None
    return grand, (cash or None)


def target_weights_block(back: list[dict]) -> dict:
    """The assets.md > dynamic.target_weights structure (percents) for the backed names."""
    block: dict = {}
    for r in back:
        block.setdefault(r["market"], {})[r["ticker"]] = r["target_pct"]
    return block


# --- readable proposal ------------------------------------------------------

def _label(row: dict) -> str:
    market = {"india": "IN", "us": "US"}.get(row["market"], row["market"])
    return f"{row['ticker']} ({row['name']}, {market})"


def format_report(proposal: dict, client: str, dry_powder: float | None,
                  legacy: list[tuple[str, str]], book_total: float | None = None,
                  cash: float | None = None) -> str:
    rows = proposal["rows"]
    lines = [f"Portfolio formation for client '{client}' - a proposal reconciled against "
             "your book.", ""]

    back = proposal["back"]
    if back:
        lines.append("Back now (proposed targets to buy / add now):")
        for r in sorted(back, key=lambda x: -x["target_pct"]):
            tag = "  (ADD to your existing position)" if r.get("relation") == "HELD" else ""
            lines.append(f"  {_label(r)}  ->  {r['target_pct']:.0f}%{tag}  ({r['conviction']} conviction)")
            lines.append(f"      {r['verdict']}  |  zone {r['zone']}  |  {r['reason']}")
    else:
        lines.append("Back now: nothing - no covered name is a buy at today's price.")

    wait = [r for r in rows if r["outcome"] == "own_but_wait"]
    if wait:
        lines.append("")
        lines.append("Own but wait (watchlist, size penciled - buy when the price comes):")
        for r in wait:
            lines.append(f"  {_label(r)}  ->  ~{r['target_pct']:.0f}% ({r['conviction']}), waiting")
            lines.append(f"      {r['verdict']}  |  zone {r['zone']}  |  why: {r['why']}")
            if str(r.get("zone") or "").upper() not in ("", "EXPENSIVE"):
                lines.append(f"      -> research zone is already {r['zone']} - the better price you're "
                             "waiting for may be here; your call.")

    watching = [r for r in rows if r["outcome"] == "watching"]
    if watching:
        lines.append("")
        lines.append("Just watching (watchlist, no size yet):")
        for r in watching:
            lines.append(f"  {_label(r)} - {r['verdict']}")

    exits = [r for r in rows if r["outcome"] == "exit"]
    if exits:
        lines.append("")
        lines.append("Exit check (research rates Avoid a name you hold - propose, never auto-sell):")
        for r in exits:
            lines.append(f"  {_label(r)} - {r['verdict']}")
            lines.append("      -> propose the exit with the tax read (LTCG vs STCG via `tax`); you decide.")

    skip = [r for r in rows if r["outcome"] == "skip"]
    if skip:
        lines.append("")
        lines.append("Skip: " + ", ".join(_label(r) for r in skip))

    if proposal["flags"]:
        lines.append("")
        lines.append("Check:")
        for flag in proposal["flags"]:
            lines.append(f"  - {flag}")

    if back:
        block = {"target_weights": target_weights_block(back)}
        lines.append("")
        lines.append("Proposed assets.md > dynamic.target_weights (percents) - these ADD to your")
        lines.append("existing targets; save on your OK:")
        for line in yaml.safe_dump(block, sort_keys=False, allow_unicode=True).splitlines():
            lines.append("  " + line)

    if back:
        buy_total = sum(r["target_pct"] for r in back)
        lines.append("")
        lines.append("Funding:")
        if book_total:
            buy_inr = buy_total / 100.0 * book_total
            line = f"  the back-now buys total ~{buy_total:.0f}% (~Rs {buy_inr:,.0f})."
            if cash is not None:
                leftover = cash - buy_inr
                if leftover >= 0:
                    line += f" You have ~Rs {cash:,.0f} cash - fits, leaves ~Rs {leftover:,.0f}."
                else:
                    line += f" You have ~Rs {cash:,.0f} cash - short ~Rs {-leftover:,.0f}."
            lines.append(line)
            if dry_powder is not None and cash is not None:
                left_pct = max(cash - buy_inr, 0.0) / book_total * 100.0
                lines.append(f"  That leaves ~{left_pct:.0f}% cash vs your ~{dry_powder:.0f}% reserve "
                             "(an average target, not a hard floor - your call).")
        else:
            lines.append(f"  the back-now buys total ~{buy_total:.0f}% of the book.")
        lines.append("  Fund cash-first; if short, rotate from the weakest name you can defend: a covered")
        lines.append("  Avoid, then a covered expensive / weak-thesis name, then - last resort - a frozen")
        lines.append("  legacy name you pick (size + gain + tax shown). Run `rebalance` for the exact trades.")
        if dry_powder is None:
            lines.append("  (No reserve set - add capital.dry_powder_pct to profile.md to hold dip-buying cash.)")

    if legacy:
        preview = ", ".join(t for _m, t in legacy[:12])
        more = f", +{len(legacy) - 12} more" if len(legacy) > 12 else ""
        lines.append("")
        lines.append(f"Frozen legacy holdings ({len(legacy)}) - research does not cover these, so they")
        lines.append("hold their current weight (moved only by a cap breach, the FIRE glide, or funding):")
        lines.append(f"  {preview}{more}")
        lines.append("  -> to judge any properly, commission a research deep-dive (a framework guess until")
        lines.append("     covered). `company <name>` shows what is known now; --write-requests saves")
        lines.append("     this list for the research house.")

    lines.append("")
    lines.append("This is a proposal - nothing is written. Adjust a size with --set TICKER=PCT, drop a")
    lines.append("name with --drop TICKER, then confirm before the targets are saved to assets.md.")
    return "\n".join(lines)


# --- command-line run -------------------------------------------------------

def _parse_kv(items: list[str]) -> dict:
    """Parse repeated KEY=VALUE args into a dict, uppercasing the key (a ticker)."""
    out: dict = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"expected TICKER=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        out[key.strip().upper()] = value.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Propose a book from the research feed, reconciled against the "
                    "client's holdings and watchlist."
    )
    parser.add_argument("--client", default="default", help="which client's book (default: default)")
    parser.add_argument("--research-path", default=None,
                        help="path to the Veda-research repo (overrides research.json)")
    parser.add_argument("--config", type=Path, default=DEFAULT_RESEARCH_CONFIG,
                        help="research.json path")
    parser.add_argument("--set", dest="set_", action="append", default=[], metavar="TICKER=PCT",
                        help="override a name's target percent (repeatable)")
    parser.add_argument("--drop", action="append", default=[], metavar="TICKER",
                        help="exclude a name from the proposal (repeatable)")
    parser.add_argument("--write-requests", action="store_true",
                        help="write the uncovered held/watchlist names to research-requests.md "
                             "for the research house to prioritise coverage")
    args = parser.parse_args(argv)

    try:
        overrides = {k: float(v) for k, v in _parse_kv(args.set_).items()}
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    drops = {t.strip().upper() for t in args.drop}

    try:
        rows, held, watched, _updated, _research = load_feed(
            args.client, args.config, args.research_path)
    except FeedError as error:
        print(str(error), file=sys.stderr)
        return error.code

    limits = load_limits(args.client)
    proposal = build_proposal(rows, limits, overrides, drops)
    legacy = legacy_holdings(rows, held)
    dry_powder = load_dry_powder_pct(args.client)
    book_total, cash = load_book_cash(args.client)
    print(format_report(proposal, args.client, dry_powder, legacy, book_total, cash))

    if args.write_requests:
        held_unc, watch_unc = coverage_requests(rows, held, watched)
        path = write_coverage_requests(args.client, held_unc, watch_unc)
        print(f"\nWrote {len(held_unc) + len(watch_unc)} coverage request(s) to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
