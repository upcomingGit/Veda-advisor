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

# Top-level risk gate. Maximum P(loss) Veda will accept on any single trade regardless of positive EV.
# Typical range: 15 (ruin-averse) to 60 (aggressive, with documented behavioral history).
max_loss_probability: <int>           # 0–100; enforced as Stage 8 second gate

identity:
  name: <string>
  display_name: <string>  # what Veda calls you

horizon:
  current_age: <int>
  target_retirement_age: <int | "never">
  effective_horizon_years: <int>  # derived

capital:
  pct_net_worth_in_market: <int>  # 0-100; stable profile fact (how much of net worth is deployed in market assets)
  # Current-state split (today's deployed capital by bucket) is TACTICAL and
  # lives in assets.md > dynamic.capital_split_current, NOT here. Per SKILL.md
  # Hard Rule #10 per-file boundary, profile.md holds only the target split.
  # target_split = DESIRED future state of deployed capital. Optional; only
  # write it when the user's current (in assets.md) and target splits differ.
  # When present, must sum to 100. Veda uses current for feasibility checks
  # and target for direction-of-travel. A mismatch biases recommendations
  # toward moves that close the gap.
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

# Concentration TARGET state (where the user wants to be) is a stable profile
# fact and lives here. CURRENT state (what the portfolio actually looks like
# today: style, position_count, largest_position_pct, largest_position_ticker)
# is TACTICAL and lives in assets.md > dynamic.concentration_snapshot, NOT
# here. Per SKILL.md Hard Rule #10 per-file boundary.
#
# Every sizing recommendation reads BOTH files:
#   - assets.md > dynamic.concentration_snapshot for feasibility: "given you
#     already hold 33 names, can you add a 34th?"
#   - profile.md > concentration.target for direction: "does this action
#     close the gap or widen it?"
# A large current-vs-target mismatch (e.g., today's style=diversified but
# target.style=focused) biases Veda toward consolidate / trim / don't-add-new
# rather than buy. Record the bridge in glide_notes (below).
concentration:
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

# FX rates used for portfolio roll-ups are TACTICAL (they move day-to-day) and
# live in assets.md > dynamic.fx_rates, NOT here. Per SKILL.md Hard Rule #9
# and Hard Rule #10 per-file boundary. profile.md records only the stable
# preference that the user holds cross-currency exposure (implied by `markets`
# containing more than one currency zone above).

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

broker:
  primary: <zerodha | other | none>
  # zerodha = live pull via scripts/kite.py; "refresh from Zerodha" works
  # other = paste or direct edit only; other broker integrations in progress
  # none = no broker (manual tracking)

data_access:
  - yahoo_finance
  - screener_in
  - bloomberg
  - seeking_alpha
  - brokerage_research: <broker_name>

notes: <string>
# anything else — family obligations, liquidity events, religious views, etc.

observed_notes: []
# Durable traits Veda learns from passing remarks, each confirmed by the user
# before writing (Hard Rule #12). Soft context for Stage 1 calibration, not hard
# rules — hard gates belong in constraints.*. One dated bullet per entry, e.g.:
#   - "2026-06-04: checks prices daily during drawdowns; prone to anxious selling."

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
<!-- Read "current" as assets.md > dynamic.concentration_snapshot.style and "target" as profile.md > concentration.target.style. -->
| Concentration = index-like | Dalio |
| Uses options/shorts | Taleb (vol awareness), Thorp (sizing) |
| Self-weakness = holds losers | Druckenmiller (first loss = best loss) always surfaces |
| Self-weakness = sells winners | Lynch (don't pull flowers) + Fisher (hold compounders) always surface |

Weights should sum to roughly 1.0 but need not be exact. Veda uses them for tie-breaking, not for weighted averaging of recommendations.
