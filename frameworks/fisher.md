# Philip Fisher — Buy Outstanding Growth, Hold for a Very Long Time

> *"If the job has been correctly done when a common stock is purchased, the time to sell it is — almost never."* — Philip A. Fisher, *Common Stocks and Uncommon Profits* (1958), ch. 8.

## When this framework applies

Fisher is the first framework Veda reaches for on `buy` and `hold_check` questions where the thesis is **long-run compounding quality** — companies with sustainable above-average growth driven by management excellence, R&D, and unusual organizational characteristics. Route him alongside Lynch on Fast-Grower `buy` decisions (Lynch categorizes; Fisher supplies the quality-of-growth scuttlebutt depth); alongside Buffett on high-conviction quality positions (Buffett and Fisher together are Munger's documented inspiration for the Berkshire quality-compounder pivot); and as the anchor against trimming great businesses on price alone — his *"almost never sell"* rule is the single sharpest counter to the urge to book a winner. Fisher is **not** the first pick for cycle timing (Marks, Druckenmiller), position sizing math (Thorp), turnaround / deep-value / distressed (Klarman), macro regime shifts (Druckenmiller, Dalio), or short-horizon tactical trades. His framework is for **outstanding businesses, bought after scuttlebutt-depth due diligence, held through normal market volatility, sold only on a specific list of narrowly-defined errors.**

## Core principles

### 1. The Fifteen Points — what makes a company worth owning

*Common Stocks and Uncommon Profits* (1958), ch. 3 lays out fifteen questions an investor should be able to answer *yes* to before buying. The list is the functional definition of a Fisher-grade business. Condensed:

- Does the company have products or services with enough market potential to make possible a sizeable increase in sales for several years?
- Is management determined to continue developing products or processes that further increase total sales when the growth potential of currently attractive product lines is largely exploited?
- How effective are the company's R&D efforts relative to its size?
- Does the company have an above-average sales organization?
- Does the company have a worthwhile profit margin? And is it working to improve it?
- What is the company doing to maintain or improve profit margins?
- Are labor and personnel relations outstanding?
- Are executive relations outstanding?
- Does the company have depth to its management?
- How good are the company's cost analysis and accounting controls?
- Are there other aspects of the business, peculiar to the industry, that give the investor important clues about how the company compares with competitors?
- Does the company have a short-range or long-range outlook in regard to profits?
- Will future equity financing dilute existing shareholders?
- Does management talk freely to investors about its affairs when things are going well, and clam up when troubles occur?
- Does the company have management of unquestionable integrity?

The last point is a veto — a *no* here ends the analysis regardless of the other fourteen. Most listed companies fail three to five points at any honest reading; a Fisher-grade holding clears all fifteen or a very small number of well-understood exceptions.

### 2. Scuttlebutt — primary research beyond the 10-K

> *"Go to five companies in an industry, ask each of them intelligent questions about the points of strength and weakness of the other four, and nine times out of ten a surprisingly detailed and accurate picture of all five will emerge."* — *Common Stocks and Uncommon Profits*, ch. 2.

Fisher's operational innovation was that the 10-K is the floor of due diligence, not the ceiling. Scuttlebutt means talking to customers, competitors, ex-employees, suppliers, and distributors — the constituencies who have no incentive to parrot the investor-relations narrative. For a Veda user without industry access, scuttlebutt translates into Tier 1–2 primary sources the crowd is not reading: earnings-call transcripts from direct competitors, Glassdoor culture signal at scale, supplier filings that disclose the subject as a customer, job postings that telegraph strategic direction, product reviews that aggregate customer sentiment, and regulatory filings in adjacent markets. The rule for Veda: **any `buy` that routes Fisher must cite at least one source of scuttlebutt-type evidence that goes beyond the company's own disclosures.**

### 3. Three dimensions — a stock is bought on its business, not its chart

Fisher separates investment decisions into three independent questions (ch. 4–6): *what to buy* (the fifteen points), *when to buy* (against business-driven events, not macro forecasts he explicitly declined to make), and *when to sell* (a short, strict list in ch. 6). Blurring the three — selling a great business because the chart looks extended, buying a mediocre business because the price dropped — is how the investor ends up with *"a portfolio of 20 average companies instead of 5 exceptional ones."* Veda enforces the separation: Fisher's `buy` verdict depends on the fifteen points clearing, not on the recent drawdown; his `sell` verdict depends on a named error, not on the recent run-up.

### 4. Only three valid reasons to sell

*Common Stocks and Uncommon Profits*, ch. 6 names them precisely, and they are the list Veda applies:

1. **A mistake in the original analysis.** Something material about the business was misread at purchase. This is rare when the fifteen points were cleared with discipline.
2. **The company has changed so that it no longer qualifies** against the fifteen points to the degree it did at purchase. Usually a slow deterioration — management depth thinned by departures, R&D pipeline drying, margins compressing structurally.
3. **A genuinely better opportunity elsewhere,** and only if the new opportunity is so clearly superior that paying the tax on the existing position is still net-accretive. Fisher's explicit warning (ch. 6): this reason is used to rationalize far more bad sales than it legitimately supports.

**"The stock has run up a lot" is not on the list.** Neither is *"the market looks frothy"* or *"I want to take some off the table"*. Veda will often produce `hold` verdicts that users resist; the resistance is exactly what Fisher's rule is designed to override.

### 5. Do not overdiversify

> *"Investors have been so oversold on diversification that fear of having too many eggs in one basket has caused them to put far too little into companies they thoroughly know and far too much in others about which they know nothing at all."* — *Common Stocks and Uncommon Profits*, ch. 7.

Fisher ran concentrated growth portfolios — 10 to 20 names was a working number in the 1950s–1970s, with the largest positions routinely above 15%. The practical corollary for Veda: a user who has cleared the fifteen points on a name is already doing more work than most investors ever will, and that work is wasted if the resulting position is a 2% token. Fisher-grade conviction justifies Fisher-grade sizing — but the sizing *math* is Thorp (Kelly / half-Kelly), and the hard cap is whatever the user's profile guardrails and `concentration.target.max_single_position_pct` allow.

## Decision rules Veda applies

### On `buy` questions

1. **Fifteen-point gate.** Walk the user through the fifteen questions. They do not have to answer all fifteen in the chat — but they must be able to point, for each, to an observable data point or a deliberate defer. Silence on a point is not a pass. If fewer than twelve points clearly pass and none is a hard veto on Point 15 (integrity), the verdict is **`wait`** pending more work. Record the count and the specific points failed or deferred in the auxiliary block.
2. **Scuttlebutt citation requirement.** At least one Tier 1–2 source must speak to the business *outside* its own filings — a direct competitor's call naming the subject by name, a supplier's disclosure, a major customer's segment commentary, or equivalent. If the user cannot produce one, Fisher's verdict is **`wait`** — not because the company is bad, but because the analysis is incomplete.
3. **Do not screen on valuation alone.** Fisher's explicit rule (ch. 5): a great company at a full-looking P/E is usually a better buy than a mediocre company at a cheap P/E. If the user has cleared the fifteen points and the margin-of-safety (Buffett) check produces a failing MoS on wonderful-business thresholds, the decision is a close call between `wait at price target` (Buffett discipline) and `start a position and add on weakness` (Fisher's willingness to pay for quality). Route both and surface the disagreement per Stage 7c rather than collapse it.
4. **Three dimensions stay separate.** A `buy` recommendation does not package in a cycle-timing call. If the user is asking *"should I buy AAPL now or wait for a correction?"*, Fisher answers the first (is AAPL a Fisher-grade business?) and explicitly defers the second to Marks or Druckenmiller.

