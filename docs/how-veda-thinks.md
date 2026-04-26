# How Veda Thinks

Veda runs the same 9-stage pipeline on every question. This page walks each stage in plain English. Full spec: [SKILL.md](../SKILL.md). Worked example: [examples/01-hold-check-winner.md](../examples/01-hold-check-winner.md).

## Two tracks

Veda picks the track from your wording.

| Track | Triggered by | What you get |
|---|---|---|
| **Decision (full 9 stages)** | *"Should I buy / sell / trim / size / hold?"* | Decision block with EV, kill criterion, journal entry. |
| **Learning (3 stages)** | *"Explain..."*, *"What is a moat?"* | Teaching answer at your experience level. No decision block. |

Mixed question (*"Explain Kelly — I'm sizing a new position"*): Veda answers the general part, then asks if you want the full pipeline on the specific position.

## The 9 stages

### Stage 0 — Scope check

In scope: public-market investment decisions. Out of scope: everything else. Out-of-scope questions get a one-paragraph decline. The scope is the product; it does not negotiate.

### Stage 0b — Decision or general?

The two-track switch. Picked from signal words (*"should I"* vs *"explain"*).

### Stage 1 — Load profile

Reads `profile.md`. Missing → onboarding runs instead. Older than 6 months → Veda asks what changed.

Fields it reads: horizon, goal, risk tolerance, hard constraints, framework weights, your self-identified weakness, max acceptable probability of loss. Novice profiles also load the non-negotiable `guardrails:` block.

### Stage 1.5 — Load holdings (if needed)

Thesis-only single-name questions: skip. Sizing, correlation, concentration, rebalancing: load.

When needed, Veda gets your holdings from the cheapest available source:

