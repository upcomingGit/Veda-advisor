# holdings-schema.md — equity-class workspace schema (v1)

This file defines what goes inside `holdings/<instance_key>/` for
`instrument_class: equity`. Non-equity classes (ETF, SGB, FD) are out of
scope for v1; see [company-workspaces.md](../docs/design/company-workspaces.md) Phase 6.

---

## `_meta.yaml` — required fields

Every workspace directory MUST contain a `_meta.yaml` at its root.

```yaml
schema_version: 1
instrument_class: equity
archetype: GROWTH          # GROWTH | INCOME_VALUE | TURNAROUND | CYCLICAL
last_touched: 2026-04-23   # ISO date; updated on any file write in this workspace
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | int | yes | Current version is `1`. Validators reject values > current. |
| `instrument_class` | enum | yes | Must match the registry row. V1 allows `equity` only. |
| `archetype` | enum | yes (equity) | One of `GROWTH`, `INCOME_VALUE`, `TURNAROUND`, `CYCLICAL`. Drives framework routing. |
| `last_touched` | ISO date | yes | Updated automatically on any write to the workspace. |

---

## Workspace files — equity class

| File | Required | Purpose | Word cap |
|---|---|---|---|
| `_meta.yaml` | yes | Metadata (see above). | n/a |
| `kb.md` | yes | Business-model summary, competitor list, macro profile. | 2,000 |
| `thesis.md` | yes | Investment thesis with explicit kill criteria. | 500 |
| `decisions/` | yes (dir) | Append-only decision log; one file per decision. | no cap |
| `fundamentals.yaml` | optional | Quarterly P&L snapshots from Tier-5 adapter. | n/a |
| `valuation.yaml` | optional | Valuation-zone data per archetype's primary metric. | n/a |
| `indicators.yaml` | optional | Leading indicators — sector-specific, user-defined keys. | n/a |
| `insiders.yaml` | optional | Insider/promoter transactions — buys, sells, pledges. | n/a |
| `shareholding.yaml` | optional | Shareholding pattern — promoter/FII/DII/public splits. | n/a |
| `governance.md` | optional | Management quality, related-party transactions, red flags. | 1,000 |
| `risks.md` | optional | Position-specific risks — concentration, regulatory, litigation. | 1,000 |
| `calendar.yaml` | optional | Corporate calendar — earnings dates, AGM, ex-dividend, splits. | n/a |
| `performance.yaml` | optional | Historical performance — entry price, CAGR, thesis tracking. | n/a |
| `disclosures.md` | optional | Material corporate announcements. | 1,500 |
| `news/<quarter>.md` | optional | Quarterly news digest; absorbed into `kb.md` on cap breach. | 1,500 |
| `earnings/<quarter>.md` | optional | Earnings-call grades per assumption; absorbed on cap breach. | 2,500 |
| `assumptions.yaml` | optional | Per-assumption grade history across quarters. Created by `earnings-grader`. Never absorbed. | n/a |
| `_absorption_log.md` | created on first absorption | Metadata log of absorbed files. | n/a |

### Creation behavior

#### When lazy creation triggers

A workspace is scaffolded only on **commit**. Exactly two triggers:

1. **Held position with a substantive question.** The ticker is in `assets.md` (user holds it), the user asks a substantive question (decision, hold_check, thesis review, valuation, risk), and no workspace exists at `holdings/<slug>/`. Scaffolded by the orchestrator at Stage 1.5.
2. **New `buy` decision.** The decision pipeline produces a `buy` action at Stage 8 for a ticker with no existing workspace. Scaffolded by the orchestrator at Stage 9a as part of the decision write. A `buy` is the unambiguous commit event.

Do NOT scaffold for:
- General questions ("what does NVDA do?")
- "Considering buying" mentions — evaluation is not commitment. Users evaluate many more names than they buy; scaffolding on intent fills `holdings/` with workspaces for rejected names.
- Watchlist mentions without a decision question.
- `WAIT` / `DECLINE` / data-gate verdicts on non-held tickers — these are point-in-time decisions, not ongoing positions. They are recorded in `journal.md` only.

**Rationale.** A workspace implies ongoing tracking (thesis, assumptions, earnings grades, decision history). Point-in-time evaluations that end in WAIT or decline do not merit that structure. The journal is the right destination for "I looked at NVDA on 2026-04-24 and declined pending valuation data."

#### Scaffolded files

On workspace scaffold (orchestrator, lazy):
- `_meta.yaml` — created with required fields (archetype inferred or asked).
- `kb.md` — created as stub: `_(to be populated)_`
- `thesis.md` — created as stub with archetype header: `_(to be populated)_`
- `decisions/` — created as empty directory.
- All other files — not created; added when data arrives.

The orchestrator scaffolds a **minimal** workspace so the decision pipeline can proceed immediately. Richer content (business-model summary, first-draft thesis, governance notes, fundamentals) is produced by subagents on first encounter or on subsequent turns — see [internal/subagents.md](subagents.md) § "Subagent write targets". Until a subagent populates them, `kb.md` and `thesis.md` remain stubs and the decision pipeline falls back to `assets.md` thesis column + general knowledge.

#### Registry row

On scaffold, if no row exists in `holdings_registry.csv` for this `instance_key`:
- Append a new row: `instance_key,equity,<display_name>,<today>,<empty>,active,<empty>`
- Narrate: `"Added <ticker> to holdings_registry.csv."`

#### Archetype inference

Archetype determines which investor frameworks are routed to the position. Inference rules:

| Company profile | Inferred archetype | Confidence |
|---|---|---|
| High earnings/revenue growth (>15% YoY), reinvesting profits, tech/biotech/SaaS | `GROWTH` | high |
| Stable earnings, regular dividends, mature business, utility/REIT/consumer staple | `INCOME_VALUE` | high |
| Commodity producer, industrial, bank, interest-rate or cycle sensitive | `CYCLICAL` | high |
| Distressed, restructuring, post-bankruptcy, management turnaround | `TURNAROUND` | high |
| Mixed signals (mature tech with dividends, diversified conglomerate) | ask user | — |

**When inference is high-confidence**, set the archetype and narrate:

> *"Archetype inferred: GROWTH (high-growth tech, reinvesting profits)."*

**When ambiguous**, ask using plain language:

> *"I need to know how you're thinking about this position — it affects which investment frameworks I'll use.*
>
> *Archetype options:*
> - **GROWTH** — you're betting on earnings/revenue growth. Metrics: PEG ratio, revenue growth rate. Frameworks: Lynch, Fisher.
> - **INCOME_VALUE** — you want steady income or undervalued assets. Metrics: dividend yield, P/E, book value. Frameworks: Buffett, Klarman.
> - **CYCLICAL** — earnings rise and fall with economic/commodity cycles. Metrics: cycle position, P/E at trough. Frameworks: Druckenmiller, Marks.
> - **TURNAROUND** — you're betting on a distressed company recovering. Metrics: debt paydown, management change, breakup value. Frameworks: Klarman, Marks.
>
> *Which fits your thesis for [TICKER]?"*

#### Narration

On lazy scaffold:

> *"Creating workspace at holdings/<slug>/. Archetype: GROWTH (inferred: high-growth tech)."*

or

> *"Creating workspace at holdings/<slug>/. Archetype: INCOME_VALUE (user confirmed)."*

### Word caps and absorption

Absorption controls workspace bloat by condensing or merging files that exceed their word caps. Per Q3 in [company-workspaces.md](../docs/design/company-workspaces.md).

#### When absorption fires

Absorption is detected and executed **during `sync`** only. Word-cap breaches are included in the sync plan; the user confirms `apply` before any absorption runs. This matches the plan-then-confirm pattern for all destructive operations.

Absorption does NOT fire automatically on file writes or session load.

#### Word count measurement

Naive whitespace split: `len(content.split())`. Matches `wc -w` roughly. Caps are soft targets, not hard thresholds.

#### Per-file behaviour

Two behaviour types:

1. **Condense in place.** Veda rewrites the file to be under the cap, preserving all citations and source URLs. Original content is overwritten. No deletion.
2. **Absorb and delete.** Veda summarises the file's content into `kb.md` (and optionally other targets), then deletes the original file.

| File | Cap | On breach | Type |
|---|---|---|---|
| `kb.md` | 2,000 | Rewrite to be under cap; preserve citations and structure | Condense in place |
| `thesis.md` | 500 | Append `## Proposed condensation` section with shorter draft; do NOT overwrite user content | Flag for user revision (special) |
| `governance.md` | 1,000 | Rewrite to be under cap; preserve structure | Condense in place |
| `risks.md` | 1,000 | Rewrite to be under cap; preserve structure | Condense in place |
| `disclosures.md` | 1,500 | Rewrite to be under cap; preserve URLs and dates | Condense in place |
| `news/<quarter>.md` | 1,500 | Summarise into `kb.md` "Recent developments" section with URLs; delete original | Absorb and delete |
| `earnings/<quarter>.md` | 2,500 | Append per-assumption grades to `assumptions.yaml` (create if absent); summarise narrative into `kb.md` "Recent earnings" section; delete original | Absorb and delete |
| `decisions/*.md` | no cap | Never absorbed | Exempt (audit trail) |

