"""
scripts/bump_version.py \u2014 propose a version bump.

The authoritative version lives in ``VERSION`` at repo root. [SKILL.md](../SKILL.md)
front-matter and [README.md](../README.md) badge mirror it. This script keeps
all three in sync and promotes an ``[Unreleased]`` entry in
[CHANGELOG.md](../CHANGELOG.md) to a new numbered release.

It deliberately does NOT run ``git commit`` or ``git tag`` for you. Tagging
and pushing are decisions worth making consciously. The script prints the
exact commands to run next.

Usage:

    python scripts/bump_version.py patch        # 0.1.0 -> 0.1.1
    python scripts/bump_version.py minor        # 0.1.1 -> 0.2.0
    python scripts/bump_version.py major        # 0.2.0 -> 1.0.0
    python scripts/bump_version.py --set 0.3.0  # explicit version
    python scripts/bump_version.py --dry-run patch  # show the diff, touch nothing

Invariants enforced:

1. ``CHANGELOG.md`` must contain at least one non-empty subsection under
   ``## [Unreleased]`` before a bump. If the ``[Unreleased]`` block is empty,
   the script refuses to proceed \u2014 releasing with no changelog is worse than
   not releasing.
2. SemVer parsing is strict: three dot-separated non-negative integers.
   Pre-release / build suffixes are not supported in v0.1; add them when a
   real need appears.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO_ROOT / "VERSION"
SKILL_FILE = REPO_ROOT / "SKILL.md"
README_FILE = REPO_ROOT / "README.md"
CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _read_version() -> tuple[int, int, int]:
    raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    m = SEMVER_RE.match(raw)
    if not m:
        raise SystemExit(
            f"VERSION file content {raw!r} is not strict SemVer "
            f"(expected MAJOR.MINOR.PATCH)."
        )
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _bump(current: tuple[int, int, int], kind: str) -> tuple[int, int, int]:
    major, minor, patch = current
    if kind == "major":
        return major + 1, 0, 0
    if kind == "minor":
        return major, minor + 1, 0
    if kind == "patch":
        return major, minor, patch + 1
    raise SystemExit(f"unknown bump kind: {kind!r}")


def _fmt(v: tuple[int, int, int]) -> str:
    return f"{v[0]}.{v[1]}.{v[2]}"


def _parse_explicit(s: str) -> tuple[int, int, int]:
    m = SEMVER_RE.match(s.strip())
    if not m:
        raise SystemExit(
            f"--set value {s!r} is not strict SemVer (expected MAJOR.MINOR.PATCH)."
        )
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _check_unreleased_nonempty(changelog: str) -> None:
    """Refuse to bump if ``[Unreleased]`` has no entries.

    An 'entry' is any non-blank line between the ``## [Unreleased]`` header and
    the next ``## [`` header (or EOF), excluding sub-headings with no body.
    """
    lines = changelog.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "## [Unreleased]":
            start = i + 1
            break
    if start is None:
        raise SystemExit("CHANGELOG.md: no '## [Unreleased]' section found.")
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("## ["):
            end = i
            break
    body = [ln for ln in lines[start:end] if ln.strip() and not ln.strip().startswith("###")]
    if not body:
        raise SystemExit(
            "CHANGELOG.md: '[Unreleased]' is empty. Add what changed under "
            "'### Added' / '### Changed' / '### Fixed' / '### Security' "
            "before bumping."
        )


def _promote_unreleased(changelog: str, new_version: str, today: str) -> str:
    """Replace ``## [Unreleased]`` with a new release header, and insert a
    fresh empty ``## [Unreleased]`` above it. Also append a link reference at
    the bottom if one isn't already there."""
    new_changelog = changelog.replace(
        "## [Unreleased]",
        f"## [Unreleased]\n\n## [{new_version}] - {today}",
        1,
    )
    # Append a link-reference stub if not present; the user can fill in the
    # compare URL when they push tags.
    if f"[{new_version}]:" not in new_changelog:
        new_changelog = new_changelog.rstrip() + (
            f"\n[{new_version}]: https://github.com/upcomingGit/Veda-advisor"
            f"/releases/tag/v{new_version}\n"
        )
    return new_changelog


def _update_skill(skill: str, new_version: str) -> str:
    """Replace the ``version:`` line inside the YAML front-matter."""
    new_skill, n = re.subn(
        r"(?m)^version:\s*[^\n]+$",
        f"version: {new_version}",
        skill,
        count=1,
    )
    if n != 1:
        raise SystemExit("SKILL.md front-matter has no 'version:' line.")
    return new_skill


def _update_readme(readme: str, new_version: str) -> str:
    """Replace the shields.io badge URL version segment."""
    new_readme, n = re.subn(
        r"version-\d+\.\d+\.\d+-blue",
        f"version-{new_version}-blue",
        readme,
        count=1,
    )
    if n != 1:
        raise SystemExit(
            "README.md has no 'version-X.Y.Z-blue' badge to update."
        )
    return new_readme


def main() -> int:
    p = argparse.ArgumentParser(description="Bump Veda's version.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "kind",
        nargs="?",
        choices=["major", "minor", "patch"],
        help="which SemVer component to bump",
    )
    g.add_argument("--set", dest="explicit", help="set an explicit version (X.Y.Z)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would change; do not touch any files",
    )
    args = p.parse_args()

    current = _read_version()
    if args.explicit:
        new = _parse_explicit(args.explicit)
    else:
        new = _bump(current, args.kind)

    if new <= current:
        raise SystemExit(
            f"refusing to bump: new version {_fmt(new)} is not greater than "
            f"current {_fmt(current)}."
        )

    changelog = CHANGELOG_FILE.read_text(encoding="utf-8")
    _check_unreleased_nonempty(changelog)

    skill = SKILL_FILE.read_text(encoding="utf-8")
    readme = README_FILE.read_text(encoding="utf-8")

    new_version = _fmt(new)
    today = date.today().isoformat()

    new_changelog = _promote_unreleased(changelog, new_version, today)
    new_skill = _update_skill(skill, new_version)
    new_readme = _update_readme(readme, new_version)

    if args.dry_run:
        print(f"[dry-run] would bump {_fmt(current)} -> {new_version}")
        print("[dry-run] files that would change:")
        print("  VERSION")
        print("  SKILL.md       (front-matter version: field)")
        print("  README.md      (shields.io badge)")
        print("  CHANGELOG.md   ([Unreleased] -> [{}] - {})".format(new_version, today))
        return 0

    VERSION_FILE.write_text(new_version + "\n", encoding="utf-8")
    SKILL_FILE.write_text(new_skill, encoding="utf-8")
    README_FILE.write_text(new_readme, encoding="utf-8")
    CHANGELOG_FILE.write_text(new_changelog, encoding="utf-8")

    print(f"Bumped {_fmt(current)} -> {new_version}")
    print()
    print("Next steps (review each before running):")
    print(f"  1. Review the CHANGELOG entry for [{new_version}].")
    print("  2. git add VERSION SKILL.md README.md CHANGELOG.md")
    print(f"     git commit -m 'chore: release v{new_version}'")
    print(f"  3. git tag -a v{new_version} -m 'Veda {new_version}'")
    print("  4. git push && git push --tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
