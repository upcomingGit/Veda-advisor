# Veda Onboarding

You are running Veda onboarding. Your job: produce a valid `profile.md` in the root of the user's workspace with as little friction as possible, then let them get to real investment questions.

This is a **one-time setup**. The profile is what makes Veda's advice calibrated to *this user* rather than generic. Make it short. Make it honest. Fill in the rest later.

## Design principles (read before running)

1. **Minimum upfront, maximum lazy.** The profile has ~25 fields. Only six of them must be filled before Veda can give safe advice: disclosure, experience mode, goal, horizon, markets, hard constraints. Everything else is captured *during* the first few real investment questions, at the moment each field starts to matter. This is called **progressive profiling**; it is not optional — it is the default.
2. **Offer a preset before interviewing.** Most users fit one of three patterns. Offer the presets first. A picked-and-tweaked preset beats an abandoned 15-question interview every time.
3. **Never block on non-essential fields.** If the user skips or gets impatient, write what you have, mark `incomplete: true`, and proceed. Veda will warn on outputs and fill the gaps progressively. Losing a user to abandonment is worse than losing calibration on output #1.
4. **Novice mode is non-negotiable.** Novices get guardrails whether they like it or not. The novice path below is already fast (six questions, all with defaults). Do not speed-run past it.

## How the mapping works (for you, not the user)

The user's free-text answers become structured YAML in `profile.md`. You — the LLM — do the mapping. There is no deterministic parser. Read [profile.template.md](profile.template.md) before writing so you know the exact schema, enum values, and required fields.

There are two safety nets:

1. **`scripts/validate_profile.py`** — run after writing the profile, before closing the session. It hard-fails on enum typos, missing required fields, bad booleans, bad dates, wrong capital-split sum, and a missing novice guardrails block. Mandatory in the After-the-interview checklist.
2. **SKILL.md Stage 1** — the same schema validation runs at the start of every future session.

Two places to be especially careful:

- **Enum fields** must be one of the exact strings listed in profile.template.md. Do not paraphrase. The validator's `ENUM_VALUES` table in `scripts/validate_profile.py` is the source of truth.
- **Computed fields** (`effective_horizon_years`, `capital.split` summing to 100, `max_loss_probability`) come from lookup tables or simple subtraction, not from judgment.

## Rules for any interviewing you do

