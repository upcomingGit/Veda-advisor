"""
Veda - single-company detail view ("tell me about Astra Microwave").

Assembles one readable dossier for a name from the best source available, and
labels every section with where it came from:

  - COVERED name (in the research manifest) -> the research packet: the call,
    the valuation zone, the full thesis (assumptions with their tripwires), the
    scorecard, fundamentals, and the curated news pulse. Research-grade depth.
  - UNCOVERED name you HOLD -> your own local workspace (kb, thesis, governance,
    risks, fundamentals, valuation), which is lighter and may be stale, plus the
    standing coverage disclaimer.
  - UNCOVERED name you do not hold -> just the header + a live calendar; the
    real analysis is the framework fallback the orchestrator runs.

The calendar is always fetched live (calendar_feed) so the dates are fresh and
cover names the packet never carries. This script only READS; the sole write is
the calendar cache inside a held name's own workspace (via calendar_feed).

    python scripts/company_view.py --client default "Astra Microwave"
    python scripts/company_view.py --client default NTPC
    python scripts/company_view.py --client default SOMENEWNAME --market us

Exit codes:
    0 - dossier printed
    1 - could not read the research feed
    2 - bad usage (argparse)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from _common import client_root, slugify
from research_feed import DEFAULT_RESEARCH_CONFIG, FeedError, _norm_market, load_feed
from calendar_feed import get_calendar

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# The canonical coverage disclaimer (SKILL Hard Rule #6). Rendered verbatim,
# with the name filled in, on any uncovered name.
DISCLAIMER = ("Research isn't covering {name}, so this is general framework analysis, "
              "not research-grade conviction - treat it as a lighter starting point, "
              "not a tracked position.")

_MARKET_LABEL = {"india": "IN", "us": "US"}

# What the packet carries (widened set). YAML files are parsed; .md files are
# surfaced as pointers (the orchestrator opens them on demand).
_PACKET_YAML = {"scorecard": "scorecard.yaml", "thesis": "thesis.yaml",
                "fundamentals": "fundamentals.yaml", "valuation": "valuation.yaml",
                "events": "events.yaml"}
_PACKET_DOCS = [("report.md", "the full write-up"), ("kb.md", "business overview"),
                ("management.md", "governance"), ("forensic.md", "risk probe")]
_LOCAL_DOCS = [("thesis.md", "your thesis + kill-criteria"), ("kb.md", "business overview"),
               ("governance.md", "governance"), ("risks.md", "risks")]


# --- reading ---------------------------------------------------------------

def _read_yaml(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def read_packet(research_path: Path, slug: str) -> dict:
    """Read a covered name's packet from published/<slug>/. YAML parsed to dicts;
    the presence of each narrative doc is recorded for pointers."""
    pdir = research_path / "published" / slug
    out: dict = {"dir": pdir, "exists": pdir.is_dir(), "docs": []}
    for key, fname in _PACKET_YAML.items():
        out[key] = _read_yaml(pdir / fname)
    for fname, _desc in _PACKET_DOCS:
        if (pdir / fname).exists():
            out["docs"].append(fname)
    return out


def read_local(client: str, slug: str) -> dict:
    """Read a held name's own workspace (clients/<client>/holdings/<slug>/)."""
    wdir = client_root(client) / "holdings" / slug
    out: dict = {"dir": wdir, "exists": wdir.is_dir(), "docs": []}
    out["fundamentals"] = _read_yaml(wdir / "fundamentals.yaml")
    out["valuation"] = _read_yaml(wdir / "valuation.yaml")
    out["assumptions"] = _read_yaml(wdir / "assumptions.yaml")
    out["meta"] = _read_yaml(wdir / "_meta.yaml")
    for fname, _desc in _LOCAL_DOCS:
        if (wdir / fname).exists():
            out["docs"].append(fname)
    return out


# --- resolution (query -> a target with coverage + relationship) -----------

def _covered_target(row: dict) -> dict:
    return {"slug": row["slug"], "ticker": row.get("ticker"), "market": row.get("market"),
            "name": row.get("name") or row["slug"], "covered": True,
            "relation": row.get("relation"), "row": row}


