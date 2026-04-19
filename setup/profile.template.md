# Veda Profile

<!--
Schema version: 0.1
Generated: <date>
Edit directly or re-run onboarding with "Veda: redo onboarding".
-->

```yaml
schema_version: 0.1
generated: <YYYY-MM-DD>
profile_last_updated: <YYYY-MM-DD>   # date of most recent edit or onboarding run; Veda re-interviews if this is > 6 months old
disclosure_acknowledged: <bool>       # must be true before Veda produces any decision output; set during onboarding
incomplete: false
experience_mode: <novice | standard>
# novice  = shorter onboarding, safe defaults, hard guardrails (see guardrails: below)
# standard = full onboarding, user-specified preferences, no automatic guardrails beyond the user's own constraints

# Top-level risk gate. Maximum P(loss) Veda will accept on any single trade regardless of positive EV.
# Computed at onboarding from experience_mode; user may override downward but not above the mode default.
#   novice   → 15  (ruin-aversion priority)
#   standard → 35  (balanced)
#   aggressive/speculation goal on standard → up to 60  (user has earned this only with documented behavioral history)
max_loss_probability: <int>           # 0–100; enforced as Stage 8 second gate

identity:
  name: <string>
  display_name: <string>  # what Veda calls you

horizon:
  current_age: <int>
  target_retirement_age: <int | "never">
  effective_horizon_years: <int>  # derived

capital:
  pct_net_worth_in_market: <int>  # 0-100; refers to current state
  # split = CURRENT state of deployed capital. Must sum to 100 when all four
  # buckets are present. Captured progressively during the first portfolio
  # question if not elicited at onboarding.
  split:
    core_long_term: <int>    # %
    tactical: <int>          # %
    short_term_trades: <int> # %
    speculation: <int>       # %
  # target_split = DESIRED future state of deployed capital. Optional; only
  # write it when the user's current and target splits differ. When present,
  # must also sum to 100. Veda uses current for feasibility checks and target
  # for direction-of-travel. A mismatch biases recommendations toward moves
  # that close the gap.
  target_split:
    core_long_term: <int>    # %
    tactical: <int>          # %
    short_term_trades: <int> # %
    speculation: <int>       # %

goal:
  primary: <capital_preservation | income | balanced_growth | aggressive_growth | speculation>
  notes: <string>  # any nuance, including multi-phase plans (e.g., growth now -> income at retirement)

risk:
  stated_tolerance: <low | medium | high | very_high>
  behavioral_history: <string>  # what they actually did in last drawdown
  calibrated_tolerance: <low | medium | high | very_high>  # Veda's read after stated + behavioral

# Concentration is split into CURRENT state (what the portfolio actually looks
# like today) and TARGET state (where the user wants it to be). Every sizing
# recommendation reads both:
#   - current for feasibility: "given you already hold 33 names, can you add a 34th?"
#   - target  for direction:   "does this action close the gap or widen it?"
# A large current-vs-target mismatch (e.g., current.style=diversified but
# target.style=focused) biases Veda toward consolidate / trim / don't-add-new
# rather than buy. Record the bridge in glide_notes.
concentration:
  current:
    style: <index_like | diversified | focused | concentrated>
    position_count: <int>            # how many names the user holds today
    largest_position_pct: <int>      # size of the single largest position today (0-100)
  target:
    style: <index_like | diversified | focused | concentrated>
    position_count: <int>            # how many names the user wants to hold
    max_single_position_pct: <int>   # ceiling the user wants to enforce going forward
  glide_notes: <string>              # optional; how the user plans to bridge current -> target

markets:  # multi-select
  - us
  - india
  - europe
  - other_developed
  - emerging
  - crypto
  - private

# Session-scoped cache of FX rates used in this profile. Present only when the
# user has cross-currency exposure (e.g., `markets` contains both `us` and
# `india`). Every entry is treated by Hard Rule #9 (SKILL.md) as STALE once
# its `as_of` date is more than 1 trading day old — Veda must re-ask or
# re-fetch before using it.
#
# Key format: `<from_ccy>_<to_ccy>` in lowercase (e.g., `usd_inr`, `eur_usd`,
# `gbp_inr`). `rate` is the multiplier to convert 1 unit of from_ccy into
# to_ccy. `source` is free text; prefer Tier 1–2 (RBI, Bloomberg, Google
# Finance, Yahoo Finance) and cite the exact page when possible.
fx_rates:
  usd_inr:
    rate: <float>         # e.g., 92.60
    as_of: <YYYY-MM-DD>   # date the rate was fetched or user-supplied
    source: <string>      # optional but recommended, e.g., "Google Finance"

style_lean:
  primary: <value | quality | growth | macro | thematic | quant | passive_plus>
  secondary: <same set, optional>

instruments:
  long_only_cash: <bool>
  margin: <bool>
  options_hedging: <bool>
  options_speculation: <bool>
  shorts: <bool>

constraints:
  religious_ethical:
    - <e.g., "sharia-compliant">
    - <e.g., "no fossil fuels">
  employer_blacklist:
    - <ticker>
  tax_regime:
    country: <ISO code>
    accounts:
      - <e.g., "Roth IRA", "PPF", "ISA">
  forced_concentration:
    - <e.g., "20% MSFT RSU until vested Dec 2027">
  other: <string>

experience:
  level: <beginner | intermediate | advanced | professional>
  years_investing: <int>
  explanation_depth: <minimal | standard | educational>  # how much Veda explains

self_identified_weakness: <string>
# e.g., "I sell winners too early and hold losers too long"

data_access:
  - yahoo_finance
  - screener_in
  - bloomberg
  - seeking_alpha
  - brokerage_research: <broker_name>

notes: <string>
# anything else — family obligations, liquidity events, religious views, etc.

# Novice-only block. Present when experience_mode: novice.
# These are hard constraints Veda enforces before any recommendation.
guardrails:
  max_single_position_pct: 8        # typical novice ceiling; tightens Thorp/Buffett sizing
  block_leverage: true              # no margin recommendations
  block_options: true               # no options (hedging or speculation)
  block_shorts: true                # no short positions
  block_lottery_bets: true          # no sub-1% speculative positions; novices don't know yet what's speculation vs investment
  require_index_comparison: true    # every single-stock buy recommendation shows the index-fund alternative's expected return side-by-side
  education_mode: true              # Veda cites frameworks with 1-line summaries + book references (see CREDITS.md)
  graduation_criteria:
    - "Lived through one 20%+ market drawdown with documented reaction in risk.behavioral_history"
    - "At least 2 years of consistent investing"
    - "Read at least 2 of: One Up on Wall Street, The Essays of Warren Buffett, The Most Important Thing"
    - "User explicitly requests graduation via 'Veda: review my experience mode'"

framework_weights:
  # Auto-derived from goal + style_lean + horizon. Veda uses these to break ties when frameworks disagree.
  buffett: <0.0 - 1.0>
  lynch: <0.0 - 1.0>
  druckenmiller: <0.0 - 1.0>
  marks: <0.0 - 1.0>
  dalio: <0.0 - 1.0>
  klarman: <0.0 - 1.0>
  thorp: <0.0 - 1.0>
  templeton: <0.0 - 1.0>
  munger: <0.0 - 1.0>
  fisher: <0.0 - 1.0>
  taleb: <0.0 - 1.0>
```

