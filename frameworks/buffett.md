# Warren Buffett — Wonderful Businesses at Fair Prices, Held for a Long Time

> *"It's far better to buy a wonderful company at a fair price than a fair company at a wonderful price."* — Berkshire Hathaway Chairman's Letter, 1989.

## When this framework applies

Buffett is the first framework Veda reaches for on any **single-name `buy` decision**, on **`hold_check` / `sell` questions where the thesis rests on business quality**, and on **`size` questions for high-conviction positions** (concentrated-conviction allowance). He is also loaded on `risk` and `crisis` questions — "rule #1: don't lose money" is the anchor against permanent impairment, and "be greedy when others are fearful" is the playbook for forced-selling markets. Buffett is **not** the first pick for short-horizon timing (route Druckenmiller), cycle inversion on commodity Cyclicals (route Lynch's inverted-P/E rule), or tail-risk / leverage / options questions (route Taleb or refuse under novice guardrails). His framework is for *businesses*, held for a long time, bought with a margin of safety, sized to conviction.

## Core principles

### 1. Circle of competence

Only invest in businesses you can understand. Size the circle honestly — it does not have to be large, it has to be *known*. "What counts for most people in investing is not how much they know, but rather how realistically they define what they don't know." (Berkshire 1992 Letter.) The penalty for drifting outside the circle is not a poor return, it is a *permanent* loss from misreading a business you had no business analyzing. Berkshire's public track record illustrates the discipline both ways: Buffett declined to invest in tech for most of his career, then bought Apple only after its ecosystem lock-in had become observable in customer behaviour; early-stage biotech and unprofitable tech never entered the circle at all.

### 2. Economic moat — durable competitive advantage

The only businesses worth owning for a long time are ones with a **durable** structural advantage that lets them earn returns on capital above the cost of capital, through a full cycle, without heroic management. Buffett names the usual sources: low-cost production (GEICO), brand / intangible pricing power (See's Candies, Coke), high switching costs (Moody's), network effects, and regulated franchise. The 1999 *Fortune* essay ("Mr. Buffett on the Stock Market", Nov 22, 1999) is the canonical statement: *"The key to investing is … determining the competitive advantage of any given company and, above all, the durability of that advantage."* A moat that is narrowing is a sell signal, regardless of price.

### 3. Margin of safety

Borrowed whole from Graham's *The Intelligent Investor* (ch. 20 — "Margin of Safety as the Central Concept of Investment"). Pay meaningfully less than your conservative estimate of intrinsic value, so that ordinary error, bad luck, and bad macro still produce an acceptable outcome. In Buffett's own application, the discount demanded **scales inversely with business quality**: a wonderful business may justify a 10–20% margin of safety because its future cash flows compound away the entry price; a mediocre business demands 30–50% because the intrinsic-value estimate itself is fragile. The margin of safety is not a screen — it is what keeps rule #1 (don't lose money) enforceable across decades.

### 4. Mr. Market — price is not value

Graham's parable, restated by Buffett in the 1987 and 1997 Letters: the market is a moody business partner who shows up every day with a different quote and neither his enthusiasm nor his despair contains information about the underlying business. His purpose is to offer prices; yours is to accept them when they are attractive and ignore them when they are not. Volatility is the investor's friend — it is the mechanism that produces the mispricings the framework exploits. Treating paper drawdown as information about the business is category error. Treating a euphoric bid as permission to sell a wonderful business is also category error, unless the bid is absurd relative to a documented intrinsic-value range.

### 5. Concentrated conviction — the fat pitch

When circle-of-competence, moat, and margin-of-safety all line up, **size up**. "Diversification is protection against ignorance. It makes little sense for those who know what they are doing." (Widely documented in interviews; echoed in the 1993 Letter on focus investing.) Buffett's own record is concentrated — at times 40%+ of Berkshire's equity portfolio has been in 1–2 names (Coca-Cola post-1988, Apple post-2016). The corollary is that **if the three gates do not all pass, the answer is cash or pass — not a small speculative position**. Buffett's "20 punches on a lifetime punchcard" metaphor (repeated across Berkshire annual meetings and letters; see *Essays of Warren Buffett* for compiled references) is the sizing discipline: act only on the rare pitches that clear every gate.

## Decision rules Veda applies

### On `buy` questions

1. **Circle-of-competence gate first.** Before any valuation, make the user explain — in two sentences — how this business makes money, who its customer is, and what would make the customer leave. If they cannot, the verdict is **`wait`**. This is Buffett's functional equivalent of Lynch's two-minute drill; it runs first because a moat estimate for a business you do not understand is noise.
2. **Moat identification.** Name the moat type (cost / brand / switching costs / network / regulatory) and a specific observable that proves it (gross margin durability across a cycle, customer retention, share gains without price cuts, peer pricing differential). "Huawei is cheaper" without sustained share shifts is not moat erosion; "AWS lost a major contract to Azure on pricing" is. State whether the moat is **widening, stable, or narrowing**. A narrowing moat vetoes the buy regardless of price.
3. **Intrinsic-value range (not a point).** Per SKILL.md Stage 6, single-point DCF outputs are forbidden. Produce a *range* built from user- or source-supplied ranges for growth, operating margin, and discount rate; or skip to a relative-multiple check (current P/E vs. 10-year historical average, vs. direct peers) with Tier 1–2 sources. The acceptable commands:
   - *"Paste a growth range (e.g., 8–12%), operating-margin range (e.g., 22–28%), and a discount rate (e.g., 9–11%), and I will produce a low-end and high-end intrinsic value. I will not DCF a single point."*
   - *"If you will not supply those ranges, I will compare current P/E against the 10-year median — cite the source — and report whether you are buying above or below that median. That is a relative check, not an intrinsic value."*
4. **Margin-of-safety check.** Record the **low end** of the intrinsic-value range and the current price. Margin of safety = (intrinsic_low − price) / intrinsic_low × 100. Per Hard Rule #8, **do not compute this in-head**. Route it through `python scripts/calc.py margin-of-safety --intrinsic-low <low> --price <current>` and paste the output verbatim into the decision block. Record both inputs and their sources so the calculation is auditable. Thresholds:
   - **Wonderful business** (moat wide, widening, management trusted): 10–20% MoS is acceptable.
   - **Good business** (moat stable, above-average returns on capital): 25–35% MoS.
   - **Average business**: 40%+ MoS, or pass. Buffett rarely buys these at all.
5. **Fat-pitch gate for sizing.** Only if all three gates pass — circle of competence, identified durable moat, margin of safety at the quality-appropriate threshold — does the buy convert into a concentrated-conviction position. If one or two gates fail, the position is either a watchlist entry (price has to come to us) or a pass. Never compromise by buying a small "starter" position to sidestep a failed gate — that is the retail error Buffett's 20-punch rule is designed to prevent.

### On `sell` / `hold_check` questions

1. **Default is hold.** Buffett's *"Our favorite holding period is forever"* (Berkshire 1988 Letter) is operationally: the burden of proof is on the sell side, not the hold side. A `hold_check` starts with a presumption of hold and requires the user to produce one of the three valid sell triggers below.
2. **Valid sell triggers** (Buffett-consistent):
   - **Moat breach.** A named, observable erosion of the durable advantage — not a fear of future erosion. ("See's lost a key supplier" is fear; "gross margins compressed 500bps for 3 consecutive years and peers took share" is evidence.)
   - **Circle-of-competence change.** Management turnover into an unproven team, a strategic pivot into a new business the user cannot evaluate, or an acquisition that changes what the company *is*. (Buffett's 2020 airline exit is an example of this rule firing — the business model he bought was not the business model he now owned.)
   - **Absurd mispricing, moat-adjusted.** Price so far above a defensible intrinsic-value range that even compounding for a decade does not close the gap. This is rare. Buffett's public lesson from Coca-Cola at ~50x earnings in 1998 is that even he did not act on this trigger (1998 Berkshire Annual Meeting, revisited in the 2004 Letter). Apply it only when the mispricing is at least 2x a conservative high-end intrinsic estimate — not "it feels expensive".
3. **Price alone is not a sell thesis.** A paper drawdown is Mr. Market quoting you a bad price; it is not business information. A user asking *"should I sell, it's down 30%"* is running a Mr. Market framework error. The correct question is *"is the moat intact?"* — if yes, hold or add; if no, sell fully.
4. **When the thesis is broken, sell fully and quickly.** Buffett does not ladder out of a broken thesis. The 2020 airlines exit was complete, across all four holdings, in a single quarter. Dribbling out signals unresolved commitment-bias — which is Munger's department; route him in.

### On `size` / `how-much` questions

1. **Concentrated-conviction allowance.** When Buffett's three gates (competence + moat + MoS) all pass, 10–25% single-position sizes are coherent. Above 25%, even Buffett's record shows pressure to manage the concentration (Berkshire trimmed its Apple stake materially in 2024; Buffett publicly cited tax considerations, and position-size management is a second plausible factor the filings are consistent with). Use this as the outside boundary, not the target.
2. **Defer the actual math to Thorp.** Buffett informs *how much conviction justifies how large a position* (via the fat-pitch gate); Thorp / Kelly produces the number. Route `python scripts/calc.py kelly --p-win <x> --odds <y>` for the sizing math. Do not size by feel.
3. **No leverage.** "If you're smart you don't need it; if you're dumb you've no business using it." (Buffett, widely documented across interviews and Berkshire annual meetings; Berkshire's ten-year Protégé Partners bet, settled in 2017, is the long-form illustration that leverage- and fee-dependent strategies underperformed the index.) Veda enforces this for any profile; for novices it is already a guardrail.

## What Buffett does NOT cover (explicit boundary)

Veda's Stage 6 requires each framework to declare where it stops. If the question falls here, do not stretch Buffett — reroute.

- **Short-term / macro timing.** Buffett has been publicly wrong on near-term direction for decades and does not try. Macro-regime questions route to Druckenmiller (who leads on `when`) and Marks (who leads on cycle / permanent-loss vs. volatility). *"Prepare, don't predict"* is Marks's territory, not Buffett's.
- **Cyclical inversion.** Commodity, shipping, homebuilder, and similar cyclicals are bought at *high* P/E (trough earnings) and sold at *low* P/E (peak earnings). That is Lynch's Cyclical rule, not Buffett's durable-moat rule. Buffett historically owned few pure cyclicals.
- **Fast-growing businesses without established profitability.** PEG-style screens for early-stage compounders are Lynch's (Fast Grower category) and Fisher's (scuttlebutt / growth runway). Buffett's margin-of-safety framework assumes an intrinsic-value estimate *can* be made; when cash-flow shape is genuinely unknowable, the framework gives no signal, and the honest answer is "outside the circle".
- **Turnarounds / distressed.** Buffett is skeptical as a rule (*"Turnarounds seldom turn"* — Berkshire 1979 Letter). When a user insists on a turnaround thesis, route Klarman (explicit on value-trap risk) and Lynch (Turnaround category has ~20–30% base-rate success per [internal/base-rates.md](../internal/base-rates.md)).
- **Position-sizing math.** Buffett *gates* concentration via the fat-pitch test; the numeric size comes from Thorp/Kelly via `scripts/calc.py kelly`.
- **Options, shorts, leverage, crypto-derivative exposure.** Reroute to Taleb for tail-risk framing; refuse under novice guardrails per SKILL.md Hard Rule #2 structural-equivalence.
- **Munger pairing — inversion is Munger's department, not Buffett's.** When Veda loads Buffett on a `sell` or `hold_check`, it should almost always also load Munger (*"would I buy this today?"*). Buffett composes the thesis; Munger tries to kill it. If Munger cannot, the thesis stands. This is how the two frameworks work together in the source material ([frameworks/munger.md](munger.md)).

## Worked example — applying Buffett

**Question:** *"Should I buy AAPL at $190? It's been flat for a year."*

**Buffett's process:**

1. **Circle of competence?** Consumer hardware with a premium-brand lock-in and a growing services attach is a business a retail user can evaluate. Ask the user to explain in two sentences why iPhone users stay on iPhone. If the answer is "switching is painful and the ecosystem is sticky", that is the moat talking — circle-of-competence gate passes for most users. Enterprise-AI accelerator businesses would not clear this gate for the same user.
2. **Moat identification.** Brand + switching costs (iCloud, iMessage, Apple Watch pairing, app library) + services margin expansion. Gross margin trajectory is the observable: Services GM ~70%, blended GM ~45%, durable over a decade. Moat **stable to widening** as Services share grows. Source: 10-K segment disclosures (Tier 1).
3. **Intrinsic-value range.** Refuse a single-point DCF per SKILL.md Stage 6. Ask user for growth range (e.g., revenue 4–7% CAGR, operating margin 30–32%) and discount rate (e.g., 8–10%). Or produce a relative-multiple check: current forward P/E vs. Apple's 10-year median and vs. peers. Cite Yahoo Finance / 10-K (T1/T2). *Do not state "$X is fair value".*
4. **Margin of safety.** Once the intrinsic-value range is set, compute MoS = (intrinsic_low − 190) / intrinsic_low × 100 via `python scripts/calc.py margin-of-safety --intrinsic-low <low> --price 190`. For a wonderful-business verdict, 10–20% MoS is the threshold. If AAPL at $190 clears that against the user's conservative range, the buy is coherent; if not, the answer is **wait at price target X**, not "buy smaller".
5. **Fat-pitch gate.** If competence + moat + MoS all pass, size to conviction via Thorp/Kelly (route separately). If MoS fails, the position is a watchlist entry at a target price, and the decision block's recommendation is **`wait`** with the specific price trigger recorded.

**Buffett's verdict (sketch):** Conditional hold-or-wait. Hold if already owned (moat intact, thesis unchanged from original buy). Buy only if a defensible intrinsic-value range produces a MoS at or above the wonderful-business threshold — otherwise wait at a named price level. **Would be wrong if:** Services growth decelerates below the single digits for 2 consecutive years, OR blended GM compresses >300bps sustained, OR iPhone unit retention (measured via active-device disclosures) rolls over.

## Verdict template (for orchestrator)

When Veda invokes Buffett, fill the `frameworks_applied[]` entry in [../templates/decision-block.md](../templates/decision-block.md) using the canonical keys (`name`, `rule_cited`, `verdict`, `action_suggested`, `would_be_wrong_if`, `framework_does_not_cover`). Buffett-specific diagnostic fields ride alongside as auxiliary keys.

```yaml
frameworks_applied:
  - name: Buffett
    rule_cited: <e.g., "Wonderful business at fair price, Berkshire 1989 Letter; margin of safety, Intelligent Investor ch. 20">
    verdict: <string — one-line summary of what Buffett says about THIS situation>
    action_suggested: <buy X | sell all | trim to Y% | hold | add | wait>
    would_be_wrong_if: <specific observable — e.g., "Services gross margin compresses >300bps for 2 consecutive years">
    framework_does_not_cover: <what Buffett is silent on here — e.g., "macro regime shift, tail-risk from options exposure">
    # --- Buffett-specific auxiliary fields (not part of the canonical schema) ---
    circle_of_competence_passed: <bool | not_asked>
    moat:
      type: <cost | brand | switching_costs | network | regulatory | none>
      direction: <widening | stable | narrowing>
      evidence:
        - <data point with source + tier>
    intrinsic_value:
      method: <range_dcf | relative_multiple | skipped>
      inputs:
        growth_pct_range: <[low, high] with source>
        op_margin_pct_range: <[low, high] with source>
        discount_rate_pct: <[low, high] with source>
      output_range: <[low, high] in currency>
      output_source_tier: <T1 | T2 | T3 | T4 | T5>
    margin_of_safety_pct: <number from `python scripts/calc.py margin-of-safety --intrinsic-low <low> --price <current>`>
    margin_of_safety_threshold_applied: <10-20 wonderful | 25-35 good | 40+ average>
    fat_pitch_gates_passed: <all_three | two_of_three | one_or_none>
```

## Sources

- *The Essays of Warren Buffett: Lessons for Corporate America*, ed. Lawrence A. Cunningham, 4th rev. ed. — thematic index into the Berkshire letters.
- Berkshire Hathaway Chairman's Letters, specifically: 1979 (turnarounds), 1987 and 1997 (Mr. Market), 1988 (favorite holding period), 1989 (wonderful company at a fair price), 1992 (circle of competence), 1993 (focus investing), 2004 (Coca-Cola / expensive-but-intact), 2017 (Protégé Partners bet).
- Benjamin Graham, *The Intelligent Investor*, rev. ed. ch. 20 — "Margin of Safety as the Central Concept of Investment".
- Warren Buffett, "The Superinvestors of Graham-and-Doddsville", *Hermes Magazine* (Columbia Business School), Fall 1984.
- Warren Buffett with Carol Loomis, "Mr. Buffett on the Stock Market", *Fortune*, November 22, 1999 — the durable-competitive-advantage / moat essay.
- Berkshire Hathaway Annual Meeting transcripts, specifically 1998 (discussion of Coca-Cola's valuation and long-hold discipline); the "20 punches on a lifetime punchcard" metaphor is a recurring Buffett theme across multiple meetings and letters rather than a single sourced remark.
