# Edward Thorp — Size Positions to the Edge; Avoid Ruin at All Costs

> *"The Kelly criterion gives the fraction of your bankroll to bet that maximizes the long-term growth rate, subject to the constraint that you never go broke."* — Edward O. Thorp, *A Man for All Markets* (2017), ch. on the Kelly criterion; restated across his 1969 and 2006 Kelly-criterion papers.

## When this framework applies

Thorp is the first framework Veda reaches for on **`size` / `how-much` questions** — the entire `how-much` cluster leads with Thorp. Route him whenever the question is *"how much should I put in X?"*, *"am I sizing this right?"*, *"how much dry powder should I keep?"*, or *"how much of my portfolio can be at risk?"*. Thorp is also routed on `risk` questions alongside Marks — *ruin avoidance* is Thorp's core discipline before any return consideration. He pairs with Buffett and Druckenmiller on concentrated-conviction `buy` decisions to produce the actual numeric size (they supply permission to concentrate; Thorp supplies the number). Thorp is **not** the first pick for business-quality theses (Buffett, Lynch, Fisher), cycle timing (Marks, Druckenmiller), value-trap screens (Klarman), or macro-regime calls (Druckenmiller, Dalio). His framework is **position-sizing math grounded in edge × odds, with ruin-probability as the binding constraint.**

## Core principles

### 1. Kelly criterion — size positions to the edge

> *f\* = (b·p − q) / b*, where *p* = probability of winning, *q* = 1 − *p*, *b* = net odds per unit staked. J. L. Kelly Jr., "A New Interpretation of Information Rate", *Bell System Technical Journal*, 1956; applied to markets by Thorp, 1969.

