# Veda

[![version](https://img.shields.io/badge/version-0.1.0-blue)](CHANGELOG.md) [![license](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

**The world's greatest investors, at your fingertips. Veda is an AI-powered Investment Advisor chat interface that brings back the thinking of the world's greatest investors and applies that thinking to your personalised situations and money problems.**

Veda thinks like the top 11 investors: Buffett, Lynch, Druckenmiller, Marks, Dalio, Klarman, Thorp, Templeton, Munger, Fisher, and Taleb. It applies their frameworks to your money decisions — what to buy or sell, when to buy or sell, how much to hold — tailored to your profile. The full playbook lives in [SKILL.md](SKILL.md) at the repo root.

To run Veda, you need to install it in a code assistant (VS Code with GitHub Copilot, Google Antigravity, Claude Code, Cursor) or use it in an AI web interface (Gemini, ChatGPT - although the experience in a chat interface will be severly limited). It runs on a folder of text files in this repo — no server, no data sale, no cut when you trade.

Every answer names the investor whose rule was used, walks you through the reasoning, and says what would prove the idea wrong. Save it, come back in six months, and see if it worked. Your decisions build a record you can learn from.

---

## The three problems every investment decision reduces to

Veda operates on the principle that all investing can be reduced to three core problems — what to buy, when to buy, and how much to hold (capital allocation). Veda analyses the question you asked, and applies the right frameworks from the right investors so that you get an idea of how you can proceed in your specific situation.

| Problem | Question | Frameworks |
|---|---|---|
| **What** to buy or sell | Good business? Broken thesis? Value trap? | Buffett (moats, intrinsic value), Lynch (categorize), Fisher (scuttlebutt), Munger (inversion), Klarman (margin of safety) |
| **When** to buy or sell | Right cycle? Right price? Macro hostile? | Marks (cycles), Druckenmiller (regimes, first loss is best), Templeton (maximum pessimism), Lynch (cyclical inversion) |
| **How much** to hold | Right size? Real diversification? Blow-up risk? | Thorp (Kelly), Dalio (uncorrelated streams), Taleb (barbell), Buffett (concentrated conviction) |

---

## Who Veda is for

Veda is for everyone who wants to become a better investor by learning to think like the best. The frameworks are timeless, but the application is personalised. Your profile (style, markets, constraints, experience) shapes how Veda applies the frameworks to your questions.

Whether you are a professional or a novice, Veda works for both situations with one filter:

> **You have to be willing to do the work.** Read the occasional book, journal your decisions, review what went wrong. Veda gives you structure; it does not replace the thinking.

If what you want is "just tell me what to buy," Veda is the wrong tool — and the honest answer from every investor in [CREDITS.md](CREDITS.md) is the same: **buy a low-cost index fund, set up a monthly SIP or DCA, and don't check the price more than quarterly.** Veda is for people who have decided to go beyond that and accept that going beyond comes with homework.

**Novice mode** swaps in a 6-question interview and hard guardrails: no position larger than 8%, no leverage, no options, no shorts, and every single-stock buy shown side-by-side with the index-fund alternative. Graduation criteria (lived through a 20%+ drawdown, 2+ years invested, read 2 canon books) are written into your profile. See [setup/profile.example-novice.md](setup/profile.example-novice.md).

**Intermediate and advanced** investors get the full framework system weighted by stated style. **Professionals** get conclusions, not explanations — depth is a profile setting.

---

## What Veda is not

- **Not a stock tipper.** Veda does not predict prices, name winners, or promise outperformance. It makes the reasoning behind your decisions explicit and auditable.
- **Not financial advice.** Every recommendation comes with reasoning you can inspect and reject. You are responsible for your own money.
- **Not a replacement for reading the books.** Frameworks are compressed distillations. If Buffett resonates, go read *The Essays of Warren Buffett*.
- **Not a Bloomberg replacement.** Veda is a reasoning layer over data you (or your assistant) provide. Live quotes and FX are an optional add-on via `yfinance`; full live-data integration is on the [roadmap](ROADMAP.md), not in v0.1.

## Why Veda vs the alternatives

| If you are using… | What Veda adds |
|---|---|
| **Plain ChatGPT / Gemini for stock questions** | Forces a named investor framework on every recommendation, refuses negative-EV trades, blocks LLM arithmetic, never uses stale prices. The same question on plain ChatGPT will give you a different confident answer every session. |
| **Reading the canon yourself** | Routes the right framework to the right question (Marks for cycles, Lynch for categorising, Munger when you are about to sell a winner) instead of asking you to remember which one applies. Books stay essential — Veda is the application layer. |
| **A paid robo-adviser or RIA** | You see and audit every rule. No commission conflicts. No 100bps fee. Trade-off: you do the journaling and the reading; Veda does the discipline. |
| **A Bloomberg terminal** | Veda is a complement, not a substitute. Use Bloomberg for data; use Veda for reasoning over that data with named-source discipline. |

---

## How Veda remembers

Every position you hold gets a folder under `holdings/<ticker>/` — its **company workspace**. This is Veda's institutional memory: thesis, knowledge base, kill criteria, quarterly fundamentals, valuation zone, full append-only decision log. Once populated, the workspace is the **primary** source for that name — not ad-hoc web search — so Veda does not contradict itself across sessions. Schema details: [docs/capabilities.md](docs/capabilities.md).

---

## Install

Veda runs inside whichever AI assistant you point it at. Pick yours — each has a native install path. Full instructions, privacy notes, and per-surface trade-offs live in [INSTALL.md](INSTALL.md).

| Assistant | Invoke with |
|---|---|
| **GitHub Copilot** (VS Code, Agent mode) | `/veda` |
| **Claude Code** | `/veda` |
| **Google Antigravity** | `/veda` (or `AGENTS.md` shim — [setup](INSTALL.md#google-antigravity)) |
| **Cursor** | `@SKILL.md` or a `.cursor/rules/veda.mdc` rule |
| **Gemini** (web Gem) | start a chat with your Veda Gem ([setup needs a shim + Knowledge upload](INSTALL.md#gemini-web)) |
| **Gemini CLI** | `/veda` |
| **ChatGPT** (web, Plus/Pro/Team/Business) | start a chat with your Veda GPT ([setup as Custom GPT or Project](INSTALL.md#chatgpt-web)) |
| **Other web chat** (Claude web, Perplexity, Grok) | paste `SKILL.md` as a system instruction |

Full capability differs by assistant (filesystem access, Python execution for the math layer, isolated subagents). Web chats work but with reduced capability — see the trade-off table in [docs/capabilities.md](docs/capabilities.md#where-veda-runs).

> **Privacy first.** Onboarding writes a `profile.md` containing your personal financial context. It is gitignored by default. Never commit it. See [INSTALL.md](INSTALL.md#before-you-install--a-word-on-privacy).

---

## Quick start

1. **Install.** Clone the repo and wire it into your assistant using [INSTALL.md](INSTALL.md).
2. **(Optional) Enable live quotes.** Run `python -m pip install -r requirements.txt` if you want Veda to pull live prices and FX rates. Skip this if you're happy pasting prices yourself — every other feature still works.
3. **Run onboarding.** Invoke `/veda` (or equivalent). The assistant interviews you in about 5 minutes (2 minutes on the novice path) and writes `profile.md`.
4. **Ask an investment question.** Example: *"Veda: should I add to my TSMC position at today's price?"*

Veda reads your profile, identifies which of the three problems you're asking about, routes to the 2–3 frameworks that apply, and returns a recommendation with an expected-value block and a pre-commit block (thesis, kill criteria, re-evaluate trigger) you can paste into your journal.

See [examples/01-hold-check-winner.md](examples/01-hold-check-winner.md) for an end-to-end walkthrough.

---

## Documentation

Plain-English guides written for finance people, not coders. Start at [docs/README.md](docs/README.md) — it is the documentation hub. The most useful pages:

| Page | Read this if you want to |
|---|---|
| [What Veda can do today](docs/capabilities.md) | See the actual capabilities list — what is shipped, what is not, where the limits are. |
| [How Veda thinks](docs/how-veda-thinks.md) | Walk through the 9 stages Veda runs every question, in plain English. |
| [Customize Veda for you](docs/customization.md) | Tune your profile, framework weights, guardrails, hard constraints, markets. |
| [Glossary](docs/glossary.md) | Look up any term Veda uses (PEG, EV, Kelly, archetype, kill criterion, base rate). |
| [FAQ](docs/faq.md) and [Troubleshooting](docs/troubleshooting.md) | Common questions and common fixes. |
| [Extending Veda](docs/extending/README.md) | Add your own framework, broker importer, calculator, or specialist worker. |

For the full orchestrator playbook (long, dense, technical), read [SKILL.md](SKILL.md). For strategic direction across roadmap tiers, read [ROADMAP.md](ROADMAP.md).

---

## Contribute

Veda is early. The bottleneck is other investors stress-testing it. Three entry points by time budget:

- **5 minutes — [open an issue](CONTRIBUTING.md#1-issues-highest-value).** Wrong framework routed? Onboarding felt off? A rule contradicts the source book?
- **1 hour — add a worked example.** Real decision where a framework helped. Use [examples/01-hold-check-winner.md](examples/01-hold-check-winner.md) as the template.
- **1 day — deepen a framework.** All eleven are shipped, but each is a working draft. Pick one, mirror [frameworks/lynch.md](frameworks/lynch.md), deepen citations by page, add worked examples. See [CONTRIBUTING.md](CONTRIBUTING.md#2-framework-edits).

Full guide and voice rules: [CONTRIBUTING.md](CONTRIBUTING.md). Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## Status

**v0.1 — early preview.** Walking skeleton with all eleven frameworks shipped (Lynch is the reference implementation; Buffett, Munger, Fisher, Druckenmiller, Marks, Klarman, Thorp, Dalio, Templeton, and Taleb ship alongside it), four shipped subagents (devil's advocate, portfolio parser, company KB builder, fundamentals fetcher), one worked example, a profile template with two worked examples (aggressive and novice), the [docs/](docs/) hub for users and contributors, and install paths for every major assistant. More worked examples, deeper per-framework citations, and more broker importers are in flight.

---

## Credits & License

- Started by [Ankur Gupta](https://github.com/upcomingGit). 
- The real thinking is the investors' mindset. Veda is scaffolding — see [CREDITS.md](CREDITS.md).
- [MIT Licence](LICENSE). Use it, fork it, build on it. Attribution appreciated.
