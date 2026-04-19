# Veda

**Your personal AI investment advisor — structured wisdom from 11 of the greatest investors, as a skill for Copilot, Claude, and Cursor.**

Veda is not a stock tipping service. It does not predict prices. It does not tell you what to buy.

Veda is a **decision framework** that plugs into your AI coding assistant and makes it reason about your investment decisions the way Warren Buffett, Peter Lynch, Stanley Druckenmiller, Howard Marks, Ray Dalio, Seth Klarman, Ed Thorp, John Templeton, Charlie Munger, Philip Fisher, and Nassim Taleb would — calibrated to **your** risk profile, time horizon, and goals.

---

## The three problems of investing

Every active investing decision reduces to one of three questions. Veda is organized around them.

### 1. What to buy, what to sell

*Is this a good business? Is this a bad business? Does the thesis hold or is it broken?*

Answered by the **quality and selection frameworks**: Buffett (wide moats, intrinsic value), Lynch (categorize — Fast Grower vs Stalwart vs Cyclical vs Turnaround), Fisher (scuttlebutt, quality checklist), Munger (inversion — how do I avoid losers?), Klarman (is "cheap" actually a value trap?).

### 2. When to buy, when to sell

*Is now the right time? Is the price right? Has the cycle turned? Is the macro hostile?*

Answered by the **timing and valuation frameworks**: Marks (where are we in the cycle?), Druckenmiller (first loss is the best loss; macro regimes), Templeton (buy at maximum pessimism), Lynch (cyclical inversion — buy at high P/E, sell at low P/E).

### 3. How much — portfolio construction

*How big should this position be? Am I diversified or just owning many of the same bet? Am I about to blow up?*

Answered by the **sizing and portfolio frameworks**: Thorp (Kelly criterion for optimal sizing), Dalio (uncorrelated return streams, correlation as the only free lunch), Taleb (barbell — safe assets + convex lottery bets, avoid the fragile middle), Buffett (concentrated conviction — if your best idea isn't 20%, you don't understand it).

### Why this matters

Most "AI financial advisors" collapse these three problems into one vague answer. They tell you *what* without saying *when*, or *how much* without checking *what*. Veda keeps them separate — because the frameworks that answer each are different, and the mistake of applying a *what* framework to a *when* question is how investors lose money.

When you ask Veda a question, the first thing it does is figure out which of the three problems you're actually asking about — then routes to the right frameworks and applies them **calibrated to your profile** (your horizon, goals, risk tolerance, hard constraints).

No hedging. No "it depends." No "consult a financial advisor." Opinionated, framework-grounded, reproducible.

---

## Contribute

Veda is early and the bottleneck is other investors stress-testing it. If you have read Buffett, Lynch, Druckenmiller, Marks, Dalio, Klarman, Thorp, Templeton, Munger, Fisher, or Taleb carefully — or if you use Veda and it gives you a bad answer — the project gets better when you push back.

Three entry points, by time budget:

