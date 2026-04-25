# Company / Instrument Workspaces — design in progress

**Status:** Draft. This document is under active iteration. Sections marked
**[DECIDED]** are closed; sections marked **[OPEN]** are being worked.
Nothing in this doc is authoritative for runtime behaviour until a final pass
lifts the **[DRAFT]** banner at the top.

This document supersedes the "structured holdings schema" bullet in
[ROADMAP.md](../ROADMAP.md) Tier 1 for everything above the
`thesis_assumptions[]` sub-item. When this doc lands, the roadmap will be
split accordingly.

---

## Motivation

Today [assets.md](../assets.md) is asked to be two things at once: a
**portfolio roll-up** (weights, concentration, FX, capital split — the
`dynamic:` YAML block handles this well) and a **per-position knowledge
store** (thesis, tags, eventually assumptions). These have opposite access
patterns — one object vs many, updated on every price move vs updated on
material events, whole-file reads vs one-ticker reads, session-lifetime
vs years-lifetime. Stuffing per-instrument knowledge into a table cell has
been increasingly strained.

Separately, three Tier 1 subagents in [internal/subagents.md](subagents.md)
(`company-kb-builder`, `news-researcher`, `earnings-grader`) have write
outputs described as "cached per ticker" without specifying where. Today
the destination is undefined.

The **instrument workspace** pattern addresses both: a persistent per-instrument
directory that is the single context bundle Veda loads when any question
touches that instrument, and the concrete write target for every per-ticker
subagent.

---

## Two-object model **[DECIDED — shape]** / **[OPEN — full schema]**

Workspaces model **two distinct object types**, and both need defined CRUD
operations. Conflating them was the mistake in earlier drafts of this design.

### Object 1: Instrument Class

An asset class or product family. Examples: `equity`, `etf`, `sgb`,
`mutual_fund`, `physical_gold`, `fd`, `bond`. Has shared semantics across
its instances (e.g., all SGBs have issue price, redemption date, coupon;
all equities have an archetype and can be routed to frameworks).

The Instrument Class is **not itself a workspace**. It is metadata that
determines what fields an instance workspace is expected to carry and how
the router treats it.

### Object 2: Instrument Instance

A specific tradable — a single company (MSFT), a specific ETF (GOLDBEES),
a specific SGB tranche (`sgb_2024_series_iv`), a specific FD with a
specific bank and maturity. Each instance is one workspace directory.

**CRUD operations live at the instance level.** The class level changes
only when Veda adds support for a new asset class, which is a code/schema
change, not a user-initiated operation.

### Why the distinction matters

- **Archetype applies to equity only.** The enum
  (`GROWTH | INCOME_VALUE | TURNAROUND | CYCLICAL`) is meaningless for an
  FD or a gold ETF. Making archetype a class-level concern instead of a
  universal column avoids that category error.
- **Expected files differ by class.** Equities expect `fundamentals.yaml`,
  `valuation.yaml`, `earnings/`, `disclosures.md`. SGBs don't — they expect
  `coupon_schedule.yaml` and nothing earnings-related. The class tells the
  schema validator what to check.
- **Router routes by class + archetype.** Equities route to framework
  clusters by archetype. Non-equity instruments skip framework routing —
  frameworks are for businesses, not bearer instruments.

### Full per-class schema **[OPEN]**

Deferred to a follow-up pass. Draft the schemas class by class, equity
first, then gold/silver variants, then debt. User experience from
StockClarity's archetype work will inform the shapes.

---

## Registry as source of truth **[DECIDED]**

A single file — **`holdings_registry.csv`** (working name, rename allowed
later) — is the declarative source of truth for which instrument instances
exist in the user's universe, past and present. Workspaces are synced from
the registry; the registry is not generated from the workspaces.

This mirrors the pattern used in StockClarity's
[sync_users_and_generate_company_artifacts.py](../../StockClarity/sync_users_and_generate_company_artifacts.py)
where `user_import.csv` drives reconciliation.

### Registry row schema (draft)

