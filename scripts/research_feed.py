"""
Veda - research feed reader.

Reads the research arm's recommendation feed (published/manifest.yaml in the
companion Veda-research repo) and reconciles it against ONE client's book:
which recommended names the client already holds, already watches, is brand new,
or is an unlisted (private) name. It flags the new and updated recommendations so
the advisor can start tracking them for the client.

Boundary: this is read-only w.r.t. the client's book. It never writes assets.md
or holdings/. The only thing it writes is the client's own "seen" cursor
(clients/<client>/research-seen.json, with --mark-seen) so a recommendation is
flagged once, not every session. The recommendation VALUE (the analyst's "My
Call") is free text and is shown verbatim as evidence; the advisor never acts on
it directly - sizing and buy/sell stay the advisor's job, through the pipeline.

Where the research repo sits: --research-path wins, else user-config/research.json,
else the sibling folder ../veda-ai-research-team.

Examples (from a terminal in the Veda-advisor folder):

    python scripts/research_feed.py --client default
    python scripts/research_feed.py --client default --mark-seen

Exit codes:
    0 - report printed
    1 - could not read (bad research path / config / manifest)
    2 - manifest not found
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml  # nested-YAML feed reader; an integration script (like dashboard/),
             # not a portable-core script, so PyYAML is the right tool here.

from _common import client_root
from reconcile import read_assets_positions

# Force UTF-8 stdout so em-dashes / ₹ in recommendation text don't mangle on
# Windows consoles that default to cp1252 (house idiom, see review_decisions.py).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Repo root is the parent of scripts/.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESEARCH_CONFIG = REPO_ROOT / "user-config" / "research.json"

# The two repos sit side by side by default.
DEFAULT_RESEARCH_PATH = "../veda-ai-research-team"

# Manifest markets are {US, IN}; the advisor's books use {us, india}.
_MARKET_ALIASES = {"india": "india", "in": "india", "us": "us", "usa": "us"}

# Held positions at or below this many shares are treated as closed, not held.
EPSILON = 1e-9


def _norm_market(raw) -> str | None:
    if not raw:
        return None
    return _MARKET_ALIASES.get(str(raw).strip().lower())


# --- reading the research repo location ------------------------------------

def resolve_research_path(config_path: Path, override: str | None) -> Path:
    """The Veda-research repo location. --research-path wins, else research.json,
    else the sibling folder next to this repo."""
    if override:
        base = override
    elif config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except ValueError:
            cfg = {}
        base = cfg.get("research_repo_path") or DEFAULT_RESEARCH_PATH
    else:
        base = DEFAULT_RESEARCH_PATH
    path = Path(base)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    return path


# --- reading the client's watchlist (holdings come from reconcile) ---------

def read_watchlist(assets_path: Path) -> set[tuple[str, str]]:
    """Parse the `## Watchlist / open orders` table into {(market, TICKER)}.

    Columns: ticker | name | market | why_tracking | target_pct | trigger.
    Header, separator, and template placeholder rows (ticker like `_(e.g. TCS)_`)
    are skipped. Stdlib only.
    """
    watched: set[tuple[str, str]] = set()
    if not assets_path.exists():
        return watched
    in_watchlist = False
    for raw in assets_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_watchlist = line.lower().startswith("## watchlist")
            continue
        if not in_watchlist or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        ticker = cells[0]
        if ticker.lower() in ("ticker", "") or ticker.startswith("_(") or set(ticker) <= set("-: "):
            continue
        market = _norm_market(cells[2])
        if not market:
            continue
        watched.add((market, ticker.upper()))
    return watched


def load_seen(path: Path) -> dict:
    """The per-client seen cursor: {slug: version, ...}. Empty when absent."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    seen = data.get("seen") if isinstance(data, dict) else None
    return seen if isinstance(seen, dict) else {}


# --- the classification core (pure: dicts in, rows out) --------------------

def classify(
    entries: list[dict],
    held: set[tuple[str, str]],
    watched: set[tuple[str, str]],
    seen: dict,
) -> list[dict]:
    """One row per manifest entry, tagged with change (vs seen) and relation
    (vs the client's book). Pure - no I/O."""
    rows: list[dict] = []
    for entry in entries:
        slug = entry.get("slug")
        listed = entry.get("listed", True)
        ticker = (entry.get("ticker") or "").strip().upper()
        market = _norm_market(entry.get("market"))
        key = (market, ticker)

        if not listed or not ticker:
            relation = "PRIVATE"
        elif key in held:
            relation = "HELD"
        elif key in watched:
            relation = "WATCHLIST"
        else:
            relation = "NEW_IDEA"

        version = (entry.get("packet") or {}).get("version")
        if slug not in seen:
            change = "NEW"
        elif seen.get(slug) != version:
            change = "UPDATED"
        else:
            change = "UNCHANGED"

        rec = entry.get("recommendation") or {}
        thesis = entry.get("thesis") or {}
        rows.append({
            "slug": slug,
            "ticker": ticker or None,
            "market": market,
            "name": entry.get("name") or slug,
            "listed": listed,
            "relation": relation,
            "change": change,
            "version": version,
            "value": rec.get("value"),
            "why": entry.get("why"),
            "statement": thesis.get("statement"),
            "assumptions": thesis.get("assumptions") or [],
            "valuation": entry.get("valuation") or {},
        })
    return rows


# --- readable report -------------------------------------------------------

_RELATION_TAG = {
    "HELD": "[HELD]",
    "WATCHLIST": "[WATCHLIST]",
    "NEW_IDEA": "[NEW IDEA]",
    "PRIVATE": "[PRIVATE]",
}

