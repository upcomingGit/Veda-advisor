# Add an Investor Framework

Add a 12th investor with no coding. Output: one markdown file at `frameworks/<investor>.md`, two routing-table entries, one worked example.

Reference: [frameworks/lynch.md](../../frameworks/lynch.md). Skeleton: [frameworks/_template.md](../../frameworks/_template.md). Read both before starting.

## Step 1 — Verify the investor deserves one

Answer in writing. Weak answers → framework will not merge.

1. **Distinct decision style?** One paragraph. *"Generic value investing"* is not distinct — Buffett, Klarman, Munger, and Marks all qualify under that label. Klarman is *value with margin of safety in distressed situations*. Druckenmiller is *macro regime + concentrated bets when the regime is clear*.
2. **Which question types does it answer better than the existing 11?** Be concrete: *"Marks covers cycle awareness; my candidate adds X that Marks does not."*
3. **Primary sources?** A book, a documented set of letters, a transcript collection. Biographies are supplements, not substitutes. No primary source = no merge.

Open a [Claim a framework](../../.github/ISSUE_TEMPLATE/new-framework-claim.yml) issue with the three answers. Prevents duplicate work.

## Step 2 — Copy the template

Create `frameworks/<investor>.md` (lowercase, no spaces). Copy `frameworks/_template.md` into it. Delete the HTML comments after reading them.

## Step 3 — Fill in the sections

Match the depth in `lynch.md` — not longer, not shorter.

### Header and quote

```markdown
# Howard Marks — Risk Is About Permanent Loss, Not Volatility

> *"The biggest risk doesn't reside in volatility. It resides in the possibility of suffering permanent loss."*
> — Howard Marks, *The Most Important Thing*, ch. 5
```

Header: `<Name> — <one-line thesis>`. The thesis is the single sentence that, if true, makes this investor different from every other. Sourced quote.

### When this framework applies

One paragraph answering:

1. Which of the three problems? (what / when / how much — often more than one.)
2. When is this the first framework to reach for vs a supporting one? **What does it explicitly NOT cover?**

The "NOT cover" sentence is the most important in the file. It prevents over-routing.

Lynch example:

> Lynch is the first framework Veda reaches for on any single-name buy, sell, hold, or trim decision. Categorize first, analyze second. Lynch does not size positions (defer to Thorp), does not judge macro (defer to Marks or Druckenmiller), does not handle options or leverage.

### Core principles

4–6 numbered principles. Each one:

- Short heading.
- One sentence stating the rule.
- 2–4 sentences explaining it.
- Primary-source citation.
- Concrete example from the investor's record where possible.

No padding. 4 real principles → ship 4. 8 → you are listing observations; collapse them.

### Decision rules Veda applies

The operational section the orchestrator reads at Stage 6. Structure by question type:

- On `buy` questions
- On `sell` / `hold_check` questions
- On `size` questions (only if your framework speaks to sizing)

Every rule must be executable. Where a number is needed:

