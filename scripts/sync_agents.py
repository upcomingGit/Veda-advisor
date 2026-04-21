"""Sync subagent definitions from internal/agents/ to host-specific discovery locations.

Canonical source of truth: internal/agents/*.md
Host-facing copies: .claude/agents/*.md (Claude Code, GitHub Copilot, Google Antigravity)

Run after editing any file in internal/agents/. Safe to run repeatedly.

Usage:
    python scripts/sync_agents.py           # sync
    python scripts/sync_agents.py --check   # exit 1 if any host copy is out of date
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_DIR = REPO_ROOT / "internal" / "agents"
HOST_DIRS = [
    REPO_ROOT / ".claude" / "agents",
    # Add more host discovery directories here as Veda supports more surfaces.
    # Each entry receives a copy of every canonical agent file.
]

BANNER = (
    "<!-- GENERATED FILE — DO NOT EDIT.\n"
    "     Canonical source: internal/agents/{name}.md\n"
    "     Edit the canonical file and run: python scripts/sync_agents.py\n"
    "-->\n\n"
)


def _render(canonical: Path) -> str:
    raw = canonical.read_text(encoding="utf-8")
    banner = BANNER.format(name=canonical.stem)
    # Insert banner after YAML frontmatter if present so host parsers still read
    # the frontmatter first.
    if raw.startswith("---\n"):
        end = raw.find("\n---\n", 4)
        if end != -1:
            split = end + len("\n---\n")
            return raw[:split] + "\n" + banner + raw[split:].lstrip("\n")
    return banner + raw


def sync(check_only: bool = False) -> int:
    if not CANONICAL_DIR.exists():
        print(f"No canonical agents directory at {CANONICAL_DIR}; nothing to sync.")
        return 0

    canonical_files = sorted(CANONICAL_DIR.glob("*.md"))
    if not canonical_files:
        print(f"No agent files in {CANONICAL_DIR}; nothing to sync.")
        return 0

    drift = False
    for canonical in canonical_files:
        rendered = _render(canonical)
        for host_dir in HOST_DIRS:
            host_dir.mkdir(parents=True, exist_ok=True)
            target = host_dir / canonical.name
            if target.exists() and target.read_text(encoding="utf-8") == rendered:
                continue
            if check_only:
                print(f"DRIFT: {target.relative_to(REPO_ROOT)} differs from canonical.")
                drift = True
                continue
            target.write_text(rendered, encoding="utf-8")
            print(f"wrote {target.relative_to(REPO_ROOT)}")

    if check_only and drift:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any host copy differs from the canonical. Do not write.",
    )
    args = parser.parse_args()
    return sync(check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
