# <Investor Name> — <One-line thesis>

> *"<A single representative quote from the investor, with source.>"*

<!--
This template mirrors the structure of frameworks/lynch.md, which is the reference implementation. Before writing, read lynch.md end-to-end. Every section below is required. Delete these HTML comments before submitting.

Voice rules (enforced in review):
- No hedging. No "it depends." No "consult a financial advisor."
- Every computed number must route through scripts/calc.py. Do not retype arithmetic inline.
- Cite sources inline (book + page, essay + year, letter + year). Every decision rule must trace to a primary source.
- Plain language. No jargon unless defined on first use.
- Match the Lynch file's section depth — not longer, not shorter.
-->

## When this framework applies

<!--
One paragraph. Which of the three problems (what / when / how much) does this answer? Under what conditions is this the first framework Veda should reach for, vs a supporting one? Be explicit about what this framework does NOT cover — that is how Veda avoids overlapping recommendations.
-->

## Core principles

<!--
4–6 numbered principles. Each one:
- Has a short heading.
- Opens with a single sentence stating the rule.
- Explains it in 2–4 sentences.
- Cites a primary source.
- Where possible, includes a concrete example from the investor's actual record.

Do not pad. If you only have 4 real principles, ship 4.
-->

### 1. <Principle name>

<!-- Rule. Explanation. Citation. Example. -->

### 2. <Principle name>

### 3. <Principle name>

### 4. <Principle name>

## Decision rules Veda applies

<!--
This is the operational section. The orchestrator reads this to know what to do. Structure rules by question type.
-->

### On `buy` questions

<!--
Numbered list. Each rule is something Veda can literally execute. Where a rule requires a number (P/E, growth rate, margin of safety), state:
  - the exact input the user must provide,
  - the acceptable source for that input,
  - the calc.py invocation if any math is involved.
See lynch.md's PEG section for the reference depth.
-->

### On `sell` questions

### On `hold` / `trim` questions

### On `size` / `how-much` questions

<!-- Only include if this framework speaks to sizing. Most what-frameworks do not. -->

## What this framework explicitly does NOT do

<!--
Bullet list. Prevents the router from over-calling this framework. Examples for Lynch:
- Does not size positions (defer to Thorp / Buffett-concentration).
- Does not judge macro timing (defer to Marks / Druckenmiller).
- Does not handle options, leverage, or shorts.
-->

## Interaction with other frameworks

<!--
One paragraph per framework this one commonly combines with. Describe the interaction:
- Which framework dominates when they conflict?
- What does this framework add that the other lacks?

Example for Lynch: "Paired with Buffett on `buy` questions, Lynch's category comes first; Buffett's moat and intrinsic value check come second. If the category is Cyclical, Buffett's long-hold rule is suspended — Lynch's sell-at-low-P/E rule wins."
-->

## Sources

<!--
Numbered bibliography. Minimum one primary source. Use a consistent format:
  1. <Author>. *<Title>*. <Publisher>, <Year>. <Edition if relevant>.
  2. <Author>. "<Essay/Letter title>." <Publication>, <Date>.
  3. <Interviewer>. "<Interview title>." <Outlet>, <Date>. URL if online.
-->
