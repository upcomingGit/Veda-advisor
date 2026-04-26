# Customize Veda for You

Veda is opinionated, but every opinion is applied **through your profile**. Edit the profile, change every decision Veda makes for you. Most users only edit 5–10 lines.

Full schema: [setup/profile.template.md](../setup/profile.template.md). Worked examples: [aggressive](../setup/profile.example-aggressive.md), [novice](../setup/profile.example-novice.md).

## Start here — the three lines that matter most

If you only ever change three things, change these. They drive most of Veda's behaviour:

| Field | What it controls | Default by mode |
|---|---|---|
| `goal.primary` | Which investor frameworks get auto-loaded on every buy | Whatever you said at onboarding |
| `max_loss_probability` | The hard ceiling on "how much can I lose on this trade?" | Novice 15, Standard 35, Aggressive up to 60 |
| `self_identified_weakness` | The bias Veda will actively guard against | Empty until you fill it |

Details on each below. Everything else is fine-tuning.

## Three ways to edit

| Method | When | How |
|---|---|---|
| **Ask Veda inline** | Single-field changes. *"Veda, change my horizon to 15 years."* | Veda updates `profile.md` and runs the validator. |
| **Edit `profile.md` directly** | Bulk changes, or you prefer a text editor. | Edit, save, then `python scripts/validate_profile.py profile.md`. |
| **Redo onboarding** | Big life change — new job, new market, marriage, retirement. | *"Veda, redo onboarding."* The current profile gets backed up to `profile.md.bak-<today>` before the new one starts. |