def resolve_target(query: str, rows: list[dict], held: set, watched: set,
                   client: str, market_hint: str = "") -> dict:
    """Resolve a name/ticker to {slug, ticker, market, name, covered, relation, row}.

    Covered names win (exact slug/ticker first, then a name substring); then a
    held or watchlisted uncovered name; then a local workspace by slug; else an
    unknown name (uncovered, not held)."""
    q = query.strip()
    qslug, qtick = slugify(q), q.upper()

    for row in rows:  # covered, exact
        if row.get("slug") == qslug or (row.get("ticker") and row["ticker"] == qtick):
            return _covered_target(row)
    for row in rows:  # covered, name substring
        if row.get("name") and q.lower() in row["name"].lower():
            return _covered_target(row)

    for market, tick in sorted(held):
        if tick == qtick or slugify(tick) == qslug:
            return {"slug": slugify(tick), "ticker": tick, "market": market,
                    "name": tick, "covered": False, "relation": "HELD", "row": None}
    for market, tick in sorted(watched):
        if tick == qtick or slugify(tick) == qslug:
            return {"slug": slugify(tick), "ticker": tick, "market": market,
                    "name": tick, "covered": False, "relation": "WATCHLIST", "row": None}

    wdir = client_root(client) / "holdings" / qslug
    if wdir.is_dir():
        meta = _read_yaml(wdir / "_meta.yaml") or {}
        return {"slug": qslug, "ticker": meta.get("ticker") or qtick,
                "market": _norm_market(meta.get("market")) or _norm_market(market_hint) or "",
                "name": meta.get("name") or qtick, "covered": False,
                "relation": "HELD", "row": None}

    return {"slug": qslug, "ticker": qtick, "market": _norm_market(market_hint) or "",
            "name": qtick, "covered": False, "relation": "NEITHER", "row": None}


# --- section formatters ----------------------------------------------------

_RELATION_LABEL = {"HELD": "HELD", "WATCHLIST": "on your WATCHLIST",
                   "NEW_IDEA": "a NEW IDEA (not held, not watchlisted)",
                   "PRIVATE": "PRIVATE / pre-listing", "NEITHER": "not held, not watchlisted"}


def _fmt_num(x) -> str:
    if isinstance(x, (int, float)):
        return f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.2f}"
    return str(x)


def _fmt_header(t: dict) -> list[str]:
    market = _MARKET_LABEL.get(t.get("market"), (t.get("market") or "?").upper())
    ticker = t.get("ticker") or "(unlisted)"
    cover = "COVERED by the research house" if t["covered"] else "UNCOVERED by the research house"
    lines = [f"=== {t['name']}  ({ticker}, {market}) ===",
             f"Coverage: {cover}    In your book: {_RELATION_LABEL.get(t['relation'], t['relation'])}"]
    if not t["covered"]:
        lines.append("Note: " + DISCLAIMER.format(name=t["name"]))
    return lines


def _fmt_call(row: dict) -> list[str]:
    rec = "the research call"
    val = row.get("value")
    if not val:
        return []
    out = ["", f"The call - research packet:", f"  {val}"]
    if row.get("why"):
        out.append(f"  why: {row['why']}")
    return out


def _fmt_valuation(val: dict | None, row: dict | None, provenance: str) -> list[str]:
    val = val or {}
    zone = val.get("zone") or (row or {}).get("valuation", {}).get("zone")
    if not zone:
        return []
    out = ["", f"Valuation - {provenance} (as of {val.get('as_of', 'n/a')}):"]
    zl = val.get("zone_long_term")
    out.append(f"  Zone: {zone}" + (f" (short-term)  /  {zl} (long-term)" if zl else ""))
    metric = val.get("primary_metric")
    mv = val.get("primary_metric_value")
    if metric and mv is not None:
        line = f"  {metric} {_fmt_num(mv)}"
        if val.get("peg_growth_pct") is not None:
            line += f" on {val['peg_growth_pct']:g}% growth"
        if val.get("peg_long_term") is not None and val.get("long_term_growth_pct") is not None:
            line += f"  (long-term {_fmt_num(val['peg_long_term'])} on {val['long_term_growth_pct']:g}%)"
        out.append(line)
    if val.get("current_pe") is not None:
        pe = f"  P/E {_fmt_num(val['current_pe'])}"
        if val.get("current_pe_percentile") is not None:
            pe += f" - {int(round(val['current_pe_percentile']))}th percentile of its 10y range"
        if val.get("historical_pe_median") is not None:
            pe += f" (median {_fmt_num(val['historical_pe_median'])})"
        out.append(pe)
    extra = []
    for key, label in (("current_pb", "P/B"), ("current_ps", "P/S"),
                       ("current_ev_ebitda", "EV/EBITDA"), ("current_dividend_yield_pct", "Div yield %")):
        if val.get(key) is not None:
            extra.append(f"{label} {_fmt_num(val[key])}")
    if extra:
        out.append("  " + " | ".join(extra))
    if val.get("zone_flag"):
        out.append(f"  ^ {val['zone_flag']}")
    return out


