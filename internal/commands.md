# Veda Commands

Full procedure, plan output formats, prompts, and narration for user-invoked administrative commands. Trigger phrases and the dispatch table live in [SKILL.md](../SKILL.md) § "Commands". Commands are distinct from the decision pipeline (Stages 0–9) — they are operations the user triggers explicitly.

---

## `sync` — reconcile holdings sources

Reconciles drift between the three holdings sources: `holdings_registry.csv` (lifecycle), `assets.md` (tactical state), and `holdings/` workspaces (qualitative knowledge).

**Two-turn pattern.** Sync is plan-then-confirm. On the first turn, Veda prints a plan showing all proposed changes. **No changes are applied until the user explicitly confirms.** The plan output ends with clear instructions telling the user what to do next.

**Turn 1 — plan output example:**

```
Sync plan:

Workspaces to scaffold (held tickers without workspaces):
  - nvda (archetype: GROWTH inferred)
  - tsmc (archetype: pending — ambiguous, will ask on apply)

Registry rows to add (held tickers without registry row):
  - nvda
  - tsmc

Orphan workspaces (workspace exists, no registry row):
  - xyz — will prompt for resolution on apply

Status mismatches:
  - (none)

Word-cap breaches (will condense/absorb on apply):
  - holdings/msft/kb.md: 2,340 words (cap 2,000) — condense in place
  - holdings/msft/news/2026-Q1.md: 1,612 words (cap 1,500) — absorb into kb.md
  - holdings/nvda/thesis.md: 612 words (cap 500) — flag for user revision

——————————————————————————————
To apply these changes, say "apply" or "yes".
To cancel, say "cancel" or "no".
```

