# Veda

**Your personal AI investment advisor — structured wisdom from 11 of the greatest investors, as a skill for Copilot, Claude Code, Cursor, and Gemini.**

Veda is not a stock tipping service. It does not predict prices. It does not tell you what to buy.

Veda is a **decision framework** that plugs into your AI coding assistant and makes it reason about your investment decisions the way Warren Buffett, Peter Lynch, Stanley Druckenmiller, Howard Marks, Ray Dalio, Seth Klarman, Ed Thorp, John Templeton, Charlie Munger, Philip Fisher, and Nassim Taleb would — calibrated to **your** risk profile, time horizon, and goals.

Technically, Veda is a folder of markdown files: instructions for your AI assistant on how to reason about investments, a profile of you written once during onboarding, and decision templates your assistant fills in so every recommendation is journal-ready. No app, no server, no subscription.

---

## The three problems Veda is organized around

Every active investing decision reduces to one of these. Most AI advisors collapse them into one vague answer; Veda keeps them separate because the frameworks that answer each are different, and applying a *what* framework to a *when* question is how investors lose money.

| Problem | Question | Frameworks |
|---|---|---|
| **What** to buy or sell | Good business? Broken thesis? Value trap? | Buffett (moats, intrinsic value), Lynch (categorize), Fisher (scuttlebutt), Munger (inversion), Klarman (margin of safety) |
| **When** to buy or sell | Right cycle? Right price? Macro hostile? | Marks (cycles), Druckenmiller (regimes, first loss is best), Templeton (maximum pessimism), Lynch (cyclical inversion) |
| **How much** to hold | Right size? Real diversification? Blow-up risk? | Thorp (Kelly), Dalio (uncorrelated streams), Taleb (barbell), Buffett (concentrated conviction) |

When you ask Veda a question, it first identifies which of the three problems you're asking about, then routes to the 2–3 frameworks that apply and calibrates them to your profile. Opinionated, framework-grounded, reproducible.

---

## Who Veda is for

Across experience levels — novice to professional — with one filter:

> **You have to be willing to spend time becoming a better investor.** Read the occasional book, journal your decisions, review what went wrong. Veda gives you structure; it does not replace the work.

If you want "just tell me what to buy," Veda is the wrong tool. The honest answer from every investor in [CREDITS.md](CREDITS.md) is the same: **buy a low-cost index fund, set up a monthly SIP / DCA, and don't check the price more than quarterly.** Veda is for people who want to go beyond that and understand that going beyond comes with homework.

**Novice mode.** Tell Veda you''re a novice and it switches to a shorter 6-question interview with hard guardrails: no position larger than 8%, no leverage, no options, no shorts, and every single-stock buy shown side-by-side with the index-fund alternative. Every recommendation includes a 1-line principle and a book reference. Graduation criteria (lived through a 20%+ drawdown, 2+ years invested, read 2 canon books) are written into your profile. See [setup/profile.example-novice.md](setup/profile.example-novice.md).

**Intermediate / advanced** investors get the full framework system weighted by stated style. **Professionals** get conclusions, not explanations — depth is a profile setting.

---

## What Veda is not

- **Not a data feed.** Veda reasons over data you or your assistant''s web tools provide. It does not fetch live prices.
- **Not financial advice.** Every recommendation comes with reasoning you can inspect and reject. You are responsible for your own money.
- **Not a replacement for reading the books.** Frameworks are compressed distillations. If Buffett resonates, go read *The Essays of Warren Buffett*.
- **Not a portfolio tracker.** For portfolio questions, Veda asks you to paste holdings (any format) at the moment they''re needed. An optional CSV importer persists them; native broker integration is on the v1.0 roadmap.

---

## Install

Pick your assistant — each has a native install path. Full instructions, privacy notes, and session-invocation guidance live in [INSTALL.md](INSTALL.md).

| Assistant | Invoke with |
|---|---|
| **GitHub Copilot** (VS Code, Agent mode) | `/veda` |
| **Claude Code** | `/veda` |
| **Gemini** (web Gem) | start a chat with your Veda Gem |
| **Gemini CLI** | `/veda` |
| **Cursor** | `@SKILL.md` or a `.cursor/rules/veda.mdc` rule |
| **ChatGPT / other web chat** | paste `SKILL.md` as a system instruction |

> **Privacy first.** Onboarding writes a `profile.md` containing your personal financial context. It is gitignored by default. Never commit it. See [INSTALL.md](INSTALL.md#before-you-install--a-word-on-privacy).

---

## Quick start

1. **Install.** Clone the repo and wire it into your assistant using [INSTALL.md](INSTALL.md).
2. **Run onboarding.** Invoke `/veda` (or equivalent). The assistant interviews you in about 5 minutes (2 minutes on the novice path) and writes `profile.md`.
3. **Ask an investment question.** Example: *"Veda: should I add to my TSMC position at today''s price?"*

Veda reads your profile, identifies which of the three problems you''re asking about, routes to the 2–3 frameworks that apply, and returns a recommendation with an expected-value block and a pre-commit block (thesis, kill criteria, re-evaluate trigger) you can paste into your journal.

See [examples/01-hold-check-winner.md](examples/01-hold-check-winner.md) for an end-to-end walkthrough.

---

## Contribute

Veda is early. The bottleneck is other investors stress-testing it. Three entry points by time budget:

- **5 minutes — [open an issue](CONTRIBUTING.md#1-issues-highest-value).** Wrong framework routed? Onboarding felt off? A rule contradicts the source book?
- **1 hour — add a worked example.** Real decision where a framework helped. Use [examples/01-hold-check-winner.md](examples/01-hold-check-winner.md) as the template.
- **1 day — ship a framework.** Ten of the eleven are unwritten. Pick one, mirror [frameworks/lynch.md](frameworks/lynch.md), cite by page. See [CONTRIBUTING.md](CONTRIBUTING.md#2-framework-edits).

Full guide and voice rules: [CONTRIBUTING.md](CONTRIBUTING.md). Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## Status

**v0.1 — early preview.** Walking skeleton with one framework (Lynch), one worked example, two profile templates, and install paths for every major assistant. Ten frameworks, more examples, and more broker importers are in flight. [Watch the repo](https://github.com/upcomingGit/Veda-advisor) for progress.

---

## Credits & License

- Started by [Ankur Gupta](https://github.com/upcomingGit). 
- The real thinking is the investors mindset. Veda is scaffolding — see [CREDITS.md](CREDITS.md).
- [MIT Licence](LICENSE). Use it, fork it, build on it. Attribution appreciated.