**thesis.md special handling.** Because thesis is user-editable (see [subagents.md](subagents.md) § "Orchestrator-written and derived files"), Veda does NOT rewrite it. Instead, it appends a `## Proposed condensation` section with a shorter draft the user can adopt. The oversized version stays until the user edits. The sync plan marks these as "flag for user revision" rather than "condense".

**Files without word caps.** All YAML files (`_meta.yaml`, `fundamentals.yaml`, `valuation.yaml`, `indicators.yaml`, `insiders.yaml`, `shareholding.yaml`, `calendar.yaml`, `performance.yaml`, `assumptions.yaml`) and `_absorption_log.md` have no word cap and are never absorbed.

#### `_absorption_log.md` format

Created on first absorption in the workspace. Each absorption event is appended as a markdown section:

```markdown
## 2026-04-24 — news/2026-Q1.md

- **Source:** holdings/msft/news/2026-Q1.md (1,612 words, cap 1,500)
- **Target:** kb.md (appended to "Recent developments" section)
- **Items absorbed:** 17 news entries
- **URLs preserved:** 17
- **Trigger:** sync apply
- **Original file:** deleted
```

For condense-in-place, the entry format is:

```markdown
## 2026-04-24 — kb.md condensation

- **Source:** holdings/msft/kb.md (2,340 words, cap 2,000)
- **Result:** Condensed to 1,890 words
- **Trigger:** sync apply
- **Original file:** overwritten
```

#### Narration

On absorption during sync apply:

> *"Condensing holdings/msft/kb.md: 2,340 → 1,890 words. Logged in _absorption_log.md."*

> *"Absorbing holdings/msft/news/2026-Q1.md (1,612 words) into kb.md. 17 entries with URLs. Deleting original. Logged in _absorption_log.md."*

> *"holdings/msft/thesis.md exceeds cap (612 words, cap 500). Appending proposed condensation section for user review."*

---

## `kb.md` — knowledge base

Plain markdown. Structure is flexible; common sections:

```markdown
# <display_name> — Knowledge Base

## Business model
_(one-paragraph summary)_

## Competitors
_(bullet list)_

## Macro sensitivity
_(interest rates, currency, commodity, regulatory exposure)_

## Key metrics to watch
_(revenue growth, margins, backlog, etc.)_
```

---

## `thesis.md` — investment thesis

Plain markdown. Must include a **kill criterion** — the condition under which
the position should be exited regardless of price.

**Ownership.** First draft is produced by `company-kb-builder` (see [internal/subagents.md](subagents.md)). The user edits it to reflect their personal conviction — the draft is a starting point, not a final answer. On subsequent refresh passes, `company-kb-builder` does NOT overwrite the user's edits; it appends a `## Proposed updates` section with any new research findings for the user to reconcile.

```markdown
# <display_name> — Investment Thesis

**Archetype:** GROWTH

## Core thesis
_(why this position exists in the portfolio)_

## Kill criterion
_(explicit condition that invalidates the thesis — e.g., "leverage >8x",
"founder exits", "regulatory ban in primary market")_

## Key assumptions
_(bulleted list of assumptions that must hold for the thesis to remain valid)_
```

