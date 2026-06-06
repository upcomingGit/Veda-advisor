"""
Veda - cohort screen.

Takes a list of companies in one sector (the cohort) and turns it into a ranked
shortlist. It answers one question: of all the names in this sector, which ones
clear my rules, and in what order do they look most worth a closer read.

This is research support, not a buy list. It never proposes a trade. It orders
names for a person to read.

See internal/screen-schema.md for the full contract.

The advisor does no research of its own. It reads the fundamentals the
Veda-research agent has already produced and applies your filters and ranking to
them. It never fetches: gathering research data is Veda-research's job. A name
with no saved research data is a data gap, never a fetch.

The scoring core (build_screen) takes the saved numbers and the rules as plain
arguments, so tests feed fixed numbers and never touch disk or the network. The
command-line run only reads the saved data files from disk.

Examples (from a terminal in the Veda-advisor folder):

    python scripts/screen.py --cohort airlines-india

Exit codes:
    0 - screen written
    1 - could not compute (bad cohort or rules file, empty cohort)
    2 - cohort file missing
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

# Repo root is the parent of scripts/.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCREEN = REPO_ROOT / "internal" / "screen.json"
DEFAULT_COHORTS = REPO_ROOT / "internal" / "cohorts"
DEFAULT_DATA_DIR = REPO_ROOT / "screen" / "data"
DEFAULT_OUT_DIR = REPO_ROOT / "screen"

EPSILON = 1e-9
FRESHNESS_DAYS = 90       # fundamentals are quarterly, so a wider window than prices.

# Sensible starting rules if the screen file is absent. Numbers start unset
# (None) so an empty rules file excludes nothing; the user fills them in.
DEFAULT_FILTERS = {
    "min_roce_pct": None,
    "max_debt_to_equity": None,
}


# --- reading the rules file ------------------------------------------------

def load_screen(path: Path) -> dict:
    """Read internal/screen.json and fill in defaults for anything missing.

    The screen is filter-only: a name either clears the filters or it does not.
    Any older `weights` block in the file is ignored.
    """
    config = {}
    if path.exists():
        config = json.loads(path.read_text(encoding="utf-8"))
    filters = dict(DEFAULT_FILTERS)
    filters.update(config.get("filters", {}))
    return {"filters": filters}


# --- small helpers ---------------------------------------------------------

def _age_days(data_date: Optional[str], run_date: str) -> Optional[int]:
    """Days between a saved number's date and the run date, or None if unknown."""
    if not data_date:
        return None
    try:
        then = date.fromisoformat(str(data_date)[:10])
        now = date.fromisoformat(str(run_date)[:10])
    except ValueError:
        return None
    return (now - then).days


# --- the filters -----------------------------------------------------------

def apply_filters(data: dict, filters: dict) -> tuple[list[str], list[str]]:
    """Check one name against the hard filters.

    Returns (fail_reasons, gap_reasons). A fail means the name breaks a rule it
    could be checked against. A gap means the number a rule needs is missing, so
    the rule could not be checked - never read as a pass or a fail.
    """
    fails: list[str] = []
    gaps: list[str] = []

    min_roce = filters.get("min_roce_pct")
    if min_roce is not None:
        value = data.get("roce_pct")
        if value is None:
            gaps.append("return on capital missing for the minimum-ROCE filter")
        elif value < min_roce:
            fails.append(f"return on capital {value:.1f}% below the minimum {min_roce:.1f}%")

    max_de = filters.get("max_debt_to_equity")
    if max_de is not None:
        value = data.get("debt_to_equity")
        if value is None:
            gaps.append("debt-to-equity missing for the maximum-debt filter")
        elif value > max_de:
            fails.append(f"debt-to-equity {value:.2f} above the maximum {max_de:.2f}")

    return fails, gaps


# --- the filter core -------------------------------------------------------

