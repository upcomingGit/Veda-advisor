# Example profile — Aggressive growth investor

<!--
Example profile to illustrate how onboarding answers map to the schema.
Persona: 32-year-old software engineer in Bangalore, 15+ year horizon, quality-growth lean, focused portfolio, sells winners too early.
-->

```yaml
schema_version: 0.1
generated: 2026-04-15
profile_last_updated: 2026-04-15
disclosure_acknowledged: true
incomplete: false
experience_mode: standard
max_loss_probability: 60    # aggressive_growth goal + high calibrated tolerance + documented behavior through two drawdowns

identity:
  name: Priya Menon
  display_name: Priya

horizon:
  current_age: 32
  target_retirement_age: 55
  effective_horizon_years: 23

capital:
  pct_net_worth_in_market: 65
  # Priya's current capital split (e.g., 70/20/0/10 today) is tactical and
  # lives in her assets.md > dynamic.capital_split_current. Only the target
  # goes here. If current and target match, Veda derives target from the
  # assets-side snapshot on the first portfolio question.
  target_split:
    core_long_term: 70
    tactical: 20
    short_term_trades: 0
    speculation: 10

goal:
  primary: aggressive_growth
  notes: "Comfortable with 40% drawdowns if thesis intact. Not comfortable with forced-sell situations (leverage)."

risk:
  stated_tolerance: high
  behavioral_history: "Added to positions during March 2020 crash. Held through 2022 drawdown without selling. Credible."
  calibrated_tolerance: high

concentration:
  # Priya's current snapshot (focused, 11 positions, largest 14%) lives in
  # her assets.md > dynamic.concentration_snapshot. Only the target is a
  # profile fact.
  target:
    style: focused
    position_count: 12
    max_single_position_pct: 15

markets:
  - india
  - us

# Priya holds both INR- and USD-denominated equities, so her assets.md pins
# today's USD-INR rate in `dynamic.fx_rates.usd_inr`. Every session refreshes
# that entry before use per Hard Rule #9 (SKILL.md). FX is tactical and does
# not belong in profile.md.

style_lean:
  primary: quality
  secondary: growth

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
      - PPF
      - EPF
      - NPS
  forced_concentration: []
  other: ""

experience:
  level: intermediate
  years_investing: 6
  explanation_depth: standard

self_identified_weakness: "I sell winners too early. Trimmed NVDA at 2x in 2023, missed the 5x."

data_access:
  - yahoo_finance
  - screener_in
  - seeking_alpha

notes: "Planning to buy a house in 3 years. Will need Rs 40L liquidity then — tracked separately from the investing portfolio."

framework_weights:
  buffett: 0.15
  lynch: 0.18
  druckenmiller: 0.05
  marks: 0.08
  dalio: 0.02
  klarman: 0.05
  thorp: 0.08
  templeton: 0.03
  munger: 0.10
  fisher: 0.18
  taleb: 0.08
```

## How Veda reads this

Priya is a long-horizon quality-growth investor with credible high risk tolerance. Her self-identified weakness (selling winners too early) means Veda will surface **Lynch's "don't pull flowers"** rule and **Fisher's "the right time to sell a great company is almost never"** on every trim decision, even if she doesn't ask for it.

Her focused concentration (12 positions, up to 15% each) means Veda will apply **Thorp's Kelly sizing** to check position sizes are justified by conviction, and **Dalio's correlation** check to ensure the 12 positions aren't all the same bet in different wrappers.

The 3-year house-purchase liquidity need is tracked separately — Veda will not touch that capital for equity recommendations.
