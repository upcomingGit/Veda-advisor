"""
Veda - research feed reader.

Reads the research arm's shared dataset (published/manifest.yaml in the
companion research repo) and reconciles it against ONE client's book. Completed
packet rows carry research-grade Calls; tracking-only rows carry approved
monitoring context but remain Not yet assessed. Both retain the separate client
relationship: held, watchlisted, neither, or private.

An explicitly ended row retains the last approved packet and Call for audit,
but is no longer active coverage and is never sized. Its semantic record hash
changes once when coverage ends; packet-only byte churn does not create an
advisor alert.

Boundary: this is read-only w.r.t. the client's book. It never writes assets.md
or holdings/. The only thing it writes is the client's own "seen" cursor
(clients/<client>/research-seen.json, with --mark-seen) so a record revision is
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
from datetime import date, datetime
import json
import re
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
RESEARCH_COMPLETE = "Completed"
NOT_YET_ASSESSED = "Not yet assessed"
MANIFEST_SCHEMA_VERSION = 4


def _norm_market(raw) -> str | None:
    if not raw:
        return None
    return _MARKET_ALIASES.get(str(raw).strip().lower())


def _valid_iso_date(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _private_company_identity_slug(name: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", str(name).casefold())
    text = re.sub(
        r"\b(?:private|unlisted|listed|limited|ltd|pvt|inc|plc|llc|corp|corporation)\b",
        " ",
        text,
    )
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _valid_horizon(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return _valid_iso_date(value) or bool(
        re.search(r"\b20\d{2}\b|\b(?:FY|CY)\s*'?\d{2,4}\b", value, re.IGNORECASE)
    )


def _valid_review_by(value, as_of: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        review_date = date.fromisoformat(value)
    except ValueError:
        return bool(re.search(r"[A-Za-z]", value))
    return review_date.isoformat() == value and review_date >= date.fromisoformat(as_of)


def _valid_iso_datetime(value) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def has_active_coverage(row: dict) -> bool:
    """Whether a row carries completed research that remains active."""
    return (
        row.get("research_status") == RESEARCH_COMPLETE
        and (row.get("coverage") or {}).get("status") == "Active"
    )


def has_ended_coverage(row: dict) -> bool:
    """Whether a row retains completed research as an explicit ending tombstone."""
    return (
        row.get("research_status") == RESEARCH_COMPLETE
        and (row.get("coverage") or {}).get("status") == "Ended"
    )


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
    """The per-client seen cursor: ``{slug: revision, ...}``. Empty when absent."""
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
    *,
    schema_version: int = MANIFEST_SCHEMA_VERSION,
) -> list[dict]:
    """One row per manifest entry, tagged with change (vs seen) and relation
    (vs the client's book). Pure - no I/O."""
    if schema_version != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"unsupported manifest schema_version {schema_version!r}")
    rows: list[dict] = []
    slugs: set[str] = set()
    for entry in entries:
        slug = entry.get("slug")
        if not isinstance(slug, str) or not slug or slug in slugs:
            raise ValueError(f"manifest entry has a missing or duplicate slug: {slug!r}")
        slugs.add(slug)
        listed = entry.get("listed")
        if not isinstance(listed, bool):
            raise ValueError(f"manifest entry '{slug}' has no valid listed flag")
        raw_ticker = entry.get("ticker")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"manifest entry '{slug}' has no valid company name")
        if listed:
            if not isinstance(raw_ticker, str) or not raw_ticker or raw_ticker != raw_ticker.strip().upper():
                raise ValueError(f"manifest entry '{slug}' has invalid market or ticker identity")
            ticker = raw_ticker
        else:
            if raw_ticker is not None:
                raise ValueError(f"manifest entry '{slug}' has invalid market or ticker identity")
            ticker = ""
        raw_market = entry.get("market")
        market = _norm_market(raw_market)
        if raw_market not in {"IN", "US"} or market is None or (listed and not ticker) or (not listed and ticker):
            raise ValueError(f"manifest entry '{slug}' has invalid market or ticker identity")
        key = (market, ticker)

        packet = entry.get("packet")
        recommendation = entry.get("recommendation")
        private_view = entry.get("private_research_view")
        private_context = entry.get("private_context")
        research_status = entry.get("research_status")
        if research_status not in {RESEARCH_COMPLETE, NOT_YET_ASSESSED}:
            raise ValueError(f"manifest v4 entry '{slug}' has no valid research_status")
        company_id = entry.get("company_id")
        expected_company_id = (
            f"{raw_market}:{ticker}"
            if listed
            else f"{raw_market}:private:{_private_company_identity_slug(name)}"
        )
        if (
            not isinstance(company_id, str)
            or not company_id
            or (listed and company_id != expected_company_id)
            or (not listed and company_id != expected_company_id)
        ):
            raise ValueError(f"manifest v4 entry '{slug}' has no company_id")
        revision = entry.get("record_hash")
        if (
            not isinstance(revision, str)
            or not revision.startswith("sha256:")
            or len(revision) != 71
            or any(char not in "0123456789abcdef" for char in revision[7:])
        ):
            raise ValueError(f"manifest v4 entry '{slug}' has no record_hash")
        tracking = entry.get("tracking")
        if not isinstance(tracking, dict):
            raise ValueError(f"manifest v4 entry '{slug}' has no tracking block")
        relationships = tracking.get("relationships")
        if (
            not isinstance(tracking.get("reviewed"), bool)
            or not isinstance(tracking.get("globally_tracked"), bool)
            or not isinstance(relationships, list)
            or any(
                not isinstance(rel, dict)
                or not isinstance(rel.get("key"), str)
                or rel.get("scope") not in {"sector", "standalone"}
                or (
                    rel.get("scope") == "sector"
                    and (not isinstance(rel.get("sector_slug"), str) or not rel["sector_slug"])
                )
                or (rel.get("scope") == "standalone" and rel.get("sector_slug") is not None)
                or rel.get("key") != (
                    f"sector:{rel.get('sector_slug')}:{company_id}"
                    if rel.get("scope") == "sector"
                    else f"standalone:{company_id}"
                )
                or rel.get("state") not in {"Tracked", "Untracked"}
                or not isinstance(rel.get("reason"), str)
                or not rel["reason"].strip()
                or not isinstance(rel.get("decision_date"), str)
                for rel in relationships
            )
            or tracking["reviewed"] != bool(relationships)
            or tracking["globally_tracked"] != any(rel["state"] == "Tracked" for rel in relationships)
        ):
            raise ValueError(f"manifest v4 entry '{slug}' has an invalid tracking block")
        coverage = entry.get("coverage")
        if research_status == NOT_YET_ASSESSED:
            if coverage is not None:
                raise ValueError(f"not-yet-assessed manifest entry '{slug}' cannot carry coverage history")
        elif (
            not isinstance(coverage, dict)
            or set(coverage) != {"status", "ended_on", "reason"}
            or coverage.get("status") not in {"Active", "Ended"}
            or (
                coverage.get("status") == "Active"
                and (coverage.get("ended_on") is not None or coverage.get("reason") is not None)
            )
            or (
                coverage.get("status") == "Ended"
                and (
                    not isinstance(coverage.get("ended_on"), str)
                    or not _valid_iso_date(coverage["ended_on"])
                    or not isinstance(coverage.get("reason"), str)
                    or not coverage["reason"].strip()
                )
            )
        ):
            raise ValueError(f"manifest v4 entry '{slug}' has an invalid coverage block")
        if research_status == RESEARCH_COMPLETE:
            packet_is_valid = (
                not isinstance(packet, dict)
                or not isinstance(packet.get("version"), int)
                or isinstance(packet["version"], bool)
                or packet["version"] < 1
            )
            listed_conclusion_invalid = listed and (
                not isinstance(recommendation, dict)
                or not isinstance(recommendation.get("value"), str)
                or not recommendation["value"].strip()
                or private_view is not None
            )
            private_conclusion_invalid = not listed and (
                recommendation is not None
                or entry.get("why") is not None
                or entry.get("valuation") is not None
                or not isinstance(private_view, dict)
                or set(private_view) != {"status", "as_of", "horizon", "review_by", "reasoning"}
                or private_view.get("status") not in {
                    "Promising", "Monitor", "Concerning", "Insufficient evidence"
                }
                or not _valid_iso_date(private_view.get("as_of"))
                or not _valid_horizon(private_view.get("horizon"))
                or not _valid_review_by(private_view.get("review_by"), private_view.get("as_of"))
                or not isinstance(private_view.get("reasoning"), str)
                or not private_view["reasoning"].strip()
                or not isinstance(private_context, dict)
                or set(private_context) != {"boat", "source_gaps", "unknowns", "freshness"}
                or not isinstance(private_context.get("boat"), dict)
                or private_context["boat"].get("status") not in {
                    "Better", "Weaker or unproven", "Insufficient evidence"
                }
                or not all(
                    isinstance(private_context["boat"].get(field), str)
                    and private_context["boat"][field].strip()
                    for field in ("segment", "as_of", "reasoning")
                )
                or not _valid_iso_date(private_context["boat"].get("as_of"))
                or (
                    private_context["boat"].get("status") == "Insufficient evidence"
                    and (
                        not isinstance(private_context["boat"].get("gap"), str)
                        or not private_context["boat"]["gap"].strip()
                    )
                )
                or any(
                    not isinstance(private_context.get(field), list)
                    or any(not isinstance(item, str) or not item.strip() for item in private_context[field])
                    for field in ("source_gaps", "unknowns")
                )
                or not isinstance(private_context.get("freshness"), dict)
                or not _valid_iso_date(private_context["freshness"].get("scorecard_as_of"))
                or not _valid_iso_date(private_context["freshness"].get("thesis_as_of"))
                or not _valid_iso_datetime(private_context["freshness"].get("website_retrieved_at"))
            )
            if packet_is_valid or listed_conclusion_invalid or private_conclusion_invalid:
                raise ValueError(f"completed manifest entry '{slug}' has no valid approved conclusion")
        else:
            if not relationships:
                raise ValueError(f"not-yet-assessed manifest entry '{slug}' has no reviewed relationship")
            if any(entry.get(field) is not None for field in ("packet", "recommendation", "private_research_view", "private_context", "why", "thesis", "valuation")):
                raise ValueError(f"not-yet-assessed manifest entry '{slug}' contains fabricated research")

        if not listed or not ticker:
            relation = "PRIVATE"
        elif key in held:
            relation = "HELD"
        elif key in watched:
            relation = "WATCHLIST"
        else:
            relation = "NEW_IDEA"

        version = (packet or {}).get("version")
        if slug not in seen:
            change = "NEW"
        elif seen.get(slug) != revision:
            change = "UPDATED"
        else:
            change = "UNCHANGED"

        rec = entry.get("recommendation") or {}
        thesis = entry.get("thesis") or {}
        rows.append({
            "slug": slug,
            "company_id": entry.get("company_id"),
            "ticker": ticker or None,
            "market": market,
            "name": name,
            "listed": listed,
            "relation": relation,
            "change": change,
            "version": version,
            "revision": revision,
            "tracking": tracking,
            "coverage": coverage,
            "research_status": research_status,
            "value": rec.get("value"),
            "private_research_view": private_view,
            "private_context": private_context,
            "why": entry.get("why"),
            "statement": thesis.get("statement"),
            "assumptions": thesis.get("assumptions") or [],
            "valuation": entry.get("valuation") or {},
        })
    silently_removed = sorted(set(seen) - slugs)
    if silently_removed:
        raise ValueError(
            "manifest silently removed previously seen research instead of publishing "
            "an explicit Ended tombstone: " + ", ".join(silently_removed)
        )
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
    if has_ended_coverage(row):
        coverage = row["coverage"]
        out = [
            f"  {_RELATION_TAG.get(row['relation'], row['relation'])} {_name(row)} "
            f"- COVERAGE ENDED {coverage['ended_on']}  [{row['change']}]",
            f"      reason: {coverage['reason']}",
        ]
        if row.get("value"):
            out.append(f"      last approved Call (historical only): {row['value']}")
        out.append("      -> treat as uncovered; do not size from the retained packet.")
        return out
    if row["research_status"] != RESEARCH_COMPLETE:
        relationships = row["tracking"].get("relationships") or []
        tracked = [rel for rel in relationships if rel.get("state") == "Tracked"]
        through = ", ".join(rel.get("sector_slug") or "standalone" for rel in tracked)
        out = [f"  {_RELATION_TAG.get(row['relation'], row['relation'])} {_name(row)} "
               f"- {NOT_YET_ASSESSED}  [{row['change']}]",
               f"      research tracking: {through or 'no active relationship'}"]
        for rel in relationships:
            scope = rel.get("sector_slug") or "standalone"
            out.append(f"      {rel.get('state')}: {scope} — {rel.get('reason')}")
        if tracked:
            out.append("      -> monitor the relationship; do not size or treat it as research coverage.")
        else:
            out.append("      -> relationship reviewed as Untracked; no company assessment or size.")
        return out
    if row.get("listed") is False:
        view = row.get("private_research_view") or {}
        context = row.get("private_context") or {}
        boat = context.get("boat") or {}
        freshness = context.get("freshness") or {}
        gaps = [*(context.get("source_gaps") or []), *(context.get("unknowns") or [])]
        return [
            f"  {_RELATION_TAG.get(row['relation'], row['relation'])} {_name(row)} "
            f"- {view.get('status')}  [{row['change']}]",
            f"      private research view: {view.get('reasoning')}",
            f"      as of {view.get('as_of')} | horizon {view.get('horizon')} | "
            f"review by {view.get('review_by')}",
            f"      Boat: {boat.get('status')} — {boat.get('reasoning')}",
            f"      website evidence refreshed {freshness.get('website_retrieved_at')}",
            *( [f"      gaps: {'; '.join(gaps)}"] if gaps else [] ),
            "      -> context only; no portfolio action, position size, funding source or trade.",
        ]
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
        lines.append("New, updated, or ended (surface these):")
        for row in flagged:
            lines.extend(_detail_lines(row))
    else:
        lines.append("New, updated, or ended: none.")

    if unchanged:
        lines.append("")
        lines.append("Already seen (unchanged since last check):")
        for row in unchanged:
            if has_ended_coverage(row):
                value = f"Coverage ended {row['coverage']['ended_on']}"
            elif row["research_status"] == RESEARCH_COMPLETE:
                value = row["value"]
            else:
                state = "Tracked" if row["tracking"]["globally_tracked"] else "Untracked"
                value = f"{NOT_YET_ASSESSED} ({state})"
            lines.append(f"  {_RELATION_TAG.get(row['relation'], row['relation'])} "
                         f"{_name(row)} - {value}")

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