- The exact input the user supplies
- Acceptable source (with [tier](../glossary.md#source-tier))
- The `scripts/calc.py` invocation

Reference depth: the PEG section in `lynch.md`.

### What this framework explicitly does NOT do

A bullet list. Be ruthless. Lynch's example:

- Does not size positions (defer to Thorp / Buffett-concentration).
- Does not judge macro timing (defer to Marks / Druckenmiller).
- Does not handle options, leverage, or shorts.
- Does not value asset-light businesses with no clear earnings (defer to Klarman or Buffett).

Empty list → framework is too broad. Re-read Step 1 question 2.

### Interaction with other frameworks

One paragraph per framework yours commonly combines with:

- Which dominates when they conflict?
- What does yours add that the other lacks?

Lynch + Buffett example:

> On `buy`, Lynch's category comes first; Buffett's moat and intrinsic value second. If the category is Cyclical, Buffett's long-hold rule is suspended — Lynch's sell-at-low-P/E rule wins.

### Sources

Numbered bibliography. At least one primary source.

```markdown
1. <Author>. *<Title>*. <Publisher>, <Year>.
2. <Author>. "<Essay or Letter title>." <Publication>, <Date>.
3. <Interviewer>. "<Interview title>." <Outlet>, <Date>. URL if online.
```

Every citation in your decision rules and core principles must trace to an entry here.

## Step 4 — Add to the router

Edit [routing/framework-router.md](../../routing/framework-router.md):

**4a. Framework cluster table.** Add your investor to the row(s) that match the problems it answers.

**4b. Primary routing table.** For each question type, either add to **Conditionally load** with a trigger condition, or (rare) promote to **Always load** — justify in the PR.

Example:

| Question type | Always load | Conditionally load |
|---|---|---|
| `buy` — single name | Lynch + Buffett | Fisher if Fast Grower; **Greenblatt if special-situation** |

Router cap: 4 frameworks per question. If your row exceeds 4, justify why — usually by displacing an existing one for a specific archetype.

**4c. Profile-based adjustment** (if applicable):

```markdown
- **If `style_lean = special_situations`**, elevate Greenblatt above routing defaults on `buy` decisions.
```

## Step 5 — Add to `framework_weights`

Edit [setup/profile.template.md](../../setup/profile.template.md). Default weight 0.05–0.10 for new frameworks (established ones sit at 0.15–0.18).

Also add to [setup/profile.example-novice.md](../../setup/profile.example-novice.md) and [setup/profile.example-aggressive.md](../../setup/profile.example-aggressive.md).

The validator loads the framework list dynamically; no script change needed.

## Step 6 — Write a worked example

This is the highest-value part. A real or realistic question your framework answers materially differently from the existing 11. Copy the structure of [examples/01-hold-check-winner.md](../../examples/01-hold-check-winner.md).

Must show:

- The question.
- All 9 stages narrated, with your framework's verdict in Stage 6.
- A complete decision block.

No worked example, no merge.

## Step 7 — Validate and submit

1. Compare your file side-by-side with `lynch.md` for depth and citation specificity.
2. Run the validator on edited example profiles:

   ```powershell
   python scripts/validate_profile.py setup/profile.example-novice.md
   python scripts/validate_profile.py setup/profile.example-aggressive.md
   ```
3. PR description: question types your framework answers, the two existing frameworks it is closest to and why it is not redundant, and a link to your worked example.

Voice: no hedging, no *"consult a financial advisor"*, cite the book.

## What gets merged

| Merged | Closed |
|---|---|
| Primary sources, clear NOT-cover boundary, worked example | Backtested-returns frameworks (Veda is decision frameworks, not strategies) |
| Distinct style not covered by existing 11 | Hedging language, generic financial advice |
| Concrete inputs and `calc.py` invocations | *"Buffett-style"* without the named investor |
| At least one primary book or letter collection | Technical analysis, sentiment-from-social, astrology |

Not adding: Jim Simons, ARK-style thematic frameworks. Veda is decision frameworks, not quantitative strategies or thematic bets.

## Worked candidate — Joel Greenblatt

- **Distinct style.** Special-situations — spin-offs, merger arb, recapitalizations, restructurings. Magic Formula = high earnings yield (E/EV) + high return on capital. Distinct from Buffett (no special-situation focus), Klarman (broader value, less mechanical), Marks (no situation focus).
- **Primary sources.** *You Can Be a Stock Market Genius* (1997); *The Little Book That Beats the Market* (2005).
- **Question types.** Spin-off `buy` decisions (Buffett does not address spin-offs); systematic value screening.
- **Decision rules.** Magic Formula screen; spin-off setup (parent forced to spin, small-cap, institutional shareholders forced to sell); merger arb sizing.
- **Routing.** Conditionally load on `buy` when situation is `spin_off | merger_arb | restructuring`.
- **Worked example.** A real spin-off (e.g., GE → GE HealthCare) walked through Greenblatt's checklist to a buy / wait / pass.

A focused week, not a weekend.