```csv
instance_key,instrument_class,display_name,first_acquired,last_disposed,status,reason
msft,equity,Microsoft,2021-03-15,,active,rsu_vest
nvda,equity,NVIDIA,2023-08-10,,active,
titanbio,equity,Titan Biotech,2025-11-02,,active,
goldbees,etf,Nippon India ETF Gold BeES,2024-05-01,,active,
sgb_2024_series_iv,sgb,SGB 2024-25 Series IV,2024-12-20,,active,
nflx,equity,Netflix,2022-06-01,2024-09-14,retired,thesis_broken
```

### Three sources, one question each

The potential pitfall is three overlapping stores of position state
(registry + `assets.md` + workspace dirs). Resolve by making each source
authoritative for exactly one question:

| Source | Authoritative for |
|---|---|
| `holdings_registry.csv` | Does this instance exist in the user's universe, past or present? Lifecycle status. |
| `assets.md` | Current tactical state — shares, price, weight, FX roll-up. |
| `holdings/<instance_key>/` | Qualitative knowledge — thesis, KB, decisions, earnings history. |

`sync` reconciles all three. Drift is surfaced on session load, not fixed
silently.

### CRUD operations on the registry **[PARTIALLY DECIDED]**

Core operations are now specified. See [SKILL.md](../../SKILL.md) § "Commands" for user-facing triggers and [internal/holdings-schema.md](../../internal/holdings-schema.md) § "Retirement" and § "Sync command contract" for detailed contracts.

| Operation | Intent | Side effects on workspaces | Status |
|---|---|---|---|
| `create_instance` | New instance enters the universe | Workspace dir scaffolded at `holdings/<instance_key>/` per class schema | **Decided** — implicit on first substantive mention of held ticker, or on `buy` decision at Stage 9a |
| `activate_instance` | Watchlist instance becomes held | Status flipped to `active` in registry | **Decided** — via `sync` orphan resolution ("add" option) |
| `retire_instance` | Position closed | Workspace moved to `holdings/_retired/<instance_key>/`; registry row gets `last_disposed` + `reason` | **Decided** — `retire <ticker>` command with reason enum |
| `rename_instance` | `instance_key` change (e.g., ticker change on corporate action) | Dir renamed; registry updated; historical references preserved | **Deferred** — low frequency; wait for real need |
| `merge_instance` | Corporate action (Abbott → AbbVie spin) | Old workspace retired with `reason: spin_off`; new workspace inherits thesis-relevant history by reference | **Deferred** — needs real example to design cross-reference |

**Decided:** Single `sync` command with plan-then-confirm pattern handles bulk scaffold and orphan resolution. Explicit `retire <ticker>` command handles retirement with reason enum.

---

## Closed decisions from Q1–Q7

Carried forward from earlier discussion so the doc is self-contained.

### **[DECIDED]** Q1 — Creation trigger

**Lazy with silent auto-creation on first substantive mention.** Explicit
`create workspace for <instance_key>` always honored. A ticker in holdings
with no workspace is reported as a neutral status line on session load;
workspace is auto-created on the first decision, hold_check, or research
question touching it. No eager creation for 35 placeholder directories.

### **[DECIDED]** Q2 — Sync discipline

Manual edits to `assets.md` do not auto-propagate. User says `sync` and
the agent reconciles. Two sub-rules:

- Veda's own writes are **atomic in the same turn** — a buy updates both
  the holdings row and `holdings/<instance>/decisions/` together, or
  neither.
- **Drift is surfaced on session load**, not silent. Compare registry +
  `assets.md` + workspace dirs; report mismatches.

**Implementation:** `sync` command is plan-then-confirm (two turns). Full contract in [SKILL.md](../../SKILL.md) § "Commands" and [internal/holdings-schema.md](../../internal/holdings-schema.md) § "Sync command contract".

### **[DECIDED]** Q3 — Bloat control via absorption

StockClarity-style: raw material gets absorbed into the KB on word-cap
breach; the original artifact is removed. **Decisions are never absorbed**
— they are append-only audit records, equivalent to the Tier-1.5 audit log
in the prose phase.

Soft caps (revise with usage):

