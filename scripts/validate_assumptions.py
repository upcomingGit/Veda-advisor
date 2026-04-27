"""
Veda - assumptions validator.

Validates holdings/<slug>/assumptions.yaml against the rules in
internal/holdings-schema.md § "Writing assumptions and checkpoints —
guardrails (validator-enforced)". Reads the workspace's _meta.yaml for
archetype and market context.

Pure stdlib. No PyYAML — line-by-line block extraction plus regex against
the known schema, matching the portability discipline of validate_profile.py.

Usage:

    python scripts/validate_assumptions.py holdings/<slug>/assumptions.yaml

Exit codes:
    0 - valid
    1 - validation failed; errors printed to stderr
    2 - file missing or unreadable

The script is intentionally strict. If you think an error is wrong, the fix
is almost always to correct the assumptions.yaml, not to relax the validator.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# -------- Allowed enums --------

VALID_CATEGORIES = {"GROWTH", "FINANCIAL_HEALTH", "COMPETITIVE", "GOING_CONCERN"}
VALID_METRIC_SOURCES = {"consolidated", "non_financial"}
VALID_MARKETS = {"US", "IN"}
VALID_ARCHETYPES = {"GROWTH", "INCOME_VALUE", "TURNAROUND", "CYCLICAL"}

# Required slot allocation per archetype (strict counts).
SLOT_ALLOCATION: dict[str, dict[str, int]] = {
    "GROWTH":       {"GROWTH": 2, "FINANCIAL_HEALTH": 1, "COMPETITIVE": 0, "GOING_CONCERN": 1},
    "INCOME_VALUE": {"GROWTH": 1, "FINANCIAL_HEALTH": 2, "COMPETITIVE": 0, "GOING_CONCERN": 1},
    "TURNAROUND":   {"GROWTH": 1, "FINANCIAL_HEALTH": 1, "COMPETITIVE": 1, "GOING_CONCERN": 1},
    "CYCLICAL":     {"GROWTH": 1, "FINANCIAL_HEALTH": 1, "COMPETITIVE": 1, "GOING_CONCERN": 1},
}

# Banned metrics in quarterly_checkpoint (case-insensitive substring match).
# These are NOT parseable from the consolidated quarterly P&L, OR they are
# better captured in transcript_checkpoint (segment metrics, KPIs from the
# call), OR they belong to a different reporting surface entirely.
BANNED_BOTH = [
    "arpac", "arpu", "segment revenue", "subscriber count", "deal tcv",
    "ebitda", "efficiency ratio", "order book", "market share",
    "utilization", "nim", "gnpa", "casa", "debtor days",
    "debt-to-equity", "interest coverage", "inventory turnover",
    "promoter shareholding", "esg score", "employee count", "store count",
    "capacity utilization", "borrowings",
]

# Additionally banned for Indian companies (these ARE in the US Screener-equivalent
# quarterly schema, but NOT in Screener.in's Indian quarterly schema).
BANNED_INDIAN_ONLY = [
    "gross profit", "gross margin",
    "operating cash flow", "ocf",
    "capex", "capital expenditure",
    "free cash flow", "fcf",
]

# Whitelisted primary-metric phrase recognition. Order matters: longer /
# more-specific patterns first. Each tuple is (compiled regex, normalised name).
# Word boundaries used to avoid e.g. "growth" matching inside "ungrowth" or
# "eps" matching inside "epsilon".
PRIMARY_METRIC_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brevenue\s+growth\b", re.IGNORECASE),               "Revenue growth %"),
    (re.compile(r"\boperating\s+profit\s+growth\b", re.IGNORECASE),    "Operating Profit growth %"),
    (re.compile(r"\bnet\s+profit\s+growth\b", re.IGNORECASE),          "Net Profit growth %"),
    (re.compile(r"\bopm\b", re.IGNORECASE),                             "OPM%"),
    (re.compile(r"\boperating\s+margin\b", re.IGNORECASE),             "OPM%"),
    (re.compile(r"\bgross\s+margin\b", re.IGNORECASE),                 "Gross Margin %"),
    (re.compile(r"\bgross\s+profit\b", re.IGNORECASE),                 "Gross Profit"),
    (re.compile(r"\bfree\s+cash\s+flow\b|\bfcf\b", re.IGNORECASE),     "Free Cash Flow"),
    (re.compile(r"\boperating\s+cash\s+flow\b|\bocf\b", re.IGNORECASE),"Operating Cash Flow"),
    (re.compile(r"\bcapex\b|\bcapital\s+expenditure\b", re.IGNORECASE),"CapEx"),
    (re.compile(r"\boperating\s+profit\b", re.IGNORECASE),             "Operating Profit"),
    (re.compile(r"\bnet\s+profit\b", re.IGNORECASE),                   "Net Profit"),
    (re.compile(r"\beps\b", re.IGNORECASE),                             "EPS"),
    (re.compile(r"\brevenue\b", re.IGNORECASE),                         "Revenue"),
]

# An inline citation: any parenthesised group containing either at least one
# digit OR at least 8 characters of content. Pure unit annotations like
# "(₹ Cr)" or "($)" are short and digit-free, so they do not count as
# grounding citations.
CITATION_PATTERN = re.compile(r"\((?:[^()]*\d+[^()]*|[^()]{8,})\)")

# Field names expected on every assumption block.
REQUIRED_FIELDS = [
    "text",
    "category",
    "quarterly_checkpoint",
    "transcript_checkpoint",
    "thesis_horizon_target",
    "checkpoint_metric_source",
]

EXPECTED_KEYS = ["A1", "A2", "A3", "A4"]


# -------- Helpers --------


def find_top_field(text: str, key: str) -> str | None:
    """Find a top-level scalar `key: value` (no leading whitespace)."""
    pattern = re.compile(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*(?:#.*)?$")
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def find_assumption_block(text: str, key: str) -> str | None:
    """Return the indented block under `  <key>:` (2-space indent), excluding
    the key line itself. Returns None if the key is not found.

    The block ends at the next sibling key (any line with exactly 2 leading
    spaces and a colon, e.g. `  A2:` or `  quarters:` doesn't apply because
    `quarters:` is at column 0), or at a top-level (column 0) non-blank line,
    or at end-of-file.
    """
    target = f"  {key}:"
    lines = text.splitlines(keepends=False)
    out: list[str] = []
    in_block = False
    for line in lines:
        if not in_block:
            if line == target or line.startswith(target + " "):
                in_block = True
            continue
        # We are inside the block. Decide whether to keep the line or stop.
        if line.strip() == "":
            out.append(line)
            continue
        # Count leading spaces
        leading = len(line) - len(line.lstrip(" "))
        if leading == 0:
            # Top-level key line — block ended.
            break
        if leading == 2:
            # Sibling key (another A2:, A3:, etc.) — block ended.
            break
        # leading >= 4 — still inside the block.
        out.append(line)
    if not in_block:
        return None
    return "\n".join(out)


def field_in_block(block: str, field: str) -> str | None:
    """Find `    field: value` in an assumption block. Returns the value with
    surrounding quotes stripped, or None if the field is absent.

    Inline `# comment` after a non-quoted scalar is stripped. Inside a quoted
    value, `#` is preserved verbatim.
    """
    pattern = re.compile(rf"(?m)^    {re.escape(field)}:[ \t]*(.*)$")
    m = pattern.search(block)
    if not m:
        return None
    raw = m.group(1).strip()
    # If quoted, return the unquoted contents (preserving any '#' inside).
    if len(raw) >= 2 and raw[0] == '"' and raw.endswith('"'):
        return raw[1:-1]
    if len(raw) >= 2 and raw[0] == "'" and raw.endswith("'"):
        return raw[1:-1]
    # Unquoted: strip an inline comment if present.
    hash_idx = raw.find("#")
    if hash_idx >= 0:
        raw = raw[:hash_idx].strip()
    return raw


def is_null_value(val: str | None) -> bool:
    """True if the YAML value is explicitly null/None or absent / empty."""
    if val is None:
        return True
    return val.strip().lower() in ("null", "none", "~", "")


def split_at_first_paren(text: str) -> str:
    """Return text before the first '(' — the target statement, exclusive of
    any inline citation or unit annotation.
    """
    idx = text.find("(")
    return text[:idx] if idx >= 0 else text


def detect_all_primary_metrics(checkpoint_text: str) -> list[str]:
    """Return the distinct normalised primary-metric names found in the
    pre-paren portion of the checkpoint, in order of first match.

    Once a pattern matches, its match span is blanked out so later (less
    specific) patterns do not double-count — e.g., "Revenue growth %" matches
    first and prevents "Revenue" from also matching the same word.
    """
    pre = split_at_first_paren(checkpoint_text)
    found: list[str] = []
    work = pre
    for pattern, name in PRIMARY_METRIC_PATTERNS:
        new_work = pattern.sub("", work)
        if new_work != work and name not in found:
            found.append(name)
        work = new_work
    return found


def detect_primary_metric(checkpoint_text: str) -> str | None:
    """Return the first primary metric found, or None."""
    metrics = detect_all_primary_metrics(checkpoint_text)
    return metrics[0] if metrics else None


def has_grounding(text: str) -> bool:
    """True if the text contains at least one citation-shaped paren group."""
    return bool(CITATION_PATTERN.search(text))


def find_banned(text: str, banned_list: list[str]) -> list[str]:
    """Return banned metric names found in text (case-insensitive, word-bounded
    where the banned phrase is a single short word like "fcf" / "ocf" /
    "capex" / "borrowings"; substring otherwise)."""
    lower = text.lower()
    hits: list[str] = []
    for b in banned_list:
        # Multi-word phrases use plain substring (already specific enough).
        # Short single tokens use word boundaries to avoid false positives
        # (e.g. "ocf" inside "Microsoft" — none today, but defensive).
        if " " in b or "-" in b:
            if b in lower:
                hits.append(b)
        else:
            if re.search(rf"\b{re.escape(b)}\b", lower):
                hits.append(b)
    return hits


def read_meta(workspace_dir: Path) -> dict[str, str | None]:
    """Read _meta.yaml from a workspace directory. Returns dict with archetype,
    market, instrument_class, schema_version. Empty dict if file is missing."""
    meta_path = workspace_dir / "_meta.yaml"
    if not meta_path.exists():
        return {}
    try:
        text = meta_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return {
        "schema_version": find_top_field(text, "schema_version"),
        "instrument_class": find_top_field(text, "instrument_class"),
        "archetype": find_top_field(text, "archetype"),
        "market": find_top_field(text, "market"),
    }


# -------- Validation --------


def validate(assumptions_path: Path) -> list[str]:
    """Return list of error strings. Empty list = valid."""
    errors: list[str] = []
    try:
        text = assumptions_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"could not read {assumptions_path}: {exc}"]

    # 0. schema_version
    sv = find_top_field(text, "schema_version")
    if sv is None or sv != "1":
        errors.append(f"schema_version: expected '1', got {sv!r}")

    # 0a. _meta.yaml context (archetype + market)
    workspace_dir = assumptions_path.parent
    meta = read_meta(workspace_dir)
    archetype = meta.get("archetype")
    market = meta.get("market")
    instrument_class = meta.get("instrument_class")

    if archetype is None:
        errors.append(f"_meta.yaml at {workspace_dir} missing archetype")
    elif archetype not in VALID_ARCHETYPES:
        errors.append(
            f"_meta.yaml archetype {archetype!r} not in {sorted(VALID_ARCHETYPES)}"
        )
    if market is None:
        errors.append(
            f"_meta.yaml at {workspace_dir} missing market "
            f"(required for the quarterly_checkpoint metric whitelist)"
        )
    elif market not in VALID_MARKETS:
        errors.append(f"_meta.yaml market {market!r} not in {sorted(VALID_MARKETS)}")
    if instrument_class is not None and instrument_class != "equity":
        errors.append(
            f"_meta.yaml instrument_class {instrument_class!r}: validator "
            f"currently supports 'equity' only"
        )

    # 1. Exactly four assumption keys A1-A4
    blocks: dict[str, str | None] = {
        k: find_assumption_block(text, k) for k in EXPECTED_KEYS
    }
    missing = [k for k, b in blocks.items() if b is None]
    if missing:
        errors.append(f"assumptions: missing required keys {missing}")
        return errors  # cannot continue without all four

    # Extract fields per assumption
    parsed: dict[str, dict[str, str | None]] = {}
    for k in EXPECTED_KEYS:
        block = blocks[k] or ""
        parsed[k] = {f: field_in_block(block, f) for f in REQUIRED_FIELDS}
        # text and category are required to be non-null
        if is_null_value(parsed[k]["text"]):
            errors.append(f"{k}.text: required (non-null)")
        if is_null_value(parsed[k]["category"]):
            errors.append(f"{k}.category: required (non-null)")

    # 2. Category enum
    for k in EXPECTED_KEYS:
        cat = parsed[k]["category"]
        if cat is not None and not is_null_value(cat) and cat not in VALID_CATEGORIES:
            errors.append(
                f"{k}.category: {cat!r} not in {sorted(VALID_CATEGORIES)}"
            )

    # 3. Slot allocation per archetype
    if archetype in SLOT_ALLOCATION:
        actual: dict[str, int] = {c: 0 for c in VALID_CATEGORIES}
        for k in EXPECTED_KEYS:
            cat = parsed[k]["category"]
            if cat in actual:
                actual[cat] += 1
        expected = SLOT_ALLOCATION[archetype]
        for c in sorted(VALID_CATEGORIES):
            if actual[c] != expected[c]:
                errors.append(
                    f"slot allocation: archetype {archetype} requires "
                    f"{expected[c]} {c} assumption(s), found {actual[c]}"
                )

    # 4. checkpoint_metric_source enum + per-category rule
    for k in EXPECTED_KEYS:
        cat = parsed[k]["category"]
        ms = parsed[k]["checkpoint_metric_source"]
        if is_null_value(ms):
            errors.append(f"{k}.checkpoint_metric_source: required (non-null)")
            continue
        if ms not in VALID_METRIC_SOURCES:
            errors.append(
                f"{k}.checkpoint_metric_source: {ms!r} not in "
                f"{sorted(VALID_METRIC_SOURCES)}"
            )
            continue
        if cat == "GOING_CONCERN" and ms != "non_financial":
            errors.append(
                f"{k} (GOING_CONCERN).checkpoint_metric_source: must be "
                f"'non_financial', got {ms!r}"
            )
        if cat in {"GROWTH", "FINANCIAL_HEALTH", "COMPETITIVE"} and ms != "consolidated":
            errors.append(
                f"{k} ({cat}).checkpoint_metric_source: must be "
                f"'consolidated', got {ms!r}"
            )

    # 5. transcript_checkpoint nullability per category
    for k in EXPECTED_KEYS:
        cat = parsed[k]["category"]
        tc = parsed[k]["transcript_checkpoint"]
        if cat == "GOING_CONCERN" and not is_null_value(tc):
            errors.append(
                f"{k} (GOING_CONCERN).transcript_checkpoint: must be null, "
                f"got non-null value"
            )
        if cat in {"GROWTH", "FINANCIAL_HEALTH", "COMPETITIVE"} and is_null_value(tc):
            errors.append(
                f"{k} ({cat}).transcript_checkpoint: required (non-null)"
            )

    # 6. Banned metrics in quarterly_checkpoint
    for k in EXPECTED_KEYS:
        cat = parsed[k]["category"]
        if cat == "GOING_CONCERN":
            continue  # binary sentinels; metric whitelist does not apply
        qc = parsed[k]["quarterly_checkpoint"]
        if is_null_value(qc):
            continue
        # Strip the citation portion before checking — banned metrics often
        # appear legitimately INSIDE a parenthesised citation as historical
        # commentary (e.g., "(FY2025 capex $64.6B per kb.md)"). The whitelist
        # applies to the target statement only.
        target = split_at_first_paren(qc)
        banned_hits = find_banned(target, BANNED_BOTH)
        if banned_hits:
            errors.append(
                f"{k}.quarterly_checkpoint: banned metric(s) {banned_hits} "
                f"in target statement (must use only the whitelist; see "
                f"internal/holdings-schema.md § 'Mandatory metric whitelist')"
            )
        if market == "IN":
            banned_in_hits = find_banned(target, BANNED_INDIAN_ONLY)
            if banned_in_hits:
                errors.append(
                    f"{k}.quarterly_checkpoint (Indian market): US-only "
                    f"metric(s) {banned_in_hits} in target statement (not "
                    f"parseable from Screener.in's Indian quarterly schema)"
                )

    # 7. Single-metric rule (compound detection)
    for k in EXPECTED_KEYS:
        cat = parsed[k]["category"]
        if cat == "GOING_CONCERN":
            continue
        qc = parsed[k]["quarterly_checkpoint"]
        if is_null_value(qc):
            continue
        metrics = detect_all_primary_metrics(qc)
        if len(metrics) > 1:
            errors.append(
                f"{k}.quarterly_checkpoint: compound (uses metrics {metrics}); "
                f"single-metric rule requires exactly one primary metric in "
                f"the target statement"
            )

    # 8. Checkpoint uniqueness across non-GOING_CONCERN assumptions
    seen: dict[str, str] = {}  # primary metric -> first key that used it
    for k in EXPECTED_KEYS:
        cat = parsed[k]["category"]
        if cat == "GOING_CONCERN":
            continue
        qc = parsed[k]["quarterly_checkpoint"]
        if is_null_value(qc):
            continue
        primary = detect_primary_metric(qc)
        if primary is None:
            errors.append(
                f"{k}.quarterly_checkpoint: could not identify a primary "
                f"metric from the whitelist"
            )
            continue
        if primary in seen:
            errors.append(
                f"{k}.quarterly_checkpoint: primary metric {primary!r} "
                f"already used by {seen[primary]} (each assumption must use "
                f"a distinct primary metric)"
            )
        else:
            seen[primary] = k

    # 9. Inline grounding — non-GOING_CONCERN quarterly_checkpoint and
    # thesis_horizon_target must contain at least one citation-shaped paren.
    for k in EXPECTED_KEYS:
        cat = parsed[k]["category"]
        if cat == "GOING_CONCERN":
            continue
        for field in ("quarterly_checkpoint", "thesis_horizon_target"):
            val = parsed[k][field]
            if is_null_value(val):
                continue
            if not has_grounding(val):
                errors.append(
                    f"{k}.{field}: missing inline grounding citation "
                    f"(parenthesised source). Add a citation like "
                    f"'(per kb.md § ...)' or '(mgmt guided X% Q3 FY2026 call)'."
                )

    # 10. Coverage: at least 3 of 4 must have BOTH non-null quarterly_checkpoint
    # AND non-null thesis_horizon_target.
    both_present = 0
    for k in EXPECTED_KEYS:
        qc = parsed[k]["quarterly_checkpoint"]
        ht = parsed[k]["thesis_horizon_target"]
        if not is_null_value(qc) and not is_null_value(ht):
            both_present += 1
    if both_present < 3:
        errors.append(
            f"coverage: at least 3 of 4 assumptions must have BOTH non-null "
            f"quarterly_checkpoint AND non-null thesis_horizon_target; "
            f"found {both_present}"
        )

    return errors


# -------- CLI --------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a Veda assumptions.yaml against the rules in "
            "internal/holdings-schema.md § 'Writing assumptions and checkpoints'."
        ),
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path to holdings/<slug>/assumptions.yaml",
    )
    args = parser.parse_args()

    if not args.path.exists():
        print(f"Error: file not found: {args.path}", file=sys.stderr)
        return 2

    errors = validate(args.path)
    if errors:
        print(f"FAIL: {args.path}", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"OK: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
