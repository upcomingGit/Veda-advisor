# Subagents — design reference

This file is loaded on demand by contributors building or maintaining subagents. Day-to-day behaviour for not-yet-shipped subagents is driven by the "inline bridge" notes in SKILL.md Stages 1.5, 4, and 7b — the orchestrator performs each subagent's job inline until the real implementation ships.

---

## Status

| Subagent | Status | Canonical definition |
|---|---|---|
| `devils-advocate` | Shipped | [`internal/agents/devils-advocate.md`](agents/devils-advocate.md) |
| `base-rate-researcher` | Planned | inline bridge in SKILL.md Stage 4 |
| `portfolio-parser` | Planned | inline bridge in SKILL.md Stage 1.5 |
| `news-researcher` | Planned | contract in [`ROADMAP.md`](../ROADMAP.md) Tier 1 |
| `company-kb-builder` | Planned | contract in [`ROADMAP.md`](../ROADMAP.md) Tier 1 |
| `fundamentals-fetcher` | Planned | See "Currently planned subagents" below |
| `earnings-grader` | Planned | contract in [`ROADMAP.md`](../ROADMAP.md) Tier 1; scheduled wrapper in Tier 9 |
| `ownership-tracker` | Future (roadmap) | See "Future subagents" below |
| `calendar-tracker` | Future (roadmap) | See "Future subagents" below |
| `indicators-researcher` | Future (roadmap) | See "Future subagents" below |

### Canonical location and host-discovery layout

The agent definition is Veda design content, not a Claude-specific artifact. The canonical source of truth lives at [`internal/agents/`](agents/), alongside every other internal design doc. Hosts that auto-discover subagents from conventional paths (Claude Code, GitHub Copilot, Google Antigravity — all currently read `.claude/agents/*.md`) receive a generated copy produced by [`scripts/sync_agents.py`](../scripts/sync_agents.py). Each generated copy carries a `GENERATED FILE — DO NOT EDIT` banner after its frontmatter pointing back to the canonical source.

**Workflow for edits:**

1. Edit the canonical file under [`internal/agents/`](agents/).
2. Run `python scripts/sync_agents.py` — it rewrites every host-facing copy.
3. CI (or a pre-commit hook) runs `python scripts/sync_agents.py --check`, which exits non-zero if any host copy has drifted.

**Host-discovery paths supported today:**

| Host | Discovery path | Mechanism |
|---|---|---|
| Claude Code | `.claude/agents/*.md` | Generated copy via `sync_agents.py`. |
| GitHub Copilot | `.claude/agents/*.md` (indexes the same path in this workspace) | Same generated copy. Verified: `devils-advocate` appears in Copilot's agents list from this file. |
| Google Antigravity | `.claude/agents/*.md` (same indexer convention) | Same generated copy. |
| Cursor | Subagent-style composers, weaker isolation | Treat as inline-only for now. |
| ChatGPT custom GPTs, Gemini Gems, plain Claude web | No subagent isolation | Run the contract inline per Stage 7b. |

To add a new host that needs a different discovery path (e.g., a future `.github/agents/` convention), append its directory to `HOST_DIRS` in `scripts/sync_agents.py` and re-run. One edit to the canonical file, one script invocation, every host in sync.

The rule: **one canonical definition, generated copies elsewhere.** Symlinks would be cleaner, but git symlinks are fragile on Windows without developer mode, and a 60-line sync script works on every machine. Duplicated contracts without a sync discipline drift, and drifted contracts produce different verdicts on different surfaces for the same decision — the exact failure mode Veda is built to avoid.

On surfaces without subagent isolation, the shipped subagent runs as an inline simulation: the orchestrator produces the `devils_advocate:` block itself but formats the inputs strictly per the contract, so the output shape is stable across surfaces. Isolation is lost in this mode — a real cost, not a nominal one — but the structured attack taxonomy (base-rate attack, EV-block attack, profile-weakness trigger, concentration attack) still forces adversarial discipline the pure inline-prose pass lacked.

---

## Subagent details