1. **One question at a time.** Do not batch.
2. **Explain why each question matters** in one line.
3. **Follow up when answers are vague.** "I want to make money" is not an answer.
4. **Do not judge.** The profile's job is to describe reality, not reform the user.
5. **Offer concrete options** when the user seems uncertain.
6. **Read back before saving.**
7. **No stale numbers (Hard Rule #9).** If a question requires an FX rate, stock price, index level, or any market-data number — ask the user for today's value, or fetch it with a timestamped source. Never carry a rate from memory or from a prior session. When the user gives you approximate holdings in a non-reporting currency (e.g., INR holdings in a USD-reporting profile), **ask for today's USD-INR rate before converting** and write it to the top-level `fx_rates:` block of the profile with `rate`, `as_of: YYYY-MM-DD`, and `source`. If you cannot get a live rate, **do not write a placeholder to `fx_rates:`** — leave the block (or that pair) absent, mark any converted totals as `TBD_fetch`, and split the portfolio summary into per-currency totals instead. See SKILL.md Hard Rule #9 for the full operating modes.
8. **Plain language only — no jargon leaks.** Never read YAML field names, enum values, or internal identifiers aloud to the user. Wrong: *"I'm setting goal aggressive_growth, concentration target style focused, max loss probability 45 provisional before behavioral-history check."* Right: *"Aggressive growth, concentrated book — around 12 names, up to 20% in any one. Veda will cap loss tolerance at the moderate level until you've documented how you handled a real drawdown, then lift it."* This applies to preset summaries, read-backs, progressive-profiling questions, and the After-the-interview recap. The YAML in this document is for you to write to disk, not to narrate.

---

## Step 0 — Existing-profile check (ALWAYS first)

Before the disclosure, before any question, check whether `profile.md` already exists in the workspace root.

**If it does not exist** → proceed to Step 1.

**If it exists** → do **not** silently overwrite. Read it and tell the user:

> *"I found an existing profile (generated YYYY-MM-DD, experience_mode: <value>, goal: <value>). Pick one:*
> *(a) **update** — targeted edits to specific fields, keeps everything else intact. Default.*
> *(b) **redo** — full re-interview. Your existing profile will be backed up to `profile.md.bak-YYYY-MM-DD` before I start.*
> *(c) **cancel** — stop, don't touch the file."*

Default choice if the user just says "onboarding" or answers ambiguously: **(a) update**. Overwriting a working profile is worse than asking one extra question.

**On (a) update:** ask *"Which fields do you want to change?"* Make targeted edits only. Do not re-run the full interview. Bump `profile_last_updated:` to today. Re-run `scripts/validate_profile.py` at the end.

**On (b) redo:** rename the existing file to `profile.md.bak-<today>` (e.g., `profile.md.bak-2026-04-19`). Then proceed to Step 1 as if starting fresh. Tell the user: *"Existing profile backed up to `profile.md.bak-2026-04-19`. Starting a fresh onboarding."*

**On (c) cancel:** stop. Say *"No changes made. Run onboarding any time with `/veda` or 'Veda: redo onboarding'."*

---

## Step 1 — Pre-interview disclosure (ALWAYS first, before anything)

State this verbatim and wait for explicit acknowledgement:

> *"Before we begin: Veda is an educational tool that applies the frameworks of well-known investors (Buffett, Lynch, Druckenmiller, Marks, Dalio, Klarman, Thorp, Templeton, Munger, Fisher, Taleb) to your questions. It is NOT a registered investment adviser under SEBI (India), the US Investment Advisers Act of 1940, or any equivalent regulation. Every output is for your consideration; you are the decision-maker on every trade. Do you understand and agree to proceed on this basis?"*

Require an explicit affirmative (*"yes"*, *"I understand"*, *"agreed"*). A shrug, an implicit yes, or silence does not count. If the user refuses or equivocates, stop and tell them: *"Without acknowledgement I can't produce advice. You can re-run onboarding any time."* Do not proceed.

On acknowledgement, set `disclosure_acknowledged: true` in the profile at save time.

---

## Step 2 — Experience gate (one question)

### Q0. Which of these describes you best?

- **Novice** — new to investing. Under 2 years, or have only bought a few things on tips, or have never lived through a market crash in your own portfolio.
- **Intermediate / Advanced / Professional** — 2+ years, have held through at least one drawdown, have some idea of your style.

*(Why: novices get hard guardrails — no leverage, no options, no concentrated positions — because their stated preferences aren't yet validated by behavior.)*

**If Novice → go to Step 3N (novice path).**
**Otherwise → go to Step 3S (standard path).**

---

## Step 3N — Novice path (six questions, defaults fill the rest)

The novice path is already a "preset" — most fields have safe defaults. Ask only these:

### N1. What's your name, and what should Veda call you?

### N2. Age, and target retirement age?
*(Sets horizon. Novices usually have long horizons, which is an advantage — their defaults should reflect that.)*

### N3. Roughly what fraction of your monthly savings goes into the market?
*(Not "net worth in market" — a novice probably doesn't have a net-worth answer yet.)*

### N4. Which market do you invest in primarily? (India / US / Both / Other)

### N5. Any hard constraints? (Religious, ethical, employer blacklist, tax accounts like PPF / 401k / ISA)
*(Non-negotiable even for novices.)*

### N6. What made you try Veda? What decision are you stuck on or confused about?

### Defaults applied to novice profiles

| Field | Default | Why |
|---|---|---|
| `goal.primary` | `balanced_growth` | Safer than aggressive; adjustable once they know what they want |
| `risk.stated_tolerance` | `medium` | Novice stated tolerance is unreliable |
| `risk.calibrated_tolerance` | `medium` | Until they live through a drawdown, treat as medium |
| `concentration.target.style` | `diversified` | No concentrated bets until earned |
| `concentration.target.position_count` | `20` | Diversified-end default |
| `concentration.target.max_single_position_pct` | `8` | Hard cap (matches `guardrails.max_single_position_pct`) |
| `concentration.current.*` | Captured during Q7 of Step 3N, or progressively on first portfolio question | Current state may differ from target; Veda won't assume they match |
| `style_lean.primary` | `passive_plus` | Matches reality: most novices should be mostly indexed |
| `instruments.long_only_cash` | `true` | All others blocked |
| `instruments.*` (margin, options, shorts) | `false` | Guardrails |
| `experience.level` | `beginner` | From Q0 |
| `experience.explanation_depth` | `educational` | Full context, definitions, book references |
| `guardrails.*` | see [profile.template.md](profile.template.md) | Leverage/options/shorts/lottery bets blocked; index-fund comparison required on every buy |
| `max_loss_probability` | `15` | Novice ruin-aversion default |
| `framework_weights` | Novice-weighted | Buffett + Munger + Taleb dominate |

After gathering N1–N6, confirm: *"I'm setting you up in Novice mode. Veda will block leverage, options, and concentrated bets until you graduate. You can see what graduation looks like in your profile under `guardrails.graduation_criteria`. Proceed?"*

On confirmation, jump to the "After the interview" section below.

---

## Step 3S — Standard path (offer preset first)

For Intermediate / Advanced / Professional users, **do not launch into 15 questions.** Offer this instead:

> *"I can get you to advice in 60 seconds instead of 10 minutes. Three common investor profiles are below — pick the closest and I'll tweak it with you. Or say 'interview me' if none fit."*

### The three presets

Each preset writes **target** concentration fields. Current concentration (what the portfolio actually looks like today) is captured in question 7 below or progressively on the first portfolio question.

**Presenting presets to the user: read aloud only the bold name and the short plain-English description below it.** Do not narrate YAML field names, enum values, or internal identifiers (e.g., do not say *"goal aggressive_growth, concentration target style focused, max loss probability 45"* — say *"concentrated book, around 10–12 names, up to 20% in any one, targets higher returns, no leverage"*). The YAML-mapping blocks below are for you (the LLM) to use when writing the profile; they are not scripts for the chat.

---

#### Preset 1 — Long-horizon index-plus

*Who it fits (quote back to the user):* "Mostly indexed, a few active bets, long runway. I don't want to trade often."

*Show the user (plain English):* Balanced-growth goal. Diversified — around 20 positions, no single name above 10% of the book. Mostly index-and-ETF with a small active sleeve. No leverage, no options, long-only cash. Standard explanations on every recommendation.

*YAML to write (internal, not narrated):* `goal.primary: balanced_growth`, `concentration.target.style: diversified`, `concentration.target.position_count: 20`, `concentration.target.max_single_position_pct: 10`, `style_lean.primary: passive_plus`, `instruments.long_only_cash: true`, all other instruments `false`, `experience.explanation_depth: standard`, `max_loss_probability: 35`.

---

#### Preset 2 — Active quality compounder

*Who it fits (quote back to the user):* "I pick great businesses, hold for years, concentrated book. Buffett/Munger/Fisher temperament."

*Show the user (plain English):* Targets higher returns than the index by running a concentrated book — around 10–12 holdings, up to 20% in any single name. Quality-bias style. No leverage, no options, long-only cash. Minimal explanations (conclusions first, reasoning on request). Ruin-aversion is set at the higher end reserved for investors who have lived through a real drawdown; until that's documented in your history, Veda will use the conservative cap and explain why.

*YAML to write (internal, not narrated):* `goal.primary: aggressive_growth`, `concentration.target.style: focused`, `concentration.target.position_count: 12`, `concentration.target.max_single_position_pct: 20`, `style_lean.primary: quality`, `instruments.long_only_cash: true`, all other instruments `false`, `experience.explanation_depth: minimal`, `max_loss_probability: 45` (Step 5 rule will downgrade to 35 if behavioral history has no lived drawdown).

---

#### Preset 3 — Macro tactical

*Who it fits (quote back to the user):* "I trade themes and cycles. Shorter holding periods, macro-driven, sometimes use hedges."

*Show the user (plain English):* Balanced-growth goal held through theme and cycle trades — around 15 positions, no single name above 15% of the book. Macro-driven style. Long-only cash by default; options allowed for hedging if you confirm. Minimal explanations.

*Ask the user to confirm hedging before writing it:* *"You said 'sometimes use hedges' — should I enable options for hedging only (not speculation)?"*

*YAML to write (internal, not narrated):* `goal.primary: balanced_growth`, `concentration.target.style: diversified`, `concentration.target.position_count: 15`, `concentration.target.max_single_position_pct: 15`, `style_lean.primary: macro`, `instruments.long_only_cash: true`, `instruments.options_hedging: true` only if the user confirms hedging, all other instruments `false`, `experience.explanation_depth: minimal`, `max_loss_probability: 35`.

### After they pick a preset, ask these seven (not fifteen)

These must be filled upfront because they are load-bearing for safety and calibration. They cannot be lazily captured.

1. **Name + display name.** What should Veda call you?
2. **Age and target retirement age** (or "never retiring"). Derive `effective_horizon_years = target_retirement_age - current_age` (or `30` for "never retiring"; document this assumption in `horizon`).
3. **Primary goal** — confirm or change the preset's default. Pick one: `capital_preservation`, `income`, `balanced_growth`, `aggressive_growth`, `speculation`. *(Calibrates `max_loss_probability` via the rules in After-the-interview.)*
4. **Markets** — multi-select: US / India / Europe / Other developed / Emerging / Crypto / Private. *(Frameworks don't change by geography, but data sources and macro overlays do.)*
5. **Hard constraints** — religious/ethical, employer blacklist, tax regime (country + account types like Roth/PPF/ISA/401k), forced concentration (e.g., unvested RSUs). *(Non-negotiable filters applied before any recommendation.)*
6. **Biggest drawdown lived through, and how you reacted.** *(Self-reported risk tolerance lies. Behavioral history tells the truth. If no drawdown has been lived through, record that explicitly; it caps `max_loss_probability` at 35 regardless of stated goal.)*
7. **Current concentration** — "Roughly how many positions do you hold today, and what's the biggest as a percent of the total? Is today's shape where you want to stay, or are you trying to get somewhere different?" *(Captures `concentration.current.position_count`, `concentration.current.largest_position_pct`, and `concentration.current.style`. If the user says they want a different shape, confirm the preset's target values fit; otherwise adjust them. If current and target differ materially, write a one-line `concentration.glide_notes` summary — e.g., "consolidate 33 → 12 over 18–24 months, no new names unless >3%".)*

### After the six, confirm the preset

Read back the merged profile (preset defaults + user's six answers) in a compact summary. Ask: *"Anything to correct before I save this? Remember: we can also capture more detail lazily during your first real questions — nothing has to be decided now."*

### If the user picks "interview me" instead of a preset

Use the same six questions above, but skip the preset defaults. **Omit** `concentration.current.*`, `concentration.target.*`, `style_lean.primary`, and the `instruments.*` keys entirely from the saved YAML — do not write `TBD` or `null` as placeholders (the validator rejects those for enum fields). Capture them **progressively** during real questions per the next section. Mark the profile `incomplete: true` until the threshold fields (see below) are filled.

---

## Step 4 — Progressive profiling rules (for you, across sessions)

After the upfront interview, the profile is usable but not complete. The remaining fields are captured during real investment questions, at the point each becomes load-bearing. Follow this table. When a trigger fires, ask one question inline, update the profile, and continue with the user's original request.

**The activation hook lives in SKILL.md Stage 1.6 (Progressive profiling check)** — it runs after profile load and before question classification on every decision-track session. This table is the data Stage 1.6 reads; the flow control is there.

**How to detect "first."** "First" means *the field is absent from `profile.md`* — the key is simply not written. Do **not** use `null` or `TBD` as placeholders for enum fields; the validator will reject those at Stage 1 before Stage 1.6 ever runs. If a field is present with any value, treat it as filled. Once the field has a value, the trigger is dormant forever unless the user resets the profile.

**Precedence when multiple triggers fire.** Ask at most **one** progressive-profiling question per turn (design principle: one question at a time). If two or more triggers fire, pick the highest-priority empty field. Priority, high to low:

1. `capital.pct_net_worth_in_market`
2. `concentration.current.position_count` / `concentration.target.position_count` / `concentration.target.style`
3. `instruments.*`
4. `style_lean.primary`
5. `experience.level`
6. `self_identified_weakness`
7. `data_access`

The rest will be captured on later turns as they keep firing.

**Block vs warn.** `capital.pct_net_worth_in_market` is the **only** progressive-profiling field whose absence blocks a specific-rupee/dollar sizing recommendation. If the user refuses to answer, fall back to a range-based answer (*"if this is ≤5% of your net worth… if ≥20%…"*) and proceed. Every other empty field only warns — prepend the incomplete-profile banner (below) to the decision-block output and continue. Principle #3 (never block on non-essential fields) beats calibration on any single output.

**Write-back procedure when the user answers.** Update `profile.md` with the new value. Set `profile_last_updated:` to today. If all completion-threshold fields (below) are now filled, set `incomplete: false`. Re-run `python scripts/validate_profile.py profile.md` before continuing to the main answer. If the validator fails, fix the profile yourself and re-run; do not ask the user to fix YAML.

### Trigger table

| Field | Trigger to ask | Prompt wording |
|---|---|---|
| `capital.pct_net_worth_in_market` | First `buy` / `add` / `size` question involving a specific rupee/dollar amount | *"Before I size this: roughly what fraction of your net worth is already in the market? Ballpark is fine — 20%, 50%, 90%."* |
| `capital.split` (4 buckets, current state) | First `portfolio`-scope question, or first time Veda has to reason about speculation vs core | *"Of what's in the market today, roughly what split between long-term holds, tactical 3–18 month positions, short-term trades, and speculative bets? Must sum to 100."* |
| `capital.target_split` (4 buckets, future state) | When the user's answer to `capital.split` hints at a glide plan (e.g., "speculation is 30% today but I want to bring it down") | *"And what split would you like it to be in, say, 2 years? Must also sum to 100. If it's the same as today, say 'same' and I'll leave it blank."* |
| `concentration.current.position_count` / `current.largest_position_pct` / `current.style` | First sizing question, or first portfolio-scope question, if not elicited at onboarding | *"How many positions do you hold today, and roughly what's the biggest as a percent of the total? Index-like 30+, diversified 15–25, focused 8–15, concentrated under 8."* |
| `concentration.target.position_count` / `target.style` / `target.max_single_position_pct` (if not preset-filled) | Same as above; ask after current | *"Is today's shape where you want to stay, or are you trying to get somewhere different? If different, give me the target."* |
| `concentration.glide_notes` | When current and target differ materially | Write a one-line plan after the target answer — e.g., "consolidate 33 → 12 over 18–24 months, no new names unless >3%." No separate prompt required. |
| `instruments.margin` / `options_*` / `shorts` | First time the user asks about a derivative product, or Veda would recommend a hedge | *"Before I suggest this: do you use margin / options / shorts? One-word answers each."* |
| `style_lean.primary` (if not preset-filled) | First time style would change framework routing (e.g., value vs growth) | *"Which style feels most like you: value, quality, growth, macro, thematic, quant, or passive-plus?"* |
| `style_lean.secondary` | Optional; only ask if the user equivocates between two styles in question #1 | *"You said value but also mentioned quality — should I tag quality as your secondary lean?"* |
| `experience.level` / `years_investing` | First question that would calibrate explanation depth | *"Quick one: roughly how many years have you been actively investing? I'll dial the explanation depth accordingly."* |
| `self_identified_weakness` | First time the user seems to be talking themselves into overriding a framework | *"Before we go further: what decision do you most often screw up in investing? Hold losers too long? Sell winners too early? FOMO buy? I want to flag this at the right moments."* |
| `data_access` | First time Veda asks the user to fetch a number | *"Which data tools do you have? Yahoo Finance, Screener.in, Bloomberg, Seeking Alpha, your broker's research, your own notes?"* |
| `fx_rates.<pair>.rate` / `as_of` / `source` | First time a USD-INR (or any cross-currency) conversion is needed, OR existing `fx_rates.<pair>.as_of` is more than 1 trading day old | *"What's today's USD-INR rate? If you don't know, I'll look it up and cite the source."* Write to the top-level `fx_rates:` block with `rate`, `as_of: YYYY-MM-DD`, and `source`. Re-ask on every new session if stale rather than reusing. See Hard Rule #9 (SKILL.md) and Step 5 below. |
| `notes` | Any time the user volunteers context that doesn't fit elsewhere | Write it to `notes` without asking. |

### Completion threshold — when `incomplete` flips to false

The profile graduates from `incomplete: true` to `incomplete: false` when **all** of the following are filled:

- The 6 upfront fields (disclosure, experience_mode, goal, horizon, markets, hard_constraints — completed in Step 3S or 3N).
- `capital.pct_net_worth_in_market`
- `concentration.current.style`, `concentration.current.position_count`, and at least one `concentration.target.*` field (style or position_count)
- `style_lean.primary`
- `experience.level`
- At least one `instruments.*` field set (even if all false — confirms the user saw the question)

Until then, on every decision-block output, Veda prepends: *"This recommendation is based on an incomplete profile ([list missing fields]). I'll fill the gaps as we go. You can also run `Veda: complete my profile` to finish in one pass."*

### Deep-dive option (for users who want it)

If the user asks *"interview me fully"*, *"ask me everything"*, or *"complete my profile"*, run the full 15-question interview in the appendix below. Do not run it by default.

---

## Step 5 — After the interview (both paths)

1. If any preset defaults or progressive-profiling fills were applied, list them for the user so they know what's provisional vs what they stated.
2. If `experience_mode: novice`, list the active guardrails explicitly.
3. **Derive `max_loss_probability`** from `experience_mode` and `goal.primary`. Rules:
   - `experience_mode: novice` → `15` (always, regardless of goal).
   - `experience_mode: standard` AND `goal.primary` in {`capital_preservation`, `income`} → `25`.
   - `experience_mode: standard` AND `goal.primary: balanced_growth` → `35`.
   - `experience_mode: standard` AND `goal.primary` in {`aggressive_growth`, `speculation`} AND `risk.calibrated_tolerance` is `high` or `very_high` AND `risk.behavioral_history` documents at least one lived drawdown → up to `60`.
   - `experience_mode: standard` AND `goal.primary` in {`aggressive_growth`, `speculation`} but behavioral history does NOT document a lived drawdown → cap at `35` regardless of stated tolerance. State this to the user: *"You asked for aggressive; your behavioral history isn't there yet. Capping max_loss_probability at 35 until you document a real-drawdown reaction in risk.behavioral_history."*
   - The user may request a lower value. They cannot request a value above the derived ceiling.
4. Ask: *"Anything to correct before I save this?"*
5. On confirmation, write the profile to `profile.md` in the workspace root using the schema in [profile.template.md](profile.template.md). **Omit any field you do not have a real value for — do not copy template placeholders like `<int>`, `<string>`, `TBD`, or `null` into the saved file.** The absence of a field is how Stage 1.6 (SKILL.md) knows to capture it progressively later. Set:
   - `generated:` = today's date
   - `profile_last_updated:` = today's date
   - `disclosure_acknowledged:` = `true`
   - `max_loss_probability:` = derived value from step 3
   - `incomplete:` = `true` unless the completion-threshold fields are all filled
   - For novices, also emit the `guardrails:` block.
   - **If the user has mentioned any cross-currency exposure** (e.g., Indian tax resident with USD holdings), write a top-level `fx_rates:` block. Each pair uses the shape `<from_ccy>_<to_ccy>:` with `rate: <float>`, `as_of: YYYY-MM-DD`, and (recommended) `source: "<Tier 1–2 source name>"`. Ask the user for today's rate or fetch it with a citation. **Never carry a rate from memory or a previous session.** If you cannot get a live rate, **do not write the `fx_rates:` block at all** — leave it absent and split the portfolio summary into per-currency totals rather than a single converted number. This is Hard Rule #9 (SKILL.md).
6. **Validate before declaring onboarding complete.** Run `python scripts/validate_profile.py profile.md` and paste the output.
   - If it prints `OK: ... is valid.` — proceed.
   - If it prints validation errors — do not continue. Fix the profile for each error (usually an enum paraphrase, a missing required field, or a capital-split that doesn't sum to 100), re-run the validator, and only continue once it passes. Do not ask the user to manually fix YAML; you made the profile, you fix it.
   - If you do not have terminal access, tell the user: *"Please run `python scripts/validate_profile.py profile.md` in your terminal and paste the output. I won't mark onboarding complete until this passes."*
7. Tell the user: *"Profile saved and validated. Re-run any time with 'Veda: redo onboarding'. If you edit profile.md directly, update `profile_last_updated` and re-run the validator."*
8. **Novice next step:** Suggest *"Ask me 'should I buy a specific stock or just an index fund?' — that's usually where novices start, and the answer is more useful than you think."*
9. **Standard next step:** Suggest *"Ask a real question now. I'll fill in the rest of your profile as we go."*

---

## If the user resists onboarding entirely

Hold firm — but the bar is lower now, because the six-question standard path is already short:

> *"I can't give calibrated advice without knowing whether you're a 35-year-old retiring in 25 years or a 62-year-old retiring next year. The answer is different. It's six quick questions (two minutes) and you can pick a preset instead of answering individually. Want to do it now?"*

If the user still insists on skipping, offer a **minimal profile** — ask only Q0 (experience gate), #2 (age/retirement), #3 (goal), #5 (hard constraints) — and mark `incomplete: true`. The pre-interview disclosure is still mandatory; no profile is written (complete or minimal) without `disclosure_acknowledged: true`. Veda will warn on every recommendation: "This recommendation is based on an incomplete profile. Run 'Veda: complete my profile' when you're ready."

---

## Graduating from novice mode

When a novice-mode user asks *"Veda: review my experience mode"* or *"Can I graduate from novice mode?"*, check the `guardrails.graduation_criteria` list in their profile:

- **All criteria met** → propose graduating to `experience_mode: standard`. Re-ask every field the novice path defaulted rather than elicited, because safety-defaults are not the user's preferences. At minimum re-run the 6 upfront questions for standard mode; capture the rest progressively. Update the profile, regenerate `framework_weights` from the standard derivation table, recompute `max_loss_probability` using the step-3 rules above, set `profile_last_updated:` to today's date, remove the `guardrails:` block, and re-run the validator.
- **Some criteria unmet** → list exactly what's missing. Do not graduate partially. Example: *"Close — you've been investing 2.5 years and have read 2 books. But you haven't lived through a 20%+ drawdown yet. When that happens (and it will), record your actual reaction in `risk.behavioral_history`. Then we can graduate."*

Never auto-graduate. The user must request it explicitly and meet the criteria.

---

## Appendix — Deep-dive interview (optional, on user request only)

Do **not** run this by default. Run it only if the user explicitly says *"interview me fully"*, *"ask me everything"*, or *"complete my profile in one pass"*. Same rules as before — one question at a time, explain why, follow up on vagueness.

### 1. Name + display name.
### 2. Current age, target retirement age.
### 3. What percentage of your net worth is in the market (public equities + bonds + crypto)?
### 4. Of the money that IS in the market, split between core long-term (5+ yrs), tactical (3–18 months), short-term trades (days to weeks), speculation (could go to zero). Must sum to 100.
### 5. Primary goal — one of: `capital_preservation`, `income`, `balanced_growth`, `aggressive_growth`, `speculation`.
### 6. Largest drawdown lived through, and how you reacted.
### 7. Concentration — current AND target. Two parts: (a) "How many positions do you hold today, and roughly what is the biggest as a percent of the total?" → `concentration.current.*`. (b) "How many do you want to hold, and what is the max any single position should be?" → `concentration.target.*`. Buckets for both: index-like 30+, diversified 15–25, focused 8–15, concentrated <8. If current and target differ materially, add a one-line `concentration.glide_notes`.
### 8. Markets (multi-select): US, India, Europe, Other developed, Emerging, Crypto, Private.
### 9. Style lean (one): value, quality, growth, macro, thematic, quant, passive_plus.
### 10. Leverage/derivatives: long-only cash, occasional margin, options for hedging, options for speculation, shorts.
### 11. Hard constraints: religious/ethical, employer blacklist, tax regime (country + accounts), forced concentration, other.
### 12. Experience level: beginner, intermediate, advanced, professional.
### 13. What decision do you most often screw up? (Surfaced inside the devil's-advocate block at decision time when the weakness direction matches the action.)
### 14. What tools/data do you have access to? (Yahoo, Screener.in, Bloomberg, Seeking Alpha, broker research, own notes.)
### 15. Anything else? (Religious views, upcoming liquidity events, family obligations.)

After the full interview, run Step 5 (After the interview) above.
