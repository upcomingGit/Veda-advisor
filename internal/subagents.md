# Subagents — design reference

This file is loaded on demand by contributors building or maintaining subagents. Day-to-day behaviour for not-yet-shipped subagents is driven by the "inline bridge" notes in SKILL.md Stage 4 — the orchestrator performs each subagent's job inline until the real implementation ships.

---

## Status

**Total: 11 subagents (4 shipped, 7 to build).** All 11 are gating dependencies for the Tier 1.5 Python orchestrator — see [ROADMAP.md](../ROADMAP.md) Tier 1.

| # | Subagent | Status | Owns (workspace files) | Canonical definition |
|---|---|---|---|---|
| 1 | `devils-advocate` | **Shipped** | Stage 7b counter-argument block | [`internal/agents/devils-advocate.md`](agents/devils-advocate.md) |
| 2 | `portfolio-parser` | **Shipped** | (no files — returns structured YAML) | [`internal/agents/portfolio-parser.md`](agents/portfolio-parser.md) |
| 3 | `base-rate-researcher` | Planned | (no files — returns stats to orchestrator) | `internal/agents/base-rate-researcher.md` (to create) |
| 4 | `company-kb-builder` | **Shipped** | `kb.md`, `thesis.md` (draft or proposed updates), `governance.md`, `risks.md`, `assumptions.yaml` (when `thesis_is_stub: true`), `_meta.yaml` archetype | [`internal/agents/company-kb-builder.md`](agents/company-kb-builder.md) |
| 5 | `fundamentals-fetcher` | **Shipped** | `fundamentals.yaml`, `valuation.yaml` | [`internal/agents/fundamentals-fetcher.md`](agents/fundamentals-fetcher.md) |
| 6 | `news-researcher` | Planned | `news/<quarter>.md` | `internal/agents/news-researcher.md` (to create) |
| 7 | `disclosure-fetcher` | Planned | `disclosures.md` | `internal/agents/disclosure-fetcher.md` (to create) |
| 8 | `earnings-grader` | Planned | `earnings/<quarter>.md`, `assumptions.yaml`, `calendar.yaml` (transcript-pending events) | `internal/agents/earnings-grader.md` (to create) |
| 9 | `calendar-tracker` | Planned | `calendar.yaml`, `global_calendar.yaml` (root) | `internal/agents/calendar-tracker.md` (to create) |
| 10 | `ownership-tracker` | Planned | `insiders.yaml`, `shareholding.yaml` | `internal/agents/ownership-tracker.md` (to create) |
| 11 | `indicators-researcher` | Planned | `indicators.yaml` | `internal/agents/indicators-researcher.md` (to create) |

