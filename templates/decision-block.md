# Decision Block Template

Every buy / sell / add / trim recommendation must produce this block. Paste it into the user's journal.

---

```yaml
date: <YYYY-MM-DD>
user_question: |
  <verbatim user question>

classification:
  type: <buy | sell | size | hold_check | macro | risk | psychology | portfolio>
  urgency: <research | in-market | crisis>
  scope: <single-name | sector | portfolio | market>

context:
  ticker: <e.g., NVDA>
  currency: <USD | INR | ...>               # currency of all figures in this block; if mixed, declare FX rate + date below
  fx_reference: <e.g., "USD/INR 83.2 as of 2026-04-18, Yahoo Finance"> # required only when cross-market figures appear
  current_price: <number + source + tier, e.g., "$875 (Yahoo Finance T2, 2026-04-19)">
  current_position: <e.g., "50 shares, cost basis $210, current value $43,750 USD">
  key_metrics:
    - <metric: value (source, tier)>

base_rate:
  stated: <string + cited source + tier, or wide range for LOW>
  confidence: <HIGH | MEDIUM | LOW | NONE>   # from Stage 4

frameworks_applied:
  - name: <Lynch | Buffett | ... >
    rule_cited: <e.g., "Fast Grower rule, One Up on Wall Street ch. 8">
    verdict: <string — what this framework says about THIS situation>
    action_suggested: <buy X | sell all | trim to Y% | hold | wait>
    would_be_wrong_if: <string — specific kill criterion>
    framework_does_not_cover: <string — what this framework is silent on here>

synthesis: <consensus | partial_disagreement | hard_conflict>
synthesis_note: <string — if disagreement, how it was broken; downgrade if base_rate.confidence is LOW/NONE>

devils_advocate:
  best_counter_argument: <string — strongest case AGAINST the recommendation; if the user's profile.self_identified_weakness is triggered by this action direction, name it here>
  why_not_persuaded: <string — specific reason(s) to proceed anyway; if you cannot produce this, escalate to hard_conflict>

recommendation:
  action: <buy | sell | add | trim | hold | wait>
  size: <e.g., "trim from 15% to 8%" | "add $5000" | "hold — no action">
  trigger_for_reevaluation:
    - <date | price_level | event | data_point>

expected_value:
  upside:
    scenario: <string>
    return_pct: <+X%>
    probability: <0.0 - 1.0>
  base:
    scenario: <string>
    return_pct: <+Y%>
    probability: <0.0 - 1.0>
  downside:
    scenario: <string>
    return_pct: <-Z%>
    probability: <0.0 - 1.0>
  # probabilities must sum to 1.00 (validated by scripts/calc.py)
  probability_justification: |
    <one paragraph: how did you arrive at these probabilities? Reference the base_rate above.
    If upside probability exceeds the base rate, state the specific user-supplied or sourced
    reason the reference class does not apply. Do not tune probabilities to make EV positive.>
  # All three numbers below must be produced by scripts/calc.py. Do NOT compute them in the LLM.
  ev_contribution: <expected_value_pct from `python scripts/calc.py ev --probs ... --returns ...`>
  p_loss: <p_loss from same calc.py invocation; 0.0–1.0 scale>
  p_loss_pct: <p_loss_pct from same calc.py invocation; 0–100 scale>
  calc_command: <exact command, e.g. "python scripts/calc.py ev --probs 0.35 0.40 0.25 --returns 60 15 -35">
  p_loss_check: <pass | fail>   # pass if p_loss_pct <= profile.max_loss_probability; fail forces "wait" or "pass" per Stage 8
  verdict: <positive | negative>  # if negative, recommendation must be "wait" or "sell"

portfolio_check:
  correlation_with_existing: <string — does this share a thesis with positions already held?>
  sector_cap_impact: <string — does this breach any sector cap in the profile?>
  portfolio_heat_before: <string — existing at-risk capital %>
  portfolio_heat_after: <string — after this trade>
  cash_position_after: <string>

pre_commit:
  thesis: |
    <one-sentence thesis for why this action will work>
  kill_criteria:
    - <specific observable that proves the thesis wrong>
    - <another one>
  reevaluate_trigger: <date | price | event>
  max_acceptable_loss_on_position: <X%>
  # If the position drops by this much, forced exit. No exceptions.

# Novice-only fields. Present when profile.experience_mode is novice.
# Required by guardrails.require_index_comparison and guardrails.education_mode.
index_comparison:
  benchmark: <Nifty 50 | S&P 500 | other — match the user's market>
  benchmark_expected_return_pct: <+X% over same horizon as the single-stock EV>
  single_stock_expected_return_pct: <+Y% — the base-case return from the expected_value block above>
  verdict: <index_wins | single_stock_wins | too_close_to_call>
  note: <string — one line explaining why>

education_note: |
  <1–2 sentences: what principle does this decision illustrate, and which book
  references it? e.g., "This is Lynch's rule for Fast Growers (One Up on Wall Street,
  ch. 8): pay up for growth, sell when growth decelerates for 2 consecutive quarters.">
```

---

## Usage notes for Veda

1. **All fields are mandatory** unless marked optional. If you don't have the data for a field, mark it `TBD` and tell the user what you need.
2. **Currency discipline.** Every number carries its currency. `fx_reference` is required whenever cross-market figures appear in the same block. No silent FX mixing.
3. **Source tiers.** Every factual number cites its source and tier (T1–T5). Tier 4–5 sources imply LOW-CONFIDENCE and must be called out in `synthesis_note`.
4. **Unit convention.** Probabilities in `expected_value.*` fields are 0.0–1.0 and must sum to 1.00 (validated by `scripts/calc.py`). `p_loss` mirrors that scale. `p_loss_pct` is `p_loss × 100` and is what the Stage-8 second gate compares against `profile.max_loss_probability` (which is 0–100).
5. **Arithmetic is Python, never LLM.** Per SKILL.md Hard Rule #8, every numeric field in this block — `ev_contribution`, `p_loss`, `p_loss_pct`, any PEG, Kelly, or FX figure elsewhere in the block — is produced by [../scripts/calc.py](../scripts/calc.py). Record the exact invocation in `calc_command`. If the computation isn't in calc.py yet, add it before filling the field.
6. **Novice-only fields:**
   - `index_comparison` is mandatory when `profile.experience_mode: novice` AND `recommendation.action` is `buy` or `add` (i.e., any decision that deploys new capital into a single stock). It is omitted for `sell`, `trim`, `hold`, and `wait` — the user already owns the position and the question is thesis-level, not allocation-level.
   - `education_note` is mandatory for every novice decision block regardless of action. It is omitted for non-novice profiles.
7. **Both EV gates are binding.**
   - First gate: if `verdict: negative`, recommendation must be `wait` or `sell`.
   - Second gate: if `p_loss_check: fail`, recommendation must be `wait` or `pass`, or size must be reduced until `p_loss_pct <= profile.max_loss_probability`.
8. **Probabilities must be anchored.** `probability_justification` is not optional. Unanchored probabilities are the most common failure mode of this template.
9. **Devil's-advocate is not optional.** If `why_not_persuaded` is empty or hand-wavy, the synthesis must be `hard_conflict` and the user must decide. When `profile.self_identified_weakness` is triggered by the action direction (e.g., weakness is "sells winners too early" and action is `trim`/`sell`), name the weakness explicitly inside `best_counter_argument` — surfacing the user's own known bias at decision time is the point.
10. **Journal append.** After showing this block to the user, append it to `journal.md` with a timestamp.
