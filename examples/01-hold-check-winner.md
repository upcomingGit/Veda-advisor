# Example 01 — Should I trim NVDA after 180% run?

This is a worked end-to-end example showing Veda's pipeline from user question to journal entry. Uses the Priya Menon example profile from [setup/profile.example-aggressive.md](../setup/profile.example-aggressive.md) and the Lynch framework.

---

## User question

> *"Veda — my NVDA position is up 180% from entry. It's now 14% of my portfolio. Should I trim?"*

## Stage 0 — Scope gate

Public-markets investment decision on a named equity. In scope. No prompt-injection, third-party-laundering, or funding-source-trap patterns in the question. Proceed.

## Stage 0b — Decision or general?

**Decision question.** User is proposing to act ("Should I trim?"). Run the full pipeline (Stages 1–9), produce a decision block, journal it.

**Regulated-advice reminder** (one-time per session, before the first recommendation): *"Reminder: Veda applies investor frameworks to your question. It is not a registered adviser. You decide whether to act."* Not repeated again this session.

## Stage 1 — Load profile

Reading `profile.md` → Priya Menon, 32, aggressive growth, focused concentration (target 12 positions, max 15%), quality-growth lean, 23-year horizon, **self-identified weakness: "I sell winners too early"**. Schema-validates. `disclosure_acknowledged: true`. `profile_last_updated: 2026-04-15` (4 days old, not stale). `max_loss_probability: 60` (carried forward to Stage 8 second gate).

## Stage 1.5 — Portfolio context

Scope is `single-name` on NVDA, so full portfolio parsing is not required. User already volunteered the load-bearing portfolio fact in the question itself ("14% of my portfolio"); that is sufficient for the single-name hold_check. Cross-correlation with other AI-compute names (TSMC, AVGO, etc.) is *not* asked here — flagged as `correlation_with_existing: TBD` in Stage 8 portfolio_check. If total AI-compute exposure exceeds 30%, the user should re-run this as a `portfolio`-scoped question; that instruction is embedded in `trigger_for_reevaluation`.

## Stage 1.6 — Progressive profiling check

Scanning Priya's profile against the onboarding Step 4 trigger table. All progressive-profiling fields are already populated: `capital.pct_net_worth_in_market: 65` and `concentration.target.style: focused` / `concentration.target.position_count: 12` in `profile.md`; today's `dynamic.concentration_snapshot.style: focused` / `position_count: 11` in `assets.md`. Plus `instruments.long_only_cash: true` with all other instruments `false`, `style_lean.primary: quality`, `experience.level: advanced`, `self_identified_weakness` set, `data_access` populated. `incomplete: false` on the profile confirms. No triggers fire; proceed to Stage 2 without an inline capture question.

## Stage 2 — Classify

```
problem:  when (dominant), how_much (secondary)
type:     hold_check
urgency:  research
scope:    single-name
```

**Dominance rule applied.** The question tags `when` (is it time to trim?) and `how_much` (is 14% too much?). Per SKILL.md Stage 2c, dominant is `when` — the trim/hold decision turns on whether the thesis or category has changed; sizing follows. Route primarily on `when`; load at most one framework for the secondary `how_much` concern (deferred to portfolio_check).

High confidence; no confirmation needed. Stated back: *"Hold-check on an up-180% position, 14% of portfolio. Not a crisis, research-timeframe."*

## Stage 3 — Data-completeness gate

What I have from the user: cost basis 2.8x ago, current position ≈14% of portfolio.

What I need: current price, trailing EPS, forward EPS estimate, revenue growth trend, any recent competitive news.

→ Either fetch via Yahoo Finance (if tool available) or ask user. For this example, assume fetched:

- Price: $875 (Yahoo Finance, 2026-04-19)
- Trailing P/E: 46.2
- Forward P/E: 32.1
- Revenue growth TTM: +78% YoY
- EPS growth TTM: +92% YoY
- Gross margin: 75.4% (up from 73.1% YoY)
- Forward EPS CAGR (proxy): no credible 3–5 year management guidance or analyst consensus number to hand; using trailing 5-year EPS CAGR of ~65% as a **forward proxy, explicitly flagged**. This overstates PEG quality if growth decelerates.
- PEG (Lynch rule — TTM P/E / forward growth): `python scripts/calc.py peg --pe 46.2 --growth 65` → **0.7108**. Inside the "attractive" band (1.0–1.5) with room to spare; still attractive even if forward growth halves to 32%.

## Stage 4 — Base rate

