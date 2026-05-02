"""Filesystem readers for the dashboard.

One function per artifact shape. All readers:

* Return ``None`` (or an empty container) when the artifact does not exist.
  Templates branch on the truthy/falsy result; broken sections are not allowed.
* Never write. Never call out to the network.
* Parse YAML with PyYAML; parse markdown verbatim (rendering happens in the
  templates via the ``markdown`` library).

Schemas mirror ``internal/holdings-schema.md``. When a field is missing in a
real workspace file, the reader leaves the corresponding key absent rather
than substituting a default — display logic is responsible for showing
"not captured" rather than masking the gap.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


# ---------------------------------------------------------------------------
# holdings_registry.csv
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegistryRow:
    instance_key: str
    instrument_class: str
    display_name: str
    first_acquired: str
    last_disposed: str
    status: str
    reason: str


def read_registry(path: Path) -> list[RegistryRow]:
    """Read holdings_registry.csv. Returns [] if missing."""
    if not path.exists():
        return []
    rows: list[RegistryRow] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            rows.append(
                RegistryRow(
                    instance_key=(raw.get("instance_key") or "").strip(),
                    instrument_class=(raw.get("instrument_class") or "").strip(),
                    display_name=(raw.get("display_name") or "").strip(),
                    first_acquired=(raw.get("first_acquired") or "").strip(),
                    last_disposed=(raw.get("last_disposed") or "").strip(),
                    status=(raw.get("status") or "").strip(),
                    reason=(raw.get("reason") or "").strip(),
                )
            )
    return rows


# ---------------------------------------------------------------------------
# assets.md  --  the YAML `dynamic:` block + per-currency Holdings tables
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HoldingRow:
    """One row from a `## Holdings (...)` markdown table.

    Numbers are kept as strings unless they parse cleanly to float; this keeps
    fidelity with the on-disk display (thousand separators, TBD_fetch markers).
    """

    ticker: str
    name: str
    shares: Optional[float]
    avg_cost: Optional[float]
    current_price: Optional[float]
    current_value: Optional[float]
    sector: str
    thesis: str
    tags: str
    raw_shares: str
    raw_avg_cost: str
    raw_current_price: str
    raw_current_value: str


@dataclass
class AssetsView:
    as_of: Optional[str] = None
    dynamic: dict[str, Any] = field(default_factory=dict)
    holdings_by_currency: dict[str, list[HoldingRow]] = field(default_factory=dict)
    cash_rows: list[dict[str, str]] = field(default_factory=list)
    cash_total_md: str = ""
    notes_md: str = ""
    raw_md: str = ""


_AS_OF_RE = re.compile(r"^\*\*As of:\*\*\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
_FENCED_YAML_RE = re.compile(r"^```yaml\n(.*?)^```", re.MULTILINE | re.DOTALL)


def _parse_number(cell: str) -> Optional[float]:
    """Parse a Holdings table cell. Returns None for placeholders / non-numeric."""
    s = (cell or "").strip()
    if not s or s.startswith("_") or s.endswith("_"):
        return None
    if "TBD" in s.upper():
        return None
    # Strip thousand separators; keep decimals.
    cleaned = s.replace(",", "").replace("\u202f", "").replace("\xa0", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _split_md_table(block: str) -> list[list[str]]:
    """Split a markdown pipe-table block into rows of cell strings.

    Drops the header row and the alignment row. Returns body rows only.
    """
    out: list[list[str]] = []
    for line in block.splitlines():
        if not line.strip().startswith("|"):
            continue
        # Skip alignment row: |---|---:|---|
        if re.match(r"^\|\s*[:\-\s|]+\|\s*$", line):
            continue
        # Drop leading/trailing pipe, split on remaining pipes.
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        out.append(cells)
    # First row is the header; skip it.
    return out[1:] if out else []


def _parse_md_table_dicts(block: str) -> list[dict[str, str]]:
    """Parse the first markdown pipe-table in a block into dict rows."""
    rows: list[list[str]] = []
    for line in block.splitlines():
        if not line.strip().startswith("|"):
            if rows:
                break
            continue
        if re.match(r"^\|\s*[:\-\s|]+\|\s*$", line):
            continue
        rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    if len(rows) < 2:
        return []
    headers = [h.strip().lower().replace(" ", "_") for h in rows[0]]
    out: list[dict[str, str]] = []
    for cells in rows[1:]:
        padded = cells + [""] * max(0, len(headers) - len(cells))
        out.append({headers[i]: padded[i].strip() for i in range(len(headers))})
    return out


def read_assets(path: Path) -> AssetsView:
    """Parse assets.md into an AssetsView. Returns an empty view if missing."""
    view = AssetsView()
    if not path.exists():
        return view
    text = path.read_text(encoding="utf-8")
    view.raw_md = text

    m = _AS_OF_RE.search(text)
    if m:
        view.as_of = m.group(1)

    yaml_match = _FENCED_YAML_RE.search(text)
    if yaml_match:
        try:
            parsed = yaml.safe_load(yaml_match.group(1)) or {}
        except yaml.YAMLError:
            parsed = {}
        view.dynamic = parsed.get("dynamic") or {}

    # Holdings tables: split on `### <Region> (<CCY>)` headers under
    # `## Holdings (equities)`.
    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)
    for sec in sections:
        if not sec.lower().startswith("holdings"):
            continue
        # Inside the Holdings section, find each `### Region (CCY)` block.
        sub_sections = re.split(r"^###\s+", sec, flags=re.MULTILINE)
        for sub in sub_sections[1:]:  # skip text before the first ###
            header_line, _, rest = sub.partition("\n")
            ccy_match = re.search(r"\(([A-Z]{3})\)", header_line)
            if not ccy_match:
                continue
            ccy = ccy_match.group(1)
            # Take everything up to the next ## or end-of-section.
            block = rest.split("\n## ")[0]
            rows: list[HoldingRow] = []
            for cells in _split_md_table(block):
                if not cells or not cells[0]:
                    continue
                # Pad to expected column count.
                cells = cells + [""] * max(0, 9 - len(cells))
                ticker, name, shares, avg_cost, current_price, current_value, \
                    sector, thesis, tags = cells[:9]
                rows.append(
                    HoldingRow(
                        ticker=ticker.strip(),
                        name=name.strip(),
                        shares=_parse_number(shares),
                        avg_cost=_parse_number(avg_cost),
                        current_price=_parse_number(current_price),
                        current_value=_parse_number(current_value),
                        sector=sector.strip(),
                        thesis=thesis.strip(),
                        tags=tags.strip(),
                        raw_shares=shares.strip(),
                        raw_avg_cost=avg_cost.strip(),
                        raw_current_price=current_price.strip(),
                        raw_current_value=current_value.strip(),
                    )
                )
            if rows:
                view.holdings_by_currency.setdefault(ccy, []).extend(rows)

    # Cash & equivalents table: pull rows out as plain dicts. The exact column
    # set varies by the user's bank/broker, so we keep raw header keys.
    cash_section = _section_after_heading(text, "## Cash & equivalents")
    if cash_section:
        view.cash_rows.extend(_parse_md_table_dicts(cash_section))
        total_match = re.search(
            r"^\*\*Total cash & equivalents:\*\*\s*(.+)$",
            cash_section,
            flags=re.MULTILINE,
        )
        if total_match:
            view.cash_total_md = total_match.group(1).strip()

    # Notes section is rendered as raw markdown for the overview tail.
    notes = _section_after_heading(text, "## Notes")
    if notes:
        view.notes_md = notes.strip()

    return view


def _section_after_heading(text: str, heading: str) -> str:
    """Return the text under a level-2 markdown heading until the next ## heading.

    The heading must appear at the start of a line (so a literal occurrence
    of the heading text inside an HTML comment or a code block does not
    count). Without this anchor the parser was matching the literal string
    ``## Notes`` inside the assets.md preamble comment and pulling in the
    entire YAML config block as if it were the user's notes.
    """
    pattern = rf"^{re.escape(heading)}\s*$"
    m = re.search(pattern, text, flags=re.MULTILINE)
    if not m:
        return ""
    rest = text[m.end():]
    next_h2 = re.search(r"^##\s", rest, flags=re.MULTILINE)
    return rest[: next_h2.start()] if next_h2 else rest


# ---------------------------------------------------------------------------
# Per-workspace YAML files
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> Optional[dict[str, Any]]:
    """Load a YAML file; return None if missing or unreadable.

    Only top-level mappings are expected in v1. A list at the top level
    (or a parse error) returns None — the dashboard treats the file as absent
    rather than guessing at an alternative shape.
    """
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def read_meta(workspace_dir: Path) -> Optional[dict[str, Any]]:
    return _load_yaml(workspace_dir / "_meta.yaml")


def read_valuation(workspace_dir: Path) -> Optional[dict[str, Any]]:
    return _load_yaml(workspace_dir / "valuation.yaml")


def read_fundamentals(workspace_dir: Path) -> Optional[dict[str, Any]]:
    return _load_yaml(workspace_dir / "fundamentals.yaml")


def read_assumptions(workspace_dir: Path) -> Optional[dict[str, Any]]:
    return _load_yaml(workspace_dir / "assumptions.yaml")


def read_indicators(workspace_dir: Path) -> Optional[dict[str, Any]]:
    return _load_yaml(workspace_dir / "indicators.yaml")


def read_insiders(workspace_dir: Path) -> Optional[dict[str, Any]]:
    return _load_yaml(workspace_dir / "insiders.yaml")


def read_shareholding(workspace_dir: Path) -> Optional[dict[str, Any]]:
    return _load_yaml(workspace_dir / "shareholding.yaml")


def read_calendar(workspace_dir: Path) -> Optional[dict[str, Any]]:
    return _load_yaml(workspace_dir / "calendar.yaml")


def read_performance(workspace_dir: Path) -> Optional[dict[str, Any]]:
    return _load_yaml(workspace_dir / "performance.yaml")


# ---------------------------------------------------------------------------
# Per-workspace markdown files
# ---------------------------------------------------------------------------

def _read_text(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def read_kb(workspace_dir: Path) -> Optional[str]:
    return _read_text(workspace_dir / "kb.md")


def read_thesis(workspace_dir: Path) -> Optional[str]:
    return _read_text(workspace_dir / "thesis.md")


def read_governance(workspace_dir: Path) -> Optional[str]:
    return _read_text(workspace_dir / "governance.md")


def read_risks(workspace_dir: Path) -> Optional[str]:
    return _read_text(workspace_dir / "risks.md")


def read_disclosures(workspace_dir: Path) -> Optional[str]:
    return _read_text(workspace_dir / "disclosures.md")


@dataclass(frozen=True)
class DigestCard:
    title: str
    date: str
    headline: str
    source: str
    url: str
    summary: str
    materiality: str
    impact: str
    period: str
    content: str


_DIGEST_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _markdown_field(body: str, label: str) -> str:
    m = re.search(rf"^-\s+\*\*{re.escape(label)}\.\*\*\s*(.+)$", body, flags=re.MULTILINE)
    return m.group(1).strip() if m else ""


def _digest_date_and_title(title: str) -> tuple[str, str]:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\s*[—-]\s*(.+)$", title)
    if not m:
        return "", title
    return m.group(1), m.group(2).strip()


def _source_name(source_line: str) -> str:
    if not source_line:
        return "source"
    return source_line.split(". Headline:", 1)[0].strip()


def _source_headline(source_line: str) -> str:
    m = re.search(r"Headline:\s*[\"“](.+?)[\"”]", source_line)
    return m.group(1).strip() if m else ""


def _digest_cards_from_markdown(text: str | None, period: str = "") -> list[DigestCard]:
    if not text:
        return []
    matches = list(_DIGEST_HEADING_RE.finditer(text))
    cards: list[DigestCard] = []
    for idx, match in enumerate(matches):
        raw_title = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        body = re.split(r"^\s*---\s*$", body, maxsplit=1, flags=re.MULTILINE)[0].strip()
        if not body:
            continue
        source_line = _markdown_field(body, "Source")
        date_text, title_text = _digest_date_and_title(raw_title)
        cards.append(
            DigestCard(
                title=title_text,
                date=date_text,
                headline=_source_headline(source_line) or title_text,
                source=_source_name(source_line),
                url=_markdown_field(body, "URL"),
                summary=_markdown_field(body, "Summary"),
                materiality=_markdown_field(body, "Materiality"),
                impact=_markdown_field(body, "Thesis impact"),
                period=period,
                content=body,
            )
        )
    return cards


def read_news_cards(workspace_dir: Path) -> list[DigestCard]:
    cards: list[DigestCard] = []
    for doc in read_news(workspace_dir):
        cards.extend(_digest_cards_from_markdown(doc.content, period=doc.period))
    return cards


def read_disclosure_cards(workspace_dir: Path) -> list[DigestCard]:
    return _digest_cards_from_markdown(read_disclosures(workspace_dir), period="disclosures")


def read_absorption_log(workspace_dir: Path) -> Optional[str]:
    return _read_text(workspace_dir / "_absorption_log.md")


def read_journal(path: Path) -> Optional[str]:
    """Read the workspace-level journal.md."""
    return _read_text(path)


@dataclass(frozen=True)
class JournalEntry:
    title: str
    date: str
    subject: str
    action_label: str
    question: str
    action: str
    frameworks: str
    ev: str
    price: str
    review_trigger: str
    workspace: str
    content: str


_JOURNAL_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _field_from_markdown(body: str, label: str) -> str:
    m = re.search(rf"^\*\*{re.escape(label)}:\*\*\s*(.+)$", body, flags=re.MULTILINE)
    return m.group(1).strip() if m else ""


def _journal_action_label(title: str, action: str) -> str:
    source = f"{action}\n{title}".upper()
    for candidate in ("BUY", "ADD", "TRIM", "SELL", "HOLD"):
        if re.search(rf"\b{candidate}\b", source):
            return candidate
    return "NOTE"


def _journal_date_and_subject(title: str) -> tuple[str, str]:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:\s*\([^)]*\))?\s*(?:[—-]\s*)?(.*)$", title)
    if not m:
        return "", title
    return m.group(1), m.group(2).strip() or title


def read_journal_entries(path: Path) -> list[JournalEntry]:
    """Parse journal.md into compact decision entries for dashboard cards."""
    text = read_journal(path)
    if not text:
        return []
    matches = list(_JOURNAL_HEADING_RE.finditer(text))
    entries: list[tuple[int, JournalEntry]] = []
    for idx, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip().strip("-").strip()
        if not body:
            continue
        action = _field_from_markdown(body, "Action")
        date_text, subject = _journal_date_and_subject(title)
        entries.append(
            (
                idx,
                JournalEntry(
                title=title,
                date=date_text,
                subject=subject,
                action_label=_journal_action_label(title, action),
                question=(
                    _field_from_markdown(body, "User question")
                    or _field_from_markdown(body, "Question")
                ),
                action=action,
                frameworks=_field_from_markdown(body, "Frameworks"),
                ev=_field_from_markdown(body, "EV"),
                price=_field_from_markdown(body, "Price"),
                review_trigger=_field_from_markdown(body, "Review trigger"),
                workspace=_field_from_markdown(body, "Workspace"),
                content=body,
                ),
            )
        )
    entries.sort(key=lambda item: (item[1].date or "", item[0]), reverse=True)
    return [entry for _, entry in entries]


@dataclass(frozen=True)
class QuarterlyDoc:
    """One file under news/ or earnings/ keyed by fiscal-quarter label."""

    period: str          # e.g. "2026-Q2" derived from the filename stem
    path: Path
    content: str


def _read_quarterly_dir(dirpath: Path) -> list[QuarterlyDoc]:
    """Return QuarterlyDocs for a per-quarter folder. Newest period first."""
    if not dirpath.is_dir():
        return []
    out: list[QuarterlyDoc] = []
    for f in sorted(dirpath.iterdir(), reverse=True):
        if not f.is_file() or not f.name.endswith(".md"):
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except OSError:
            continue
        out.append(QuarterlyDoc(period=f.stem, path=f, content=content))
    return out


def read_news(workspace_dir: Path) -> list[QuarterlyDoc]:
    return _read_quarterly_dir(workspace_dir / "news")


def read_earnings(workspace_dir: Path) -> list[QuarterlyDoc]:
    return _read_quarterly_dir(workspace_dir / "earnings")


# ---------------------------------------------------------------------------
# decisions/ — append-only audit log
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DecisionDoc:
    """One file under decisions/. Filename pattern: YYYY-MM-DD-<action>[-N].md"""

    date: str            # ISO yyyy-mm-dd parsed from filename
    action: str          # buy | add | trim | sell | hold (raw filename slice)
    suffix: str          # "" or "-2", "-3", ... for collisions
    title: str           # first non-empty line of the file (typically `# trim — ...`)
    path: Path
    content: str


_DECISION_NAME_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})-([a-z]+)(-\d+)?\.md$"
)


def read_decisions(workspace_dir: Path) -> list[DecisionDoc]:
    """Return DecisionDocs sorted newest first."""
    ddir = workspace_dir / "decisions"
    if not ddir.is_dir():
        return []
    out: list[DecisionDoc] = []
    for f in ddir.iterdir():
        if not f.is_file():
            continue
        m = _DECISION_NAME_RE.match(f.name)
        if not m:
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except OSError:
            continue
        title = next(
            (ln.lstrip("# ").strip() for ln in content.splitlines() if ln.strip()),
            f.stem,
        )
        out.append(
            DecisionDoc(
                date=m.group(1),
                action=m.group(2),
                suffix=m.group(3) or "",
                title=title,
                path=f,
                content=content,
            )
        )
    out.sort(key=lambda d: (d.date, d.suffix), reverse=True)
    return out


# ---------------------------------------------------------------------------
# Workspace discovery
# ---------------------------------------------------------------------------

def list_workspace_slugs(holdings_dir: Path) -> list[str]:
    """Slugs are the immediate subdirectory names under holdings/."""
    if not holdings_dir.is_dir():
        return []
    return sorted(
        p.name
        for p in holdings_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )
