# Peter Lynch — Know What You Own, Categorize First

> *"Behind every stock is a company. Find out what it's doing."*

## When this framework applies

Lynch is the first framework Veda reaches for on any **single-name buy, sell, hold, or trim decision**. Before any DCF, before any macro overlay, before any position sizing — Lynch's rule is: **categorize first, analyze second.** The rules for holding a Fast Grower are opposite to the rules for holding a Cyclical. Get the category wrong and every subsequent decision is wrong.

## Core principles

### 1. The six categories

Every stock is one of these. The category determines the rules.

| Category | Growth rate | How to buy | How to hold | How to sell |
|---|---|---|---|---|
| **Slow Grower** | 2–5% | Only for dividends. P/E must be very cheap. | Collect the yield. | Sell if dividend is cut or growth goes negative. Don't hold for capital gains. |
| **Stalwart** | 10–12% | Buy when P/E is below historical average. | Hold steady. | Sell at 30–50% gain if P/E exceeds historical average — rotate into cheaper Stalwarts. |
| **Fast Grower** | 20–25%+ | Pay up — PEG < 1.5 is attractive. Size up if conviction is high. | Hold as long as growth persists. | Sell when earnings growth decelerates for 2 consecutive quarters OR when the company can't find new growth avenues. |
| **Cyclical** | Variable | **Inverted logic.** Buy at HIGH P/E (trough earnings). Buy when the industry is left for dead. | Hold through the cycle. | Sell at LOW P/E (peak earnings). Sell when everyone says "this time is different — the cycle is dead." |
| **Turnaround** | Negative → positive | Size small. The base rate is ~25% success. | Hold through the ugly middle. | Sell when the turnaround succeeds and the stock re-rates (it becomes a Stalwart, not a Turnaround). |
| **Asset Play** | N/A | Buy when market cap < (hidden asset value – liabilities). | Wait for the catalyst that surfaces the value. | Sell when the catalyst happens OR when the asset loses its value. |

### 2. The two-minute drill

Before buying any stock, the user must be able to explain in **two minutes, to a 12-year-old**, why they own it. If they can't, they shouldn't.

Veda should literally ask: *"In 2 minutes or less, why is this a good investment? What has to go right?"* If the user rambles or hedges, that's the signal.

### 3. Sell the losers, let the winners run

> *"Pulling out the flowers and watering the weeds" — the #1 investor mistake.*

Mechanical rebalancing from winners to losers destroys returns. A stock that is up 200% because the business is compounding is not "too expensive" — it is working. The original thesis is playing out. Don't trim a Fast Grower just because it's up.

**BUT**: if the category has changed (Fast Grower decelerating into Stalwart; Cyclical at peak), the rule changes with it. Category change → sell trigger.

### 4. Stick to what you understand

> *"Never invest in an idea you can't illustrate with a crayon."*

If the user can't describe the business model, the customer, the competition, and what would go wrong — they are speculating, not investing. That's fine if labeled as speculation (Taleb framework). It's not fine if labeled as a long-term position.

### 5. The ten-bagger mindset

Fast Growers are the source of life-changing returns. A 10-bagger covers 9 losing positions. Lynch's observation: **most investors sell 10-baggers at 2x** because they're anchored to purchase price and can't believe the gains are real. If you find a Fast Grower with a long runway, the goal is to hold it for the full runway, not to trim at the first double.

## Decision rules Veda applies

### On `buy` questions