Base rate for "stock up 180% that continues up another 100%+": **roughly 25–40%** in documented secular-trend runs (early Microsoft, early Amazon, early NVDA-style). Base rate for "stock up 180% that subsequently drops >30% in next 18 months": **roughly 30–50%** (widely-documented momentum-reversal frequency; wide range reflects uncertainty about whether the stock is in a secular trend or a cyclical peak). Base rate favors holding winners in clear secular trends; favors trimming winners in commodity/cyclical industries. Compute AI demand is currently classified secular, not cyclical — but that classification is contested.

**`base_rate_confidence: LOW`** — these are general-knowledge ranges, not researched for this specific situation. The `base-rate-researcher` subagent (Tier 1–3 only) returned `not_found` for this niche reference class, so the orchestrator is making the Tier 4 hedged-range call inline per SKILL.md Stage 4. Carrying the flag forward into Stages 7 and 8; ranges are deliberately wide per the Stage 4 discipline rule (no point estimates for Tier 4–5).

## Stage 5 — Route frameworks

Primary (hold_check, up): **Lynch + Fisher**.
Profile adjustment (self-weakness = "sells winners too early"): add **Munger** (inversion — "would I buy today?"), elevate Fisher.

Final: **Lynch, Fisher, Munger** (3 frameworks). Do not load Marks, Klarman, Druckenmiller — not relevant.

## Stage 6 — Apply each framework

### Lynch

- **Category detected**: Fast Grower. Evidence: +78% revenue, +92% EPS, expanding margins.
- **Category changed?** No. Still Fast Grower. No deceleration evidence.
- **Original thesis intact?** Yes — AI compute demand still outstripping supply; no hyperscaler insourcing at scale yet.
- **Pulling flowers?** User is trimming on price alone. That's the flaw.
- **Verdict**: **Hold.** Lynch's rule on Fast Growers: hold until growth decelerates for 2 consecutive quarters OR thesis breaks.
- **Would be wrong if**: EPS growth drops below 20% for 2 Qs, OR a major hyperscaler announces in-house replacement at scale, OR gross margin compresses >500bps.

### Fisher

- NVDA passes 5 of the 6 Fisher quality checks: product runway (AI compute multi-decade), management (Huang track record), R&D effectiveness (CUDA ecosystem moat), margins (75%+), uniqueness (CUDA lock-in).
- **"The right time to sell a great company is almost never."** Fisher held Motorola 40 years. Trimming a compounder at 180% when the moat is intact is the classic retail error Fisher wrote against.
- **Verdict**: **Hold all.** Do not trim a quality compounder without evidence of moat erosion.
- **Would be wrong if**: CUDA moat breaks (major customer migrates to AMD/custom silicon successfully), OR Huang leaves, OR R&D intensity drops.

### Munger (inversion)