def build_screen(
    sector: str,
    tickers: list[str],
    data_by_ticker: dict[str, Optional[dict]],
    config: dict,
    as_of: str,
    freshness_days: int = FRESHNESS_DAYS,
) -> dict:
    """Filter a cohort down to the names that clear every rule. Pure: every
    number comes from the arguments.

    tickers is the cohort, in file order. data_by_ticker maps a ticker to its
    saved numbers (or None when no data could be found). config is the parsed
    rules file (filters only). Survivors are listed alphabetically; the screen
    does not rank or score them.
    """
    filters = config["filters"]

    survivors: list[dict] = []
    excluded: list[dict] = []
    data_gaps: list[dict] = []

    for ticker in tickers:
        data = data_by_ticker.get(ticker)
        if data is None:
            data_gaps.append({"ticker": ticker, "market": None,
                              "missing": "no research data; run the bridge on this cohort first"})
            continue

        fails, gaps = apply_filters(data, filters)
        market = data.get("market")
        if fails:
            excluded.append({"ticker": ticker, "market": market, "reason": "; ".join(fails)})
        elif gaps:
            data_gaps.append({"ticker": ticker, "market": market, "missing": "; ".join(gaps)})
        else:
            survivors.append(data)

    for item in survivors:
        age = _age_days(item.get("as_of"), as_of)
        item["stale"] = age is not None and age > freshness_days

    survivors.sort(key=lambda item: item["ticker"])

    return {
        "sector": sector,
        "as_of": as_of,
        "freshness_days": freshness_days,
        "filters": filters,
        "survivors": survivors,
        "excluded": excluded,
        "data_gaps": data_gaps,
        "stale": any(item["stale"] for item in survivors),
        "scope_note": (
            "This screen lists the names in a cohort that clear your filters. It "
            "does not rank, score, find ideas, or propose trades. To act on a "
            "name, research it in Veda first."
        ),
    }


# --- readable report -------------------------------------------------------

def _valuation_lines(item: dict) -> list[str]:
    """The display-only valuation block for one survivor: multiples and zones.

    Valuation does not filter. It is shown so you can read a name on whichever
    lens fits it. Each zone names the metric and the thresholds research used,
    so how the zone was reached is visible, not hidden.
    """
    valuation = item.get("valuation") or {}
    multiples = valuation.get("multiples") or {}
    zones = valuation.get("zones") or []
    if not multiples and not zones:
        return []

    lines = ["       valuation (shown for context):"]
    labels = [("pe", "PE"), ("pb", "PB"), ("ps", "PS"),
              ("peg", "PEG"), ("ev_ebitda", "EV/EBITDA")]
    parts = [f"{label} {multiples[key]}" for key, label in labels
             if multiples.get(key) is not None]
    if parts:
        lines.append("         multiples: " + ", ".join(parts))
    for z in zones:
        zone = z.get("zone") or "not placed"
        metric = z.get("primary_metric")
        value = z.get("primary_metric_value")
        basis = f" by {metric} {value}" if metric is not None else ""
        thresholds = z.get("thresholds")
        thresh = f"; thresholds {json.dumps(thresholds)}" if thresholds else ""
        lines.append(f"         {z.get('archetype')} ({z.get('role')}): {zone}{basis}{thresh}")
    return lines