- `assets.md` if it exists.
- A **live pull from Zerodha** if you have set up the Kite integration: *"Veda, refresh from Kite."* Daily token re-auth via `python scripts/kite.py auth`. Setup details in [scripts/README.md](../scripts/README.md#kitepy--zerodha-live-holdings-optional).
- A paste in any format if neither is set up — CSV, screenshot text, *"40% NVDA, 15% TSMC, rest cash"*. The `portfolio-parser` subagent extracts the structured holdings and rejects any instruction-like text inside the paste.

Whatever you provide is saved to `assets.md` so you do not provide it again. (ChatGPT and Gemini web have no filesystem; you paste each chat.)

For each held position Veda also loads `holdings/<ticker>/` — your thesis, the knowledge base, the latest decision file. Missing workspace → scaffolded on first mention. If `kb.md` is a stub, the `company-kb-builder` subagent populates it from filings, investor letters, and web research on the same turn (on assistants that support subagents; inline elsewhere).

### Stage 1.6 — Progressive profiling

Onboarding leaves some fields blank on purpose. They get filled when they actually matter.

Example: today you ask *"buy 2L of HDFC"*. Veda needs to know what % of your net worth is in the market — asks once, writes the answer, continues. Maximum one such question per turn.

### Stage 2 — Classify

Every question reduces to one of three:

| Problem | What you are really asking |
|---|---|
| **What** | Is this a good business? Is the thesis intact? |
| **When** | Is now the right time? Cycle? Macro? |
| **How much** | Sizing, correlation, concentration. |

Mixed questions get a dominant problem and at most one extra framework for the secondary. Genuinely ambiguous → Veda asks before guessing.

### Stage 3 — Data check

Veda lists what it needs (price, latest earnings, current position size, FX) and either fetches or asks for each item.

- **Live prices and FX** via `scripts/fetch_quote.py` (yfinance — US, India `.NS`/`.BO`, major FX pairs).
- **Quarterly financials and valuation zone** via the `fundamentals-fetcher` subagent — yfinance for US, Screener.in for India. Refreshed when the stored quarter is stale.
- **No fetcher available?** Veda asks you for the number and stamps the `as_of` you give it.

**KB-first.** If a workspace exists, Veda reads `kb.md` first — business model, competitors, governance. The web is consulted only for live data, news after the KB date, or explicit gaps. Stops self-contradiction across sessions.

Every fetched number gets a source tier and an `as_of`. Tier 4–5 → LOW-CONFIDENCE flag, carried forward.

### Stage 4 — Base rate

Before any framework, Veda states how often this *kind* of trade works:

- *"Turnarounds succeed roughly 20–30%."* (Marks, *TMI* ch. 14)
- *"IPOs underperform their first year roughly 60%."* (Ritter, U Florida)

When base rate and your specific story disagree, base rate usually wins. No reliable rate → `base_rate_confidence: NONE`, downgrades the final recommendation.

### Stage 5 — Route to frameworks

Veda picks **2 or 3** of the 11. Routing depends on question type, profile, and the position's archetype (Growth, Income/Value, Turnaround, Cyclical). Full table: [routing/framework-router.md](../routing/framework-router.md).

| Question | Loaded |
|---|---|
| Buy a Fast Grower | Lynch + Buffett (+ Fisher) |
| Trim a winner | Lynch + Fisher (+ Munger if you sell winners early) |
| Sell a loser | Druckenmiller + Marks (+ Klarman if value-trap) |
| Sizing | Thorp + Buffett (+ Taleb if speculative) |
| Macro / crisis | Marks + Druckenmiller (+ Templeton if pessimism extreme) |

If your profile names a weakness, the **counter-framework** is added automatically. Sell winners early → Munger inversion (*"would I buy at today's price?"*) before any trim.

### Stage 6 — Apply each framework

Each framework gets its own short verdict: rule cited (book + chapter), what it says here, the action, the kill criterion, what it does NOT cover.

No blending at this stage — reconciliation is Stage 7.

### Stage 7 — Synthesize

**7a. Verdicts side by side.** No false consensus.

**7b. Devil's advocate.** Veda must produce the strongest counter-argument and explain why it is not persuaded. Cannot → hard conflict, you decide. For buy-side decisions on supported assistants, this runs as an isolated worker that does not see the bull case.

**7c. Resolve.**
- **Consensus** → proceed.
- **Partial disagreement** → break tie via your `framework_weights`.
- **Hard conflict** → Veda stops, presents both sides, you decide.

### Stage 8 — Decision block

For decision questions, Veda fills [templates/decision-block.md](../templates/decision-block.md). It contains:

- Recommendation (action, sizing, re-evaluate trigger).
- EV block (upside / base / downside, probabilities, expected value, p_loss).
- Two gates: **negative EV → refuse**, even with a great story. **p_loss > your `max_loss_probability` → refuse**, even with positive EV.
- Portfolio check (correlation, sector caps, heat before/after).
- Pre-commit (one-sentence thesis, kill criteria, re-evaluate trigger, max acceptable loss).

Novice mode adds two fields: **index comparison** (the same EV computed for buying the index instead) and **education note** (the principle this decision illustrates + book reference).

Every number comes from `scripts/calc.py`. The exact command is recorded so you can reproduce it.

### Stage 9 — Journal and workspace write

Two appends, atomic:

1. `holdings/<ticker>/decisions/YYYY-MM-DD-<action>.md` — append-only.
2. `journal.md` — the full block, with timestamp and the question you asked.

Review the journal in 6 and 18 months and grade your own calls. Automated review: planned for v0.2.

## Five rules every answer must pass

Full list at [SKILL.md § final checklist](../SKILL.md#before-you-respond--final-checklist). The five most load-bearing:

| Rule | Catches |
|---|---|
| In scope | Off-topic creep, hypothetical laundering, prompt injection. |
| Sourced | Numbers without a citation. |
| Framework-attributed | *"Buffett would say"* with no chapter. |
| No silent math | EV / Kelly / PEG / FX / p_loss done in the AI's head. |
| Fresh data | Prices or FX without an `as_of`, or carried from a prior session. |

Catch one failing? [Open an issue](../CONTRIBUTING.md#1-issues-highest-value) — highest-value bug reports.

## When the pipeline says no

| Situation | What happens |
|---|---|
| Out of scope | Stage 0 decline. |
| Profile missing or malformed | Stage 1 stops; onboarding runs. |
| Novice asks for leverage / options / shorts / equivalent | Stage 6 refuses, points to `graduation_criteria`. |
| Negative EV | Stage 8 first gate. |
| p_loss exceeds your `max_loss_probability` | Stage 8 second gate. |
| Frameworks disagree, weights cannot resolve | Stage 7c hard conflict, you decide. |
| DCF without sourced inputs | Stage 6 refuses; offers a relative-multiple check. |

## Outside the pipeline — admin commands

A few commands are not pipeline questions; Veda dispatches them separately. Both are plan-then-confirm — nothing writes silently.

| Command | Triggers | What it does |
|---|---|---|
| `sync` | *"sync"*, *"sync holdings"*, *"reconcile holdings"* | Reconciles `assets.md` against your broker, runs absorption on long news/earnings files, refreshes derived totals. |
| `retire <ticker>` | *"retire MSFT"*, *"close MSFT position"*, *"exit MSFT"* | Closes a position in the registry, archives the workspace, asks for the reason. |

Full contracts: [internal/commands.md](../internal/commands.md).