def _fmt_thesis_packet(thesis: dict | None) -> list[str]:
    if not thesis:
        return []
    head = thesis.get("thesis") if isinstance(thesis.get("thesis"), dict) else {}
    out = ["", f"Thesis - research packet"
           + (f" (status: {head.get('status')}, as of {head.get('as_of')})" if head.get("status") else "")
           + ":"]
    if head.get("statement"):
        out.append(f"  {head['statement']}")
    for a in thesis.get("assumptions") or []:
        if not isinstance(a, dict):
            continue
        out.append(f"  {a.get('id')} [{a.get('status')}]  {a.get('claim')}")
        if a.get("breaks_if"):
            out.append(f"       breaks if: {a['breaks_if']}")
    return out


def _fmt_assumptions_local(assumptions: dict | None) -> list[str]:
    if not assumptions:
        return []
    items = assumptions.get("assumptions")
    if not isinstance(items, dict) or not items:
        return []
    out = ["", "Thesis anchors - your local notes:"]
    for aid, a in items.items():
        if not isinstance(a, dict):
            continue
        cat = f" ({a.get('category')})" if a.get("category") else ""
        text = a.get("text") or a.get("claim") or a.get("statement") or ""
        out.append(f"  {aid}{cat}  {text}".rstrip())
    return out


def _fmt_scorecard(scorecard: dict | None) -> list[str]:
    if not scorecard:
        return []
    cards = scorecard.get("cards") or []
    if not cards:
        return []
    out = ["", "Scorecard - research packet:"]
    for c in cards:
        if not isinstance(c, dict):
            continue
        q = c.get("question") or c.get("lens") or ""
        out.append(f"  {q}: {c.get('value')}"
                   + (f" - {c['one_liner']}" if c.get("one_liner") else ""))
    return out


def _fmt_fundamentals(fund: dict | None, provenance: str, n: int = 4) -> list[str]:
    if not fund:
        return []
    quarters = fund.get("quarters") or []
    if not quarters:
        return []
    cur = fund.get("currency") or ""
    out = ["", f"Fundamentals - {provenance} ({cur} mm, source {fund.get('source', 'n/a')}, "
           f"as of {fund.get('as_of', 'n/a')}):", "  recent quarters:"]
    for q in quarters[-n:][::-1]:
        if not isinstance(q, dict):
            continue
        rev = _fmt_num(q.get("revenue_mm")) if q.get("revenue_mm") is not None else "n/a"
        ni = _fmt_num(q.get("net_income_mm")) if q.get("net_income_mm") is not None else "n/a"
        eps = q.get("eps_diluted")
        eps_s = f"  EPS {eps}" if eps is not None else ""
        out.append(f"    {q.get('period', '?'):>9}  revenue {rev:>10}  net income {ni:>9}{eps_s}")
    return out


def _fmt_calendar(cal: dict, lookforward_days: int) -> list[str]:
    out = ["", f"Upcoming calendar - live (as of {cal.get('as_of')}"
           + (", cached" if cal.get("cached") else "") + "):"]
    upcoming = cal.get("upcoming") or []
    if not upcoming:
        out.append(f"  no scheduled events in the next {lookforward_days} days "
                   "(common for Indian names between results)")
    for ev in upcoming:
        note = ev.get("note")
        out.append(f"  {ev.get('date')}  {ev.get('event')}" + (f"  - {note}" if note else ""))
    return out