_NEXT_STEP = {
    "HELD": "you hold this - research has a maintained view; a hold-check can use it.",
    "WATCHLIST": "already on your watchlist - refresh the note if the view changed.",
    "NEW_IDEA": "not in your book or watchlist - add to the watchlist to start tracking it.",
    "PRIVATE": "unlisted - watch-only; track for an IPO / listing.",
}


def _name(row: dict) -> str:
    market = {"india": "IN", "us": "US"}.get(row["market"], row["market"] or "?")
    ticker = row["ticker"] or "(unlisted)"
    return f"{ticker} ({row['name']}, {market})"


def _detail_lines(row: dict) -> list[str]:
    out = [f"  {_RELATION_TAG.get(row['relation'], row['relation'])} {_name(row)} "
           f"- {row['value']}  [{row['change']}]"]
    if row["why"]:
        out.append(f"      why: {row['why']}")
    if row["statement"]:
        out.append(f"      thesis: {row['statement']}")
    if row["assumptions"]:
        parts = "; ".join(
            f"{a.get('id')} {a.get('status')}"
            for a in row["assumptions"] if isinstance(a, dict)
        )
        out.append(f"      assumptions: {parts}")
    # The valuation axis of the timing read, beside the assumption axis above:
    # the story (assumptions) says whether to own it; the zone says whether the
    # price is attractive now. Both are research evidence; sizing stays the
    # advisor's job.
    val = row.get("valuation") or {}
    if val.get("zone"):
        dual = bool(val.get("zone_long_term"))
        bits = [f"zone {val['zone']}"]
        mv = val.get("metric_value")
        if val.get("metric") and mv is not None:
            mv_str = f"{mv:.2f}" if isinstance(mv, (int, float)) else str(mv)
            piece = f"{val['metric']} {mv_str}"
            if val.get("metric") == "PEG" and isinstance(val.get("peg_growth_pct"), (int, float)):
                piece += f" on {val['peg_growth_pct']:g}% growth"
            bits.append(piece)
        if val.get("pe_percentile_10y") is not None:
            bits.append(f"PE {int(round(val['pe_percentile_10y']))}th pctile (10y)")
        label = "valuation (short-term)" if dual else "valuation"
        line = f"      {label}: {' | '.join(bits)}"
        if val.get("as_of"):
            line += f"  (as of {val['as_of']})"
        out.append(line)
        if val.get("flag"):
            out.append(f"        ^ {val['flag']}")
        if dual:
            lt_bits = [f"zone {val['zone_long_term']}"]
            if isinstance(val.get("long_term_growth_pct"), (int, float)):
                lt_bits.append(f"on {val['long_term_growth_pct']:g}% growth")
            out.append(f"      valuation (long-term): {' | '.join(lt_bits)}")
    hint = _NEXT_STEP.get(row["relation"])
    if hint:
        out.append(f"      -> {hint}")
    return out


def format_report(rows: list[dict], client: str, manifest_updated) -> str:
    lines = [f"Research feed for client '{client}' (manifest updated {manifest_updated}).", ""]

    flagged = [r for r in rows if r["change"] in ("NEW", "UPDATED")]
    unchanged = [r for r in rows if r["change"] == "UNCHANGED"]

    if flagged:
        lines.append("New or updated (surface these):")
        for row in flagged:
            lines.extend(_detail_lines(row))
    else:
        lines.append("New or updated: none.")

    if unchanged:
        lines.append("")
        lines.append("Already seen (unchanged since last check):")
        for row in unchanged:
            lines.append(f"  {_RELATION_TAG.get(row['relation'], row['relation'])} "
                         f"{_name(row)} - {row['value']}")

    def rel_count(rel: str) -> int:
        return sum(1 for r in rows if r["relation"] == rel)

    new_n = sum(1 for r in rows if r["change"] == "NEW")
    upd_n = sum(1 for r in rows if r["change"] == "UPDATED")
    lines.append("")
    lines.append(
        f"Summary: {new_n} new, {upd_n} updated | held {rel_count('HELD')}, "
        f"watchlist {rel_count('WATCHLIST')}, new ideas {rel_count('NEW_IDEA')}, "
        f"private {rel_count('PRIVATE')}."
    )
    lines.append(
        "Zones: CHEAP / FAIR / EXPENSIVE (today's price on the archetype's metric vs its "
        "own history; a ^ line flags a cheap/fair read whose price is near its 10y high)."
    )
    return "\n".join(lines)


# --- command-line run ------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read the research recommendation feed and reconcile it against one client's book."
    )
    parser.add_argument("--client", default="default", help="which client's book (default: default)")
    parser.add_argument("--research-path", default=None,
                        help="path to the Veda-research repo (overrides research.json)")
    parser.add_argument("--config", type=Path, default=DEFAULT_RESEARCH_CONFIG,
                        help="research.json path")
    parser.add_argument("--mark-seen", action="store_true",
                        help="record the current versions so they are not re-flagged next session")
    args = parser.parse_args(argv)

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
    manifest_updated = doc.get("updated")

    root = client_root(args.client)
    assets_path = root / "assets.md"
    seen_path = root / "research-seen.json"

    positions = read_assets_positions(assets_path) if assets_path.exists() else {}
    held = {key for key, shares in positions.items() if abs(shares) > EPSILON}
    watched = read_watchlist(assets_path)
    seen = load_seen(seen_path)

    rows = classify(entries, held, watched, seen)
    print(format_report(rows, args.client, manifest_updated))

    if args.mark_seen:
        cursor = {
            "manifest_updated": str(manifest_updated) if manifest_updated is not None else None,
            "seen": {row["slug"]: row["version"] for row in rows},
        }
        seen_path.parent.mkdir(parents=True, exist_ok=True)
        seen_path.write_text(json.dumps(cursor, indent=2) + "\n", encoding="utf-8")
        print(f"\nMarked {len(rows)} recommendation(s) as seen for client '{args.client}'.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
