# Example profile — Novice investor

<!--
Example profile to illustrate how novice onboarding answers map to the schema.
Persona: 24-year-old software engineer, first job, 6 months of investing experience, has read one book,
bought a few stocks on social-media tips, wants to learn properly. No drawdown history yet.
-->

```yaml
schema_version: 0.1
generated: 2026-04-18
profile_last_updated: 2026-04-18
disclosure_acknowledged: true
incomplete: false
experience_mode: novice
max_loss_probability: 15    # novice default — ruin aversion, untested behavioral history

identity:
  name: Rahul Sharma
  display_name: Rahul

horizon:
  current_age: 24
  target_retirement_age: 55
  effective_horizon_years: 31

capital:
  pct_net_worth_in_market: 15
  split:
    core_long_term: 70       # defaulted for novices — long-term is the safer default
    tactical: 0
    short_term_trades: 0
    speculation: 30          # user admitted tip-chasing; captured honestly

goal:
  primary: balanced_growth   # defaulted for novices without strong stated preference
  notes: "Wants to learn. Not sure what realistic returns look like yet."

risk:
  stated_tolerance: high     # self-reported; novices almost always overestimate
  behavioral_history: "Never lived through a drawdown. Stated tolerance is untested."
  calibrated_tolerance: medium  # Veda downgrades until behaviorally validated

concentration:
  style: diversified         # defaulted for novices
  target_position_count: 20
  max_single_position_pct: 8 # tight cap — novice guardrail

markets:
  - india

style_lean:
  primary: passive_plus      # defaulted — novices start here whether they know it or not
  secondary: quality

instruments:
  long_only_cash: true
  margin: false
  options_hedging: false
  options_speculation: false
  shorts: false

constraints:
  religious_ethical: []
  employer_blacklist: []
  tax_regime:
    country: IN
    accounts:
      - EPF
  forced_concentration: []
  other: ""

experience:
  level: beginner
  years_investing: 0.5
  explanation_depth: educational  # novices get full context, definitions, teach-as-we-go

self_identified_weakness: "Buy on hype / social-media tips. Don't know how to research a stock."

data_access:
  - yahoo_finance
  - screener_in

notes: "Starting out. Wants to learn. Primary question right now is 'should I buy specific stocks or just index?'"

# Novice guardrails — hard constraints Veda enforces automatically for novice profiles.
guardrails:
  max_single_position_pct: 8        # no concentrated bets until graduated
  block_leverage: true
  block_options: true
  block_shorts: true
  block_lottery_bets: true          # no sub-1% speculative positions
  require_index_comparison: true    # every single-stock buy recommendation must show
                                    # the index-fund alternative's expected return side-by-side
  education_mode: true              # Veda explains vocabulary, cites frameworks with 1-line
                                    # summaries, links to books in CREDITS.md
  graduation_criteria:              # what needs to be true before novice mode can be turned off
    - "Lived through one 20%+ market drawdown with documented reaction"
    - "At least 2 years of consistent investing"
    - "Read at least 2 of: One Up on Wall Street, The Essays of Warren Buffett, The Most Important Thing"
    - "User explicitly requests graduation via 'Veda: review my experience mode'"

framework_weights:
  # Novice weights favor the frameworks that teach discipline and avoid disaster.
  # Munger (inversion, avoid losers) and Buffett (concentration + margin of safety) dominate.
  # Taleb weighted for ruin-avoidance education.
  # Druckenmiller, Thorp underweighted — aggressive sizing is not appropriate yet.
  buffett: 0.20
  munger: 0.18
  lynch: 0.12
  fisher: 0.10
  taleb: 0.12
  marks: 0.10
  klarman: 0.08
  dalio: 0.05
  thorp: 0.03
  templeton: 0.02
  druckenmiller: 0.00
```

## How Veda reads this

Rahul is a novice. `experience_mode: novice` activates a different set of behaviors:

1. **Every single-stock `buy` or `add` decision gets an index-fund comparison.** If Rahul asks "should I buy HDFC Bank?", Veda shows him the framework-based answer AND the expected return of just buying Nifty 50. Often the index answer wins — and that's the lesson. (Sell/trim/hold decisions don't need an index comparison — he already owns the position; the question is whether the thesis still holds.)

2. **Hard caps on sizing.** 8% max per position. No "well, you have high conviction so 15% is OK." Novices don't have earned conviction.

3. **Education mode on.** Every framework cited includes a 1-line summary and a book reference. "Lynch's rule for Fast Growers (*One Up on Wall Street*, ch. 8): pay up for growth, sell when growth decelerates for 2 consecutive quarters."

4. **Blocks leverage, options, shorts, lottery bets** at the profile level. If Rahul asks "should I buy calls on NVDA?", Veda says: *"Your profile blocks options. This is a guardrail for novices. You can graduate by [graduation_criteria]."* No workaround.

5. **Calibrated tolerance < stated tolerance.** Rahul said "high" but has never been tested. Veda treats him as medium until behavior proves otherwise.

6. **Teaches through decisions, not lectures.** Every decision block includes a "what this decision taught you" line at the bottom. Over time Rahul builds a library of real decisions with real rationale.

The goal is not to keep Rahul in novice mode forever. The goal is to keep him alive long enough to graduate — and to have a journal of well-reasoned decisions by the time he does.
