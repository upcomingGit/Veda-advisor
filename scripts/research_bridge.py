"""
Veda - research bridge.

Brings the numbers Veda-research already worked out for a cohort into the
advisor, so the cohort screen can read them. It asks Veda-research for each name
in a cohort, takes the fundamentals it returns, and writes one small data file
per name under screen/data/<TICKER>.json - the exact file the screen reads.

This is the one-step handoff. Without it you run the research fetch by hand for
each name and copy the numbers across. The boundary stays the firm's rule:
research gathers and computes; the advisor takes what research produced and
applies your filters later, in the screen. The bridge itself judges nothing and
computes no valuation. It copies research's own numbers, including the valuation
zones research worked out and the thresholds behind each one, so you can see
exactly how a zone was reached.

How it asks: it runs Veda-research's fundamentals command once per name, in the
research folder you point it at (internal/research.json, or --research-path).
Each name in the cohort names its market plainly - "india" or "us" - next to a
bare ticker (INDIGO, not INDIGO.NS), the same way holdings do; the bridge
forwards that market so research fetches from the right place. When a cohort
name carries an archetype, the bridge forwards that label too, so research
returns the valuation zone measured against it. The advisor never picks the
market or the archetype; both are research's, recorded next to the ticker the
same way the ticker itself is copied in from a dossier.

The mapping core (map_to_screen_data) is pure: it takes one research output as a
plain dict and returns the screen's data shape, so tests feed fixed numbers and
never touch the network or the research folder. Only the command-line run shells
out to research and writes files.

Examples (from a terminal in the Veda-advisor folder):

    python scripts/research_bridge.py --cohort airlines-india

Exit codes:
    0 - the run finished; some names may be gaps (see the report)
    1 - could not run (bad cohort or config, or research failed for every name)
    2 - cohort file missing
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Repo root is the parent of scripts/.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COHORTS = REPO_ROOT / "internal" / "cohorts"
DEFAULT_DATA_DIR = REPO_ROOT / "screen" / "data"
DEFAULT_RESEARCH_CONFIG = REPO_ROOT / "internal" / "research.json"

# Where the Veda-research repo sits if internal/research.json does not say.
# The two repos are kept side by side, so the sibling folder is the default.
DEFAULT_RESEARCH_PATH = "../veda-ai-research-team"

# The Veda-research command the bridge calls, relative to the research folder.
FETCH_SCRIPT = "scripts/fetch_fundamentals.py"

# How long to wait for one name before giving up on it.
CALL_TIMEOUT_SECONDS = 180

# The archetype labels research understands. The bridge only checks the label
# is one of these before forwarding it; it never decides which one applies.
ARCHETYPES = {"GROWTH", "INCOME_VALUE", "TURNAROUND", "CYCLICAL"}

# Market from the currency research reports, with a ticker-suffix fallback.
CURRENCY_TO_MARKET = {"INR": "india", "USD": "us"}
INDIA_SUFFIXES = (".NS", ".BO")

# The form the research fetch wants for its --market flag, by our market name.
MARKET_TO_FETCH_FLAG = {"india": "IN", "us": "US"}

# How a cohort entry may spell its market, mapped to the two we use.
_MARKET_ALIASES = {
    "india": "india", "in": "india", "ind": "india", "nse": "india", "bse": "india",
    "us": "us", "usa": "us", "united states": "us", "nasdaq": "us", "nyse": "us",
}


class BridgeError(Exception):
    """Raised when one research call cannot be turned into usable data."""


# --- the mapping core (pure: numbers in, the screen's shape out) -----------

def _market(currency: Optional[str], ticker: str) -> Optional[str]:
    """The market the screen expects (india/us), from the currency or the ticker."""
    if currency:
        mapped = CURRENCY_TO_MARKET.get(currency.upper())
        if mapped:
            return mapped
    upper = ticker.upper()
    if any(upper.endswith(suffix) for suffix in INDIA_SUFFIXES):
        return "india"
    return "us"


def read_market(entry: dict, ticker: str) -> Optional[str]:
    """The market for one cohort name: the entry's own `market` field first.

    A cohort entry names its market plainly - "india" or "us" - next to the
    ticker, the same way holdings do. Bare tickers carry no suffix to read, so
    the field is how the bridge knows where a name trades. When the field is
    missing the bridge falls back to the bundled bare-ticker table, and only
    then (later, in map_to_screen_data) to the currency research reports.
    Returns "india", "us", or None when nothing settles it.
    """
    raw = entry.get("market")
    if raw:
        return _MARKET_ALIASES.get(str(raw).strip().lower())
    # No usable field - try the bundled bare-ticker table, the same source
    # the quote fetcher uses. A missing table just means no fallback here.
    try:
        from ticker_market_lookup import lookup_market
        return lookup_market(ticker)
    except Exception:
        return None


def _zone_entry(block: dict, role: str) -> dict:
    """One valuation-zone row, copied from a research zone block. Computes nothing."""
    return {
        "archetype": block.get("archetype"),
        "role": role,
        "zone": block.get("zone"),
        "primary_metric": block.get("primary_metric"),
        "primary_metric_value": block.get("primary_metric_value"),
        "thresholds": block.get("zone_thresholds"),
        "percentile_basis": block.get("percentile_basis"),
    }


def map_to_screen_data(output: dict, ticker: str, market: Optional[str] = None) -> dict:
    """Turn one Veda-research fundamentals output into the screen's data shape.

    Pure: every number comes from `output`. The advisor copies; it does not
    recompute a single value. `output` is the JSON the research fetch prints for
    one name. The returned dict is what gets written to screen/data/<TICKER>.json.

    `market` is the cohort's own market for the name ("india"/"us"); when given
    it is used as-is, since the cohort states it plainly. When it is not given
    the market is read from the currency research reported, falling back to the
    ticker itself.
    """
    derived = output.get("derived_ratios") or {}
    valuation = output.get("valuation") or {}

    multiples = {
        "pe": valuation.get("current_pe"),
        "pb": valuation.get("current_pb"),
        "ps": valuation.get("current_ps"),
        "peg": valuation.get("current_peg"),
        "ev_ebitda": valuation.get("current_ev_ebitda"),
    }

    # A zone is present only when research was given an archetype to measure
    # against. The zone value itself can still be null (research could not place
    # it); the bridge carries that through, with the thresholds, unchanged.
    zones: list[dict] = []
    if valuation.get("archetype"):
        zones.append(_zone_entry(valuation, "primary"))
    secondary = valuation.get("secondary") or {}
    if secondary.get("archetype"):
        zones.append(_zone_entry(secondary, "secondary"))

    return {
        "ticker": ticker.upper(),
        "market": market or _market(output.get("currency"), ticker),
        "as_of": output.get("as_of"),
        "roce_pct": derived.get("roce_ttm_pct"),
        "roe_pct": derived.get("roe_ttm_pct"),
        "debt_to_equity": derived.get("debt_to_equity"),
        "trailing_growth_pct": valuation.get("trailing_growth_pct"),
        "fcf_yield_pct": derived.get("fcf_yield_pct"),
        "valuation": {
            "multiples": multiples,
            "zones": zones,
        },
    }


# --- the call seam (asks research and gets one JSON output back) ------------

def call_research(
    repo_path: Path,
    python_cmd: str,
    ticker: str,
    primary: Optional[str] = None,
    secondary: Optional[str] = None,
    market: Optional[str] = None,
    timeout: int = CALL_TIMEOUT_SECONDS,
) -> dict:
    """Run the research fetch for one name and return its parsed JSON output.

    This is the whole of how the advisor reaches the research repo: one command,
    run in the research folder, its printed JSON read back. A failed run or
    unreadable output raises BridgeError so the caller can record it as a gap.

    `market` ("india"/"us") is forwarded as the fetch's --market flag, so a bare
    ticker like INDIGO is read on the right market instead of being guessed from
    its (absent) suffix. When the market is unknown the flag is left off and the
    fetch falls back to its own suffix detection.
    """
    command = [python_cmd, FETCH_SCRIPT, "--ticker", ticker]
    fetch_flag = MARKET_TO_FETCH_FLAG.get(market or "")
    if fetch_flag:
        command += ["--market", fetch_flag]
    if primary:
        command += ["--archetype", primary]
        if secondary:
            command += ["--archetype-secondary", secondary]

    try:
        result = subprocess.run(
            command,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as error:
        raise BridgeError(f"could not start the research command ({python_cmd}): {error}")
    except subprocess.TimeoutExpired:
        raise BridgeError(f"the research call timed out after {timeout}s")

    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        last = detail[-1] if detail else f"exit code {result.returncode}"
        raise BridgeError(f"research could not return data: {last}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise BridgeError("research output was not readable JSON")


# --- reading the cohort and its research-authored labels -------------------

def _clean_label(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return str(value).strip().upper()


def read_labels(entry: dict) -> tuple[Optional[str], Optional[str], list[str]]:
    """Pull the research-authored archetype labels off one cohort name.

    Returns (primary, secondary, notes). A label that is not one research
    understands is dropped with a note rather than passed on. A secondary equal
    to the primary is dropped (research needs two distinct lenses).
    """
    notes: list[str] = []
    primary = _clean_label(entry.get("primary"))
    secondary = _clean_label(entry.get("secondary"))

    if primary and primary not in ARCHETYPES:
        notes.append(f"primary archetype '{primary}' is not one research knows; ignored")
        primary = None
    if secondary and secondary not in ARCHETYPES:
        notes.append(f"secondary archetype '{secondary}' is not one research knows; ignored")
        secondary = None
    if secondary and not primary:
        notes.append("secondary archetype ignored because there is no primary")
        secondary = None
    if secondary and secondary == primary:
        notes.append("secondary archetype dropped because it matches the primary")
        secondary = None
    return primary, secondary, notes


def _zone_gap_note(data: dict) -> Optional[str]:
    """Say which valuation zone is missing, so the report can flag it as a gap."""
    if not data["valuation"]["zones"]:
        return "no valuation zone (add a primary archetype to this cohort name)"
    missing = [z["archetype"] for z in data["valuation"]["zones"] if z.get("zone") is None]
    if missing:
        return "valuation zone not placed for " + ", ".join(missing)
    return None


# --- config (where the research folder is) ---------------------------------

def load_research_config(path: Path) -> dict:
    """Read internal/research.json, falling back to the sibling folder default."""
    config = {}
    if path.exists():
        config = json.loads(path.read_text(encoding="utf-8"))
    return {
        "research_repo_path": config.get("research_repo_path") or DEFAULT_RESEARCH_PATH,
        # A null or missing python means "the interpreter running the advisor".
        "python": config.get("python") or sys.executable,
    }


def _resolve_repo_path(raw: str) -> Path:
    """A relative research path is read against the advisor repo root."""
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    return candidate.resolve()


def _resolve_cohort_path(cohort: str, cohorts_dir: Path) -> Path:
    """Accept either a sector name (airlines-india) or a path to a cohort file."""
    candidate = Path(cohort)
    if candidate.suffix == ".json" and candidate.exists():
        return candidate
    return cohorts_dir / f"{cohort}.json"


# --- command-line run ------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bring Veda-research's fundamentals for a cohort into screen/data.",
    )
    parser.add_argument("--cohort", required=True,
                        help="cohort sector name (e.g. airlines-india) or a path to a cohort file")
    parser.add_argument("--cohorts-dir", type=Path, default=DEFAULT_COHORTS, help="cohorts folder")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                        help="where to write one data file per name")
    parser.add_argument("--research-config", type=Path, default=DEFAULT_RESEARCH_CONFIG,
                        help="config file naming the research folder")
    parser.add_argument("--research-path", default=None,
                        help="research folder, overriding the config file")
    parser.add_argument("--timeout", type=int, default=CALL_TIMEOUT_SECONDS,
                        help="seconds to wait for one name before giving up on it")
    args = parser.parse_args(argv)

    cohort_path = _resolve_cohort_path(args.cohort, args.cohorts_dir)
    if not cohort_path.exists():
        print(f"cohort file not found: {cohort_path}", file=sys.stderr)
        return 2

    try:
        cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
        config = load_research_config(args.research_config)
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1

    repo_path = _resolve_repo_path(args.research_path or config["research_repo_path"])
    python_cmd = config["python"]
    if not (repo_path / FETCH_SCRIPT).exists():
        print(f"research fetch not found at {repo_path / FETCH_SCRIPT}", file=sys.stderr)
        print("set the research folder in internal/research.json or pass --research-path",
              file=sys.stderr)
        return 1

    sector = cohort.get("sector") or cohort_path.stem
    names = cohort.get("names", [])
    if not names:
        print(f"cohort {sector} has no names", file=sys.stderr)
        return 1

    args.data_dir.mkdir(parents=True, exist_ok=True)

    written: list[dict] = []
    zone_gaps: list[dict] = []
    failed: list[dict] = []

    for entry in names:
        ticker = entry["ticker"]
        market = read_market(entry, ticker)
        primary, secondary, label_notes = read_labels(entry)
        try:
            output = call_research(
                repo_path, python_cmd, ticker, primary, secondary, market, args.timeout
            )
        except BridgeError as error:
            failed.append({"ticker": ticker, "reason": str(error)})
            continue

        data = map_to_screen_data(output, ticker, market)
        out_path = args.data_dir / f"{ticker.upper()}.json"
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append({"ticker": ticker, "notes": label_notes})

        gap = _zone_gap_note(data)
        if gap:
            zone_gaps.append({"ticker": ticker, "missing": gap})

    print(_report(sector, args.data_dir, written, zone_gaps, failed))
    if failed and not written:
        return 1
    return 0


def _report(sector: str, data_dir: Path, written: list, zone_gaps: list, failed: list) -> str:
    """A plain-text summary of what the run wrote and what is still a gap."""
    lines: list[str] = []
    lines.append(f"Research bridge: {sector}")
    lines.append(f"  wrote {len(written)} data file(s) to {data_dir}")

    if written:
        lines.append("")
        lines.append("Written:")
        for item in written:
            lines.append(f"  {item['ticker']}")
            for note in item["notes"]:
                lines.append(f"       note: {note}")

    if zone_gaps:
        lines.append("")
        lines.append("Zone gaps (data written, but a valuation zone is missing):")
        for item in zone_gaps:
            lines.append(f"  {item['ticker']}: {item['missing']}")

    if failed:
        lines.append("")
        lines.append("Failed (no data written; research could not return it):")
        for item in failed:
            lines.append(f"  {item['ticker']}: {item['reason']}")

    lines.append("")
    lines.append("The bridge copies research's numbers; it judges and computes nothing.")
    lines.append("  Next, run the screen on this cohort to filter what was written.")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