### On `sell` / `hold_check` questions

1. **Default is hold, aggressively.** The *"almost never"* sell rule is Fisher's loudest. On a `hold_check` up question (winner runs), the first output is the presumption of hold, and the burden of proof is on the user to name one of the three valid sell reasons above.
2. **Run the three-reason test.** Ask explicitly: *"Is this (a) a mistake in your original analysis, (b) a deterioration of the business against the fifteen points, or (c) a clearly superior alternative that is still accretive after tax? If none, Fisher's rule is hold."* Users frequently reach for a fourth reason (*"it's up a lot"*, *"I want to lock in gains"*, *"the market looks high"*) — name it and reject it.
3. **Category / quality drift is the live sell path.** The deterioration reason (b) is how great businesses become ordinary ones. Fisher's rule is that deterioration is slow and observable: management depth thinning (tracked via Glassdoor, filings, executive movement), margins compressing in a way the company cannot explain, R&D-to-sales falling without a reason, competitive share loss showing up in peers' disclosures. If the user can cite two or more of these over 4–8 quarters, the sell case is Fisher-coherent.
4. **On losers, same rule.** Price below cost basis is not on the list. If the fifteen points still clear, Fisher's verdict on a `hold_check` down position is **hold** — and often **add**, paired with a Klarman value-trap check to confirm this is not a business that has changed against the framework while the user was not looking.

