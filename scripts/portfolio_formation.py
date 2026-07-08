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

Formation is candidate-scoped: it sizes the research names, not your whole book.
It does not read your current holdings, so the whole-book checks - sector and
country caps, and the true cash - belong to the rebalancer, which sees them.

This first read is a starting point, not the last word. The advisor reads the
fuller thesis and report and can override any name's size with --set, or drop a
name with --drop. The arithmetic stays in this script, never in the chat
(Hard Rule #8).

Examples (from a terminal in the Veda-advisor folder):

    python scripts/portfolio_formation.py --client default
    python scripts/portfolio_formation.py --client default --set BABA=8 --drop PARAS

Exit codes:
    0 - proposal printed
    1 - could not read (bad research path / manifest)
    2 - manifest not found
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from concentration import load_limits
from research_feed import DEFAULT_RESEARCH_CONFIG, _norm_market, resolve_research_path

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


def conviction_from_assumptions(entry: dict) -> tuple[str, str]:
    """A first-cut conviction (high/medium/low) from how the assumptions hold.

    Returns (conviction, reason). Two or more weak assumptions caps it at low; a
    mostly-on-track thesis reads high; the middle reads medium.
    """
    assumptions = (entry.get("thesis") or {}).get("assumptions") or []
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


def first_cut(entry: dict) -> tuple[str, str, str]:
    """A mechanical read of one manifest entry: (outcome, conviction, reason).

    outcome: back_now | own_but_wait | watching | skip.
    conviction is set only for back_now / own_but_wait (the names worth backing).
    A starting point the advisor can override.
    """
    if not entry.get("listed", True) or not entry.get("ticker"):
        return "watching", "", "unlisted - watch for a listing"
    verdict = verdict_word((entry.get("recommendation") or {}).get("value"))
    if verdict == "Avoid":
        return "skip", "", "research says avoid"
    if verdict != "Invest":
        return "watching", "", "research says watch, not buy yet"

    conviction, reason = conviction_from_assumptions(entry)
    zone = str((entry.get("valuation") or {}).get("zone") or "").upper()
    text = " ".join(filter(None, [
        str((entry.get("recommendation") or {}).get("value") or ""),
        str(entry.get("why") or ""),
    ])).lower()
    if zone == "EXPENSIVE" or any(w in text for w in _WAIT_WORDS):
        return "own_but_wait", conviction, "buy, but wait for a better price; " + reason
    return "back_now", conviction, reason


# --- sizing (pure: entries + limits + overrides -> a proposal) --------------

def _row(entry: dict, outcome: str, conviction: str, reason: str) -> dict:
    val = entry.get("valuation") or {}
    return {
        "ticker": (entry.get("ticker") or "").upper(),
        "market": _norm_market(entry.get("market")) or (entry.get("market") or "?"),
        "name": entry.get("name") or entry.get("slug"),
        "outcome": outcome,
        "conviction": conviction,
        "reason": reason,
        "verdict": (entry.get("recommendation") or {}).get("value"),
        "zone": val.get("zone"),
        "why": entry.get("why"),
        "target_pct": None,
        "capped": False,
    }


def build_proposal(entries: list[dict], limits: dict, overrides: dict,
                   drops: set) -> dict:
    """One proposal: rows tagged with an outcome and (where backed) a target %.

    Candidate-scoped: it sizes only the research names, not your existing book.
    Each backed name gets a conviction-based %, trimmed to the single-name cap
    (--set overrides). The whole-book checks - sector and country caps, and the
    true cash - belong to the rebalancer, which sees the current holdings.
    """
    cap_pct = (limits.get("max_per_stock") or 1.0) * 100.0

    rows: list[dict] = []
    for entry in entries:
        ticker = (entry.get("ticker") or "").upper()
        if ticker and ticker in drops:
            continue
        outcome, conviction, reason = first_cut(entry)
        row = _row(entry, outcome, conviction, reason)
        if outcome in ("back_now", "own_but_wait"):
            base = overrides.get(ticker, CONVICTION_WEIGHT.get(conviction, 0.0))
            row["capped"] = base > cap_pct
            row["target_pct"] = round(min(base, cap_pct), 1)
        rows.append(row)

    back = [r for r in rows if r["outcome"] == "back_now"]
    flags = [f"{r['ticker']} trimmed to the {cap_pct:.0f}% single-name cap"
             for r in rows if r["capped"]]
    return {"rows": rows, "back": back, "flags": flags, "cap_pct": cap_pct}


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


def format_report(proposal: dict, client: str) -> str:
    rows = proposal["rows"]
    lines = [f"Portfolio formation for client '{client}' - a proposal for the research names, "
             "not a saved book.", ""]

    back = proposal["back"]
    if back:
        lines.append("Back now (proposed targets for the research names to buy now):")
        for r in sorted(back, key=lambda x: -x["target_pct"]):
            lines.append(f"  {_label(r)}  ->  {r['target_pct']:.0f}%  ({r['conviction']} conviction)")
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

    watching = [r for r in rows if r["outcome"] == "watching"]
    if watching:
        lines.append("")
        lines.append("Just watching (watchlist, no size yet):")
        for r in watching:
            lines.append(f"  {_label(r)} - {r['verdict']}")

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

    lines.append("")
    lines.append("Scope: the research names only - formation does not read your current holdings")
    lines.append("yet. After you save the targets, run `rebalance` for the whole-book view and its")
    lines.append("single-name / sector / country cap warnings.")
    lines.append("This is a proposal. Adjust any size with --set TICKER=PCT, drop a name with")
    lines.append("--drop TICKER, then confirm before the targets are written to assets.md.")
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
        description="Propose a target-weight book from the research feed and your limits."
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
    args = parser.parse_args(argv)

    try:
        overrides = {k: float(v) for k, v in _parse_kv(args.set_).items()}
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    drops = {t.strip().upper() for t in args.drop}

    research = resolve_research_path(args.config, args.research_path)
    manifest_path = research / "published" / "manifest.yaml"
    if not manifest_path.exists():
        print(f"research manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    try:
        doc = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        print(f"could not parse manifest: {error}", file=sys.stderr)
        return 1
    entries = [e for e in (doc.get("entries") or []) if isinstance(e, dict) and e.get("slug")]

    limits = load_limits(args.client)
    proposal = build_proposal(entries, limits, overrides, drops)
    print(format_report(proposal, args.client))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