**Assumption keys.** `## Key assumptions` MUST contain exactly **four** bullets using stable keys `A1`, `A2`, `A3`, `A4` that match the `assumptions` map in [`assumptions.yaml`](#assumptionsyaml--optional). Four is the working count — enough to cover a growth driver, a margin/unit-economics driver, a financial-health constraint, and a going-concern guard without bloating the thesis. The keys are what allow cross-quarter grade comparison to be anchored to the same statement over time. Example bullet: `- **A1.** Azure revenue growth >20% YoY`.

---

## `decisions/` — decision log

One file per decision, named `YYYY-MM-DD-<action>.md`. Allowed actions match the SKILL.md decision pipeline: `buy`, `add`, `trim`, `sell`, `hold`.

| Action | File example | Meaning |
|---|---|---|
| buy | `2026-04-23-buy.md` | New position opened |
| add | `2026-04-23-add.md` | Existing position increased |
| trim | `2026-04-23-trim.md` | Existing position partially reduced |
| sell | `2026-04-23-sell.md` | Position fully closed |
| hold | `2026-04-23-hold.md` | Hold-check resulted in no action (still journaled) |

**Filename collisions.** If a decision file with the same name already exists (same ticker, same day, same action), append a numeric suffix: `2026-04-23-hold-2.md`, `-3.md`, etc. Never overwrite existing decision files.

Decision files are append-only audit records. They are never absorbed,
edited, or deleted.

Minimal structure:

```markdown
# <action> — <display_name>

**Date:** YYYY-MM-DD
**Action:** <action>
**Shares:** <delta or total>
**Price:** <execution price or range>

## Rationale
_(why this decision was made)_

## Frameworks consulted
_(which investor frameworks informed the decision)_
```

---

## `fundamentals.yaml` — optional

Structured quarterly financials. One snapshot per quarter covering P&L, cash flow, and balance-sheet summary. Populated by `fundamentals-fetcher` (see [subagents.md](subagents.md)) or manually. All monetary values in millions (reporting currency of the company) unless suffixed otherwise.

**Derived ratios are not stored.** Gross margin, operating margin, ROE, FCF yield, debt/equity, etc. are computed on read from the fields below — same principle as `assumptions.yaml`'s cross-quarter view. Storing them would duplicate state and risk drift on data revisions.

```yaml
quarters:
  - period: 2026-Q1
    as_of: 2026-04-21
    source: yfinance

    # Income statement
    revenue_mm: 61900
    gross_profit_mm: 42800
    operating_expenses_mm: 15200
    operating_income_mm: 27600
    net_income_mm: 21900
    eps_diluted: 2.94
    diluted_shares_mm: 7450

    # Cash flow
    operating_cash_flow_mm: 28400
    capex_mm: -14200
    free_cash_flow_mm: 14200

    # Balance sheet (period end)
    cash_and_equivalents_mm: 76000
    total_debt_mm: 52000
    total_equity_mm: 238000
```

| Field | Required | Notes |
|---|---|---|
| `period` | yes | Fiscal quarter label (e.g., `2026-Q1`). Unique within `quarters[]`. |
| `as_of` | yes | ISO date of the reporting period end or data-fetch date. |
| `source` | yes | Data source and tier (e.g., `yfinance`, `company 10-Q`). |
| `revenue_mm` | yes | Net revenue for the quarter, in millions. |
| `gross_profit_mm` | optional | Revenue minus cost of revenue. Omit when the company does not disclose. |
| `operating_expenses_mm` | optional | OpEx excluding cost of revenue (SG&A + R&D etc.). |
| `operating_income_mm` | yes | Operating profit. |
| `net_income_mm` | yes | Bottom-line profit attributable to common shareholders. |
| `eps_diluted` | yes | Diluted EPS in reporting currency. |
| `diluted_shares_mm` | optional | Diluted share count, in millions. Enables market-cap and BVPS derivation. |
| `operating_cash_flow_mm` | optional | Cash from operations. |
| `capex_mm` | optional | Capital expenditures, signed negative if outflow. |
| `free_cash_flow_mm` | optional | OCF + CapEx (CapEx carried with its sign). |
| `cash_and_equivalents_mm` | optional | Cash + short-term investments at period end. |
| `total_debt_mm` | optional | Short-term + long-term debt. |
| `total_equity_mm` | optional | Book value of equity at period end. |

**Omitted by design** — add only when a real question needs them: segment revenue breakdowns, working-capital detail, deferred revenue, stock-based compensation, per-share book value, comprehensive income, minority interest. These belong in separate files (`indicators.yaml` for sector-specific series) or in `kb.md` prose.

---

## `valuation.yaml` — optional

Valuation-zone snapshot per archetype's primary metric. Example for GROWTH:

```yaml
primary_metric: PEG
current_pe: 34.2
forward_growth_pct: 12.5
peg: 2.74
zone: FAIR            # CHEAP | FAIR | EXPENSIVE
zone_thresholds:
  cheap_below: 1.0
  expensive_above: 2.0
as_of: 2026-04-21
source: yfinance + analyst consensus
```

---

## `indicators.yaml` — optional

Leading indicators specific to the company's sector. User-defined keys;
examples below are illustrative. Updated quarterly or as data arrives.

```yaml
as_of: 2026-04-21
source: company filings, industry reports

# Examples by sector — use only what applies
order_book_months: 14.2          # industrials, defense
backlog_mm: 8500                 # construction, IT services
same_store_sales_yoy_pct: 4.2    # retail
net_subscriber_adds_k: 320       # telecom, streaming
capacity_utilization_pct: 87     # manufacturing, commodities
pipeline_value_mm: 12000         # pharma, biotech
monthly_active_users_mm: 285     # consumer tech
loan_growth_yoy_pct: 18          # banks, NBFCs
npa_pct: 1.2                     # banks, NBFCs
```

---

## `insiders.yaml` — optional

Insider and promoter transactions. For India: SAST disclosures, promoter
pledging. For US: Form 4 filings.

```yaml
transactions:
  - date: 2026-03-15
    person: Satya Nadella
    role: CEO
    type: sell              # buy | sell | gift | pledge | release
    shares: 10000
    price: 415.20
    value_mm: 4.15
    source: SEC Form 4
    note: Pre-planned 10b5-1

pledging:                   # India-specific; track promoter pledging %
  promoter_pledged_pct: 0.0
  as_of: 2026-03-31
  source: BSE shareholding pattern
```

---

## `shareholding.yaml` — optional

Quarterly shareholding pattern. For India: BSE/NSE filings. For US: 13F
aggregations, proxy statements.

```yaml
as_of: 2026-03-31
source: BSE shareholding pattern

# India format
promoter_pct: 72.3
fii_pct: 12.4
dii_pct: 8.1
public_pct: 7.2

# US format (use instead of above for US equities)
# insider_pct: 0.1
# institutional_pct: 74.2
# retail_pct: 25.7

# Historical trend (last 4 quarters)
history:
  - period: 2026-Q1
    promoter_pct: 72.3
    fii_pct: 12.4
  - period: 2025-Q4
    promoter_pct: 72.3
    fii_pct: 11.8
```

---

## `governance.md` — optional

Management quality, related-party transactions, auditor notes, red flags.
Word cap: 1,000. Condensed in place if breached (see § "Word caps and absorption").

```markdown
# <display_name> — Governance

## Management quality
_(founder-led vs professional; tenure; track record)_

## Related-party transactions
_(material RPTs, if any; arms-length assessment)_

## Auditor notes
_(qualifications, emphasis of matter, auditor changes)_

## Red flags
_(any concerns: pledging, frequent equity dilution, opaque subsidiaries)_

## Board composition
_(independence ratio, key committee chairs)_
```

---

## `risks.md` — optional

Position-specific risks beyond general market risk. Word cap: 1,000.
Condensed in place if breached (see § "Word caps and absorption").

```markdown
# <display_name> — Risk Register

## Customer concentration
_(top customer %, contract renewal risk)_

## Supplier/input concentration
_(single-source dependencies, commodity exposure)_

## Regulatory exposure
_(pending legislation, license renewals, environmental)_

## Litigation
_(material lawsuits, contingent liabilities)_

## Competitive threats
_(new entrants, technology disruption, pricing pressure)_

## Execution risks
_(capex projects, integrations, key-person dependency)_
```

---

## `calendar.yaml` — optional

Corporate calendar. Dates that matter **for this specific position** — earnings, AGM, dividends, splits, regulatory filings. Macro events (FOMC, CPI, budget) do NOT belong here; see [`global_calendar.yaml`](#global_calendaryaml--root-level-optional).

**Ownership.** Written by `calendar-tracker` (future subagent, see [subagents.md](subagents.md)) or manually. Also written by `earnings-grader` when a quarter is graded with transcript anchors still pending — it appends a single `Transcript grading pending — <period>` follow-up event and clears it on the transcript regrade. See [`assumptions.yaml` § Transcript-gap signalling](#assumptionsyaml--optional). Updated as announcements are made. Stale entries (past dates) can be pruned quarterly, or moved to the `past:` section for audit reference.

```yaml
as_of: 2026-04-21

upcoming:
  - event: Q3 FY26 earnings
    date: 2026-04-24
    time: 16:30 ET
    source: company IR

  - event: Annual General Meeting
    date: 2026-06-15
    source: BSE filing

  - event: Ex-dividend
    date: 2026-05-10
    dividend_per_share: 0.75
    record_date: 2026-05-12
    source: company announcement

  - event: Stock split
    date: 2026-07-01
    ratio: "10:1"
    source: board resolution

# Past events can be archived here or deleted
past:
  - event: Q2 FY26 earnings
    date: 2026-01-25
```

**Portfolio-wide derived view.** Per-instance `calendar.yaml` is the single source of truth for that position's events, but the user should not have to open each workspace's calendar to see what is coming up across the portfolio. At session load — when the question is `portfolio`, `macro`, or `risk`, or when the user asks an explicit calendar question — the orchestrator derives a read-only chronological roll-up across all per-instance `calendar.yaml` files (default window: next 30 days), merges it with [`global_calendar.yaml`](#global_calendaryaml--root-level-optional), sorts by date, and tags per-instance rows with the holding slug. The roll-up is computed on read and never persisted; no new file, no new field. See [SKILL.md](../SKILL.md) Stage 1.5 for the load contract.

---

## `performance.yaml` — optional

Historical performance tracking. Entry price, returns, thesis accuracy.
Derived from `decisions/` and market data.

```yaml
entry:
  first_buy_date: 2021-03-15
  first_buy_price: 230.50
  avg_cost: 245.80           # weighted average across all buys
  total_invested: 52847.00
  shares_held: 215
  source: decisions/ + assets.md

current:
  price: 418.07
  value: 89885.05
  as_of: 2026-04-21

returns:
  total_return_pct: 70.1     # (current_price / avg_cost - 1) * 100
  cagr_pct: 11.2             # annualized since first_buy_date
  holding_period_years: 5.1

# Thesis tracking — did key assumptions hold?
thesis_tracking:
  - assumption: "Cloud growth >20% YoY"
    status: met              # met | partially_met | missed
    note: "Azure grew 29% in FY25"

  - assumption: "Operating margin >35%"
    status: met
    note: "FY25 margin 42%"

dividends_received: 1280.00  # cumulative, if tracking
```

---

## `assumptions.yaml` — optional

Per-assumption grade history across earnings quarters. Created by `earnings-grader` on first earnings event; appended each quarter thereafter. Never word-capped, never absorbed — this is the durable cross-quarter record.

**Ownership.** Written by `earnings-grader`. Not user-edited after the initial assumption set is captured from `thesis.md`. The orchestrator reads the file; the user sees the derived cross-quarter view in Stage 6 framework output when relevant.

### Three checkpoint anchors per assumption

Each assumption carries up to three forward-looking anchors. Without an anchor, a grade is not possible — *"Azure grew 29%"* is not BEAT/MEET/MISS unless someone wrote down *"Q1 Azure ≥ 25%"* first.

| Anchor | What it tests | When it is graded | Data tier |
|---|---|---|---|
| `quarterly_checkpoint` | Near-term, consolidated-results target for the coming quarter. Tactical. | When the quarterly financial results land. | Reported financials — highest tier. |
| `transcript_checkpoint` | Segment metric or management-commentary target that lives in the earnings call, not the headline P&L. | When the earnings-call transcript is available. | Call transcript — mid tier; may lag results by days or weeks. |
| `thesis_horizon_target` | Multi-year target for the full thesis horizon. Structural. | On thesis reviews, not every quarter. | User-defined; graded on reflection, not on routine earnings. |

Each anchor is optional but at least one must be present per assumption — a grade needs something to measure against. The `quarterly_checkpoint` is the most common and should be set for almost all assumptions. `transcript_checkpoint` is set where the call adds information the P&L does not (segment growth, pricing commentary, capex pace). `thesis_horizon_target` is set when the user wants a multi-year goal recorded alongside the quarterly rhythm.

If an assumption has no `quarterly_checkpoint` and no `transcript_checkpoint`, the quarter's grade row for that key is simply absent — there is nothing to grade. The horizon target is revisited on decision reviews, not on earnings days.

### Schema

Exactly **four assumptions** per equity workspace, keyed `A1`–`A4`. Four is the working count for v1 — enough to cover a growth driver, a margin/unit-economics driver, a financial-health constraint, and a going-concern guard without bloating the thesis.

```yaml
schema_version: 1

# Exactly four assumptions. Keys A1-A4 are stable for the life of the position.
# MUST mirror the four bullets in thesis.md § "Key assumptions".
assumptions:
  A1:
    text: "Azure revenue grows >20% YoY over the thesis horizon"
    category: GROWTH                # optional free-form label
    quarterly_checkpoint: "Q1 FY27 Azure revenue growth >= 25% YoY"
    transcript_checkpoint: "Q1 FY27 call: mgmt reaffirms AI-pipeline conversion; no capacity constraints flagged"
    thesis_horizon_target: "FY28 Azure revenue >= $180B (FY26: ~$105B)"

  A2:
    text: "Operating margin holds above 35% through AI-capex cycle"
    category: MARGIN
    quarterly_checkpoint: "Q1 FY27 operating margin >= 35%"
    transcript_checkpoint: "Q1 FY27 call: capex intensity peaks this year; margin trough <= 150 bps"
    thesis_horizon_target: "FY28 operating margin >= 38%"

  A3:
    text: "Free cash flow covers buybacks + dividends + capex without net debt"
    category: FINANCIAL_HEALTH
    quarterly_checkpoint: "Q1 FY27 FCF / (buybacks + dividends + capex) >= 1.0"
    transcript_checkpoint: null
    thesis_horizon_target: "FY28 net cash position maintained"

  A4:
    text: "No antitrust or regulatory action forces material business changes"
    category: GOING_CONCERN
    quarterly_checkpoint: "No material DOJ/EU enforcement action in Q1 FY27"
    transcript_checkpoint: null
    thesis_horizon_target: "Through FY28: no forced divestiture or structural remedy"

# Per-quarter grades, appended by earnings-grader. Never overwritten, never deleted.
# Each assumption grade has up to three anchor entries (quarterly, transcript, horizon).
# Include only anchors that (a) exist on the assumption and (b) can be graded with available data.
quarters:
  - period: 2026-Q1
    graded_on: 2026-04-24
    source: earnings/2026-Q1.md (absorbed)
    grades:
      A1:
        quarterly:  { grade: BEAT, strength: STRONG,   note: "Azure +29% YoY, guide raised" }
        transcript: { grade: MEET, strength: MODERATE, note: "Mgmt confident; minor capacity commentary" }
      A2:
        quarterly:  { grade: MEET, strength: MODERATE, note: "42% op margin, in line" }
        transcript: { grade: MEET, strength: MODERATE, note: "Capex intensity elevated; no margin surprise" }
      A3:
        quarterly:  { grade: BEAT, strength: STRONG,   note: "FCF 1.6x combined return-of-capital + capex" }
      A4:
        quarterly:  { grade: MEET, strength: MODERATE, note: "No material enforcement in quarter" }
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | int | yes | Current version is `1`. |
| `assumptions` | map | yes | Exactly four keys: `A1`, `A2`, `A3`, `A4`. Must mirror the four bullets in `thesis.md § Key assumptions`. |
| `assumptions[Ax].text` | string | yes | The assumption statement. |
| `assumptions[Ax].category` | string | optional | Free-form label (e.g., `GROWTH`, `MARGIN`, `FINANCIAL_HEALTH`, `GOING_CONCERN`). No enforced vocabulary. |
| `assumptions[Ax].quarterly_checkpoint` | string or null | at least one anchor per assumption | Near-term consolidated-result target for the upcoming quarter. |
| `assumptions[Ax].transcript_checkpoint` | string or null | at least one anchor per assumption | Segment / call-commentary target available only from the earnings transcript. |
| `assumptions[Ax].thesis_horizon_target` | string or null | optional | Multi-year target. Graded on thesis review, not on every earnings event. |
| `quarters[]` | list | yes | Append-only. Each entry is one graded earnings event. |
| `quarters[].period` | string | yes | Fiscal-quarter label, e.g., `2026-Q1`. Unique across `quarters[]`. |
| `quarters[].graded_on` | ISO date | yes | When the grading pass ran. |
| `quarters[].source` | string | yes | Pointer to the source artifact (typically `earnings/<quarter>.md (absorbed)` after absorption). |
| `quarters[].grades` | map | yes | Keyed by assumption (`A1`–`A4`). Keys with nothing to grade this quarter are omitted. |
| `quarters[].grades[Ax].quarterly` | map | optional | Grade against `quarterly_checkpoint`. Present when results are in. |
| `quarters[].grades[Ax].transcript` | map | optional | Grade against `transcript_checkpoint`. Present when the transcript is available. |
| `quarters[].grades[Ax].horizon` | map | optional | Grade against `thesis_horizon_target`. Present only on thesis-review events, not routine quarters. |
| `quarters[].grades[Ax].<anchor>.grade` | enum | yes (inside the anchor) | `BEAT` \| `MEET` \| `MISS`. |
| `quarters[].grades[Ax].<anchor>.strength` | enum | yes (inside the anchor) | `STRONG` \| `MODERATE` \| `MARGINAL`. |
| `quarters[].grades[Ax].<anchor>.note` | string | yes (inside the anchor) | One-line rationale, ≤ 20 words. |

**Missing transcript is not a special state.** If the transcript is not yet available when grading runs, the `transcript` entry for affected assumptions is simply omitted for that quarter. The `quarterly` entry stands alone. When the transcript later arrives, the user (or a future re-grade pass) can append transcript grades in the same quarter block — the quarter is appended-to, not replaced.

**Transcript-gap signalling.** The user is reminded that a transcript regrade is owed through two paths, both automatic and neither a new state machine:

1. **Calendar follow-up event.** When `earnings-grader` writes a `quarters[]` entry with at least one assumption that has a `transcript_checkpoint` but no `transcript` grade, it also appends a single follow-up event to the position's [`calendar.yaml`](#calendaryaml--optional) in the same write — e.g., `event: "Transcript grading pending — 2026-Q1"`, `date: <graded_on + 7 days>`, `source: earnings-grader (auto)`, `note: "A1, A2 transcript anchors ungraded for 2026-Q1."`. When the transcript grades are later written, the same agent moves the entry to `past:` (or deletes it) in that same write. No new file, no new field.
2. **Derived-on-read surface.** When Stage 1.5 loads `assumptions.yaml`, it scans the latest quarter and flags any `Ax` where the assumption has a `transcript_checkpoint` but the quarter has no `transcript` grade. The flag is surfaced once in the load narration (e.g., *"Transcript grading pending for A1, A2 (2026-Q1)."*) so the user sees the gap on any thesis-touching question about the position, even if they didn't look at the calendar. Nothing is persisted — the flag is re-derived each load.

These two paths are deliberately redundant. The calendar nudges in time (via `global_calendar.yaml`'s 14-day window and the position's own `calendar.yaml`); the load-time derivation catches anything that slipped past the calendar.

**No rollover pass.** When a new quarter is graded, the `earnings-grader` (or the user) writes the new `quarters[]` entry and, in the same write, updates the `quarterly_checkpoint` / `transcript_checkpoint` fields on each assumption to point to the *next* quarter. There is no separate ceremony for rolling checkpoints forward.

**No factor weights, no mechanical health scores, no HOLDING/AT_RISK/BROKEN state machine.** Veda does not compute a numeric composite (see "No conviction score" below). Anchor grades are qualitative inputs to framework verdicts, not a score.

**Keyset stability.** Keys `A1`–`A4` are stable for the life of the position. If the user revises `thesis.md`, the corresponding `text` field in `assumptions.yaml` is updated under the same key — never renumber. An orphan key that appears in `quarters[].grades` but not in the top-level `assumptions` map is a data-quality flag for the next `sync`.

### Derived cross-quarter view

The file stores history; Veda computes the **cross-quarter view** on read. Nothing about the view is persisted in `assumptions.yaml` itself — persisting it would duplicate state and risk drift.

When the orchestrator loads `assumptions.yaml` (see SKILL.md Stage 1.5), it derives:

- **Latest-quarter grade counts by anchor.** E.g., *"2026-Q1: quarterly 2 BEAT / 2 MEET / 0 MISS; transcript 0 BEAT / 2 MEET / 0 MISS."* Anchors are counted separately — a quarterly BEAT and a transcript MEET on the same assumption are two data points.
- **Grade transitions vs. the prior quarter, by anchor.** For each key, note any change, citing the anchor type (e.g., `A1.quarterly: BEAT → MEET; A1.transcript: BEAT → BEAT`). Tactical moves (quarterly anchor) and commentary moves (transcript anchor) are surfaced separately.
- **Multi-quarter MISS streaks per anchor.** A streak is consecutive MISS grades on the **same anchor type** for the **same assumption key**. Quarterly-anchor misses and transcript-anchor misses are counted as independent streaks. Any streak ≥ 2 is flagged. Streaks ≥ 3 on a single anchor are promoted to the decision block's source-tier/flags section — the thesis is materially deteriorating on that dimension.
- **Horizon-target drift.** When a `horizon` grade is present in any quarter, surface the latest one alongside the quarterly/transcript view — it puts the tactical rhythm into structural context.

Consumption points (no new pipeline stages):

| Stage | Use |
|---|---|
| Stage 1.5 (holdings load) | If question touches thesis review / `hold_check` / `sell` / `trim`, load `assumptions.yaml` alongside `thesis.md`. |
| Stage 6 (framework apply) | Frameworks that weigh on thesis health (Druckenmiller *"refuses to admit the thesis is broken"*, Fisher scuttlebutt, Klarman deterioration watch) reference the cross-quarter view when it materially changes their verdict. A transcript-anchor MISS streak is evidence the call is telling a different story than the headline — often the most valuable signal in the file. |
| Stage 9a (decision write) | If the decision is `trim` / `sell` / `hold` on a held position and `assumptions.yaml` exists, the Rationale section of the decision file cites the latest quarter's grade counts (split by anchor) and any MISS streaks. |

**No conviction score.** Veda does not compute a numeric composite like StockClarity's 0–100 conviction score. Sizing stays with Thorp/Kelly; framework verdicts stay qualitative. The cross-quarter view is evidence for those framework verdicts, not a replacement.

### Narration

When the orchestrator surfaces cross-quarter evidence in Stage 6 or Stage 9a:

> *"Assumption health (holdings/msft/assumptions.yaml, last 2 quarters, quarterly anchor): A1 BEAT → BEAT; A2 MISS → MEET; A3 BEAT → BEAT; A4 MEET → MEET. Transcript anchor: A1 BEAT → MEET; A2 MEET → MEET."*

> *"Assumption health: A3.transcript MISS streak of 3 quarters — call commentary deteriorating even though headline FCF still beats. Flagged for Stage 7 devil's-advocate."*

---

## Registry row schema

The registry (`holdings_registry.csv`) is the source of truth for which
instances exist. Schema:

```csv
instance_key,instrument_class,display_name,first_acquired,last_disposed,status,reason
```

| Column | Type | Required | Notes |
|---|---|---|---|
| `instance_key` | slug | yes | Lowercase alphanumeric + underscore. Matches directory name. |
| `instrument_class` | enum | yes | V1: `equity` only. |
| `display_name` | string | yes | Human-readable name. |
| `first_acquired` | ISO date | yes | When the position was first opened. |
| `last_disposed` | ISO date | if retired | When the position was fully exited. |
| `status` | enum | yes | `active`, `retired`, or `watchlist`. |
| `reason` | string | optional | Acquisition or disposal reason (e.g., `rsu_vest`, `thesis_broken`). |

### Instance-key slugging rule

- Lowercase the raw ticker.
- Replace `.` with `_` (`NVDA.L` → `nvda_l`).
- Replace any other non-alphanumeric character with `_`.
- Collapse consecutive underscores.
- Reject if empty or starts with a digit.

---

## `global_calendar.yaml` — root-level, optional

Portfolio-wide macro calendar. One file at the workspace root (sibling of `holdings_registry.csv` and `assets.md`), NOT inside any `holdings/<instance>/` directory. Events here affect many positions or the portfolio as a whole — FOMC decisions, CPI prints, budget days, elections, OPEC meetings, major regulatory deadlines.

**Rationale.** Duplicating "FOMC May 6" across 20 per-instance `calendar.yaml` files is wrong. Macro events have their own cadence, their own sources, and are consumed by `macro`-type questions rather than single-position questions.

**Ownership.** Written by `calendar-tracker` (future subagent — scope extended from per-instance `calendar.yaml` to include this root-level file; see [subagents.md](subagents.md)) or manually. Until the subagent ships, the file is user-maintained or absent.

**Load trigger.** The orchestrator loads `global_calendar.yaml` in Stage 1.5 when the question type is `macro`, `risk`, or `portfolio`, or when any upcoming event in the file falls within 14 days. For `buy` / `sell` / `hold_check` on a single name, load only if the instrument is directly sensitive to an imminent macro event (e.g., a bank position days before an FOMC decision).

### Schema

```yaml
as_of: 2026-04-24

upcoming:
  - event: FOMC rate decision
    date: 2026-05-06
    region: US
    category: central_bank
    source: Federal Reserve calendar
    note: Consensus holds; watch QT pace language.

  - event: India CPI (April 2026)
    date: 2026-05-12
    region: IN
    category: macro_data
    source: MoSPI release calendar

  - event: OPEC+ ministerial
    date: 2026-06-01
    region: global
    category: commodity
    source: OPEC website
    note: Affects energy positions.

# Past events can be kept for audit or pruned
past:
  - event: FOMC rate decision
    date: 2026-03-18
    region: US
```

| Field | Required | Notes |
|---|---|---|
| `as_of` | yes | ISO date of last update. |
| `upcoming[]` | yes (can be empty) | Forward-looking events. |
| `upcoming[].event` | yes | Short event name. |
| `upcoming[].date` | yes | ISO date. Intraday timing belongs in `note` if relevant. |
| `upcoming[].region` | yes | One of `US`, `IN`, `EU`, `UK`, `JP`, `CN`, `global`. Extend only when a held position sits in a region not listed. |
| `upcoming[].category` | yes | One of `central_bank`, `macro_data`, `political`, `commodity`, `regulatory`, `other`. |
| `upcoming[].source` | yes | Where the date was sourced. Never leave unsourced. |
| `upcoming[].note` | optional | One-line context or thesis-impact hook. |
| `past[]` | optional | Same shape as `upcoming[]`. Kept for audit; can be pruned. |

**What does NOT belong here.** Per-instance earnings, dividend dates, AGMs, stock splits — those go in `holdings/<instance>/calendar.yaml`. A macro event tied to a single holding (e.g., a drug-approval PDUFA date) belongs in the position's own `calendar.yaml`, not here.

---

## Validation checklist — session load procedure

Run this checklist at session start and before any `sync` operation. Failed
rows are quarantined (excluded from context) but do not block other rows.

### Step 1: Registry file checks

1. **File exists?**
   - If missing: `holdings_registry.csv not found. Create it or copy from holdings_registry.template.csv.`
   - Stop registry validation; proceed to workspace validation only.

2. **UTF-8 readable without BOM?**
   - If BOM detected or encoding error: `holdings_registry.csv not readable (encoding issue). Save as UTF-8 without BOM.`
   - Stop registry validation.

3. **Header row matches schema?**
   - Expected: `instance_key,instrument_class,display_name,first_acquired,last_disposed,status,reason`
   - If mismatch: `Registry header does not match schema. Expected: <expected>. Got: <actual>.`
   - Stop registry validation.

### Step 2: Per-row validation

For each data row (skip header), check in order. On first failure, quarantine
the row and move to the next row.

| Check | Error message |
|---|---|
| Exactly 7 fields | `Line N: expected 7 fields, got M.` |
| `instance_key` matches `^[a-z0-9_]+$` | `Line N: instance_key '<value>' must be lowercase alphanumeric + underscore. Suggest: '<slugified>'.` |
| `instance_key` is unique | `Line N and M share instance_key '<key>'. Registry requires uniqueness.` |
| `instrument_class` is `equity` (V1) | `Line N: instrument_class '<value>' not supported in V1. Allowed: equity.` |
| `display_name` is non-empty | `Line N: display_name missing.` |
| `first_acquired` parses as YYYY-MM-DD | `Line N: first_acquired '<value>' not ISO date. Use YYYY-MM-DD.` |
| If non-empty, `last_disposed` parses as YYYY-MM-DD | `Line N: last_disposed '<value>' not ISO date. Use YYYY-MM-DD.` |
| `status` is `active`, `retired`, or `watchlist` | `Line N: status '<value>' invalid. Allowed: active, retired, watchlist.` |
| If `status=retired`: `last_disposed` and `reason` non-empty | `Line N: status=retired but last_disposed/reason missing.` |
| If `status=active`: `last_disposed` is empty | `Line N: status=active but last_disposed is set. Clear it or flip to retired.` |

### Step 3: Close-match warning

Triggered on `sync` when new rows are being added (not on every session load).
For each new `instance_key`, compare against all existing instance keys
(active and retired). If Levenshtein distance ≤ 2:

`New instance '<new_key>' is N edit(s) away from existing '<existing_key>'. Typo? If intentional, confirm to proceed.`

This is a warning, not an error. Proceed after user confirmation.

### Step 4: Workspace validation

For each non-quarantined registry row, check `holdings/<instance_key>/` **only if the directory exists**. A missing workspace is not an error at this step — it is counted as drift in Step 5a and scaffolded on next mention of the ticker per Step 5b. Validate the contents of workspaces that exist:

| Check | Error message |
|---|---|
| `_meta.yaml` exists | `holdings/<key>/_meta.yaml: file missing. Workspace corrupt.` |
| `_meta.yaml` parses as YAML | `holdings/<key>/_meta.yaml: parse error (<details>). Workspace quarantined.` |
| `schema_version` present and ≤ 1 | `holdings/<key>/_meta.yaml: schema_version <x> > current (1).` |
| `instrument_class` matches registry | `holdings/<key>/_meta.yaml: instrument_class mismatch. Registry says <x>, meta says <y>.` |
| `archetype` present and in enum | `holdings/<key>/_meta.yaml: archetype '<value>' invalid. Allowed: GROWTH, INCOME_VALUE, TURNAROUND, CYCLICAL.` |
| `last_touched` parses as ISO date | `holdings/<key>/_meta.yaml: last_touched '<value>' not ISO date.` |

### Step 5: Drift detection

Drift detection runs in **two modes** to avoid flooding the user with messages:

#### 5a. Session-load summary (runs once at session start)

Count mismatches across all three sources. Do NOT enumerate every drifted ticker — just summarize.

| Condition | Counted as |
|---|---|
| Ticker in `assets.md` holdings but no registry row | drift |
| Ticker in `assets.md` holdings but no workspace | drift (will scaffold on mention) |
| Workspace exists but no registry row | orphan |
| Registry row exists but no workspace | drift |

**Narration at session load** — one line only:

> *"Drift: 19 equity tickers in assets.md without workspaces (will scaffold on mention). 1 orphan workspace."*

If zero drift: no message (silence = healthy).

#### 5b. On-mention: scaffold missing workspace

When the user mentions a specific ticker in a substantive question (decision, hold_check, thesis review, valuation, risk):

| Condition | Action |
|---|---|
| Ticker in `assets.md` but no workspace | Scaffold workspace per "Creation behavior" section. Narrate: `Creating workspace at holdings/<slug>/. Archetype: <value>.` |
| Ticker in `assets.md` but no registry row | Add registry row, scaffold workspace. Narrate: `Added <ticker> to registry. Creating workspace at holdings/<slug>/. Archetype: <value>.` |
| Workspace exists but registry row missing | Quarantine workspace. Narrate: `holdings/<key>/ exists but no registry row. Workspace quarantined.` |

This keeps session load quiet and scaffolds workspaces on-demand.

### Step 6: Summary narration

At the end of session-load validation, one summary block:

```
Registry: N rows loaded, M quarantined.
Workspaces: X loaded, Y quarantined.
Drift: Z tickers without workspaces (will scaffold on mention), W orphans.
```

If all pass and no drift: `Holdings validated. No issues.`

If registry file is missing entirely: `holdings_registry.csv not found. Workspace loading skipped.`

---

## Cross-reference: three sources, one question each

| Source | Authoritative for |
|---|---|
| `holdings_registry.csv` | Does this instance exist? Lifecycle status. |
| `assets.md` | Current tactical state — shares, price, weight, FX. |
| `holdings/<instance_key>/` | Qualitative knowledge — thesis, KB, decisions. |

Drift between sources is surfaced on session load, not fixed silently.

---

## Retirement

### Retirement directory

Retired workspaces are moved to `holdings/_retired/<instance_key>/`. This preserves the decision log and historical knowledge for reference. The directory structure inside remains unchanged.

Example: `holdings/nvda/` → `holdings/_retired/nvda/`

### Retirement reason enum

The registry `reason` column uses one of these values:

| Value | Meaning |
|---|---|
| `thesis_broken` | Kill criterion triggered, structural thesis failure. The position was exited because the investment thesis was invalidated. |
| `rebalance` | Sold for portfolio reasons (concentration, correlation, capital needs). Thesis was intact at time of exit. |
| `user_exit` | User-driven sell with no specific framework trigger. |
| `spin_off` | Corporate action — position replaced by a spin-off entity. The old workspace is retired; the spin-off may get its own workspace. |
| `merge` | Corporate action — position absorbed by an acquirer. |
| `other` | Free-text reason. When selected, prompt user for the reason and store it in the `reason` column. |

### Registry row update on retirement

When retiring a position:

1. Set `status` to `retired`
2. Set `last_disposed` to today's date (ISO format: YYYY-MM-DD)
3. Set `reason` to the selected enum value (or free text for `other`)

Example row after retirement:
```
nvda,equity,NVIDIA,2024-01-15,2026-04-24,retired,thesis_broken
```

---

## Sync command contract

The `sync` command reconciles drift between the three holdings sources. Full trigger phrases and narration are in [SKILL.md](../SKILL.md) § "Commands".

### What sync detects

| Condition | Classification | Resolution |
|---|---|---|
| Ticker in `assets.md` but no registry row | drift | Add registry row |
| Ticker in `assets.md` but no workspace | drift | Scaffold workspace |
| Workspace exists but no registry row | orphan | Prompt user: retire / add / skip |
| Registry row exists but no workspace | drift | Scaffold workspace (if status=active) |
| Registry status=retired but ticker in `assets.md` holdings | mismatch | Report; user must clarify |
| Registry status=active but ticker not in `assets.md` holdings | mismatch | Report; user may want to retire or re-add |
| Markdown file exceeds word cap | word-cap breach | Condense in place, absorb and delete, or flag for user (per file type) |

### Two-turn pattern

Sync is **plan-then-confirm**:

1. **Turn 1 (plan):** Print a summary of all proposed changes. End with explicit instructions: *"To apply these changes, say 'apply' or 'yes'. To cancel, say 'cancel' or 'no'."*
2. **Turn 2 (apply):** On user confirmation (`apply`, `yes`, `confirm`), execute the plan. On cancellation or any other input, abort with no changes.

This pattern prevents accidental destructive operations.

### Bulk scaffold behavior

When `assets.md` contains multiple held tickers without workspaces, sync scaffolds all of them in one pass:

1. **High-confidence archetypes:** Scaffold immediately using the inference table (see "Archetype inference" above). Narrate each scaffold.
2. **Ambiguous archetypes:** Marked as "pending" in the plan. During apply, prompt for each one using the plain-language archetype explanation. Wait for user response before proceeding.

Ambiguous archetypes do not block the batch — high-confidence scaffolds proceed while ambiguous ones are prompted interactively.

### Orphan resolution

For each orphan workspace (directory exists, no registry row), prompt interactively during apply:

> *"holdings/xyz/ has no registry row. Options:*
> *  - retire — move to _retired/, add registry row with status=retired*
> *  - add — add registry row with status=active (you hold this)*
> *  - skip — leave as orphan for now (not recommended)*
> *Which?"*

Wait for user response.

- If **`retire`**: prompt for `first_acquired` date (when the user originally bought the position — required by registry validation; if unknown, user may enter `<today>` but this will be a known-bad value). Then prompt for retirement reason (see enum above). Add a new registry row with `status=retired`, `first_acquired=<entered>`, `last_disposed=<today>`, `reason=<selected>`. Move workspace to `_retired/`.
- If **`add`**: add registry row with `status=active`, `first_acquired=<today>` (user can correct later). Leave workspace in place.
- If **`skip`**: leave unchanged and note in summary. The orphan will resurface on next sync.

### What sync does NOT do

- **Does not touch `assets.md`.** Tactical state (positions, prices, weights) has its own refresh paths in Stage 1.5.
- **Does not proactively retire.** Sync surfaces mismatches but does not auto-retire. To retire, the user must explicitly invoke `retire <ticker>`.
- **Does not delete workspaces.** Even orphans are prompted, not deleted. Retirement moves to `_retired/`; permanent deletion is manual.
- **Does not absorb outside of apply.** Word-cap breaches are detected and shown in the plan, but absorption only runs when the user confirms apply. Absorption rules are in § "Word caps and absorption" above.