**Word-cap breach detection.** Sync scans all markdown files in all workspaces that have word caps (kb.md, thesis.md, governance.md, risks.md, disclosures.md, news/*.md, earnings/*.md). YAML files and decision files are excluded. Word count is naive whitespace split (`len(content.split())`). Files exceeding their cap are listed in the plan with the action that will be taken on apply.

**Turn 2 — apply on confirmation.** User says `apply`, `yes`, or `confirm` → Veda executes the plan and narrates each change. User says `cancel`, `no`, or asks a different question → sync aborted, no changes made.

**Orphan resolution (interactive).** For each orphan workspace during apply, prompt:

> *"holdings/xyz/ has no registry row. Options:*
> *  - retire — move to _retired/, add registry row with status=retired*
> *  - add — add registry row with status=active (you hold this)*
> *  - skip — leave as orphan for now (not recommended)*
> *Which?"*

Wait for user response before proceeding to the next orphan.

**Bulk scaffold behavior.** Sync scaffolds all held tickers without workspaces in one pass. Archetypes are inferred where high-confidence — these are scaffolded without prompts. Ambiguous archetypes (marked "pending" in the plan) are prompted one-by-one during apply; they do not block the batch.

**What sync does NOT do:**
- Sync does not touch `assets.md` — tactical state has its own refresh paths (Stage 1.5 patterns 1–4).
- Sync does not proactively retire positions — to retire, the user must explicitly invoke `retire <ticker>`.

Full retirement procedure, reason enum, and registry update rules are in [holdings-schema.md](holdings-schema.md) § "Retirement". Full word-cap and absorption rules are in [holdings-schema.md](holdings-schema.md) § "Word caps and absorption".

---

## `retire <ticker>` — close a position

Retires a workspace and updates the registry. Used when a position is sold or exited.

**Procedure:**

1. **Check registry row exists.** If no registry row exists for `<ticker>`, prompt for `first_acquired` date (required by registry validation) before proceeding. Without a registry row, this is effectively an orphan-retire and the sync-path rules apply.

2. **Prompt for retirement reason** (enum — user picks one):
   - `thesis_broken` — kill criterion triggered, structural thesis failure
   - `rebalance` — sold for portfolio reasons, thesis intact
   - `user_exit` — user-driven sell, no framework trigger
   - `spin_off` — corporate action (position replaced by spin-off)
   - `merge` — corporate action (position absorbed by acquirer)
   - `other` — free text (user provides reason)

3. **Move workspace:** `holdings/<slug>/` → `holdings/_retired/<slug>/`

4. **Update registry row:** set `status=retired`, `last_disposed=<today>`, `reason=<selected>`. If this is an orphan-retire (no prior row), also set `first_acquired` from the prompt in Step 1.

5. **Narrate:**

> *"Retired nvda. Moved holdings/nvda/ to holdings/_retired/nvda/. Registry updated: status=retired, last_disposed=2026-04-24, reason=thesis_broken."*

**Note:** Retirement is distinct from deletion. The workspace is preserved in `_retired/` for historical reference. The decision log remains intact. To permanently delete, the user must manually remove the `_retired/<slug>/` directory.

---

## `refresh portfolio news` — batch news update across all held positions

Invokes the `news-researcher` subagent ([`internal/agents/news-researcher.md`](agents/news-researcher.md)) once per held position, in sequence, to refresh `holdings/<slug>/news/<quarter>.md` for the current calendar quarter. Used when the user wants a quarterly catch-up across the entire portfolio without asking a per-position question.

**Why this is a command, not background work.** Per [ROADMAP.md](../ROADMAP.md) Tier 1.5, Veda is local-first with no scheduler and no daemon. Background polling is deferred to Tier 3 (hosted). Until then, batch news refresh is an explicit user-invoked command.

**Two-turn pattern.** Plan-then-confirm, mirroring `sync`. On the first turn, Veda prints the plan; no subagent invocations happen until the user confirms.

**Turn 1 — plan output example:**

```
Refresh portfolio news plan:

Quarter: 2026-Q2 (calendar)
Held positions: 8 (per holdings_registry.csv where status=active)

Will refresh:
  - msft (US)        — existing news/2026-Q2.md is 12 days old; will refresh
  - nvda (US)        — existing news/2026-Q2.md is 3 days old; SKIP (< 7 days)
  - tsmc (US)        — no news/2026-Q2.md yet; will create
  - aapl (US)        — no news/2026-Q2.md yet; will create
  - reliance (India) — existing news/2026-Q2.md is 8 days old; will refresh
  - hdfcbank (India) — no news/2026-Q2.md yet; will create
  - infy (India)     — existing news/2026-Q2.md is 2 days old; SKIP (< 7 days)
  - tcs (India)      — existing news/2026-Q2.md is 31 days old; will refresh

Will be invoked: 6 subagent calls (5-op web cap each = up to 30 web operations).
Will be skipped: 2 (refreshed within last 7 days).

————————————————————————————
To apply, say "apply" or "yes".
To cancel, say "cancel" or "no".
To refresh a subset, say "apply only <ticker1>, <ticker2>".
To force-refresh skipped tickers too, say "apply all (force)".
```

**Skip threshold.** A position is skipped if its `news/<quarter>.md` file's modification time is < 7 days old. The threshold balances freshness against cost — a portfolio of 20 holdings refreshed daily would burn a lot of web operations for marginal news updates. Tighten or relax with the user's preference.

**Turn 2 — apply on confirmation.** User says `apply`, `yes`, or `confirm` → Veda invokes `news-researcher` once per planned ticker, **in sequence** (not in parallel — keeps the web-operation budget visible to the user, and avoids rate-limit storms on shared RSS feeds). After each invocation, narrate per the subagent's narration rule. After all invocations, emit a final summary line:

> *"Refresh complete. 6 tickers refreshed: 14 material events total (5 STRUCTURAL, 9 TACTICAL), 21 routine filtered. 0 cap breaches. Total web ops: 24/30."*

If any individual subagent invocation returns `status: insufficient_input` or fails completely, log the failure in the summary and continue with the rest — one ticker's failure does not block the batch.

**Forced refresh.** `apply all (force)` overrides the 7-day skip rule and refreshes every active position. Use sparingly — mostly useful right after a major macro event (Fed decision, war, regulatory shock) when the user wants every position re-graded against the new context.

**Subset refresh.** `apply only msft, tsmc` invokes only the named tickers. Useful when the user wants to refresh a specific cohort (e.g., "my US semis only") without the full portfolio cost.

**What this command does NOT do:**
- Does not invoke other per-ticker subagents (`fundamentals-fetcher`, `disclosure-fetcher`, `earnings-grader`). For batch refresh of those, separate commands will exist when needed; until then, `fundamentals-fetcher` and `disclosure-fetcher` are invoked per-question on Stage 3 (with their own freshness gates — latest-stored-quarter for fundamentals, 24-hour mtime for disclosures), and `earnings-grader` is event-driven (when the user pastes a transcript or earnings actuals are released).
- Does not absorb into `kb.md`. If any refreshed `news/<quarter>.md` exceeds the 1,500-word cap, the absorption is performed on the next `sync apply` per the existing word-cap-breach mechanism. The plan output flags any cap breaches discovered after refresh.
- Does not write any positions outside the active cohort (status=retired, status=watching). Only `status=active` positions are refreshed.

---

## The ledger-based views — a shared note

`performance`, `concentration`, and `rebalance` all read the transaction ledger
(`ledger/transactions.jsonl`), not `assets.md`. `assets.md` stays the file the
chat trusts for current positions; these three views are the ledger's job
because they need the dated history (`performance`) or the same replay math
(`concentration`, `rebalance`).

**Run `reconcile` first, every time.** It is fast and offline. If it exits
non-zero, the ledger and `assets.md` disagree — warn the user in one line before
showing the result, then still show it:

> *"Heads up: your ledger and assets.md disagree on 2 name(s) (run `reconcile` for the list). The numbers below come from the ledger, so record any missing trades first."*

**If the ledger is missing or empty,** these views have nothing to compute. Say
so plainly and point to recording trades:

> *"Your ledger is empty, so there is no performance/concentration/proposal to show yet. Tell me your trades as they happen (I bought / I sold ...) and I will record them, or run `python scripts/ledger.py add ...` yourself. See internal/ledger-schema.md."*

**Code execution.** These commands run a Python script. Where you can execute
code, run it and paste the readable output. Where you cannot, emit the exact
command for the user to run and report back (the same two modes as Hard Rule #8).

---

## `performance` — book NAV vs benchmark

Shows how the book is doing against a fair benchmark, run like a mutual fund: a
growth-of-100 line for the book next to a blended Nifty 50 / S&P 500 line.

**Procedure:**

1. Run `reconcile` (shared note above). Warn on disagreement.
2. Run `python scripts/nav.py`. It reads the ledger, fetches prices and the
   exchange rate from yfinance, and writes `nav/nav-series.jsonl`.
3. Surface the latest row in plain language: the book's NAV per unit (a
   growth-of-100 number), the benchmark's, and which is ahead and by how much.
   Name the benchmark as price-return (it leaves out index dividends, so it
   slightly understates the bar). Full contract in [nav-schema.md](nav-schema.md).

> *"Book NAV per unit: 112.4 (up 12.4% since inception). Blended benchmark: 109.1. The book is 3.3 points ahead. Benchmark is price-return, so the real bar is a touch higher. Source: yfinance, <date>."*

**What it does NOT do.** It does not pick stocks, place trades, or judge whether
the book is well-run — it reports the number. It does not change the ledger.

---

## `concentration` — caps check

Shows where the book is concentrated today and whether any single name, sector,
or market is over the limits you set in `internal/caps.json`.

**Procedure:**

1. Run `reconcile` (shared note above). Warn on disagreement.
2. Run `python scripts/concentration.py`. It reads the ledger, each holding's
   `_meta.yaml` for its sector, and `internal/caps.json` for the limits, fetches
   prices and the exchange rate, writes `concentration/snapshot.json`, and prints
   a table.
3. Surface the breaches first, then the clean lines. For each breach, state how
   far over the cap it is and the number to act on. A name with no sector in
   `_meta.yaml` shows as a data gap (`unknown` sector) to fix, not a breach. Full
   contract in [concentration-schema.md](concentration-schema.md).

> *"One breach: NTPC is 12.3% of the book, cap is 10% — about ₹X over. Power sector 24% (cap 25%) is fine. Cash is 8% of the book. Source: yfinance, <date>."*

**What it does NOT do.** It does not trim anything or propose trades — that is
`rebalance`. It does not change the ledger or `assets.md`.

---

## `rebalance` — trade proposal toward targets

Turns your target weights into a list of trades that would move the book toward
them, within a no-trade band, staying inside your caps.

**Procedure:**

1. Run `reconcile` (shared note above). Warn on disagreement.
2. Check `internal/caps.json` has `targets`. If it has none, there is nothing to
   balance toward — offer first-time setup: *"You have no target weights set yet.
   Run `python scripts/rebalance.py --setup` for the plain-language setup, then
   set a target weight per name you want to hold."* Do not invent targets.
3. Run `python scripts/rebalance.py`. It reads the ledger, `_meta.yaml`, and
   `internal/caps.json` (targets, caps, band), fetches prices and the exchange
   rate, writes `rebalance/proposal.json`, and prints a table.
4. Surface the proposed buys and sells, the no-trade band that filtered small
   differences, cash shown as its own target line, and any cap that constrained a
   target. If a cash target is set and the targets do not sum to 100%, surface the
   allocation warning. Full contract in
   [rebalance-schema.md](rebalance-schema.md).

**Restate the hard rule, every time.** This is a proposal, not an order. Nothing
here places or stages a trade. A person reads it, edits it, and only then acts.

> *"Proposal (toward your targets, 2% band): buy 30 NTPC, sell 5 MSFT. Two names inside the band — no trade. This is a proposal, not an order; nothing is placed. When you act, tell me and I will record it. Source: yfinance, <date>."*

**What it does NOT do.** It never trades. It does not decide your targets — you
set those in `internal/caps.json`, including the cash target. It does not change
the ledger.

---

## `reconcile` — ledger vs assets.md

Compares the ledger against `assets.md`, name by name, and reports where they
disagree. Share counts only — no prices, no network. Changes nothing.

This is also the guard the three ledger-based views run before showing a number.

**Procedure:**

1. Run `python scripts/reconcile.py`. It prints a table (market, ticker, ledger
   shares, assets.md shares, status) and a one-line summary, and exits `0` if the
   two books agree, `1` if they disagree, `2` if a file is missing.
2. If they agree, say so in one line. If they disagree, list the names and the
   status (mismatch / in ledger only / in assets only), and point to the fix —
   record the missing trade (which writes both books) or correct whichever file
   is wrong. Full contract in [reconcile-schema.md](reconcile-schema.md).

> *"Your books agree: 6 names match."*
> *"Your books disagree on 1 name: NTPC is 100 in the ledger, 60 in assets.md. Either a sell was recorded in assets.md but not the ledger, or the other way round. Tell me the trade and I will fix both, or correct the wrong file."*

**What it does NOT do.** It does not fix anything — it reports. It does not
compare values or weights, only share counts. Cash is not reconciled — it is a
line-item in `assets.md`, shown as a position by `concentration` and `performance`.

---

## `record` — log an executed trade

The chat proposes; you execute at the broker; then you tell the chat, and it
records the trade in both books so they stay in step. (A future Kite integration
will feed the ledger directly; until then this is how trades land.)

**Procedure:**

1. **Read the trade from the user's words.** Buy or sell, ticker, shares, price,
   date, and market (india / us). Ask for any field that is missing or unclear —
   never guess a price or a share count.
2. **Append to the ledger.** Run `python scripts/ledger.py add --type <buy|sell>
   --date <YYYY-MM-DD> --market <india|us> --currency <INR|USD> --ticker <T>
   --shares <N> --price <P>` (add `--lot-id` on a sell when the user names the
   lot). Contract in [ledger-schema.md](ledger-schema.md).
3. **Update `assets.md`.** Apply the same change to the holdings table as a delta
   edit (Stage 1.5 pattern 2): adjust the share count, recompute the row and the
   `dynamic.*` roll-ups via `scripts/calc.py`. This keeps the file the chat
   trusts current.
4. **Reconcile.** Run `python scripts/reconcile.py` to confirm the two books now
   agree, and say so.
5. **Confirm both writes** in one line.

> *"Recorded: bought 100 NTPC at 350 on 2026-06-03. Ledger line added, assets.md updated, totals recomputed. Reconcile: books agree."*

**Cash matters too.** A buy spends cash and a sell raises it. If the user is
funding the book or withdrawing, record the cash event as well (`--type cash_in`
or `cash_out` with `--amount`, not `--shares`/`--price`), so the NAV pipeline
sees the money-in / money-out timing it needs. Ask if it is unclear whether fresh
cash came in.

**What it does NOT do.** It does not place the trade — you already did, at your
broker. It records what happened. It never invents a price; if the user did not
give one, ask.

---

## `refresh cohort <name>` — pull research data for a cohort

Fills a cohort's research data so the screen has numbers to filter on. This is
the one step that crosses to the Veda-research work: for each name in the cohort
it asks the research agent for that name's fundamentals and writes them under
`screen/data/`. It carries the numbers across and nothing more — it does not
filter or judge. Research gathers; the Advisor filters.

**Procedure:**

1. Confirm the cohort file exists at `internal/cohorts/<name>.json`. If not, tell
   the user to create it (a sector name and the list of tickers, each with the
   archetype label research assigned it). Do not invent the names.
2. Run `python scripts/research_bridge.py --cohort <name>`. It reads the cohort,
   asks Veda-research for each name (the research repository's location is in
   `internal/research.json`), maps each answer into `screen/data/<TICKER>.json`,
   and prints a summary of what it wrote, which names came back with no valuation
   zone, and which failed.
3. Surface that summary in plain language: how many names were refreshed, any
   that failed (and why), and any zone gaps to be aware of. Full contract in
   [screen-schema.md](screen-schema.md).

> *"Refreshed 5 of 6 names in airlines-india. One failed (SPICEJET: no data from research). Two have no valuation zone yet. Run `screen airlines-india` to filter them."*

**What it does NOT do.** It does not filter — that is `screen`. It judges
nothing; the archetype labels are research's call, forwarded as given. It writes
only under `screen/data/`, never the ledger or `assets.md`.

---

## `screen <name>` — filter a cohort

Takes a cohort — the names in one sector — and narrows them to the names that
clear your filters, so research time goes to the few worth a closer read first.
This is research support, not a buy list. It never proposes a trade and it does
not rank the survivors; it lists names for you to read.

**Procedure:**

1. Run `python scripts/screen.py --cohort <name>`. It reads the cohort and each
   name's saved research data under `screen/data/`, applies your filters from
   `internal/screen.json`, writes `screen/<name>.json`, and prints the names that
   cleared the filters.
2. If names come back as data gaps ("no research data"), tell the user to run
   `refresh cohort <name>` first — the screen does not fetch, gathering is the
   bridge's job.
3. Surface the names that cleared the filters, then the excluded names and the
   rule each failed, then any data gaps. Show the valuation beside each name but
   say plainly it is shown, not used to filter — a name can fit more than one
   lens, so the judgment stays with you. Full contract in
   [screen-schema.md](screen-schema.md).

> *"Screened airlines-india on your filters (min return on capital, max debt). Three names cleared: INDIGO, and two others, listed alphabetically. Valuation is shown, not used to filter — INDIGO reads FAIR on the growth lens, CHEAP on the cyclical lens. This lists names to read; it is not a buy list and it does not rank them."*

**What it does NOT do.** It does not fetch research — that is `refresh cohort`. It
does not rank, score, propose a trade, size a position, or set a target. It lists
the names in this cohort that clear your filters, nothing wider. Valuation never
filters; it is shown for you to weigh.

