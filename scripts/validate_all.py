"""
Veda - run all schema validators in one shot.

Walks the repo and runs:
  - validate_profile.py on profile.md (if present)
  - validate_assumptions.py on every holdings/<slug>/assumptions.yaml

Use case:
  - Pre-commit sanity ("did I break anything?")
  - Post-edit sanity after touching profile.md or any assumption file
  - CI / release gate

Pure stdlib. Imports the per-validator modules so each validator's logic
stays in one place.

Usage:

    python scripts/validate_all.py

Exit codes:
    0 - all valid
    1 - one or more validation failures; per-file errors printed to stderr
    2 - validator script itself errored (import failure, etc.)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python scripts/validate_all.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_assumptions  # noqa: E402
import validate_profile      # noqa: E402


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    profile_path = repo_root / "profile.md"
    holdings_dir = repo_root / "holdings"

    fail_count = 0
    pass_count = 0

    # 1. profile.md
    if profile_path.exists():
        errors = validate_profile.validate(profile_path)
        if errors:
            fail_count += 1
            print(f"FAIL: {profile_path.relative_to(repo_root)}", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
        else:
            pass_count += 1
            print(f"OK:   {profile_path.relative_to(repo_root)}")
    else:
        print(f"SKIP: {profile_path.relative_to(repo_root)} (file not present)")

    # 2. holdings/*/assumptions.yaml
    if holdings_dir.is_dir():
        # Sort for deterministic output
        for assumptions_path in sorted(holdings_dir.glob("*/assumptions.yaml")):
            errors = validate_assumptions.validate(assumptions_path)
            rel = assumptions_path.relative_to(repo_root)
            if errors:
                fail_count += 1
                print(f"FAIL: {rel}", file=sys.stderr)
                for e in errors:
                    print(f"  - {e}", file=sys.stderr)
            else:
                pass_count += 1
                print(f"OK:   {rel}")
    else:
        print(f"SKIP: {holdings_dir.relative_to(repo_root)}/ (directory not present)")

    print()
    print(f"Summary: {pass_count} passed, {fail_count} failed")
    return 1 if fail_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