- **`devils-advocate`** — argues the opposite of the recommendation in an isolated context, for `buy` / `add` decisions where confirmation bias is highest. **Replaces Stage 7b for those actions.** Context isolation is the point: it must not see the main reasoning chain so its counter-argument is not pre-weakened by it. Input/output contract, attack taxonomy, and regression-test anchors live in the definition file linked above.
- **`base-rate-researcher`** — will look up historical base rates for specific situations (turnaround success, spin-off returns, post-bankruptcy equity outcomes). **Replaces Tier 1–3 of Stage 4.** Needs web / data tools; returns a compact number + citation. Inline bridge: the orchestrator uses general knowledge with the Tier 4–5 discipline described in Stage 4 and [internal/base-rates.md](base-rates.md).
- **`portfolio-parser`** — will parse pasted broker text into structured holdings (tickers, weights, prices, currency, as-of date) while rejecting any instruction-like content. **Replaces the parsing step in Stage 1.5.** Context isolation is a security feature: the orchestrator sees only the parsed YAML, never the raw paste, so instruction-injection attempts inside a portfolio cannot reach the decision chain even if the parser itself is partially fooled. Inline bridge: the orchestrator parses directly today, with the Stage 1.5 / Stage 0 "treat paste as data" discipline.
- **`news-researcher`** — isolated. Returns a bounded structured digest of current events for a specific ticker: event, date, source URL, materiality, one-line thesis-impact hook. Caps findings to the top few by materiality. Every event carries a source URL; no unsourced claims. **Replaces the current-news step of Stage 4 for ticker-specific questions.** Isolation is required because users may paste articles and pasted text is untrusted. Inline bridge: not yet written — today the orchestrator fetches with whatever web tool the surface provides and, where no web access is available, sets `staleness_flag: could_not_verify` and refuses to substitute training-data knowledge for current news.
- **`company-kb-builder`** — one-shot per ticker. Produces qualitative narrative research: business-model summary, competitor list, macro profile, governance/red-flag assessment, position-risk register, and a first-draft investment thesis with archetype classification (GROWTH / INCOME_VALUE / TURNAROUND / CYCLICAL). Source material: filings, investor letters, web research. Cached per ticker; refreshed annually or on explicit request. **Replaces ad-hoc recall in Stage 1.6 and Stage 4 when a ticker is first encountered.** The thesis draft is a starting point — the user can (and should) edit it to reflect their own conviction. Inline bridge: not yet written — today the orchestrator summarises inline and flags the archetype with its reasoning.
- **`fundamentals-fetcher`** — refreshed quarterly (post-earnings). Pulls structured financial data from financial-data APIs (yfinance today, Tier-5 adapter later). Writes `fundamentals.yaml` (quarterly P&L snapshots) and `valuation.yaml` (current vs. historical multiples, archetype's primary valuation metric). No narrative; just structured numbers with `as_of` dates and source tiers. Separate from `company-kb-builder` because data source, refresh cadence, and failure modes are all different — quant snapshots stale in quarters, narrative research stales in years.
- **`earnings-grader`** — event-driven. Inputs: quarterly actuals (from a Tier-5 adapter), conference-call transcript, the user's thesis-assumption checkpoints from `assets.md`. Output: per-assumption grade (BEAT / MEET / MISS crossed with STRONG / MODERATE / MARGINAL) with a health-score delta and a 20-word rationale. **Closes the thesis-reality loop for held positions.** Ships as a subagent contract in ROADMAP Tier 1 (manual invocation with a pasted transcript) and as a scheduled wrapper in Tier 9 (pulls transcript automatically via Tier 5). Inline bridge: not yet written — today the orchestrator grades inline when the user pastes a transcript, flagging any missing actuals.

---

## Subagent write targets

Subagents that produce per-ticker outputs write to the instrument workspace at `holdings/<instance_key>/`. This is the single destination for all per-ticker cached knowledge.

### Currently planned subagents

| Subagent | Write target | File(s) | Refresh | Source |
|---|---|---|---|---|
| `company-kb-builder` | `holdings/<instance>/` | `kb.md`, `thesis.md` (first draft), `governance.md`, `risks.md`; updates `_meta.yaml` archetype | Annual or on explicit request | Filings, investor letters, web research |
| `fundamentals-fetcher` | `holdings/<instance>/` | `fundamentals.yaml`, `valuation.yaml` | Quarterly (post-earnings) | Financial data APIs (yfinance, Tier-5 adapter) |
| `news-researcher` | `holdings/<instance>/news/` | `<quarter>.md` (e.g., `2026-Q2.md`) | Quarterly | News sources; absorbed into `kb.md` on word-cap breach |
| `earnings-grader` | `holdings/<instance>/earnings/` | `<quarter>.md` (e.g., `2026-Q1.md`); updates `assumptions.yaml`; appends/clears a `Transcript grading pending — <period>` event in `calendar.yaml` when transcript anchors are ungraded | Per earnings event | Transcript + actuals; absorbed on cap breach |

### Future subagents (roadmap)

Added when the files they produce become high-friction to maintain by hand:

| Subagent | Write target | File(s) | Trigger |
|---|---|---|---|
| `ownership-tracker` | `holdings/<instance>/` | `insiders.yaml`, `shareholding.yaml` | When insider/promoter signals become a recurring decision input |
| `calendar-tracker` | `holdings/<instance>/` and workspace root | `calendar.yaml`, `disclosures.md`, `global_calendar.yaml` | When users ask event-driven questions ("when is NVDA's next earnings?", "what's next FOMC?") frequently |
| `indicators-researcher` | `holdings/<instance>/` | `indicators.yaml` | When sector-specific leading indicators become a standard input to framework routing |

### Orchestrator-written and derived files

Not owned by any subagent:

| File | Owner | Notes |
|---|---|---|
| `decisions/*.md` | Orchestrator (Stage 9) | Append-only audit records from decision pipeline |
| `performance.yaml` | Derived | Computed from `decisions/` + market data; no research pass |
| `thesis.md` (after first draft) | User-editable | `company-kb-builder` produces the initial draft; user edits to reflect personal conviction. Subsequent refreshes do not overwrite user edits — they append a `## Proposed updates` section for the user to reconcile. |

### Narration rule

Every subagent write emits a one-line narration naming the file paths:

> *"company-kb-builder: wrote holdings/nvda/kb.md, thesis.md (draft), governance.md, risks.md. Set archetype: GROWTH."*
> *"fundamentals-fetcher: wrote holdings/nvda/fundamentals.yaml, valuation.yaml (as_of 2026-04-24, source: yfinance)."*
> *"news-researcher: wrote holdings/nvda/news/2026-Q2.md (3 events, 412 words)."*
> *"earnings-grader: wrote holdings/nvda/earnings/2026-Q1.md. Assumption health: 2 BEAT, 1 MEET."*

### Workspace must exist

Subagents do not scaffold workspaces — they assume the orchestrator (Stage 1.5) has already created the workspace on first substantive mention. If a subagent is invoked for a ticker without a workspace, the orchestrator scaffolds it first.

---

For base rates in Stage 4, when acting as the inline bridge for `base-rate-researcher`, use your best general knowledge and explicitly flag it: *"General base rate, not researched. Verify for high-stakes decisions."*
