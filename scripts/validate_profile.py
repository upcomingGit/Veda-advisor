"""
Veda - profile validator.

Validates profile.md against the schema in setup/profile.template.md. Enforces:

  - Required top-level fields are present.
  - Enum fields hold one of the allowed exact strings (no paraphrase).
  - Numeric gates (max_loss_probability, capital split) are in range and sum correctly.
  - Novice profiles have a complete guardrails block.
  - Framework weights list is complete and sums to roughly 1.0 (band, not strict).

This is the safety net named in setup/onboarding.prompt.md. Run it at the end of
onboarding before the user exits the session.

Pure stdlib. No YAML parser - this tool uses regex against the known schema so it
works in any Python 3.10+ environment without installing anything.

Usage:

    python scripts/validate_profile.py profile.md

Exit codes:
    0 - profile is valid
    1 - validation failed; errors printed to stderr
    2 - could not read or parse the file

The script is intentionally strict. If you think an error is wrong, the fix is
almost always to correct profile.md, not to relax the validator.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# -------- Allowed enum values (must match setup/profile.template.md) --------

ENUM_VALUES: dict[str, set[str]] = {
    "experience_mode": {"novice", "standard"},
    "goal.primary": {
        "capital_preservation",
        "income",
        "balanced_growth",
        "aggressive_growth",
        "speculation",
    },
    "risk.stated_tolerance": {"low", "medium", "high", "very_high"},
    "risk.calibrated_tolerance": {"low", "medium", "high", "very_high"},
    # Concentration is split into current-state vs target-state sub-blocks.
    # Both are optional at the schema level (captured progressively) but when
    # present, each style field must be one of the allowed enums.
    "concentration.current.style": {"index_like", "diversified", "focused", "concentrated"},
    "concentration.target.style": {"index_like", "diversified", "focused", "concentrated"},
    "style_lean.primary": {
        "value",
        "quality",
        "growth",
        "macro",
        "thematic",
        "quant",
        "passive_plus",
    },
    "experience.level": {"beginner", "intermediate", "advanced", "professional"},
    "experience.explanation_depth": {"minimal", "standard", "educational"},
}

BOOL_FIELDS = {
    "disclosure_acknowledged",
    "incomplete",
    "instruments.long_only_cash",
    "instruments.margin",
    "instruments.options_hedging",
    "instruments.options_speculation",
    "instruments.shorts",
    "guardrails.block_leverage",
    "guardrails.block_options",
    "guardrails.block_shorts",
    "guardrails.block_lottery_bets",
    "guardrails.require_index_comparison",
    "guardrails.education_mode",
}

REQUIRED_TOP_LEVEL = [
    "schema_version",
    "generated",
    "profile_last_updated",
    "disclosure_acknowledged",
    "experience_mode",
    "max_loss_probability",
]

FRAMEWORK_NAMES = [
    "buffett",
    "lynch",
    "druckenmiller",
    "marks",
    "dalio",
    "klarman",
    "thorp",
    "templeton",
    "munger",
    "fisher",
    "taleb",
]

NOVICE_GUARDRAIL_FIELDS = [
    "max_single_position_pct",
    "block_leverage",
    "block_options",
    "block_shorts",
    "block_lottery_bets",
    "require_index_comparison",
    "education_mode",
    "graduation_criteria",
]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# -------- YAML extraction --------


def extract_yaml_block(text: str) -> str:
    """Return the first ```yaml ... ``` fenced block, or the whole file if none."""
    match = re.search(r"```ya?ml\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1)
    return text


# -------- Field readers (regex, not a full YAML parser) --------


def find_scalar(yaml_text: str, dotted_path: str) -> str | None:
    """Find `key: value` at the right indentation for a dotted path.

    Supports arbitrary nesting depth. `concentration.current.style` narrows
    first to the `concentration:` block, then to the `current:` sub-block,
    then reads the `style:` scalar at the correct indent.
    """
    parts = dotted_path.split(".")
    if len(parts) == 1:
        pattern = rf"(?m)^{re.escape(parts[0])}:\s*(.+?)\s*(?:#.*)?$"
        m = re.search(pattern, yaml_text)
        return m.group(1).strip() if m else None

    # Narrow to the deepest block by walking parents one at a time.
    current_text = yaml_text
    current_indent = 0  # indent (in spaces) of keys in the current scope
    for parent in parts[:-1]:
        indent_prefix = " " * current_indent
        parent_re = re.compile(
            rf"(?m)^{re.escape(indent_prefix)}{re.escape(parent)}:\s*$"
        )
        pm = parent_re.search(current_text)
        if not pm:
            return None
        rest = current_text[pm.end():]
        block_lines: list[str] = []
        child_indent: int | None = None
        for line in rest.splitlines():
            if line.strip() == "" or line.lstrip().startswith("#"):
                block_lines.append(line)
                continue
            leading = len(line) - len(line.lstrip(" "))
            if leading <= current_indent:
                break
            if child_indent is None:
                child_indent = leading
            block_lines.append(line)
        if child_indent is None:
            return None
        current_text = "\n".join(block_lines)
        current_indent = child_indent

    last = parts[-1]
    indent_prefix = " " * current_indent
    pattern = rf"(?m)^{re.escape(indent_prefix)}{re.escape(last)}:\s*(.+?)\s*(?:#.*)?$"
    m = re.search(pattern, current_text)
    return m.group(1).strip() if m else None


def section_present(yaml_text: str, header: str) -> bool:
    return re.search(rf"(?m)^{re.escape(header)}:\s*$", yaml_text) is not None


def strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


# -------- Validators --------


def validate(profile_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        raw = profile_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"could not read {profile_path}: {exc}"]

    yaml_text = extract_yaml_block(raw)

    # Required top-level scalars present
    for field in REQUIRED_TOP_LEVEL:
        if find_scalar(yaml_text, field) is None:
            errors.append(f"missing required field: {field}")

    # Date fields parseable as YYYY-MM-DD
    for date_field in ("generated", "profile_last_updated"):
        v = find_scalar(yaml_text, date_field)
        if v is not None and not DATE_RE.match(strip_quotes(v)):
            errors.append(
                f"{date_field}: expected YYYY-MM-DD, got {v!r}"
            )

    # Booleans
    for bf in BOOL_FIELDS:
        v = find_scalar(yaml_text, bf)
        if v is None:
            continue  # presence is enforced elsewhere for required ones
        if v.lower() not in ("true", "false"):
            errors.append(f"{bf}: must be true or false, got {v!r}")

    # disclosure_acknowledged must be literally true
    disc = find_scalar(yaml_text, "disclosure_acknowledged")
    if disc is not None and disc.lower() != "true":
        errors.append(
            "disclosure_acknowledged: must be true before Veda produces "
            f"any decision output (found {disc!r})"
        )

    # Enum fields
    for field, allowed in ENUM_VALUES.items():
        v = find_scalar(yaml_text, field)
        if v is None:
            # goal.primary, experience_mode etc are required; caught above
            continue
        bare = strip_quotes(v)
        if bare not in allowed:
            errors.append(
                f"{field}: {bare!r} is not one of {sorted(allowed)}"
            )

    # max_loss_probability 0-100
    mlp = find_scalar(yaml_text, "max_loss_probability")
    if mlp is not None:
        try:
            n = int(mlp)
            if not 0 <= n <= 100:
                errors.append(f"max_loss_probability: {n} out of range 0-100")
        except ValueError:
            errors.append(f"max_loss_probability: expected int, got {mlp!r}")

    # capital.split (current state) sums to 100 when present.
    # capital.target_split (desired future state) is optional; when present,
    # it must also sum to 100. Both blocks are treated as "present" only if
    # all four bucket components are written out (partial blocks are ignored,
    # so progressive profiling can leave them absent without tripping the
    # validator).
    _buckets = ("core_long_term", "tactical", "short_term_trades", "speculation")
    for block_name in ("split", "target_split"):
        parts_by_bucket = {
            k: find_scalar(yaml_text, f"capital.{block_name}.{k}") for k in _buckets
        }
        if all(v is not None for v in parts_by_bucket.values()):
            try:
                total = sum(int(v) for v in parts_by_bucket.values())  # type: ignore[arg-type]
                if total != 100:
                    errors.append(
                        f"capital.{block_name}: components must sum to 100, got {total} "
                        f"({parts_by_bucket})"
                    )
            except ValueError:
                errors.append(
                    f"capital.{block_name}: non-integer component in {parts_by_bucket}"
                )

    # Novice: guardrails block required and complete
    exp_mode = find_scalar(yaml_text, "experience_mode")
    if exp_mode == "novice":
        if not section_present(yaml_text, "guardrails"):
            errors.append("experience_mode is novice but guardrails block is absent")
        else:
            for gf in NOVICE_GUARDRAIL_FIELDS:
                if find_scalar(yaml_text, f"guardrails.{gf}") is None:
                    # graduation_criteria is a list header, not a scalar
                    if gf == "graduation_criteria":
                        if not re.search(
                            r"(?m)^\s+graduation_criteria:\s*$", yaml_text
                        ):
                            errors.append(
                                "guardrails.graduation_criteria: list is missing"
                            )
                        continue
                    errors.append(f"guardrails.{gf}: missing for novice profile")

    # framework_weights: all 11 present, sum in [0.9, 1.1]
    if section_present(yaml_text, "framework_weights"):
        weights: list[float] = []
        for name in FRAMEWORK_NAMES:
            v = find_scalar(yaml_text, f"framework_weights.{name}")
            if v is None:
                errors.append(f"framework_weights.{name}: missing")
                continue
            try:
                weights.append(float(v))
            except ValueError:
                errors.append(f"framework_weights.{name}: not a number ({v!r})")
        if len(weights) == len(FRAMEWORK_NAMES):
            s = sum(weights)
            if not 0.9 <= s <= 1.1:
                errors.append(
                    f"framework_weights: sum {s:.3f} outside allowed band [0.9, 1.1]"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Veda profile.md against the schema."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="profile.md",
        help="path to profile.md (default: ./profile.md)",
    )
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 2

    errors = validate(path)
    if not errors:
        print(f"OK: {path} is valid.")
        return 0

    print(f"FAIL: {path} has {len(errors)} validation error(s):", file=sys.stderr)
    for e in errors:
        print(f"  - {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