| File | Cap | On breach |
|---|---|---|
| `kb.md` | 2,000 words | Condensation pass; citations preserved |
| `thesis.md` | 500 words | Flag for user revision (append proposed condensation) |
| `governance.md` | 1,000 words | Condensation pass |
| `risks.md` | 1,000 words | Condensation pass |
| `disclosures.md` | 1,500 words | Condensation pass |
| `news/<quarter>.md` | 1,500 words | Absorb claims into `kb.md` with URLs; delete file |
| `earnings/<quarter>.md` | 2,500 words | Absorb grades into `assumptions.yaml`; summarize into `kb.md`; delete file |
| `decisions/*.md` | no cap | Never absorbed |

Every absorption logged in `_absorption_log.md` at workspace root — metadata
only, not content.

**Implementation:** Absorption fires during `sync` only (plan-then-confirm). Full per-file behaviour, `_absorption_log.md` format, and narration rules in [internal/holdings-schema.md](../../internal/holdings-schema.md) § "Word caps and absorption".

### **[DECIDED]** Q4 — Per-user, gitignored

`holdings/` and `holdings_registry.csv` go in `.gitignore`. Schema docs
(this file, per-class schemas) remain in-repo. Each user has their own
workspace tree. No cross-user tracking.

### **[DECIDED]** Q5 — Prose runtime carries this; Python not a prerequisite

The workspace pattern ships entirely in the prose runtime. Tier 1.5
(Python orchestrator) refines it with write atomicity, scheduled
absorption, enforced word caps, and cross-tenant isolation — none of which
is required for the pattern to deliver value. Shipping now creates the
migration source Tier 1.5 needs.

### **[DECIDED — class model]** / **[OPEN — per-class schemas]** Q6 — Non-equity instruments

