# Framework Router

Given a question's **problem classification** (`what` / `when` / `how_much`) and the user's `profile.md`, select **2–3 frameworks** to apply. Never load all 11.

## The three-problem model

Every investment question maps to one or more of:

1. **What to buy / sell** — is this a good business? Is the thesis intact?
2. **When to buy / sell** — is now the time? Price, cycle, macro.
3. **How much** — position sizing, portfolio construction, correlation.

Frameworks cluster around these. Most questions touch one problem primarily; some touch two (e.g., "should I trim my 20% NVDA position after a 180% run" = partly #2 *when to sell*, partly #3 *too concentrated?*).

## Archetype input

For ticker-specific questions, read the position's `archetype` from `holdings/<instance_key>/_meta.yaml`. The archetype informs conditional routing:

| Archetype | Maps to | Conditional frameworks elevated |
|---|---|---|
| `GROWTH` | Lynch Fast Grower | Fisher (growth quality), Lynch (PEG, earnings growth) |
| `INCOME_VALUE` | Lynch Stalwart / Slow Grower | Buffett (moat, margin of safety), Klarman (value discipline) |
| `TURNAROUND` | Lynch Turnaround | Klarman (margin of safety on distressed), Marks (permanent loss vs volatility) |
| `CYCLICAL` | Lynch Cyclical | Druckenmiller (cycle timing), Marks (second-level thinking on cycle position) |

If no workspace exists or archetype is missing, infer from company profile (per [internal/holdings-schema.md](../internal/holdings-schema.md) § "Archetype inference") and proceed.

## Framework clusters

| Problem | Primary frameworks | What they answer |
|---|---|---|
| **What** | Buffett, Lynch, Fisher, Munger, Klarman | Business quality, moat, category, thesis integrity, value-trap detection |
| **When** | Marks, Druckenmiller, Templeton, Lynch (cyclical rules) | Cycle positioning, macro regime, cyclical inversion, maximum-pessimism timing |
| **How much** | Thorp, Dalio, Taleb, Buffett (concentration) | Kelly sizing, correlation, barbell tail-risk, concentrated-conviction allowance |

Munger is a cross-cutting framework — inversion and bias-detection apply to all three problems. Route Munger whenever the user's self-identified weakness is in play (see profile adjustments below).

## Primary routing table (question type → frameworks)

| Question type | Problem focus | Always load | Conditionally load |
|---|---|---|---|
| `buy` — single name | what (primary), when (secondary) | Lynch (categorize) + Buffett (margin of safety) | Fisher if category = Fast Grower; Marks if market feels frothy (*when*); Klarman if stock appears "cheap" |
| `sell` — single name | what (is thesis broken?) | Munger (inversion: would I buy today?) | Lynch (category-specific sell rules); Druckenmiller (first loss best loss) if thesis broken |
| `size` — how much to allocate | how much | Thorp (Kelly) + Buffett (concentrated conviction) | Taleb if position is speculative (<1% lottery); Dalio if portfolio already correlated |
| `hold_check` — up large, should I trim? | when + how much | Lynch (don't pull flowers) + Fisher (great company rarely sells) | Munger (inversion); Dalio if position has grown to correlation-risk size |
| `hold_check` — down large, should I cut? | what (is thesis broken?) | Druckenmiller (first loss = best loss) + Marks (permanent loss vs volatility) | Klarman (value trap check); Munger (anchoring check) |
| `macro` — should macro override thesis? | when | Druckenmiller (macro matters short-term) + Marks (prepare don't predict) | Dalio (economic machine); Templeton if pessimism is extreme |
| `risk` — is this too risky? | what + how much | Marks (permanent loss) + Thorp (ruin avoidance) | Dalio (correlation); Taleb (tail risk) if leveraged/short-vol |
| `psychology` — am I making an error? | cross-cutting | Munger (always) + Taleb (skin in the game) | — |
| `portfolio` — diversified / concentrated? | how much | Dalio (correlation) + Thorp (sizing) | Buffett (fat pitch test); Marks (cycle positioning) |
| `crisis` — market crashing | when | Templeton (max pessimism) + Buffett (greedy when fearful) | Druckenmiller (macro context); Marks (risk = permanent loss, not paper) |

## Profile-based adjustments

After primary routing, adjust based on profile. **Missing-field rule first:** if a field referenced below is absent from `profile.md` (progressive profiling hasn't captured it yet), **skip that adjustment silently** and do not trigger it. Empty ≠ match. Stage 1.6 will capture the field on a later turn; until then, the primary-routing row stands alone.

- **If `experience_mode: novice`:** routing for options / shorts / margin questions does **not** happen — Stage 2 of SKILL.md blocks those via the structural-equivalence rule before the router runs. For novice `buy` / `hold_check` / `size` questions that do reach the router, elevate Buffett + Munger + Taleb (ruin avoidance) above routing defaults; this mirrors the novice-weighted `framework_weights` set at onboarding.

- **If `self_identified_weakness` matches the situation, always add the counter-framework.**
  - Weakness = "hold losers" → add Druckenmiller to any `hold_check` down situation.
  - Weakness = "sell winners early" → add Munger (inversion: "would I buy today at this price?") to any `hold_check` up situation. Lynch + Fisher are already in the primary route; the additional Munger inversion forces the user to confront whether they'd repurchase at current price.
  - Weakness = "buy on hype" → add Marks (second-level thinking) + Klarman (patience) to any `buy`.
  - Weakness = "panic sell" → add Buffett (rule #1: don't lose money is not "never have paper losses") + Templeton.

- **If `goal = capital_preservation`**, always add Klarman or Marks to buy decisions.
- **If `goal = speculation`**, always add Taleb to size decisions.
- **If `instruments` includes options speculation or shorts**, always add Taleb to risk questions.
- **If `concentration = concentrated` (<8 positions)**, always add Buffett and Thorp to size decisions.
- **If `style_lean = quality`**, elevate Buffett, Munger, Fisher above routing defaults.
- **If `style_lean = macro`**, elevate Druckenmiller, Dalio above routing defaults.
- **If `style_lean = passive_plus`**, elevate Klarman, Marks above routing defaults on `buy` decisions — a passive-plus investor is saying "my default is the index; any single-stock buy must clear a high valuation-discipline bar." Do **not** elevate Fisher or Lynch's growth framings for this style.

## Cap

Never route more than 4 frameworks to a single question. If more qualify, use `framework_weights` from the profile to pick the top 3. If `framework_weights` is absent (incomplete profile), fall back to the ordering in the primary-routing row — "Always load" frameworks win over "Conditionally load" ones.

## Fallback defaults (when no row matches cleanly)

If the question does not cleanly match any row in the primary routing table — even after profile adjustments — use these defaults by dominant problem:

| Dominant problem | Fallback frameworks |
|---|---|
| `what`     | Buffett + Lynch            |
| `when`     | Marks + Druckenmiller      |
| `how_much` | Thorp + Munger             |

When a fallback is used, the orchestrator (Stage 5) must state it explicitly: *"No routing row matched cleanly. Using fallback: [pair]."* This surfaces router gaps so they can be patched in a later update.

## Tie-breaking

When two frameworks give conflicting recommendations:

1. **Default: show the conflict.** Don't synthesize away real disagreement.
2. **If profile horizon is long (>10 years)**, weight: Buffett > Druckenmiller, Lynch > Marks (tactical framers).
3. **If profile horizon is short (<5 years)**, weight: Druckenmiller > Buffett, Marks > Lynch.
4. **If goal is capital preservation**, weight: Klarman, Marks, Taleb > everything.
5. **If goal is aggressive growth or speculation**, weight: Lynch, Fisher, Druckenmiller, Thorp > Klarman, Marks.

## Example

User profile: aggressive growth, focused concentration, self-weakness = "sells winners too early", long horizon.

Question: *"My NVDA position is up 180%. Should I trim?"*

- Primary (hold_check up): Lynch + Fisher
- Profile adjustment (weakness = sells winners): add Fisher (already there), elevate
- Profile adjustment (weakness = sells winners): add Munger (inversion — "would I buy today at this price?")
- Final: **Lynch, Fisher, Munger** (3 frameworks).
- Do NOT load Marks, Klarman, Druckenmiller — not relevant here.