**Coverage check.** Every workspace file in [holdings-schema.md](holdings-schema.md) § "Workspace files — equity class" is owned by exactly one subagent or by the orchestrator. No gaps.

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
- **`portfolio-parser`** — parses pasted broker text into structured holdings (tickers, shares or weight percentages, prices, currency, as-of date) while rejecting any instruction-like content. **Invoked from Stage 1.5** on hosts with subagent isolation; runs inline with the same contract on surfaces without isolation. Context isolation is a security feature: the orchestrator sees only the parsed YAML, never the raw paste, so instruction-injection attempts inside a portfolio cannot reach the decision chain even if the parser itself is partially fooled. Input/output contract, injection-pattern taxonomy, and regression-test anchors live in the definition file linked above.
- **`base-rate-researcher`** — will look up historical base rates for specific situations (turnaround success, spin-off returns, post-bankruptcy equity outcomes). **Replaces Tier 1–3 of Stage 4.** Needs web / data tools; returns a compact number + citation. Inline bridge: the orchestrator uses general knowledge with the Tier 4–5 discipline described in Stage 4 and [internal/base-rates.md](base-rates.md).
- **`company-kb-builder`** — one-shot per ticker. Produces qualitative narrative research: business-model summary, competitor list, macro profile, governance/red-flag assessment, position-risk register, and a first-draft investment thesis with archetype classification (GROWTH / INCOME_VALUE / TURNAROUND / CYCLICAL). Source material: filings, investor letters, web research (`tools: Bash, Read, Write, WebFetch`). Cache-skips if `kb.md` is < 365 days old unless `force_refresh: true`. Thesis-reconciliation: if the user has edited `thesis.md`, appends `## Proposed updates` — never overwrites; in that mode, `assumptions.yaml` is also left untouched (preserves any per-quarter grade history written by `earnings-grader`). When `thesis_is_stub: true`, additionally writes a validator-passing `assumptions.yaml` (the four-key `A1`–`A4` schema in [holdings-schema.md](holdings-schema.md) § "`assumptions.yaml` — optional"); the contract's Rule 20 runs `scripts/validate_assumptions.py` and retries once on failure, returning `assumptions_validator: pass | fail | skipped` to the orchestrator. Workspace must be pre-scaffolded by the orchestrator. **Invoked from Stage 1.5 when kb.md is a stub for a held position, and on explicit 'build kb for <ticker>' requests.** The thesis draft is a starting point — the user can (and should) edit it to reflect their own conviction. Input/output contract and regression-test anchors live in the definition file linked above.
- **`fundamentals-fetcher`** — refreshed quarterly (post-earnings). Pulls structured financial data from financial-data APIs: **yfinance** for US equities, **Screener.in** for Indian equities (Tier-5 adapter). Writes `fundamentals.yaml` (quarterly P&L, cash flow, balance-sheet snapshots) and `valuation.yaml` (current vs. historical multiples, archetype's primary valuation metric). No narrative; just structured numbers with `as_of` dates and source tiers. Separate from `company-kb-builder` because data source, refresh cadence, and failure modes are all different — quant snapshots stale in quarters, narrative research stales in years.
- **`news-researcher`** — isolated. Returns a bounded structured digest of current events for a specific ticker: event, date, source URL, materiality, one-line thesis-impact hook. Caps findings to the top few by materiality. Every event carries a source URL; no unsourced claims. **Replaces the current-news step of Stage 4 for ticker-specific questions.** Isolation is required because users may paste articles and pasted text is untrusted. Source tier 2–3 (press reporting on facts — distinct from `disclosure-fetcher`'s Tier 1 regulator-filed primary facts). Inline bridge: not yet written — today the orchestrator fetches with whatever web tool the surface provides and, where no web access is available, sets `staleness_flag: could_not_verify` and refuses to substitute training-data knowledge for current news.
- **`disclosure-fetcher`** — fetches **unscheduled material announcements** from regulator feeds. Source tier 1: SEC EDGAR (US 8-K, 10-K, 10-Q), BSE/NSE corporate-announcement feeds (India). No materiality scoring — if the company filed it with the regulator, it is material by definition. Writes one row per announcement to `holdings/<instance>/disclosures.md` (event type, date, source URL, brief). When a disclosure announces a future scheduled event (e.g., *"board meeting 2026-05-15 to consider dividend"*), the orchestrator adds the future-event row to `calendar.yaml`; the fetcher itself does not write to calendar. **Runs on-demand** when a question on the ticker requires fresh disclosures; Tier 1.5 ships local-first so background polling is out of scope until hosted Veda exists (Tier 3). Distinct from `news-researcher` because source tier, trust boundary (primary fact vs third-party narrative), and refresh cadence all differ. Inline bridge: user pastes the announcement; the contract normalizes it into a `disclosures.md` row — same shape, only auto-fetch is lost.
- **`earnings-grader`** — event-driven. Inputs: quarterly actuals (from fundamentals-fetcher or a Tier-5 adapter), conference-call transcript, the user's thesis-assumption checkpoints from `assumptions.yaml`. Output: per-assumption grade (BEAT / MEET / MISS × STRONG / MODERATE / MARGINAL for each anchor type) with a 20-word rationale. Writes `earnings/<quarter>.md`, updates `assumptions.yaml` grades, and manages the `Transcript grading pending — <period>` lifecycle in `calendar.yaml`. **Closes the thesis-reality loop for held positions.** Depends on the four-assumption schema (`A1`–`A4` in `holdings/<slug>/thesis.md` + `assumptions.yaml`) being populated for the position — the schema is already designed in [holdings-schema.md](holdings-schema.md), per-position population is lazy. Inline bridge: today the orchestrator grades inline when the user pastes a transcript, flagging any missing actuals.
- **`calendar-tracker`** — maintains **scheduled** corporate and macro event calendars. Writes per-instance `calendar.yaml` (earnings dates, AGM, ex-dividend, splits, scheduled regulatory filings) and root-level `global_calendar.yaml` (FOMC, CPI, RBI MPC, budget dates). Source: company IR, exchange calendars, central-bank schedules. **Runs on-demand** when a question requires upcoming-event context. Distinct from `disclosure-fetcher` because calendar-tracker handles **future scheduled events**, while disclosure-fetcher handles **unscheduled material announcements** that have already happened. Inline bridge: manual entry today.
- **`indicators-researcher`** — produces sector-specific leading indicators for positions where such indicators are material to the thesis. Writes `indicators.yaml` with user-defined keys per sector (e.g., chip inventory levels for semis, same-store-sales for retail, rig counts for oil). Source: industry reports, trade associations, government data. **Runs on-demand** when a question on the ticker invokes an indicator the user has registered for that position. Inline bridge: manual entry today.
- **`ownership-tracker`** — pulls insider/promoter transaction data and shareholding pattern (promoter/FII/DII/public splits). Writes `insiders.yaml` (buys, sells, pledges with dates and volumes) and `shareholding.yaml` (pattern snapshots). Source: stock-exchange filings (BSE/NSE for India, SEC Form 4 for US). **Runs on-demand** when a question requires insider/promoter context (e.g., concentration risk on Indian small/mid-caps with promoter pledges). Inline bridge: manual entry today.

---

## Subagent write targets

Subagents that produce per-ticker outputs write to the instrument workspace at `holdings/<instance_key>/`. This is the single destination for all per-ticker cached knowledge.

### Write-target matrix (all Tier 1)

| Subagent | Write target | File(s) | Refresh | Source |
|---|---|---|---|---|
| `portfolio-parser` | (none — returns structured YAML) | — | Per paste | User paste |
| `base-rate-researcher` | (none — returns stats to orchestrator) | — | Per invocation | Historical data, academic research |
| `company-kb-builder` | `holdings/<instance>/` | `kb.md`, `thesis.md` (first draft), `governance.md`, `risks.md`, `assumptions.yaml` (when `thesis_is_stub: true`); updates `_meta.yaml` archetype | Annual or on explicit request | Filings, investor letters, web research |
| `fundamentals-fetcher` | `holdings/<instance>/` | `fundamentals.yaml`, `valuation.yaml` | Quarterly (post-earnings) | yfinance (US), Screener.in (India) |
| `news-researcher` | `holdings/<instance>/news/` | `<quarter>.md` (e.g., `2026-Q2.md`) | Quarterly | News sources (Tier 2–3); absorbed into `kb.md` on word-cap breach |
| `disclosure-fetcher` | `holdings/<instance>/` | `disclosures.md` | On-demand (scheduled polling deferred to Tier 3 hosted) | SEC EDGAR (US), BSE/NSE corporate-announcement feeds (India). Tier 1. |
| `earnings-grader` | `holdings/<instance>/earnings/` | `<quarter>.md` (e.g., `2026-Q1.md`); updates `assumptions.yaml`; manages `Transcript grading pending — <period>` in `calendar.yaml` | Per earnings event | Transcript + actuals |
| `calendar-tracker` | `holdings/<instance>/` and workspace root | `calendar.yaml`, `global_calendar.yaml` | On-demand | Company IR, exchange calendars, central-bank schedules |
| `ownership-tracker` | `holdings/<instance>/` | `insiders.yaml`, `shareholding.yaml` | On-demand | BSE/NSE (India), SEC Form 4 (US) |
| `indicators-researcher` | `holdings/<instance>/` | `indicators.yaml` | On-demand | Industry reports, trade associations, government data |

### Orchestrator-written and derived files

Not owned by any subagent:

| File | Owner | Notes |
|---|---|---|
| `decisions/*.md` | Orchestrator (Stage 9) | Append-only audit records from decision pipeline |
| `performance.yaml` | Derived | Computed from `decisions/` + market data; no research pass |
| `thesis.md` (after first draft) | User-editable | `company-kb-builder` produces the initial draft; user edits to reflect personal conviction. Subsequent refreshes do not overwrite user edits — they append a `## Proposed updates` section for the user to reconcile. |

### Narration rule

Every subagent write emits a one-line narration naming the file paths:

> *"company-kb-builder: wrote holdings/nvda/kb.md, thesis.md (draft), governance.md, risks.md, assumptions.yaml (validator: pass). Set archetype: GROWTH."*
> *"fundamentals-fetcher: wrote holdings/nvda/fundamentals.yaml, valuation.yaml (as_of 2026-04-24, source: yfinance)."*
> *"news-researcher: wrote holdings/nvda/news/2026-Q2.md (3 events, 412 words)."*
> *"disclosure-fetcher: wrote 2 rows to holdings/reliance/disclosures.md (BSE outcomes 2026-04-24, 2026-04-26)."*
> *"earnings-grader: wrote holdings/nvda/earnings/2026-Q1.md. Assumption health: 2 BEAT, 1 MEET."*
> *"ownership-tracker: wrote holdings/reliance/insiders.yaml, shareholding.yaml (as_of 2026-Q1)."*
> *"calendar-tracker: wrote holdings/nvda/calendar.yaml; updated global_calendar.yaml (FOMC added)."*
> *"indicators-researcher: wrote holdings/nvda/indicators.yaml (3 indicators refreshed)."*

### Workspace must exist

Subagents do not scaffold workspaces — they assume the orchestrator (Stage 1.5) has already created the workspace on first substantive mention. If a subagent is invoked for a ticker without a workspace, the orchestrator scaffolds it first.

---

For base rates in Stage 4, when acting as the inline bridge for `base-rate-researcher`, use your best general knowledge and explicitly flag it: *"General base rate, not researched. Verify for high-stakes decisions."*