If the validator fails, Veda refuses to answer until the profile parses (Hard Rule #1).

## Time horizon and goal

```yaml
horizon:
  current_age: 38
  target_retirement_age: 60
  effective_horizon_years: 22

goal:
  primary: balanced_growth   # capital_preservation | income | balanced_growth | aggressive_growth | speculation
  notes: "Growth until 55, switch to income thereafter."
```

`goal.primary` drives routing. `capital_preservation` adds Klarman + Marks to every buy. `aggressive_growth` or `speculation` elevates Lynch, Fisher, Druckenmiller.

## Risk tolerance and maximum loss

```yaml
risk:
  stated_tolerance: high            # low | medium | high
  calibrated_tolerance: medium      # what you actually do when prices fall
  behavioral_history: "Held through 2020 COVID drawdown, sold half in 2022 tech rout."

max_loss_probability: 35   # 0–100; the Stage 8 second gate
```

`max_loss_probability` is the most important risk knob. Positive EV but p_loss above this number → trade refused.

| Mode | Default `max_loss_probability` |
|---|---|
| Novice | 15 |
| Standard | 35 |
| Aggressive growth / speculation | up to 60 (requires documented `behavioral_history`) |

Lowering it: anytime. Raising above mode default: Veda asks you to confirm.

**Not sure what to set?** Pick the mode default and adjust after a few months of journal entries. The honest version of `calibrated_tolerance` is one notch below `stated_tolerance` for most people — we say we are higher-risk than we actually behave when prices fall. If you have never sat through a 30%+ drawdown, set `calibrated_tolerance` to `low`.

## Self-identified weakness

```yaml
self_identified_weakness: "I sell winners too early"
```

The single most useful line in your profile. Triggers the **counter-framework** in routing:

| Weakness | Counter added |
|---|---|
| `"I hold losers"` | Druckenmiller (first loss = best loss) on losing-position hold-checks. |
| `"I sell winners too early"` | Munger inversion (would I buy at today's price?) on winning-position hold-checks. |
| `"I buy on hype"` | Marks + Klarman on every buy. |
| `"I panic sell"` | Buffett + Templeton on every sell or trim during drawdowns. |

Do not name a weakness → no counter. Be honest; this field is not graded.

**Don't know your weakness yet?** Leave the field empty until you have 10–20 journal entries. Then read the journal and look for the pattern that keeps repeating: do you keep regretting the trims, or the holds? The cuts, or the adds? The pattern is your weakness. Write it down.

## Hard constraints

```yaml
hard_constraints:
  esg: false
  sharia: false
  employer_blacklist: ["INFY", "TCS"]
  jurisdiction_blacklist: ["RU", "IR"]
  max_single_position_pct: 12           # ceiling regardless of Kelly
```

Applied before any framework runs. A Kelly suggestion of 18% is silently capped at your ceiling.

## Style lean

```yaml
style_lean:
  primary: quality   # value | growth | quality | macro | passive_plus
```

Soft preference. Elevates frameworks above the routing default:

| Style | Elevated |
|---|---|
| `value` | Klarman, Buffett, Marks |
| `growth` | Lynch, Fisher, Druckenmiller |
| `quality` | Buffett, Munger, Fisher |
| `macro` | Druckenmiller, Dalio, Marks |
| `passive_plus` | Klarman, Marks (high valuation bar before any single-stock buy) |

## Framework weights — tie-breakers

```yaml
framework_weights:
  buffett: 0.15
  lynch: 0.18
  munger: 0.10
  fisher: 0.08
  druckenmiller: 0.10
  marks: 0.12
  klarman: 0.08
  thorp: 0.06
  dalio: 0.05
  templeton: 0.05
  taleb: 0.03
```

Weights are ordinal — they break ties, they do not multiply outputs. Sum should land in [0.9, 1.1].

Tune weights only after months of use, when one framework keeps pulling you in a direction you regret. The journal is your evidence. Do not tune weights to win a single argument with Veda.

## Novice guardrails

```yaml
experience_mode: novice
guardrails:
  max_single_position_pct: 8
  block_leverage: true
  block_options: true
  block_shorts: true
  block_lottery_bets: true
  require_index_comparison: true
  education_mode: true
  graduation_criteria:
    - "Lived through one drawdown of 20% or more without panic-selling"
    - "Two years invested with documented quarterly reviews"
    - "Read at least two of the canon books"
```

Non-negotiable mid-session. Veda will not relax them on request.

**Structural equivalence.** Leveraged ETFs (2x, 3x), single-stock leveraged funds, volatility products (UVXY, SVXY), crypto derivatives, and micro-cap lottery bets are refused with the same script as direct leverage — same payoff asymmetry, same ruin risk.

**`require_index_comparison`.** Every novice buy decision shows the index alternative side by side. Often the index wins. That is the lesson.

**`education_mode`.** Every framework citation includes a one-line summary and a book reference.

**Graduating.** When you have met all three `graduation_criteria`, ask: *"I think I have met my graduation criteria — review and update."* Veda walks your `behavioral_history` and journal, then switches you to `standard`.

## Markets and instruments

```yaml
markets:
  primary: IN          # IN | US | UK | SG | EU
  secondary: [US]
  base_currency: INR

instruments:
  long_only_cash: true
  mutual_funds: true
  bonds: false
  options: false       # set true only with proven track record
  shorts: false
  margin: false
  crypto: false
```

An instrument set to `false` means Veda will never recommend an action that requires it (related frameworks still load for risk discussion).

`markets.primary: IN` quotes prices in INR, uses NSE/BSE ticker conventions, and applies Indian tax rules. `US` switches to USD, S&P 500 benchmark, US tax wrappers (401(k), IRA, ESPP, ISO/NSO). Cross-market: every number labelled with currency and an FX rate stamped with `as_of`.

## Concentration target

```yaml
concentration:
  target:
    style: focused          # index_like | diversified | focused | concentrated
    position_count: 12
    max_single_position_pct: 15
```

| Style | Positions | Sizing bias |
|---|---|---|
| `index_like` | 30+ | Follow benchmark weights. |
| `diversified` | 15–25 | Standard Kelly. |
| `focused` | 8–14 | Larger sizes on highest-conviction names. |
| `concentrated` | 5–8 | Buffett-style. Requires high `max_loss_probability`. |

Today's actual concentration lives in `assets.md > dynamic.concentration_snapshot`. Profile holds the **target**; assets holds **today**. Mismatch → Veda biases toward consolidate / trim / no-new-names.

## Capital allocation target

```yaml
capital:
  pct_net_worth_in_market: 65
  target_split:
    core_long_term: 70
    tactical: 25
    short_term_trades: 0
    speculation: 5
```

Four buckets must sum to 100 (validator enforces). Today's actual split lives in `assets.md > dynamic.capital_split_current`.

## Disclosure acknowledgement

```yaml
disclosure_acknowledged: true
```

Set during onboarding. If missing or `false`, Veda re-surfaces the disclosure before the next decision question.

## After editing

1. Run the validator: `python scripts/validate_profile.py profile.md`.
2. On the next chat, tell Veda: *"I updated my profile."*
3. If you edited the file directly, set `profile_last_updated` to today.

**What the validator output looks like.**

Success (silent, exit 0):

```
(no output — profile is valid)
```

Failure (exit 1, prints the offending field):

```
profile.md: ERROR
  experience_mode: "Standard"
    expected one of: novice | standard
  capital.target_split: sums to 95, must sum to 100
```

Fix each line, save, re-run.

## Common adjustments

You usually do not come to this page wanting to change `framework_weights[3]`. You come because **you want Veda to behave differently in some specific way**. Here are the recipes for the most common ones.

### "Make Veda push me toward holding winners longer"

```yaml
self_identified_weakness: "I sell winners too early"
```

That is it. Adds Munger inversion to every hold-check on a winning position — you have to answer *"would I buy this at today's price?"* before any trim.

### "I'm tighter on risk this year"

Lower these two:

```yaml
max_loss_probability: 20         # was 35
hard_constraints:
  max_single_position_pct: 8     # was 12
```

Veda will refuse more trades and cap sizes harder.

### "I switched from US to India trading"

Redo onboarding (the cleanest path), or edit:

```yaml
markets:
  primary: IN
  secondary: [US]
  base_currency: INR
```

Veda re-quotes everything in INR and applies STCG/LTCG rules.

### "I want to stop trading options"

```yaml
instruments:
  options: false
```

Taleb's tail-risk frame still loads for risk discussion, but Veda will never recommend an action that requires options.

### "I want a stricter check before any new buy"

```yaml
style_lean:
  primary: passive_plus
```

Klarman + Marks elevated on every buy. The valuation bar gets meaningfully higher — the index stays the default.

### "I keep wishing I had bought earlier"

Review your journal for the pattern — are you regretting `WAIT` decisions or `PASS` decisions? If `WAIT`s where the price ran away, set:

```yaml
self_identified_weakness: "I wait too long for a better entry"
```

Not one of the four canned weaknesses, but Veda still surfaces it in Stage 7b devil's-advocate as relevant context.

### "I want Veda to forget everything and start fresh"

```
Veda, redo onboarding.
```

The current profile is backed up to `profile.md.bak-<today>` before the interview restarts.

## What you cannot customize

Encoded in [SKILL.md](../SKILL.md) Hard Rules:

| Cannot turn off | Why |
|---|---|
| Source-tier labelling | Auditability. |
| Framework attribution | *"Buffett would say"* with no citation is the failure Veda exists to prevent. |
| `scripts/calc.py` for arithmetic | LLMs miscalculate. |
| `as_of` on every price and FX | Stale numbers produce confident-sounding wrong answers. |
| 9-stage pipeline order | Skipping or reordering ships bad advice with high confidence. |
| Out-of-scope decline scripts | The scope is the product. |