---

## Derivation rules (for Veda, not the user)

When generating `framework_weights` from the user's answers:

| User signal | Weight increase |
|---|---|
| Long horizon (15+ years) | Buffett, Lynch, Fisher, Munger |
| Short horizon (<5 years) | Druckenmiller, Marks, Klarman |
| Goal = capital preservation | Klarman, Marks, Taleb |
| Goal = aggressive growth | Lynch, Fisher, Druckenmiller |
| Goal = speculation | Taleb, Thorp |
| Style = value | Klarman, Templeton, Buffett |
| Style = quality | Buffett, Munger, Fisher |
| Style = growth | Lynch, Fisher |
| Style = macro | Druckenmiller, Dalio |
| Concentration = concentrated | Buffett, Thorp |
| Concentration current=diversified AND target=focused (mismatch) | Munger (inversion — don't add new names), Lynch (categorize what you already own) |
| Concentration = index-like | Dalio |
| Uses options/shorts | Taleb (vol awareness), Thorp (sizing) |
| Self-weakness = holds losers | Druckenmiller (first loss = best loss) always surfaces |
| Self-weakness = sells winners | Lynch (don't pull flowers) + Fisher (hold compounders) always surface |

Weights should sum to roughly 1.0 but need not be exact. Veda uses them for tie-breaking, not for weighted averaging of recommendations.

### Novice weights (override)

When `experience_mode: novice`, ignore the derivation table above and use these fixed weights. Novice frameworks are ordered around ruin-avoidance and discipline, not return maximization.

| Framework | Novice weight | Why |
|---|---|---|
| Buffett | 0.20 | Margin of safety, circle of competence, never lose money |
| Munger | 0.18 | Inversion — avoiding losers matters more than finding winners at this stage |
| Taleb | 0.12 | Ruin avoidance, skin-in-the-game discipline |
| Lynch | 0.12 | Categorize first (the single most teachable idea in investing) |
| Fisher | 0.10 | If buying individual stocks, at least buy quality |
| Marks | 0.10 | Risk = permanent loss, not volatility |
| Klarman | 0.08 | Value-trap detection |
| Dalio | 0.05 | Diversification basics |
| Thorp | 0.03 | Sizing, but deprioritized because novice sizing is capped by guardrail |
| Templeton | 0.02 | Rarely relevant at novice stage |
| Druckenmiller | 0.00 | Aggressive sizing / macro timing is not for novices |

On graduation to `experience_mode: standard`, weights recompute from the full derivation table using the user's answers to the questions that were skipped or defaulted on the novice path (Q3, Q4, Q5, Q6, Q7, Q9, Q10, Q12, Q13, Q14, Q15 — re-interviewed at graduation time).