def format_report(report: dict) -> str:
    """A plain-text table of the screen for standard output."""
    lines: list[str] = []
    lines.append(f"Cohort screen: {report['sector']} (as of {report['as_of']})")
    if report["stale"]:
        lines.append(f"  WARNING: a survivor's numbers are more than {report['freshness_days']} days old.")

    filters = report["filters"]
    lines.append("")
    lines.append("Rules in force:")
    min_roce = filters.get("min_roce_pct")
    max_de = filters.get("max_debt_to_equity")
    lines.append(f"  Minimum return on capital: {min_roce:.1f}%" if min_roce is not None
                 else "  Minimum return on capital: off (not set)")
    lines.append(f"  Maximum debt-to-equity:    {max_de:.2f}" if max_de is not None
                 else "  Maximum debt-to-equity:    off (not set)")

    lines.append("")
    lines.append("Names that cleared the filters:")
    if report["survivors"]:
        lines.append(
            f"  {'#':>2} {'name':<12} {'market':<6} "
            f"{'ROCE':>7} {'D/E':>6} {'growth':>7} {'FCF%':>6}"
        )
        for position, item in enumerate(report["survivors"], start=1):
            roce = f"{item['roce_pct']:.1f}%" if item.get("roce_pct") is not None else "-"
            de = f"{item['debt_to_equity']:.2f}" if item.get("debt_to_equity") is not None else "-"
            gr = f"{item['trailing_growth_pct']:.1f}%" if item.get("trailing_growth_pct") is not None else "-"
            fcf = f"{item['fcf_yield_pct']:.1f}" if item.get("fcf_yield_pct") is not None else "-"
            stale = "  (stale)" if item["stale"] else ""
            lines.append(
                f"  {position:>2} {item['ticker']:<12} {str(item.get('market') or '-'):<6} "
                f"{roce:>7} {de:>6} {gr:>7} {fcf:>6}{stale}"
            )
            for line in _valuation_lines(item):
                lines.append(line)
    else:
        lines.append("  (no name cleared the filters)")

    if report["excluded"]:
        lines.append("")
        lines.append("Excluded (failed a filter):")
        for item in report["excluded"]:
            lines.append(f"  {item['ticker']} ({item.get('market') or '-'}): {item['reason']}")

    if report["data_gaps"]:
        lines.append("")
        lines.append("Data gaps (a number was missing, so the name was set aside):")
        for item in report["data_gaps"]:
            lines.append(f"  {item['ticker']} ({item.get('market') or '-'}): {item['missing']}")

    lines.append("")
    lines.append("Scope: this screen lists the names in a cohort that clear your filters.")
    lines.append("  It does not rank, score, find ideas, or propose trades. To act on a")
    lines.append("  name, research it in Veda first.")

    return "\n".join(lines)


# --- command-line run (reads the cohort, the rules, and the research data) --

def _data_path(data_dir: Path, ticker: str) -> Path:
    return data_dir / f"{ticker.upper()}.json"


def load_saved(ticker: str, data_dir: Path) -> Optional[dict]:
    """Read one name's saved research data, or None if Veda-research has not produced it.

    The advisor never gathers this data. Each file is the Veda-research agent's
    fundamentals output for one name, placed under the data folder. A missing or
    unreadable file is a data gap; the screen reports it for you to fix by
    running Veda-research on the cohort.
    """
    path = _data_path(data_dir, ticker)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _resolve_cohort_path(cohort: str, cohorts_dir: Path) -> Path:
    """Accept either a sector name (airlines-india) or a path to a cohort file."""
    candidate = Path(cohort)
    if candidate.suffix == ".json" and candidate.exists():
        return candidate
    return cohorts_dir / f"{cohort}.json"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Veda cohort screen.")
    parser.add_argument("--cohort", required=True,
                        help="cohort sector name (e.g. airlines-india) or a path to a cohort file")
    parser.add_argument("--screen", type=Path, default=DEFAULT_SCREEN, help="rules file")
    parser.add_argument("--cohorts-dir", type=Path, default=DEFAULT_COHORTS, help="cohorts folder")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                        help="folder of Veda-research data files, one per name")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="screen output folder")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="run date YYYY-MM-DD")
    parser.add_argument("--freshness-days", type=int, default=FRESHNESS_DAYS,
                        help="flag saved numbers older than this many days as stale")
    args = parser.parse_args(argv)

    cohort_path = _resolve_cohort_path(args.cohort, args.cohorts_dir)
    if not cohort_path.exists():
        print(f"cohort file not found: {cohort_path}", file=sys.stderr)
        return 2

    try:
        cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
        config = load_screen(args.screen)
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1

    sector = cohort.get("sector") or cohort_path.stem
    names = cohort.get("names", [])
    if not names:
        print(f"cohort {sector} has no names", file=sys.stderr)
        return 1

    tickers: list[str] = []
    data_by_ticker: dict[str, Optional[dict]] = {}
    for entry in names:
        ticker = entry["ticker"]
        tickers.append(ticker)
        data_by_ticker[ticker] = load_saved(ticker, args.data_dir)

    report = build_screen(sector, tickers, data_by_ticker, config, args.as_of, args.freshness_days)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"{sector}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(format_report(report))
    print(f"\nwrote screen to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