1. **Demand a category.** Before any other analysis, ask/infer: what is this? If the user can't say, help them categorize using revenue growth, industry cyclicality, and balance sheet.
2. **Apply category-specific buy rule** (see table above).
3. **Run the two-minute drill.** If the user can't articulate the thesis in 2 minutes, the recommendation is `wait` until they can.
4. **PEG check for Fast Growers.** PEG = **current (TTM) P/E** divided by **forward earnings growth rate** (the next 3–5 years, annualized, expressed as a percent). Lynch is explicit in *One Up on Wall Street*: pay for the growth *ahead*, not the growth *behind*. Using trailing growth understates PEG for decelerating stocks and overstates it for accelerating ones — both failures. Interpretation: PEG < 1.0 = very attractive; 1.0–1.5 = attractive; > 2.0 = expensive, needs unusually durable growth to justify.

   **Sourcing the two inputs (Veda never estimates either).**
   - **Current P/E (TTM)**: user must paste from a screener. Good sources: Screener.in *Current PE* field (India), Yahoo Finance *Trailing P/E* (US), broker research. Avoid *Forward P/E* — that already bakes in a growth assumption and will contaminate the ratio.
   - **Forward growth rate**: the single most-abused Lynch input. Three acceptable sources, in order of preference:
     1. **Management guidance** for the next 2–3 years, if issued and credible. Cite the specific earnings call or filing.
     2. **Analyst consensus** for 3–5 year EPS CAGR. Yahoo's *Analysis* tab, Seeking Alpha, or broker consensus. Write down the number *and* the source.
     3. **Historical 3–5 year EPS CAGR as a proxy**, only when the business model has not structurally changed. Flag explicitly: *"Using trailing 5-year EPS CAGR of X% as a forward proxy because no guidance or consensus is available. This overstates PEG quality if growth is decelerating."*
   - If the user cannot produce any of the three, Lynch's verdict is **`wait`** on the buy, not a guessed PEG. Tell the user: *"I need the forward earnings growth rate. Paste the 3–5 year EPS CAGR estimate from Yahoo's Analysis tab, or the management guidance number, or I'll assume you don't have the input and my answer is wait."*

   **Do not compute PEG in-head** (Hard Rule #8); route it through `python scripts/calc.py peg --pe <current_pe> --growth <forward_growth_pct>` and paste the output verbatim into the decision block. Record both inputs and their sources in `rule_cited` so the calculation is auditable.
5. **Avoid Slow Growers unless you specifically want income.** They rarely produce good total returns.

### On `sell` / `hold_check` questions

1. **Has the category changed?** This is the master question. Fast Grower → Stalwart is a sell signal. Cyclical at peak P/E (meaning low P/E on peak earnings) is a sell signal.
2. **Is the original thesis still intact?** If yes, hold. If no, sell — don't wait for "proof."
3. **Are you pulling flowers?** If the only reason to sell is "it's up a lot," that's not a reason. Lynch's rule: **price is not a thesis.**
4. **For winners**, the default answer is hold. Veda should require the user to produce a specific reason to sell, not a specific reason to hold.
5. **For losers**, the question is different: *has the thesis broken, or has only the price dropped?* If the thesis is intact and the price is down, that's an add opportunity. If the thesis is broken, sell now.

### On `size` questions (supporting framework to Thorp)

1. **Fast Growers deserve larger sizes** given appropriate conviction. Lynch ran concentrated growth funds.
2. **Cyclicals should be sized smaller** due to timing risk.
3. **Turnarounds should be sized smallest** due to base-rate failure.

## What Lynch does NOT cover (explicit boundary)

Veda's Stage 6 requires each framework to declare where it stops. If the question falls here, do not stretch Lynch — reroute.

- **Lynch underweights macro.** In a 2008-style crisis, even great Fast Growers get sold. Don't let "hold through volatility" become "hold through a solvency crisis." Druckenmiller's macro framework overrides during regime shifts.
- **Lynch is US-equity-biased.** The category rules travel globally, but "10-bagger" stories are rarer in slow-growing economies.
- **Category detection is harder than it looks.** A Stalwart growing at 11% during a 12-year bull run may look like a Fast Grower. A Fast Grower decelerating may look like a Stalwart. Be honest about the base rate growth, not the last 2 quarters.
- **Lynch does not size.** He informs category-based sizing tilts (Fast Growers deserve more, Turnarounds less) but position sizing math is Thorp, not Lynch.
- **Lynch does not value.** PEG is a screen, not a valuation. Intrinsic-value estimates belong to Buffett / Klarman, not Lynch.
- **Lynch does not time cycles.** Cyclical entries/exits are inverted-P/E signals; the macro timing layer is Marks / Druckenmiller.
- **"Don't pull flowers" is not "never trim."** If a single position has grown to a portfolio-threatening weight (say 40%+), portfolio-level rules (Dalio, Thorp) override Lynch's "let winners run." Take some off the table for survival, not for return optimization.
- **Novice-mode interaction.** If `experience_mode: novice`, the `block_lottery_bets: true` guardrail vetoes Lynch `buy` verdicts on **Turnarounds** (base rate ~25% success) and speculative **Asset Plays**. Stage 6 must refuse these via the structural-equivalence script even if Lynch's category rule would otherwise endorse them. Fast Growers and Stalwarts remain available to novices; Turnarounds become available only after graduation.

## Worked example — applying Lynch

**Question:** *"I own NVDA, up 180% from my cost basis. Should I trim?"*

**Lynch's process:**

1. **What category is NVDA right now?** Fast Grower. Earnings growth still 25%+, new market (AI compute) still expanding, gross margins still high.
2. **Has the category changed?** No. No decel in earnings growth yet. No sign of lost pricing power.
3. **Is the original thesis intact?** Yes — AI compute demand still outstripping supply.
4. **Is the user pulling flowers?** Almost certainly yes. "Up 180%" is not a thesis change.

**Lynch's verdict:** Hold. Do not trim on price alone. **Would be wrong if:** earnings growth decelerates for 2 consecutive quarters, OR hyperscalers start insourcing compute (AMD/custom silicon taking share at scale), OR gross margins compress by >500bps.

## Verdict template (for orchestrator)

When Veda invokes Lynch, fill the `frameworks_applied[]` entry in [templates/decision-block.md](../templates/decision-block.md) using the canonical keys (`name`, `rule_cited`, `verdict`, `action_suggested`, `would_be_wrong_if`, `framework_does_not_cover`). Lynch-specific diagnostic fields (category detection, drill) ride alongside as auxiliary keys — they are useful for auditing but do not replace the canonical schema.

```yaml
frameworks_applied:
  - name: Lynch
    rule_cited: <e.g., "Fast Grower, One Up on Wall Street ch. 8 — don't pull flowers">
    verdict: <string — one-line summary of what Lynch says about THIS situation>
    action_suggested: <buy X | sell all | trim to Y% | hold | add | wait>
    would_be_wrong_if: <specific observable — e.g., "earnings growth decelerates for 2 consecutive quarters">
    framework_does_not_cover: <what Lynch is silent on here — e.g., "macro regime, position sizing math">
    # --- Lynch-specific auxiliary fields (not part of the canonical schema) ---
    category_detected: <slow_grower | stalwart | fast_grower | cyclical | turnaround | asset_play>
    category_evidence:
      - <data point>
    category_changed_recently: <bool>
    two_minute_drill_passed: <bool | not_asked>
```

## Sources

- *One Up on Wall Street* (Peter Lynch with John Rothchild, 1989) — the category system, two-minute drill, "don't pull flowers"
- *Beating the Street* (Peter Lynch with John Rothchild, 1993) — applied examples, sell discipline
- Lynch's Magellan Fund letters (1977–1990)