- Question: *"If I didn't own NVDA today, would I buy it at $875?"*
- At TTM P/E 46.2 with forward growth proxy ~65% — PEG ~0.71. Inside Lynch's "attractive" band (1.0–1.5) with room to spare — still attractive even if forward growth halves.
- If the user would buy at current price with current data, then trimming is incoherent (selling what you'd buy).
- **Verdict**: **Hold.** If user says they wouldn't buy today, the next question is "why not?" — that answer is the real sell thesis. If they can't articulate it, the urge to trim is psychology, not analysis.

## Stage 7 — Synthesis

### 7a. Verdicts stated separately

Lynch: hold. Fisher: hold. Munger: hold (via inversion).

### 7b. Devil's-advocate pass

> *Best counter-argument: NVDA at forward P/E 32 already prices in ~20% sustained earnings growth for years. If AI capex budgets compress even moderately (e.g., hyperscalers discover training-efficiency gains and slow GPU orders), the multiple compresses to 20x and the stock loses 35%+ even without a recession. Priya's overall AI-compute exposure through related names may exceed what the 14% single-position line shows.*
>
> *Why I'm not persuaded: the counter is a thesis on AI capex, not on NVDA. No evidence of budget compression yet — hyperscaler Q1 2026 capex guides were all up. CUDA switching costs are a specific moat against the 'efficiency gains move share' scenario. The portfolio-level concentration concern is real but separable — flagged in portfolio_check as TBD; will revisit as a `portfolio`-scoped question if total AI-compute exposure >30%.*

### 7c. Resolve

**Consensus.** All three frameworks say hold; devil's-advocate survives. Base-rate confidence is LOW — note this in the synthesis, but three-framework consensus on an intact thesis survives that discount.

## Stage 8 — Decision block

> **Arithmetic.** Every numeric field in the block below is produced by `scripts/calc.py` per Hard Rule #8. The exact invocation is recorded inline (`calc_command`) and the probabilities are validated by `calc.py` (they sum to 1.00 within tolerance). Do not retype the output.

```yaml
date: 2026-04-19
user_question: |
  My NVDA position is up 180% from entry. It's now 14% of my portfolio. Should I trim?

classification:
  problem_dominant: when
  problem_secondary: how_much
  type: hold_check
  urgency: research
  scope: single-name

context:
  ticker: NVDA
  currency: USD
  current_price: "$875 (Yahoo Finance T2, 2026-04-19)"
  current_position: "14% of portfolio, up 180% from entry"
  key_metrics:
    - "Trailing P/E: 46.2 (Yahoo Finance T2)"
    - "Forward P/E: 32.1 (Yahoo Finance T2)"
    - "Revenue growth TTM: +78% YoY (Yahoo Finance T2)"
    - "EPS growth TTM: +92% YoY (Yahoo Finance T2)"
    - "Gross margin: 75.4% (up 230bps YoY) (10-K / T1)"
    - "PEG (Lynch rule — TTM P/E 46.2 / forward-growth proxy 65%): 0.7108 via `calc.py peg`"

base_rate:
  stated: "Stocks up ~180% in a secular-trend run continue up another 100%+ in roughly 25–40% of documented cases (general knowledge, not researched); stocks up 180% drop >30% within 18 months in roughly 30–50% of cases (widely-documented momentum-reversal frequency; wide range because secular-vs-cyclical classification is contested). Reference class is AI/compute Fast Growers in early-to-mid secular trend."
  confidence: LOW

frameworks_applied:
  - name: Lynch
    rule_cited: "Fast Grower sell rule, One Up on Wall Street ch. 8 — hold until growth decelerates for 2 consecutive quarters"
    verdict: "Fast Grower, category unchanged, thesis intact. Price alone is not a sell signal."
    action_suggested: hold
    would_be_wrong_if: "EPS growth <20% for 2 consecutive quarters, OR hyperscaler insourcing at scale, OR GM compression >500bps"
    framework_does_not_cover: "Macro regime shifts (reroute to Druckenmiller if one is suspected); intrinsic valuation (Buffett/Klarman); position sizing math (Thorp)"
    # --- Lynch-specific auxiliary fields (not part of the canonical schema) ---
    category_detected: fast_grower
    category_evidence:
      - "Revenue growth TTM +78% YoY"
      - "EPS growth TTM +92% YoY"
      - "GM expanding (75.4%, +230bps YoY)"
      - "Secular trend (AI compute) with multi-year runway"
    category_changed_recently: false
    two_minute_drill_passed: true
    peg_inputs:
      ttm_pe: 46.2
      ttm_pe_source: "Yahoo Finance Trailing P/E, 2026-04-19"
      forward_growth_pct: 65
      forward_growth_source: "trailing 5-year EPS CAGR used as forward proxy — no management guidance or analyst consensus available; flagged per Lynch sourcing protocol"
      peg_value: 0.7108

  - name: Fisher
    rule_cited: "'The right time to sell a great company is almost never' — Common Stocks and Uncommon Profits, ch. 7"
    verdict: "Great company, moat intact (CUDA ecosystem). Trimming a compounder at 180% without moat-erosion evidence is the classic retail error Fisher wrote against."
    action_suggested: hold
    would_be_wrong_if: "CUDA moat erosion evidenced by major customer migration, OR key management departure, OR R&D intensity drop"
    framework_does_not_cover: "Portfolio-level concentration limits (Dalio/Thorp); short-horizon trading; cyclical inversion"

  - name: Munger
    rule_cited: "Inversion — Poor Charlie's Almanack, 'Psychology of Human Misjudgment'"
    verdict: "At PEG ~0.71 (TTM P/E 46.2 / forward growth proxy 65%) user would buy today. Trimming what you'd buy is incoherent."
    action_suggested: hold
    would_be_wrong_if: "User can articulate a specific reason they wouldn't buy at current price — that reason is the real sell thesis"
    framework_does_not_cover: "Specific sizing; specific valuation; timing decisions"

synthesis: consensus
synthesis_note: "All three frameworks converge on hold. Position at 14% is within profile max (15%). Base-rate confidence is LOW — treat with appropriate humility, but three-framework consensus on a clearly intact thesis survives that discount."

devils_advocate:
  best_counter_argument: "NVDA at forward P/E 32 already prices in ~20% sustained earnings growth for years. If AI capex budgets compress even moderately (e.g., hyperscalers discover training efficiency gains and slow GPU orders), the multiple compresses to 20x and the stock loses 35%+ in a non-recession scenario. Priya also has AI-adjacent exposure elsewhere — concentration is larger than the 14% line suggests. Priya's profile flags 'sells winners too early (trimmed NVDA at 2x in 2023, missed the 5x)' — and the three frameworks unanimously say hold. If she trims anyway, she should write down one specific piece of evidence that has changed about the business (not the price); if she can't, the trim is the bias, not the analysis."
  why_not_persuaded: "The capex counter is a thesis on AI spending, not on NVDA. No evidence yet of budget compression — hyperscaler Q1 2026 capex guides were all up. CUDA switching costs are a specific moat against the 'efficiency gains move share' scenario. Portfolio-level concentration check flagged as TBD in portfolio_check — if total AI-compute exposure exceeds 30%, revisit separately. The weakness callout reinforces rather than overturns the hold: the known bias points in the direction of the mistake the user is considering."

recommendation:
  action: hold
  size: "No action. Maintain full 14% position."
  trigger_for_reevaluation:
    - "Next NVDA earnings (date TBD) — watch EPS growth and GM"
    - "Any AMD/custom-silicon hyperscaler insourcing news"
    - "Position reaches 18% of portfolio (3pp above target cap) — then revisit, but trim only if Lynch category changed, not on price"

expected_value:
  upside:
    scenario: "Secular AI compute trend continues, CUDA moat holds, +60% in 12 months"
    return_pct: "+60%"
    probability: 0.35
  base:
    scenario: "Growth decelerates but remains strong, stock +15% in 12 months"
    return_pct: "+15%"
    probability: 0.40
  downside:
    scenario: "Hyperscaler insourcing accelerates or cyclical demand correction, -35%"
    return_pct: "-35%"
    probability: 0.25
  probability_justification: |
    Base rate for continued upside in AI/compute Fast Growers at similar stages is roughly 25–40% (LOW confidence, general knowledge) — upside probability 0.35 sits inside that band. Base rate for a >30% drawdown within 18 months for a stock up ~180% is roughly 30–50%; downside probability 0.25 is below the naive base rate, justified by (a) CUDA moat reducing fundamental downside risk, (b) no insourcing evidence yet, (c) management continuity, (d) attractive PEG leaving room for multiple expansion. If moat evidence weakens, downside probability should widen back toward the 40% base rate and the recommendation flips.
  # Numbers below produced by scripts/calc.py per SKILL.md Hard Rule #8. Do not retype.
  ev_contribution: +18.2500      # percent
  p_loss: 0.2500
  p_loss_pct: 25.00
  calc_command: "python scripts/calc.py ev --probs 0.35 0.40 0.25 --returns 60 15 -35"
  p_loss_check: pass   # 25.00 ≤ profile.max_loss_probability (60) — pass
  verdict: positive

portfolio_check:
  correlation_with_existing: "Check: does user hold TSMC, AVGO, or other AI-compute names? If total AI-compute exposure >30%, the bet is effectively concentrated even if no single position breaches 15%."
  sector_cap_impact: "Within profile limits."
  portfolio_heat_before: "<TBD — needs current portfolio snapshot>"
  portfolio_heat_after: "Unchanged — hold action."
  cash_position_after: "Unchanged."

pre_commit:
  thesis: |
    NVDA remains a Fast Grower in a secular AI compute trend. Category unchanged, moat intact, PEG attractive. Trimming on price alone is the exact error Priya identified in onboarding ('sells winners too early'). Hold until category changes.
  kill_criteria:
    - "EPS growth <20% for 2 consecutive quarters"
    - "Major hyperscaler announces in-house silicon replacement at scale"
    - "Gross margin compression >500bps"
    - "Huang departure"
  reevaluate_trigger: "Next earnings release"
  max_acceptable_loss_on_position: "40% drawdown from current price triggers review, not automatic exit — check if thesis is broken or only price has moved"
```

## Stage 9 — Journal

Appended to `journal.md` with timestamp `2026-04-19T10:23:00`.

---

## Meta-commentary

This example shows Veda working as intended:

1. Profile-aware — the devil's-advocate block names Priya's specific weakness (sells winners too early) as part of the counter-argument.
2. Framework-routed — only 3 frameworks loaded, not all 11.
3. Forced decision artifact — EV block, kill criteria, re-evaluate trigger all written down.
4. Non-hedging — clear "hold" recommendation with a specific number of reasons it could be wrong.
5. Journal-ready — the block is pasteable and reviewable in 6 months.

Compare with the same question asked to a generic "AI financial advisor": *"Trimming is a personal decision based on your risk tolerance and financial goals. Consider consulting a financial advisor."* That answer is worthless because it doesn't know Priya, doesn't cite a framework, and doesn't produce anything she can journal.
