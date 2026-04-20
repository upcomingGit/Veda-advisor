# Contributing to Veda

Veda is a small, opinionated project. It will stay opinionated. That shapes what contributions fit and what don't.

## Ways to contribute

### 1. Issues (highest value)

If Veda gave you bad advice, classified a question wrong, routed to the wrong frameworks, or the onboarding questions felt off — **open an issue**. Include:

- The exact question you asked.
- Your profile (anonymized — redact numbers if you want).
- What Veda said.
- Why you think it was wrong.
- What you think it should have said.

Short, specific issues beat long speculative ones.

### 2. Framework edits

Each `frameworks/<investor>.md` file is a compressed distillation of a real investor's published thinking. It will be imperfect. If you think a decision rule is wrong, or missing, or overweighted, open a PR with:

- **The specific edit.** Not "rewrite Lynch" — a diff.
- **A source citation.** Book + page, essay + year, interview + date. No citations = no merge.
- **A worked example.** Show a concrete question where the old text gave the wrong answer and the new text gives the right one.

Framework edits without a citation or a worked example will be closed. This is not hostile — it's how the repo stays trustworthy.

### 3. New frameworks

Eight of the eleven investor frameworks (Fisher, Druckenmiller, Marks, Klarman, Dalio, Thorp, Templeton, Taleb) are unwritten. Pick one you know well:

1. Open a claim issue using the [Claim a framework](.github/ISSUE_TEMPLATE/new-framework-claim.yml) template so two people don't duplicate work.
2. Copy [frameworks/_template.md](frameworks/_template.md) to `frameworks/<investor>.md` and fill it in. The template mirrors the section structure of [frameworks/lynch.md](frameworks/lynch.md), which is the reference implementation — read it end-to-end before writing.
3. Open the PR. At least one primary source (a book the investor wrote, or a collection of their letters/essays) is required. Secondary biographies are supplements, not substitutes.

The current 11 investors are the set for v1. Before proposing a 12th, open an issue explaining:

- Why this investor's thinking is not already covered by the existing 11.
- Which question types it answers better than the current frameworks.
- Two worked examples showing differentiated advice.

We will not add Jim Simons, ARK-style thematic investors, or any framework built primarily on backtested returns. Veda is about decision frameworks, not quantitative strategies.

### 4. Worked examples

Examples in `examples/` are the most user-facing documentation. PRs adding real decisions (anonymized to whatever degree you want) are welcome. Use the structure of `examples/01-hold-check-winner.md` as a template.

### 5. Install / setup docs

If you got Veda working in an assistant not currently documented (Gemini, local LLM, ChatGPT with custom GPTs, etc.) — write it up. A short "here's what I did, here's what worked" PR to the README's Install section is high value.

## What will NOT be merged

- **Hedging language.** Any edit that adds "it depends on your risk tolerance," "consult a financial advisor," "past performance is not indicative of future results," "diversification is important" etc. These exist in the world to protect writers from liability, not to help readers make decisions. Veda refuses to hedge by design.
- **Generic financial advice** that doesn't trace to a specific investor's framework. "Always keep 6 months of expenses in cash" may be true, but it's not Veda's job.
- **Market-timing heuristics.** "Buy on RSI < 30, sell on RSI > 70." Rules-based strategies are their own thing — Veda is about decision *frameworks*, not trading systems.
- **Astrology, sentiment-from-social, or other low-signal inputs** as framework primitives.
- **Changes to the three-problem model** (what / when / how much) without a serious written case. That framing is load-bearing.
- **Inline arithmetic in worked examples.** Per SKILL.md Hard Rule #8, every computed number (EV, P(loss), PEG, Kelly, FX, weights) must come from `scripts/calc.py` with the exact invocation shown alongside the number. Worked examples or framework edits that retype a computed number without a `calc_command` trail will be asked to redo them against calc.py.
- **PRs that accidentally include your `profile.md` or `journal.md`.** These are in `.gitignore`. If one slips through, the PR will be closed and you'll be asked to re-open with it removed.

## PR mechanics

1. Fork the repo.
2. Branch: `fix/<short-name>`, `framework/<investor>-<change>`, `example/<name>`, or `docs/<area>`.
3. Make the change.
4. Open the PR. GitHub will auto-populate the description from [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) — fill every section. PRs that leave the template blank, or delete it, will be closed with a request to re-open using it.

PRs typically merge within a week or get specific feedback on what to adjust. If I don't respond in two weeks, ping on the PR.

## Voice

Veda's voice is direct, opinionated, plain-spoken. No emojis. No motivational language. No "great question!" No hedging. Match that in your contributions — including issue titles and PR descriptions. If you're not sure what the voice sounds like, read `SKILL.md` and `frameworks/lynch.md`.

## Licensing

By contributing, you agree that your contribution is licensed under Veda's [MIT license](LICENSE).

## Code of conduct

Be honest, be specific, be useful. Disagreement is welcome; bad-faith argument or personal attacks are not. Issues and PRs that drift into either will be closed without further discussion. Full terms: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