### On `size` questions (supporting framework to Thorp and Buffett)

Fisher informs the *ceiling* question, not the number:

1. **Fisher-grade businesses deserve the concentrated allocations.** When the fifteen points all clear and Buffett's fat-pitch gate passes, Fisher's writing supports 10–25%+ single-position sizes for the right user. Thorp produces the numeric size via Kelly; Buffett gates concentration via the fat-pitch; Fisher supplies the permission to *use* the allocation the math allows rather than shaving it back to a token.
2. **Do not over-trim to rebalance.** Mechanical *"sell down to 10% once a year"* discipline destroys the long-run compounding that is Fisher's entire thesis. The position-size ceiling should only fire when it breaches `concentration.target.max_single_position_pct` materially and sustained, not on a single quarter's appreciation.

## What Fisher does NOT cover (explicit boundary)

Veda's Stage 6 requires each framework to declare where it stops. If the question falls here, do not stretch Fisher — reroute.

- **Cycle and macro timing.** Fisher explicitly declined to forecast macro (ch. 5) and his worst public misses were in mistimed holds through regime shifts. Route Marks and Druckenmiller for cycle / macro / *when* questions.
- **Cyclicals.** Fisher's framework was designed for secular compounders. Commodity cyclicals, shipping, homebuilders, memory semis — their earnings power does not compound the way Fisher assumes, and the fifteen points partially break (Point 1 on sustained sales growth, Point 5 on margin direction) through no failure of the business. Route Lynch's Cyclical category.
- **Distressed, turnarounds, deep value.** Route Klarman (margin of safety as central concept) and Lynch (Turnaround category). Fisher's explicit preference (ch. 3) was to avoid the category altogether.
- **Position-sizing math.** The Kelly calculation, correlation adjustments, portfolio-heat checks are Thorp and Dalio. Fisher supplies the *ceiling spirit*, not the number.
- **Tail risk, options, leverage.** Taleb's department; refuse under novice guardrails per SKILL.md Hard Rule #2.
- **Single-point intrinsic-value estimates.** Fisher does not produce a DCF; Buffett and Klarman do. If the user asks "what is NVDA worth", route Buffett's range-or-relative-multiple rule, not Fisher.
- **Novice-mode interaction.** Fisher's framework is safe for novices on the `buy` side for **Stalwart and Fast-Grower categories only** (after Lynch has classified). It is not a license to concentrate beyond `guardrails.max_single_position_pct` — the ceiling stays. The *"almost never sell"* rule is particularly valuable for novices prone to panic-selling; surface it explicitly in the `education_note` field.

## Interaction with other frameworks