Workspaces are keyed by **instrument instance**, not by asset class. `GOLD`
is not a workspace; `GOLDBEES` is. `SILVER` is not a workspace; a specific
SGB tranche is. Asset-class-level macro knowledge ("what is gold's role in
a portfolio") belongs in a separate macro surface, not in `holdings/`.

Directory name: renamed `companies/` → `holdings/` to reflect that it
holds more than companies.

Archetype applies to `instrument_class: equity` only. Other classes have
class-specific profile blocks in `_meta.yaml` and are skipped by the
framework router.

### **[DECIDED]** Q7 — Registry CSV as source of truth

Captured above in [Registry as source of truth](#registry-as-source-of-truth-decided).

---

## Scoping for v1 **[DECIDED — equity only]**

**V1 ships `instrument_class: equity` workspaces only.** Non-equity rows in
[assets.md](../assets.md) stay in their current sections without a workspace
directory. GOLDBEES, SGBs, FDs, and physical metals continue to be handled
exactly as they are today until a later pass adds their class schemas.

Rationale: the V1 risk is **not** whether the class abstraction holds up
across classes — that can be proved later on a small, additive change. The
V1 risk is whether the source-of-truth flow (registry → sync → workspaces)
is robust against a real user editing a real CSV by hand. Two additional
classes multiply the surface for malformed input without buying confidence
in the core flow. Close the registry/sync/validation story first on a
single class, then add classes one at a time in follow-up passes.

Concrete V1 consequence: the `instrument_class` column in the registry is
present and required, but the **only** accepted value in V1 is `equity`.
Any other value is a validation error (see robustness section below).
When Scope B lands, that allowlist expands; the rest of the schema does
not change.

---

## Robustness — registry and workspace validation **[DECIDED — principles]** / **[OPEN — exact rules]**

The StockClarity lesson with
[sync_users_and_generate_company_artifacts.py](../../StockClarity/sync_users_and_generate_company_artifacts.py)
and `user_import.csv`: **the human-edited CSV is the biggest source of
silent corruption.** Misspelt tickers, trailing commas, smart-quotes
autocorrected by Excel, rows pasted with the wrong column count, a file
saved as CSV-with-BOM, an `instrument_class` of `Equity` instead of
`equity`. Every one of those has happened and will happen. The registry
must be paranoid; the sync must fail loudly; the user must know exactly
what to fix.

Two shaping principles carry through:

1. **Fail closed, never silent.** Any registry or `_meta.yaml` parse
   failure blocks the affected instance from being loaded into decision
   context, full stop. Veda announces the failure and refuses to answer
   ticker-specific questions about that instance until it is fixed.
   Downstream decisions against a broken workspace are the exact class of
   silent corruption the system is designed to prevent.
2. **Fix-forward is the user's job; Veda proposes, does not mutate.** When
   Veda detects a likely fix ("you wrote `Equity`, the allowlist is
   `equity` — change line 4?"), it proposes the patch and waits for
   explicit approval. No auto-correction of user-authored source-of-truth
   files.

### Registry validation rules (draft)

Run on every session load and before every `sync` operation:

| Check | Failure mode | User-facing message |
|---|---|---|
| File exists and is UTF-8 readable | Missing or BOM-prefixed | `holdings_registry.csv not readable (encoding: <detected>). Save as UTF-8 without BOM.` |
| Header row matches exact schema | Column missing, extra, or reordered | `Registry header does not match schema. Expected: <...>. Got: <...>.` |
| Every row has exact column count | Row-level malformation | `Line N: expected 7 fields, got M. Contents: <raw line>.` |
| `instance_key` matches `^[a-z0-9_]+$` | Uppercase, spaces, dashes | `Line N: instance_key '<value>' must be lowercase alphanumeric + underscore. Suggest: '<slugified>'.` |
| `instance_key` is unique | Duplicate row | `Line N and M share instance_key '<key>'. Registry requires uniqueness.` |
| `instrument_class` in V1 allowlist (`equity` only) | Any other class, casing error, typo | `Line N: instrument_class '<value>' not supported in V1. Allowed: equity. If '<value>' was intentional, wait for later scope.` |
| `status` in {`active`, `retired`, `watchlist`} | Typo | `Line N: status '<value>' invalid. Allowed: active, retired, watchlist.` |
| Date fields parse as YYYY-MM-DD | Excel-coerced `MM/DD/YYYY`, empty where required | `Line N: first_acquired '<value>' not ISO date. Use YYYY-MM-DD.` |
| `retired` rows have non-empty `last_disposed` and `reason` | Half-retirement | `Line N: status=retired but last_disposed/reason missing.` |
| `active` rows have empty `last_disposed` | Stale disposal date | `Line N: status=active but last_disposed is set. Clear it or flip to retired.` |
| Display-name field present and non-empty | Silent when other fields are OK | `Line N: display_name missing — needed for unambiguous reporting.` |

A failed check **does not** stop other rows from loading. Each failed row
is quarantined — reported on session load, excluded from workspace
reconciliation — and the user can address them one at a time.

### `_meta.yaml` validation rules (draft)

For every workspace directory under `holdings/`:

| Check | Failure mode | Handling |
|---|---|---|
| File exists | Directory without `_meta.yaml` | Workspace treated as corrupt; quarantined with name listed. |
| Parses as valid YAML | Tab indentation, unbalanced quotes, smart quotes | Parse error surfaced with line/column; workspace quarantined. |
| `schema_version` present and ≤ current | User edited to a future version | `holdings/<key>/_meta.yaml schema_version <x> > current <y>. Have you rolled back the repo?` |
| `instrument_class` matches the registry row for this `instance_key` | Registry says equity, meta says etf | Hard mismatch; workspace quarantined until registry and meta agree. |
| `archetype` present iff `instrument_class == equity` | Non-equity workspace with archetype, equity without | Equity: prompt for archetype. Non-equity: surplus archetype flagged as stray. |
| `archetype` in enum (`GROWTH`, `INCOME_VALUE`, `TURNAROUND`, `CYCLICAL`) | Typo or custom value | Reject with allowlist; propose closest match if Levenshtein ≤ 2. |
| `last_touched` parses as ISO date | Garbled | Reject; suggest today's date if empty. |

### Instance-key slugging rule

Because users will paste tickers in mixed case, with spaces, or with
exchange dots, define slugging once so every surface (registry input,
workspace directory, `assets.md` pointer) agrees:

- Lowercase the raw ticker.
- Replace `.` with `_` (`NVDA.L` → `nvda_l`).
- Replace any other non-alphanumeric character with `_`.
- Collapse consecutive underscores.
- Reject if the result is empty or starts with a digit.

The slug is the `instance_key`. `display_name` carries the human-facing
form. Users hand-editing the CSV should write the slug directly; if they
paste the raw ticker, the session-load validation flags it with the
proposed slug.

### Misspelt-ticker handling (the specific case in Q)

A user typing `MSTF` instead of `MSFT` in the registry is
**indistinguishable at validation time** from a deliberate addition of a
new instrument. The sync pass does not reject the row — it scaffolds
`holdings/mstf/` as a new workspace. Two guards mitigate the
corresponding damage:

1. **On new-instance creation, Veda announces it and shows the resolved
   display name** (pulled by inline `company-kb-builder` bridge). If the
   user sees `Created workspace for MSTF (display_name: "MSTF — not
   recognised as a public equity")`, the typo is obvious on the next
   turn.
2. **Close-match hints at registry validation time.** When a new
   `instance_key` is added that is Levenshtein ≤ 2 from an existing
   instance (active or retired), surface a warning: `New instance 'mstf'
   is 1 edit away from existing instance 'msft'. Typo? If intentional,
   confirm to proceed.` Non-blocking, just a speed bump.

A ticker the user *removes* from the registry entirely (e.g., they
delete the MSFT row by accident) is caught by the drift check on the
next session load: workspace present, registry row missing, asset row
still shows the position. All three sources disagree — user is prompted
to reconcile.

### Backup before every sync

`sync` writes `holdings_registry.csv.bak.<timestamp>` before modifying
any file. StockClarity's experience: one silent write with a bug in the
sync script cost a user a hand-maintained history. The backup is cheap;
recovery without it is not.

---

## User-facing transparency **[DECIDED — principle]**

An upstream rule that binds every runtime behaviour in this design:
**Veda narrates every workspace state change as it happens.** The user
must never discover a workspace was created, absorbed, quarantined, or
synced by opening a file on their own.

Rationale: workspaces are user-owned state Veda is actively managing.
Silent mutation of user state is the failure mode regulated advisors are
most feared for. Verbose narration is the low-cost way to retain trust
and to make the system auditable by reading the chat log alone.

### What gets narrated, and when

| Event | Narration (example) |
|---|---|
| Lazy workspace creation | `First substantive mention of NVDA. Creating workspace at holdings/nvda/. Archetype inferred: GROWTH (company-kb-builder inline bridge).` |
| Workspace loaded for a decision | `Loading holdings/msft/ for this decision: thesis (last touched 2026-03-14), kb (absorbed Q1 2026 news on 2026-03-31), 1 prior decision on file.` |
| Drift detected on session load | `Drift detected on session load: 1 item. AAPL appears in assets.md holdings but has no workspace or registry row. Run 'sync' to reconcile.` |
| Registry validation failure | `Registry validation: 2 rows quarantined. Line 5: instrument_class 'Equity' not in allowlist (equity). Line 11: first_acquired '03/15/2024' not ISO date. Other 24 rows loaded normally.` |
| Meta-file corruption | `holdings/nvda/_meta.yaml failed to parse (line 4: tab character in YAML). Workspace quarantined; NVDA-specific questions will be refused until the file is fixed. Other workspaces unaffected.` |
| Absorption pass | `news/2026-Q1.md for MSFT reached 1,512 words (cap 1,500). Absorbing 17 digest entries into kb.md with source URLs preserved; deleting the raw file. Logged in _absorption_log.md.` |
| Atomic write of a decision | `Writing decision to holdings/msft/decisions/2026-04-22-hold.md and updating the MSFT row in assets.md. Both or neither.` |
| Sync command | `Sync plan: 3 new workspaces to scaffold (aapl, tsmc, asml); 1 workspace to retire (nflx); 0 renames. Confirm to proceed.` |
| Close-match warning | `New registry entry 'mstf' is 1 edit away from existing 'msft'. Intended? Confirm to proceed or correct the row.` |

### Narration discipline

- **Every narration line names the file path it refers to.** The user can
  always open the file to verify.
- **Narration is terse.** One or two lines per event, not a paragraph.
  Noise loses its own signal.
- **State-changing events require confirmation in ambiguous cases** (new
  instrument creation, retirements, syncs affecting >1 workspace). Pure
  reads (loading context) are narrated but do not block.
- **Footer summary at turn end**, when any workspace was touched:
  `Workspace activity this turn: created 1 (nvda), updated 1 (msft).`
  Mirrors the same end-of-turn honesty the `as_of` / staleness rules use
  elsewhere in [internal/assets-schema.md](assets-schema.md).

### Documentation mirror

Every doc that describes these behaviours — SKILL.md Stage 1.5, the
subagent contracts in [internal/subagents.md](subagents.md), the router
in [routing/framework-router.md](../routing/framework-router.md) — must
include the narration line the user sees when that behaviour fires. The
rule: if a behaviour is not documented with its narration string, it is
not shipped.

---

## Directory layout **[DECIDED — shape]**

```
holdings/
  msft/
    _meta.yaml                     # instrument_class: equity, archetype: GROWTH
    kb.md
    thesis.md
    assumptions.yaml               # written by earnings-grader per quarter; see internal/holdings-schema.md
    fundamentals.yaml
    valuation.yaml
    disclosures.md
    news/2026-Q1.md
    earnings/2026-Q1.md
    decisions/2026-04-22-buy.md
    _absorption_log.md
  goldbees/
    _meta.yaml                     # instrument_class: etf, no archetype
    kb.md
    decisions/...
  _retired/
    nflx/
      ...
holdings_registry.csv
global_calendar.yaml               # portfolio-wide macro calendar; see internal/holdings-schema.md
```

---

## Open questions

- **[OPEN]** Full equity-class schema — required/optional files and
  `_meta.yaml` fields. Next item to close.
- **[OPEN]** Registry operation surface — single `sync` command vs
  explicit per-op commands. Lean: single `sync` with a plan-then-confirm
  pattern (see Narration table).
- **[OPEN]** Implicit vs explicit `create_instance` on first mention of
  a new ticker. Lean: implicit with narration + close-match warning.
- **[OPEN]** Instance-key collision rules (e.g., US MSFT vs a hypothetical
  India `MSFT.BO`). Propose `msft_us` / `msft_in` suffix convention,
  layered on top of the slugging rule.
- **[OPEN]** Watchlist (prospect) workspaces — do they live in
  `holdings/watchlist/<instance>/`, and what is the merge path when the
  instrument is bought? Registry status `watchlist` is already reserved.
- **[DECIDED]** `assumptions.yaml` shape. Per-assumption grade history
  across quarters, append-only, never absorbed, no numeric conviction
  score. Full schema and derived cross-quarter view in
  [internal/holdings-schema.md](../../internal/holdings-schema.md)
  § "`assumptions.yaml` — optional".
- **[OPEN]** Absorption-pass quality check — how do we confirm no signal
  was lost? Mirror whatever verification StockClarity uses.
- **[OPEN]** Corporate actions — the `merge_instance` / `rename_instance`
  operations need concrete playbooks (TCS buyback, Abbott/AbbVie spin,
  reverse splits). Likely defer until the first real event forces the
  decision.
- **[OPEN]** Exact V1 allowlist-expansion mechanism — a single const in
  schema doc, or a separate `class_registry.yaml`? Decide when Scope B
  actually starts, not now.

---

## Execution plan — phased rollout

Incremental delivery. Each phase is self-contained, testable, and builds
on the previous without breaking existing functionality.

### Phase 0: Schema foundation (no runtime changes)

**Goal:** Establish all structural artifacts without changing any runtime
behavior.

| Deliverable | Description |
|---|---|
| `internal/holdings-schema.md` | Equity-class schema: required/optional files, `_meta.yaml` field definitions. |
| `holdings_registry.template.csv` | Header row + example row. The real file is gitignored; template is committed. |
| `.gitignore` additions | `holdings/`, `holdings_registry.csv`, `holdings_registry.csv.bak.*`. |

**Exit gate:** Schema docs reviewed; no code runs, no files created in
`holdings/`.

### Phase 1: Pilot workspace (MSFT)

**Goal:** Create a single real workspace to validate the schema
end-to-end.

| Deliverable | Description |
|---|---|
| `holdings/msft/` | Pilot workspace with all required files per Phase 0 schema. |
| `holdings/msft/_meta.yaml` | `instrument_class: equity`, `archetype: GROWTH`, `schema_version: 1`, `last_touched: <date>`. |
| `holdings/msft/kb.md` | Stub with placeholder text. |
| `holdings/msft/thesis.md` | Stub with placeholder text. |
| `holdings/msft/decisions/` | Empty directory or one example decision. |
| `holdings_registry.csv` | Seeded with MSFT row. |

**Exit gate:** Workspace validates against Phase 0 schema; registry row
parses cleanly.

### Phase 2: Registry validation logic

**Goal:** Make the registry robust to hand-editing errors before any
automation touches it.

| Deliverable | Description |
|---|---|
| Validation checklist or script | Applies every rule from the Robustness section. |
| Error messages | Match the exact user-facing messages in this doc. |
| Close-match warning | Levenshtein ≤ 2 hint for new instance keys. |

**Exit gate:** Deliberately malformed rows are caught with correct
messages.

### Phase 3: Session-load integration (read path)

**Goal:** SKILL.md Stage 1.5 loads workspace context when a held ticker
is mentioned — read-only, no writes yet.

| Deliverable | Description |
|---|---|
| SKILL.md Stage 1.5 update | On ticker mention, load `holdings/<instance>/` if present. |
| Drift detection | Surface mismatches between registry, workspace dirs, `assets.md`. |
| Narration strings | Add session-load narration lines to SKILL.md. |

**Exit gate:** MSFT-specific question loads workspace and narrates it;
deliberate drift is surfaced.

### Phase 4: Lazy creation + write path

**Goal:** New tickers get workspaces on first substantive mention;
decisions are written atomically.

| Deliverable | Description |
|---|---|
| Lazy workspace creation | Scaffold `holdings/<slug>/` on first decision/hold_check/research. |
| Atomic decision writes | Write to `holdings/<instance>/decisions/` + update `assets.md` in same turn. |
| Subagents.md update | Point write targets at `holdings/<instance>/`. |
| Framework-router update | Read `archetype` from `_meta.yaml`. |

**Exit gate:** Decision on new ticker scaffolds workspace, writes
decision file, updates assets.md, fires all narration.

### Phase 5: Absorption + sync command

**Goal:** Bloat control and user-facing `sync` command.

| Deliverable | Description |
|---|---|
| Absorption pass | Condensation on word-cap breach; log to `_absorption_log.md`. |
| `sync` command | Plan-then-confirm reconciliation across registry, assets.md, workspace dirs. |
| Retirement flow | Move workspace to `holdings/_retired/`; update registry. |

**Exit gate:** Sync scaffolds missing workspaces; retires marked
instances.

### Phase 6 (deferred): Multi-class expansion

**Trigger:** Phases 0–5 stable for at least one quarter.

| Deliverable | Description |
|---|---|
| Per-class schema docs | `holdings-schema-etf.md`, `holdings-schema-sgb.md`, etc. |
| Expand allowlist | `instrument_class` validator accepts new classes. |

---

## What lands in v1

1. This doc lifted out of **[DRAFT]** — remaining **[OPEN]** items either
   closed or explicitly deferred with a named trigger.
2. Equity-class schema — required/optional files and `_meta.yaml` fields.
3. Registry schema + validation rules ready to run — same session-load
   check and quarantine behaviour described in the Robustness section.
4. Pilot workspace: `holdings/msft/` end-to-end. Real `_meta.yaml`, real
   `kb.md`, real `thesis.md` with kill criterion, one example decision.
5. `holdings_registry.csv` seeded with MSFT (and whichever other equity
   positions the user chooses to onboard first; the rest lazy-create per
   Q1).
6. Updates to dependent files:
   - [internal/subagents.md](subagents.md) — subagent write targets point
     at `holdings/<instance>/`; each entry lists the narration string the
     subagent emits.
   - [routing/framework-router.md](../routing/framework-router.md) —
     archetype → framework cluster mapping reads `_meta.yaml`.
   - SKILL.md Stage 1.5 — load `holdings/<instance>/` on ticker mention;
     drift check + registry validation on session load; narration rules.
   - [ROADMAP.md](../ROADMAP.md) Tier 1 — split the structured-holdings
     bullet; defer `thesis_assumptions[]` until `earnings-grader` is in
     flight; note V1 is equity-only with non-equity scope expansion as a
     follow-up item.
   - `.gitignore` — add `holdings/` and `holdings_registry.csv`.

What is explicitly **not** in v1: non-equity instrument classes, migrating
all 34 other equity rows (lazy per Q1), `thesis_assumptions[]` schema,
Python sync, scheduled absorption, corporate-action playbooks.