Kelly answers the quantitative sizing question that every other investing framework defers to: given an edge, how much bankroll to stake on each bet. The full Kelly formula maximizes long-run logarithmic growth of the bankroll; it also produces, *by construction*, a zero probability of ruin if the inputs are exactly right. The inputs — *probability of winning* and *net odds* — must be honest estimates. This is the rub: in markets the user rarely knows *p* and *b* with certainty, and over-estimating either produces a position that is larger than Kelly-optimal and carries a non-zero ruin risk. For Veda: **every Kelly calculation runs through `python scripts/calc.py kelly --p-win <p> --odds <b>`** (Hard Rule #8), with the inputs sourced from base-rate analysis (Stage 4) and scenario probabilities (Stage 8), not from the user's gut.

### 2. Half-Kelly — the practical default for real-world sizing

Thorp's own operational discipline at Princeton/Newport and Ridgeline Partners was to run **half-Kelly or smaller**, not full Kelly (documented throughout *A Man for All Markets* and the 2006 Kelly-criterion paper with Rotando/Poundstone). The reasoning is explicit: full Kelly is growth-optimal only when probabilities are known exactly. In the real world they are estimated with error, and the growth-rate penalty for over-sizing (being above Kelly-optimal) is severe — accepting meaningful ruin risk for a marginal expected growth improvement. Half-Kelly retains roughly 75% of the long-run growth rate while reducing drawdowns roughly proportionally. For Veda, **half-Kelly is the default reported number** — `scripts/calc.py kelly` outputs both and Veda should paste the half-Kelly as the recommended size, surfacing full-Kelly for reference only.

### 3. Never bet the house — ruin avoidance is prior

Before Kelly runs at all, the user must never stake an amount that, lost, would end the game. Thorp's documented risk rule across *Beat the Dealer* (1962), *Beat the Market* (1967, with Kassouf), and *A Man for All Markets* (2017) is: **sizing rules that could produce ruin are not sizing rules; they are gambling rules.** Operational consequence for Veda:

- **Kelly fraction is applied to *at-risk capital*, not total net worth.** The user's emergency reserve, essential living expenses for a named horizon, and any capital promised to near-term obligations (school fees, a home down payment) are outside the bankroll. Kelly only sizes the portion the user can afford to lose without life-altering consequence.
- **Concentration caps are floors on what sizing can do.** If Kelly returns 0.20 (20%) and the user's `concentration.target.max_single_position_pct` is 10, the recommendation is 10%, not 20%. The profile guardrail is the binding constraint; Kelly's output is an *upper* bound within that constraint.
- **Novice caps are absolute.** Under `experience_mode: novice`, `guardrails.max_single_position_pct` (typically 8) binds regardless of Kelly's number. *"Thorp says 15%"* is not a novice recommendation — *"Kelly math suggests 15%, your guardrail caps at 8%, so 8% is the answer"* is.

### 4. Probability × odds, not narrative

> *"A mathematical edge, however small, is all that matters. Without it, you're just gambling no matter how you dress it up."* — Thorp, paraphrased throughout *A Man for All Markets* and his Wilmott Magazine columns.

A Kelly fraction built on narrative-derived probabilities is not Kelly — it is Kelly's *form* with retail *inputs*. The discipline is to anchor *p* to Stage 4's base rate (turnarounds ~25%, not 60%) and to anchor *b* to the scenario ratios produced in Stage 8 (upside/downside return ratios, computed by `scripts/calc.py ev`). Veda's operational rule: **Kelly inputs must be traceable.** If the user insists on *p* = 0.70 for a turnaround against a 25% base rate, the `probability_justification` must document the *specific* reason the reference class does not apply — and absent that, the base rate stands and Kelly is recomputed with it. Narrative-inflated probabilities systematically produce over-sized positions; this is the single most common Kelly misuse.

### 5. Correlation kills — portfolio heat is the real constraint

*Beat the Market* (1967) and *A Man for All Markets* (2017) both repeat the point: two positions that look independent but move together are one position. Kelly's formula sizes one bet at a time; a portfolio of five Kelly-sized positions all tracking the same underlying factor is running the sum of five Kelly bets on that factor, which is **over-sized**. For Veda: before approving a Kelly-sized `buy` or `add`, the portfolio check at Stage 8 must surface correlation with existing positions. Route Dalio for the correlation analysis; Thorp supplies the discipline to act on what Dalio finds. When correlation is high, *individual Kelly sizes are scaled down* in proportion — a second position correlated 0.8 with an existing one should be sized at roughly *20%* of its solo-Kelly figure, not 100%.

## Decision rules Veda applies

### On `size` / `how-much` questions

1. **Define the bankroll.** Ask the user (or read from profile): what is the pool of at-risk capital this sizing decision draws from? Not net worth — the *deployable* investing bankroll after emergency reserve and near-term obligations. Record in auxiliary fields. Every Kelly percentage that follows is a percentage of *this* pool, not of net worth.
2. **Gather p and b honestly.** Pull *p* from the Stage 8 EV block (the upside probability for the bet to work) anchored to Stage 4 base rate. Pull *b* from the upside/downside ratio (upside return divided by the absolute value of the downside return). If either feels over-stated, route Munger's bias checklist (over-optimism, narrative bias) before proceeding.
3. **Run `scripts/calc.py kelly`.** Per Hard Rule #8, do not compute in-head. Paste `kelly_full` and `kelly_half` verbatim.
4. **Apply constraints in order: ruin, guardrail, concentration, correlation.**
   - If `kelly_fraction ≤ 0` → the bet has no positive-EV Kelly stake. Verdict: **`wait` or pass.**
   - Cap at `guardrails.max_single_position_pct` if novice.
   - Cap at `concentration.target.max_single_position_pct` for standard.
   - Scale down for correlation with existing positions (route Dalio for the correlation score; apply a rough *correlation-discount* — a new position correlated 0.8 with existing exposure takes ~20% of its solo-Kelly size).
5. **Default to half-Kelly.** Report half-Kelly as the recommended size and full-Kelly as reference. A user asking *"why half?"* gets principle 2 above, cited.
6. **Portfolio heat check.** Sum the downside probabilities × downside return percentages across all positions including the proposed new one; this is the portfolio's total at-risk percentage if all downsides realize at once. If total portfolio heat exceeds what the user can absorb (route `scripts/calc.py ev` per position), the size must be trimmed further regardless of what Kelly says about this single bet.

### On `risk` questions

1. **Ruin-avoidance first.** Is any single position sized such that its downside would materially impair the user's bankroll? *"Materially impair"* means: downside scenario ending the investing program, forcing tax-inefficient selling elsewhere, or breaching a hard obligation.
2. **Concentration audit.** List positions by current portfolio weight; flag any above `concentration.target.max_single_position_pct`. The recommendation on over-concentration is *not* always trim — if the over-concentration is Fisher/Buffett-grade quality, the recommendation may be hold-at-ceiling while new capital flows elsewhere. But surface the breach.
3. **Correlation-adjusted concentration.** Route Dalio. A portfolio with no single position above 10% but five positions each 8% in highly-correlated names is *effectively* 40% concentrated in the correlated factor — Thorp's discipline is to size the *factor exposure*, not the individual names.

### On `buy` questions (sizing-secondary role)

Thorp is rarely the primary thesis framework on a `buy`. When routed alongside Buffett or Druckenmiller, Thorp's role is: given the primary framework's `buy` verdict and its implied upside/downside scenarios, produce the numeric size via `scripts/calc.py kelly`. Do not alter the thesis verdict; do alter the size recommendation if Kelly says the edge is too thin to size meaningfully (*"edge is positive but Kelly-optimal size is 2% — at your cost of attention and tax friction, the position is not worth the slot"*). That is a coherent Thorp output.

## What Thorp does NOT cover (explicit boundary)

- **Business quality, moat, category, intrinsic value.** The *p* and *b* inputs to Kelly come from elsewhere; Thorp does not estimate them. Route Buffett, Lynch, Fisher, Klarman for the thesis.
- **Cycle timing.** Kelly assumes the edge estimate is stable at the moment of sizing. If the cycle is at an extreme and mean-reversion is likely, Marks's overlay should adjust the inputs (probability of adverse outcome higher late in a cycle) before Kelly runs — not afterward.
- **Tail-risk structuring.** Kelly assumes the distribution of outcomes is known. Taleb's domain — fat tails, black swans, convex payoffs — is where Kelly inputs are *unknown* and sizing must use a different tool (barbell, explicit tail-hedging). If the bet has a credible left tail not captured in the scenario set, Kelly is the wrong tool and Taleb routes.
- **Macro regime.** Druckenmiller's 18–24-month regime thesis can be Kelly-sized, but the regime call itself is not Thorp's.
- **Value-trap detection.** Klarman's category — if the user is pulling a cheap-looking name's *p* from backward-looking metrics, Thorp's Kelly gives the right answer to the wrong question. Klarman must screen first.
- **Novice-mode interaction.** Thorp's weight in novice `framework_weights` is deliberately low (0.03) per [profile.template.md](../setup/profile.template.md), not because sizing doesn't matter for novices — it matters most — but because the novice's sizing is already capped by `guardrails.max_single_position_pct` at a level well below most Kelly recommendations. Thorp's role for novices is to *explain why the cap exists* (ruin avoidance) rather than to produce the number. Surface principle 3 in the `education_note` whenever a novice pushes against the guardrail.

## Interaction with other frameworks

- **Paired with Buffett** on concentrated-conviction `buy` decisions. Buffett's fat-pitch gate decides *whether to concentrate*; Thorp's Kelly decides *how much*. On conflict — Buffett's concentration instinct vs. Thorp's Kelly-returning-a-modest-number — the smaller of the two wins (Thorp's ruin-avoidance discipline governs).
- **Paired with Dalio** on portfolio construction. Dalio supplies the correlation matrix; Thorp supplies the sizing. Together they produce correlation-adjusted Kelly sizes, which are almost always smaller than solo-Kelly numbers.
- **Paired with Druckenmiller** on high-conviction macro bets. Druckenmiller supplies the regime thesis and the *"courage to be a pig"* permission; Thorp enforces the cap via half-Kelly and ruin-avoidance.
- **Paired with Taleb** on speculative positions. If a position is sized as a small lottery ticket (Taleb barbell), Kelly is not applied in the standard sense — the position is sized *below* any Kelly optimum deliberately, with the asymmetric payoff justifying the slot. Surface the frame explicitly in the decision block.

## Worked example — applying Thorp

**Question:** *"Buffett's framework says NVDA is a fat-pitch buy for me. How much should I put in?"*

**Thorp's process:**

1. **Define bankroll.** User's at-risk investing capital is, say, ₹50 lakh. Emergency reserve and near-term obligations are outside. Percentages below are against the ₹50L pool.
2. **Pull *p* and *b* honestly.**
   - *p*: probability the buy thesis works over the horizon. From Stage 8 EV block — say 0.55 on a bullish but not extreme probability set, anchored to a Stage 4 base rate of mega-cap compounder 3-year positive returns (historically in the 55–65% range, Tier 3–4 general knowledge — flag LOW if no better source).
   - *b*: upside-to-downside ratio. Upside scenario +60% over 3 years, downside scenario −25%. *b* = 60 / 25 = 2.4.
3. **Run the calculator.** `python scripts/calc.py kelly --p-win 0.55 --odds 2.4` → `kelly_full: 0.3625`, `kelly_half: 0.1813`. (Paste the actual tool output; do not retype the math.)
4. **Apply constraints.**
   - Ruin: at 18% of a ₹50L bankroll, the downside −25% on the position = 4.5% of the bankroll. Tolerable.
   - Concentration: user's `concentration.target.max_single_position_pct` is 15. Cap at 15%.
   - Correlation: user already owns TSMC at 12% and AVGO at 8%. All three are AI-semiconductor-beneficiary names; correlation to the AI-compute factor is high. Route Dalio. Factor exposure sums to 20% already; adding a Kelly-15% NVDA position drives factor exposure to 35%, above most prudent single-factor caps.
5. **Final sizing.** The combination of the 15% concentration cap and the ~20% AI-compute factor exposure already in the book suggests starting NVDA at 5–7%, with a plan to add up to ~10% only if TSMC or AVGO is trimmed or the factor view strengthens. This is materially smaller than the 18% half-Kelly solo number — that is the correlation discipline doing its job.

**Thorp's verdict:** Buy at **5–7% of at-risk bankroll** (≈ ₹2.5L–₹3.5L), with a documented path to ~10% conditional on reducing correlated exposure. Do not take the solo-Kelly 18% given the existing factor exposure. **Would be wrong if:** the correlation assumption is overstated (semi-conductors decouple from AI-compute demand) AND the user can document that specific decoupling, in which case the position could scale toward the half-Kelly number.

## Verdict template (for orchestrator)

```yaml
frameworks_applied:
  - name: Thorp
    rule_cited: <e.g., "Kelly criterion, 'Optimal Gambling Systems for Favorable Games', Thorp 1969; half-Kelly default, A Man for All Markets">
    verdict: <string>
    action_suggested: <size X% | wait | reduce to Y% | pass>
    would_be_wrong_if: <specific — e.g., "correlation assumption overstated and user documents decoupling">
    framework_does_not_cover: <e.g., "business quality, cycle timing, tail-risk structure">
    # --- Thorp-specific auxiliary fields ---
    bankroll_defined: <amount + currency>
    kelly_inputs:
      p_win: <0.0 - 1.0>
      p_source: <Stage 4 base rate + Tier + justification if it diverges>
      odds_b: <ratio>
      odds_source: <Stage 8 scenarios + source>
    kelly_output:
      kelly_full: <from scripts/calc.py kelly>
      kelly_half: <from scripts/calc.py kelly>
      calc_command: <exact command>
    constraints_applied:
      ruin_check: <pass | fail>
      novice_guardrail_cap: <int | n/a>
      concentration_target_cap: <int>
      correlation_discount_pct: <int — how much the solo-Kelly was scaled down>
    final_recommended_size_pct: <int — percentage of bankroll>
    portfolio_heat_after: <int — total at-risk-if-all-downsides percentage>
```

## Sources

- Edward O. Thorp. *Beat the Dealer: A Winning Strategy for the Game of Twenty-One*. Blaisdell, 1962 (rev. Vintage 1966).
- Edward O. Thorp and Sheen T. Kassouf. *Beat the Market: A Scientific Stock Market System*. Random House, 1967.
- Edward O. Thorp. "Optimal Gambling Systems for Favorable Games." *Revue de l'Institut International de Statistique*, 1969 — original Kelly-applied-to-markets paper.
- Edward O. Thorp. *A Man for All Markets: From Las Vegas to Wall Street, How I Beat the Dealer and the Market*. Random House, 2017.
- Edward O. Thorp. "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market." Rev. 2006 — the canonical summary paper. (Originally presented at the 10th International Conference on Gambling and Risk Taking, 1997.)
- J. L. Kelly Jr. "A New Interpretation of Information Rate." *Bell System Technical Journal*, 1956 — the source formula.
- William Poundstone. *Fortune's Formula: The Untold Story of the Scientific Betting System That Beat the Casinos and Wall Street*. Hill and Wang, 2005 — narrative history, useful for understanding the Kelly/Thorp/Shannon intellectual lineage.