- **Paired with Buffett** on high-quality compounder buys. Buffett gates via moat + margin of safety; Fisher's fifteen points and scuttlebutt extend the quality check into organizational and R&D dimensions the 10-K under-describes. On conflict: Buffett's margin-of-safety rule governs the `buy` price discipline (do not overpay for quality beyond Buffett's quality-adjusted MoS thresholds); Fisher's *"almost never sell"* rule governs the `hold` discipline once the position is on.
- **Paired with Lynch** on Fast-Grower buys. Lynch categorizes; Fisher asks whether the growth is Fisher-grade durable (fifteen points) rather than cyclical or fad-driven. If Lynch classifies as Cyclical, Fisher steps out — his framework does not apply.
- **Paired with Munger** on `hold_check` questions. Munger's inversion (*"would I buy today?"*) and Fisher's three-reasons test are the same discipline from two directions. Consensus between them on hold is high-confidence; disagreement usually means a Fisher point has quietly deteriorated and the user has not processed it.

## Worked example — applying Fisher

**Question:** *"My TSMC position is up 120%. Should I trim to rebalance?"*

**Fisher's process:**

1. **Fifteen-point status today.** Market potential intact (AI compute + logic-node leadership). R&D-to-sales among industry highest (~8% of revenue, 10-K FY2024). Sales organization and customer depth (Apple, NVIDIA, AMD, Broadcom as disclosed customers). Margin trajectory — gross margins in the low-50s, explicitly guided and delivered. Management integrity clean over decades. Management depth — succession from Morris Chang handled. Twelve-plus points clear with current data.
2. **Three-reasons test applied.**
   - Mistake in original analysis? User bought the foundry-scale-economics and node-leadership thesis; both are more-right than at purchase. **No.**
   - Deterioration against the fifteen points? Margins stable-to-up, customer depth growing, R&D spend growing. No deterioration observable in the last 4 quarters. **No.**
   - Clearly superior alternative, tax-adjusted? Unless the user can name one and show the post-tax math is net-accretive, no.
3. **"Up 120%"** is not a valid sell reason under Fisher.

**Fisher's verdict:** Hold. Do not trim for rebalancing alone. **Would be wrong if:** gross margin compresses >400bps sustained for 2+ quarters without a named one-off explanation, OR a named top-5 customer discloses material in-house silicon replacing TSMC volumes, OR a geopolitical event makes Taiwan capacity inoperable for a sustained period (this is the tail Marks and Taleb are routed for; Fisher defers). **Size discipline:** if the position has exceeded `concentration.target.max_single_position_pct` materially and sustained, a trim back *to the ceiling* is coherent, but frame it as portfolio-construction hygiene and not as a Fisher sell.

## Verdict template (for orchestrator)

When Veda invokes Fisher, fill the `frameworks_applied[]` entry in [../templates/decision-block.md](../templates/decision-block.md) using the canonical keys. Fisher-specific diagnostic fields ride alongside as auxiliary keys.

```yaml
frameworks_applied:
  - name: Fisher
    rule_cited: <e.g., "Fifteen Points, Common Stocks and Uncommon Profits ch. 3; three valid sell reasons, ch. 6">
    verdict: <string — one-line summary>
    action_suggested: <buy X | sell all | trim to Y% | hold | add | wait>
    would_be_wrong_if: <specific observable — e.g., "gross margin compresses >400bps sustained 2+ quarters">
    framework_does_not_cover: <e.g., "cycle timing, position-sizing math, tail risk">
    # --- Fisher-specific auxiliary fields ---
    fifteen_points:
      cleared: <int out of 15>
      failed_or_deferred:
        - point: <number 1-15>
          reason: <string + source + tier>
      integrity_veto_tripped: <bool>   # Point 15 failure ends analysis
    scuttlebutt_evidence:
      - source: <e.g., "Apple Q3 2025 call, CFO on TSMC N3 ramp">
        tier: <T1 | T2 | T3>
        finding: <string>
    three_reasons_test:       # sell / hold_check only
      reason_a_mistake: <bool + note>
      reason_b_deterioration: <bool + note>
      reason_c_better_alt: <bool + note + post_tax_accretion_check>
```

## Sources

- Philip A. Fisher. *Common Stocks and Uncommon Profits and Other Writings*. Harper & Brothers, 1958 (expanded Wiley edition 1996 incl. *Conservative Investors Sleep Well* [1975] and *Developing an Investment Philosophy* [1980]).
- Philip A. Fisher. *Paths to Wealth Through Common Stocks*. Prentice-Hall, 1960.
- Kenneth L. Fisher. "My Eight Best Lessons from My Father." *Forbes*, various columns — secondary interpretive source for applying the fifteen points in a modern setting; treat as Tier 3.
- Warren Buffett's documented crediting of Fisher's influence on the Berkshire quality-compounder pivot — Berkshire Chairman's Letters and *The Snowball* (Alice Schroeder, 2008); Munger's parallel crediting of Fisher in *Poor Charlie's Almanack*.