- **5 minutes — open an issue.** Veda routed your question to the wrong framework? Onboarding question felt wrong? A framework rule contradicts the source book? File it. Include the question, what Veda said, and what you think it should have said. See [CONTRIBUTING.md](CONTRIBUTING.md#1-issues-highest-value).
- **1 hour — add a worked example.** Real decision you made (or avoided) where a framework helped. Anonymize freely. Use [examples/01-hold-check-winner.md](examples/01-hold-check-winner.md) as the template. These are the highest-leverage documentation in the repo.
- **1 day — ship a framework.** Ten of the eleven frameworks (Buffett, Munger, Fisher, Druckenmiller, Marks, Klarman, Dalio, Thorp, Templeton, Taleb) are unwritten. Pick one you know well, mirror [frameworks/lynch.md](frameworks/lynch.md), cite the source books by page. See [CONTRIBUTING.md](CONTRIBUTING.md#2-framework-edits) for the citation bar.

Other high-value paths: additional broker CSV parsers for [scripts/import_portfolio.py](scripts/import_portfolio.py) (Groww, ICICI Direct, Interactive Brokers, Fidelity), and install docs for assistants not yet covered (Gemini, ChatGPT custom GPTs, local LLMs).

Full guide, voice rules, and what will not be merged: [CONTRIBUTING.md](CONTRIBUTING.md). Conduct expectations: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## What Veda actually is (technically)

Veda is a folder of markdown files. Specifically:

- **Instructions for your AI assistant** on how to reason about investment decisions.
- **A profile of you**, written once during onboarding and re-read every time.
- **A set of decision templates** your assistant fills in so every recommendation is journal-ready.

That's it. No app to install, no server to run, no subscription. You clone the repo, point your AI assistant at it, and Veda becomes part of how that assistant thinks about your investing questions.

---

## Who Veda is for

Veda works for investors across the experience spectrum — novice to professional — but there is **one filter** that decides whether Veda can help you:

> **You have to be willing to spend time becoming a better investor.**

That means reading the occasional book, journaling your decisions, reviewing what went wrong and why, and treating investing as a skill you develop over years. Veda gives you a structured way to do that. It does not replace the work.

If that sounds like unnecessary effort — if you want "just tell me what to buy" — Veda is the wrong tool. For that use case, the honest answer from every investor in [CREDITS.md](CREDITS.md) is the same: **buy a low-cost index fund or an ETF, set up a monthly SIP / DCA, and don't check the price more than quarterly.** That advice is worth more than anything Veda could give you, because it's the one you'll actually execute. Veda is for people who want to go beyond that — and who understand that going beyond comes with homework.

### Novice or expert, the filter is the same

- **Novices** are welcome. Veda has a dedicated novice mode with hard guardrails (no leverage, no options, no concentrated positions) and teaches as you go — every recommendation comes with the framework, a 1-line summary of the principle, and a book reference. Every single-stock buy comes with an index-fund comparison so you learn when the index wins and when a specific stock genuinely beats it. See the [Novice mode](#novice-mode) section below.
- **Intermediate and advanced** investors get the full framework system, weighted by their stated style and calibrated by their stated weakness.
- **Professionals** get conclusions, not explanations. Explanation depth is a profile setting.

What Veda cannot do, for any experience level: make you invest more time than you're willing to. If you don't do the reading, don't journal your decisions, don't review quarterly — the product will still produce advice, but the advice will get worse over time because the profile will drift from reality. Invest the time.

---

## Novice mode

If you tell Veda during onboarding that you're a novice, it switches to a different mode:

- **Shorter interview** (6 questions instead of 15). Unknown fields get safe defaults.
- **Hard guardrails** applied to every recommendation:
  - No single position larger than 8% of portfolio.
  - No leverage, no options, no shorts, no sub-1% speculative "lottery" bets.
  - Every single-stock buy recommendation shows the index-fund alternative side-by-side.
- **Education mode.** Every framework citation includes a 1-line summary and a book reference so you learn the principle, not just the answer.
- **Graduation criteria** are spelled out in your profile. Typical bar: lived through one 20%+ drawdown with documented reaction, 2+ years of investing, read at least 2 of the canon books.

The goal isn't to keep you a novice forever. It's to keep you alive long enough to earn graduation — and to have a journal of well-reasoned decisions by the time you do.

See [setup/profile.example-novice.md](setup/profile.example-novice.md) for a worked example.

---

## What Veda is not

- **Not a data feed.** Veda does not fetch live prices. Your assistant's web tools (if any) do that. Veda reasons over whatever data you or the assistant provides.
- **Not financial advice.** Veda is a reasoning tool. Every recommendation comes with reasoning you can inspect and reject. You are responsible for your own money.
- **Not a replacement for reading the books.** These frameworks are compressed distillations. If Buffett's approach resonates, go read *The Essays of Warren Buffett*. Veda points you at the ideas; it does not replace them.
- **Not a portfolio tracker.** For portfolio-level questions, Veda asks you to paste your holdings (in any format) at the moment they're needed. There's also an optional CSV importer for users who want persistence across sessions — but it's never required. Native broker integration is on the v1.0 roadmap (see [Status](#status)).

---

## What's in the box

Current v0.1 contents:

```
SKILL.md                                 The orchestrator — your assistant's entry point. 9-stage pipeline.
README.md                                This file.
CONTRIBUTING.md                          How to contribute; voice rules; what will not be merged.
CODE_OF_CONDUCT.md                       Contributor Covenant v2.1, adapted.
CREDITS.md                               The investors whose work this scaffolds around.
LICENSE                                  MIT.
frameworks/
  lynch.md                               Reference framework. 10 more (Buffett, Munger, etc.) are coming.
  _template.md                           Starter file mirroring lynch.md's structure. Use this for new frameworks.
routing/
  framework-router.md                    Problem (what/when/how-much) + profile → which frameworks to apply.
setup/
  onboarding.prompt.md                   The interview that produces your profile.
  profile.template.md                    Schema for profile.md.
  profile.example-aggressive.md          Worked example: 32-year-old aggressive-growth investor.
  profile.example-novice.md              Worked example: 24-year-old novice with guardrails.
templates/
  decision-block.md                      EV block + portfolio check + pre-commit block.
examples/
  01-hold-check-winner.md                End-to-end: "should I trim NVDA after 180% run?"
scripts/
  calc.py                                Required. Deterministic math for EV, P(loss), Kelly, PEG, FX, weights-sum. No LLM arithmetic — ever.
  validate_profile.py                    Required at onboarding. Schema-validates profile.md (enums, required fields, novice guardrails).
  import_portfolio.py                    Optional. CSV → portfolio.md converter. Supports Zerodha + generic CSV today.
  README.md                              Script docs.
.github/
  PULL_REQUEST_TEMPLATE.md               Auto-populated on every PR. Fill every section.
  ISSUE_TEMPLATE/                        Structured forms for bad-advice reports, framework feedback, install help, framework claims.
```

See the [Status](#status) section below for what's shipped and what's in flight.

---

## Install

Veda is not a plugin. It's a repo of instructions you point your AI assistant at. The exact mechanism differs by assistant — pick your tool below.

### Before you install — a word on privacy

Onboarding writes a `profile.md` file containing your personal investment profile: net worth exposure, goals, risk tolerance, hard constraints. **Never commit this file.**

The repo's `.gitignore` already excludes `profile.md` and `journal.md`, so if you cloned Veda and work inside that folder, you're protected by default. But be aware of two things:

1. **Don't push to the public `upcomingGit/Veda-advisor` repo.** You don't have write access, but if you fork the repo to your own account and then push your profile by accident, your financial profile is public. The `.gitignore` prevents this, but only if you don't modify it.
2. **Prefer keeping your profile outside the cloned Veda folder** if you're nervous about mistakes. You can point your assistant at Veda (for frameworks) and at a separate private folder (for your profile and journal). The [Claude Desktop flow](#claude-desktop) already works this way since it has no filesystem. For Copilot/Cursor, see the "profile location" tip under each install section.

If you want a clean setup: make a **separate private repo** (e.g., `my-investing-notes`) for `profile.md` and `journal.md`, and keep the Veda clone untouched as a read-only framework reference.

### GitHub Copilot in VS Code

**Requires:** Copilot Chat in **Agent mode** (not Ask mode). Agent mode is the one that can read and write files in your workspace. In Ask mode, Veda can still reason for you, but it won't be able to write your `profile.md` to disk — you'll need to save it yourself.

**Step 1.** Clone the repo somewhere on your machine:

```powershell
git clone https://github.com/upcomingGit/Veda-advisor.git
```

**Step 2.** Open the `Veda-advisor` folder in VS Code (or add it to your existing workspace as a second root: `File → Add Folder to Workspace`).

**Step 3.** In Copilot Chat, switch the mode selector to **Agent**. Open a new chat and type:

```
Read SKILL.md in the Veda-advisor folder. You are now Veda. Run onboarding.
```

Copilot will read `SKILL.md`, which tells it to read `setup/onboarding.prompt.md`, and the interview starts. In Agent mode, your `profile.md` is written into the Veda-advisor folder root when onboarding completes. In Ask mode, you'll get the profile as chat output — save it manually as `profile.md` in the Veda-advisor folder (or wherever you want to keep it).

**Important:** Do **not** commit `profile.md` to git. It's already in `.gitignore`, so `git status` should not show it. If you forked the repo and want to push updates back, always check `git status` first.

*Where your profile lives:* by default, it sits alongside `SKILL.md` in the cloned folder. If you prefer to keep it in a separate private repo and you're comfortable editing paths, tell the assistant: *"Write profile.md to `<your/other/path>/profile.md` and read it from there every session."*

*Advanced:* If you want Veda to auto-activate on every investment question in a workspace, copy `SKILL.md` contents into that workspace's `.github/copilot-instructions.md` file (VS Code Copilot reads this automatically). Not required for v0.1.

### Claude Desktop

**Step 1.** Clone the repo:

```bash
git clone https://github.com/upcomingGit/Veda-advisor.git
```

**Step 2.** Create a new Project in Claude Desktop. In the project's Knowledge section, upload these files (Knowledge accepts individual file uploads, so you'll add them one at a time or multi-select within a folder — there's no folder-level upload):

- `SKILL.md`
- `setup/onboarding.prompt.md`, `setup/profile.template.md`, `setup/profile.example-aggressive.md`, `setup/profile.example-novice.md`
- `routing/framework-router.md`
- `templates/decision-block.md`
- Every file in `frameworks/` (currently just `frameworks/lynch.md`)

*(Claude Desktop can't execute Python, so [scripts/import_portfolio.py](scripts/import_portfolio.py) isn't useful there. If you want portfolio-aware advice in Claude, run the importer locally first and upload the generated `portfolio.md`.)*

**Step 3.** In the project's Custom Instructions, paste: *"You are Veda. Follow SKILL.md on every investment question. Run onboarding if no profile exists in this conversation."*

**Step 4.** Start the conversation with *"Run Veda onboarding"*. Claude will produce your profile inline in chat. **Copy it and save it somewhere private** (your own notes app, a private GitHub repo, a local file) — Claude Desktop doesn't persist arbitrary files for you outside the Project Knowledge store. At the start of each future session, paste your saved profile back in before asking investment questions.

### Cursor

**Step 1.** Clone the repo inside your working directory.

**Step 2.** Either (a) `@`-reference `SKILL.md` at the start of your investment chat, or (b) create a Cursor rule file at `.cursor/rules/veda.mdc` whose body instructs the model to follow `SKILL.md` whenever an investment question is asked. Cursor's MDC rule format is documented in Cursor's own docs — the minimum content is a line like *"When the user asks an investment question, read and follow `SKILL.md` in this workspace."*

**Step 3.** Run onboarding the same way: *"Read SKILL.md. You are Veda. Run onboarding."*

**Important:** Same privacy rule as Copilot — `profile.md` stays uncommitted.

### Any other LLM (ChatGPT, Gemini, etc.)

The repo works with any assistant that can read markdown you paste or reference. Minimum viable setup: copy-paste `SKILL.md` as a system/custom instruction, then paste `setup/onboarding.prompt.md` to start. Save the resulting profile somewhere private and paste it back at the start of each session.

### Connecting your portfolio (fully optional)

Portfolio-level questions — *"am I too concentrated in semis?"*, *"does this new position overlap with what I already own?"*, *"what's my real portfolio heat?"* — need Veda to see your holdings.

**You don't have to do anything up front.** The default workflow is: when Veda needs your holdings, it will ask, and you paste them in any format — a copy from your broker app, a spreadsheet dump, or rough natural language (*"40% NVDA, 15% TSMC, 10% AVGO, rest cash"*). Veda parses whatever you send. No CSV required, no script to run, no markdown to hand-write. After answering, Veda will offer to save those holdings to `portfolio.md` so you don't have to re-paste them next time — you can say no.

**Optional power-user shortcut.** If you trade often and want persistence without pasting, there's a CSV importer:

```powershell
# Export your holdings from Zerodha Kite (or any broker) as a CSV, then:
python scripts/import_portfolio.py zerodha holdings.csv
# Or, for any broker whose CSV has ticker / shares / avg_cost / current_price columns:
python scripts/import_portfolio.py generic my_export.csv
```

The script writes `portfolio.md`. Theses and tags are filled in *lazily* — when you ask Veda about a specific holding, it asks you for the one-line thesis and saves it back. You never batch-fill the whole file.

- `portfolio.md` is gitignored by default. Never commit it.
- Supported brokers today: Zerodha, plus a generic CSV importer.
- More brokers coming in v0.2 (Groww, ICICI Direct, Interactive Brokers, Fidelity).
- Native broker integration via MCP is on the v1.0 roadmap.

See [scripts/README.md](scripts/README.md) for details. Most users can ignore this section and just paste holdings when asked.

---

## Quick start (after install)

1. **Run onboarding.** Type in chat: *"Run Veda onboarding."* The assistant will interview you (about 5 minutes; 2 minutes on the novice path) and write `profile.md`.
2. **Ask an investment question.** Example: *"Veda: should I add to my TSMC position at today's price?"*
3. **Veda will:**
   - Read your profile.
   - Identify which of the three problems you're asking about (what / when / how much).
   - Route to the 2–3 frameworks that apply.
   - Return a recommendation with an expected-value block and a pre-commit block.
4. **Log the decision.** The pre-commit block (thesis, kill criteria, re-evaluate trigger) is designed to be pasted into your investment journal — not git-committed. Keep your journal private.

See [examples/](examples/) for an end-to-end walkthrough ([01-hold-check-winner.md](examples/01-hold-check-winner.md) is the only one shipped in v0.1; more are on the roadmap).

---

## Status

**v0.1 — early preview.** The walking skeleton works end-to-end for one worked example (a hold-check on a winner) with one framework (Lynch).

Shipped:
- Orchestrator (SKILL.md), onboarding (standard + novice paths), profile schema with guardrails, framework router, decision-block template.
- One framework: Lynch.
- Two example profiles: aggressive-growth (standard) and novice-with-guardrails.
- One worked example: hold-check (trim a winner?).
- CSV → portfolio.md importer (`scripts/import_portfolio.py`) with Zerodha + generic parsers — optional; default flow is paste-holdings-inline.
- Privacy defaults: profile.md, journal.md, portfolio.md all gitignored.

Not yet shipped:
- Remaining 10 framework files (Buffett, Munger, Fisher, Druckenmiller, Marks, Klarman, Dalio, Thorp, Templeton, Taleb).
- More example profiles (conservative, income).
- More worked examples (buy, sell-loser, crisis, size-a-bet, novice-index-vs-single-stock).
- Additional broker CSV parsers (Zerodha only today; Groww / ICICI Direct / Interactive Brokers / Fidelity planned for v0.2).
- Subagents referenced in SKILL.md (devil's-advocate, base-rate-researcher, portfolio-parser) are design-stage only — the orchestrator performs their work inline today, with an explicit bridge at each stage.

v1.0 roadmap (further out):
- Native broker integration via MCP. Zerodha already ships an MCP server; Veda would read positions live instead of via CSV re-import.
- Journal replay: retrospective scoring of past decision blocks against realized outcomes to recalibrate `framework_weights` over time.

Follow progress by [watching the repo](https://github.com/upcomingGit/Veda-advisor).

---

## Credits

Built by [Ankur Gupta](https://github.com/upcomingGit). See [CREDITS.md](CREDITS.md) for the investors whose work shaped this — the real thinking is theirs; Veda is just the scaffolding.

## Contributing

See the [Contribute](#contribute) section above for the three entry points (issue / example / framework). Full contribution guide, voice rules, and what will not be merged: [CONTRIBUTING.md](CONTRIBUTING.md). Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE). Use it, fork it, build on it. Attribution appreciated.