def _fmt_events(events: dict | None, n: int = 5) -> list[str]:
    if not events:
        return []
    items = events.get("events") or []
    if not items:
        return []
    items = sorted([e for e in items if isinstance(e, dict)],
                   key=lambda e: e.get("event_date") or "", reverse=True)
    out = ["", f"Recent developments - research packet (events.yaml, updated {events.get('updated', 'n/a')}):"]
    for e in items[:n]:
        cat = f"[{e.get('category')}] " if e.get("category") else ""
        summary = (e.get("summary") or "").strip()
        if len(summary) > 160:
            summary = summary[:157] + "..."
        out.append(f"  {e.get('event_date', '?')}  {cat}{summary}")
    return out


def _fmt_docs(target: dict, packet: dict | None, local: dict | None) -> list[str]:
    out: list[str] = []
    if target["covered"] and packet and packet.get("docs"):
        descs = dict(_PACKET_DOCS)
        listed = ", ".join(f"{d} ({descs.get(d, '')})" for d in packet["docs"])
        out += ["", "More on file - research packet (open as needed):",
                f"  {listed}", f"  at {packet['dir']}"]
    if local and local.get("docs"):
        descs = dict(_LOCAL_DOCS)
        listed = ", ".join(f"{d} ({descs.get(d, '')})" for d in local["docs"])
        out += ["", "More on file - your local notes (open as needed):",
                f"  {listed}", f"  at {local['dir']}"]
    return out


# --- assembly --------------------------------------------------------------

def build_dossier(target: dict, packet: dict | None, local: dict | None,
                  calendar: dict, lookforward_days: int) -> str:
    lines = _fmt_header(target)
    if target["covered"]:
        row = target["row"] or {}
        lines += _fmt_call(row)
        lines += _fmt_valuation((packet or {}).get("valuation"), row, "research packet")
        lines += _fmt_thesis_packet((packet or {}).get("thesis"))
        lines += _fmt_scorecard((packet or {}).get("scorecard"))
        lines += _fmt_fundamentals((packet or {}).get("fundamentals"), "research packet")
        lines += _fmt_calendar(calendar, lookforward_days)
        lines += _fmt_events((packet or {}).get("events"))
    else:
        if local and local.get("exists"):
            lines += _fmt_valuation(local.get("valuation"), None, "your local notes")
            lines += _fmt_assumptions_local(local.get("assumptions"))
            lines += _fmt_fundamentals(local.get("fundamentals"), "your local notes")
        lines += _fmt_calendar(calendar, lookforward_days)
    lines += _fmt_docs(target, packet, local)
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Assemble one company's dossier from the best source available "
                    "(research packet for covered names, your local workspace for held "
                    "uncovered names), with a live calendar.")
    p.add_argument("query", help="Company name or ticker (e.g. 'Astra Microwave' or NTPC).")
    p.add_argument("--client", default="default", help="Active client (default: default).")
    p.add_argument("--market", default="", help="Market hint (us / india) for an unknown name.")
    p.add_argument("--research-path", default=None, help="Override the research repo path.")
    p.add_argument("--config", type=Path, default=DEFAULT_RESEARCH_CONFIG)
    p.add_argument("--lookforward-days", type=int, default=180)
    args = p.parse_args()

    try:
        rows, held, watched, _updated, research = load_feed(
            args.client, args.config, args.research_path)
    except FeedError as error:
        print(str(error), file=sys.stderr)
        return 1

    target = resolve_target(args.query, rows, held, watched, args.client, args.market)

    packet = read_packet(research, target["slug"]) if target["covered"] else None
    local = read_local(args.client, target["slug"]) if not target["covered"] else None

    if target.get("market") and target.get("ticker"):
        calendar = get_calendar(args.client, target["slug"], target["ticker"],
                                target["market"], lookforward_days=args.lookforward_days)
    else:
        calendar = {"as_of": "n/a", "upcoming": [], "cached": False,
                    "errors": ["market unknown - pass --market us|india to fetch the calendar"]}

    print(build_dossier(target, packet, local, calendar, args.lookforward_days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