# --- feed loader (shared by main + the detail-view / events digest) --------

class FeedError(Exception):
    """Raised when the research feed cannot be read. `code` is the process exit
    code main() should return (missing manifest -> 2, unparseable -> 1)."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def load_feed(client: str, config_path: Path = DEFAULT_RESEARCH_CONFIG,
              research_override: str | None = None):
    """Resolve the research repo, load the manifest, reconcile it against one
    client's book, and classify every manifest record.

    Returns (rows, held, watched, manifest_updated, research_path):
    - rows: one classified entry per completed or tracking-only manifest name.
      - held / watched: the client's own {(market, ticker)} sets, which may
        include names the research house does NOT cover.
      - research_path: the resolved Veda-research repo (for packet reads).
    Raises FeedError on a missing (code 2) or unparseable (code 1) manifest.
    """
    research = resolve_research_path(config_path, research_override)
    manifest_path = research / "published" / "manifest.yaml"
    if not manifest_path.exists():
        raise FeedError(f"research manifest not found: {manifest_path}", code=2)
    try:
        doc = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise FeedError(f"could not parse manifest: {error}", code=1)
    if not isinstance(doc, dict):
        raise FeedError("invalid research manifest: root must be a mapping", code=1)
    schema_version = doc.get("schema_version")
    if schema_version != MANIFEST_SCHEMA_VERSION:
        raise FeedError(
            f"unsupported research manifest schema {schema_version!r}; "
            f"expected {MANIFEST_SCHEMA_VERSION}",
            code=1,
        )
    entries = doc.get("entries")
    if not isinstance(entries, list):
        raise FeedError("invalid research manifest: entries must be a list", code=1)
    manifest_updated = doc.get("updated")

    root = client_root(client)
    assets_path = root / "assets.md"
    seen_path = root / "research-seen.json"

    positions = read_assets_positions(assets_path) if assets_path.exists() else {}
    held = {key for key, shares in positions.items() if abs(shares) > EPSILON}
    watched = read_watchlist(assets_path)
    seen = load_seen(seen_path)

    try:
        rows = classify(entries, held, watched, seen, schema_version=schema_version)
    except ValueError as error:
        raise FeedError(f"invalid research manifest: {error}", code=1) from error
    return rows, held, watched, manifest_updated, research


# --- command-line run ------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read the shared research dataset and reconcile it against one client's book."
    )
    parser.add_argument("--client", default="default", help="which client's book (default: default)")
    parser.add_argument("--research-path", default=None,
                        help="path to the Veda-research repo (overrides research.json)")
    parser.add_argument("--config", type=Path, default=DEFAULT_RESEARCH_CONFIG,
                        help="research.json path")
    parser.add_argument("--mark-seen", action="store_true",
                        help="record current row revisions so they are not re-flagged next session")
    args = parser.parse_args(argv)

    try:
        rows, _held, _watched, manifest_updated, _research = load_feed(
            args.client, args.config, args.research_path)
    except FeedError as error:
        print(str(error), file=sys.stderr)
        return error.code

    print(format_report(rows, args.client, manifest_updated))

    if args.mark_seen:
        seen_path = client_root(args.client) / "research-seen.json"
        cursor = {
            "manifest_updated": str(manifest_updated) if manifest_updated is not None else None,
            "seen": {row["slug"]: row["revision"] for row in rows},
        }
        seen_path.parent.mkdir(parents=True, exist_ok=True)
        seen_path.write_text(json.dumps(cursor, indent=2) + "\n", encoding="utf-8")
        print(f"\nMarked {len(rows)} research record(s) as seen for client '{args.client}'.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
