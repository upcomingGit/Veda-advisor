# rebalance-schema.md — rebalancing proposal (v1)

The rebalancing proposal turns the transaction ledger and your target weights
into a list of trades that would move the book toward those targets. It answers
one question: to reach the weights I want, what should I buy and sell, and how
much.

This is Module 4. It reads Module 1 (the ledger) for what is held, reads each
holding's `_meta.yaml` for its sector, reads `internal/caps.json` for the
targets, the caps, and the no-trade band, and fetches current prices and the
exchange rate from yfinance. It writes one proposal file and prints a readable
table.

`internal/caps.json` is your rebalance plan file. You edit this file directly.
It stores three things: your target weights (`target_weights`), your limits
(`max_per_stock`, `max_per_sector`, `max_per_country`), and your
ignore-small-difference setting (`ignore_drift_below`).

## First-time setup (no JSON editing needed)

If you are new to the system, you do not have to write JSON by hand. Run:

```
python scripts/rebalance.py --setup
```

It asks a few plain-language questions (most in one stock, most in Indian
stocks, most in US stocks, most in one sector, and the ignore-small-differences
band). Every question shows a sensible default in brackets — press Enter to keep
it, or type a number like `10`. You can also accept all the defaults at once
without answering anything. The setup writes `internal/caps.json` for you and
keeps any target weights you have already set. You can run it again any time to
change the rules.

The defaults, if you accept them: 10% most in one stock, 70% in Indian stocks,
50% in US stocks, 30% in one sector, and a 2% ignore-small-differences band.

Setup fills in the rules, not your target weights. To get an actual trade list
you still set a target weight for each stock you want to hold (see below); the
rules are the limits those targets must stay inside.

It is a proposal, not an order. **Nothing here ever places or stages a trade.**
A person reads the proposal, edits it as they see fit, and only then acts. This
is the hard rule: a signal never auto-triggers a buy or sell.

## What a target weight means

A target weight is the share of the whole book value you want a name to hold.
The book value is the rupee value of all holdings plus all cash — the same
denominator the caps use. A target of 0.08 means "I want this name to be eight
percent of the book."

Targets are ceilings' companions, not the same thing. A cap says how large a
name may get; a target says how large you want it to be. The proposal trades
toward the target; the caps stay the limit it must not cross.

Cash is a target like any stock. You set a cash target the same way you set a
stock target — `target_weights.cash` is the share of the book you want to hold in
cash — and the proposal treats it as an equal position: it shows cash on its own
row with its current and target weight, and checks that your stocks plus cash add
up to 100% of the book. When you have not set a cash target, cash is whatever the
stock trades leave over, and the proposal says so on the cash row rather than
assuming the leftover was intended.

## The targets and band in the caps file

`internal/caps.json` carries the targets and the no-trade band alongside the
caps:

```json
{
  "max_per_stock": 0.10,
  "max_per_country": { "india": 0.70, "us": 0.50 },
  "max_per_sector": { "default": 0.30 },
  "ignore_drift_below": 0.02,
  "target_weights": {
    "cash": 0.20,
    "india": { "NTPC": 0.08 },
    "us": { "MSFT": 0.06 }
  }
}
```

- `target_weights` — a target weight per name, grouped by country (`india` or
  `us`) and then by ticker, plus an optional `cash` line for the share of the
  book to hold in cash. Each number is a fraction of the book value. You fill
  these in; they are your mandate.
- `target_weights.cash` — the cash target, treated as an equal position. Optional:
  leave it out and cash is whatever the stock trades leave. When you set it, your
  stock targets plus the cash target should sum to 100% of the book, or the
  proposal warns that part of the book is unallocated or over-allocated.
- `ignore_drift_below` — the no-trade band, as a fraction of the book. A name
  already within this many percentage points of its target is left alone. The
  default is `0.02` (two percentage points). The band stops the proposal from
  churning a name over a small gap, which matches the rule that winners should
  not be trimmed just to rebalance.

Older files may use the terse names (`single_name`, `market`, `sector`,
`rebalance_band`, `targets`). These are still read and mapped onto the current
names automatically, so an existing file keeps working unchanged.

## Where each input comes from

- **Holdings.** Replayed from the ledger up to the proposal date, the same way
  the concentration view does it: buys add shares, sells subtract, splits and
  bonuses rescale, cash flows move cash. Shares of a name are aggregated across
  lots. The split and bonus factors are the same functions the NAV pipeline
  uses, so the modules cannot drift apart on that math.
- **Targets, caps, band.** Read from `internal/caps.json`.
- **Sector.** Read from each holding's `_meta.yaml`, the same scan the
  concentration view uses, so the proposal can check each target against the
  sector cap. A holding whose `_meta.yaml` gives no sector is listed as a data
  gap; its sector cap cannot be checked until that is fixed.
- **Prices and the exchange rate.** From yfinance at run time. The US sleeve is
  valued in rupees at the exchange rate as of the proposal date, the same
  convention the NAV and concentration modules use.

## How a trade is proposed

For each name currently held:

1. **Current weight** = the name's rupee value / book value.
2. **Target weight** = the target from the caps file.
3. **Gap** = target weight − current weight.
4. **No-trade band.** If the gap is smaller than `ignore_drift_below` either way,
   the name is left alone (action `hold`, reason "within band").
5. **Trade value** = gap × book value. A positive gap is a buy; a negative gap
   is a sell.
6. **Trade shares** = trade value / the name's rupee price per share. India
   trades round to whole shares; US trades may be fractional, matching how the
   brokers work. A trade that rounds to zero shares is left alone (action
   `hold`, reason "rounds to zero shares").
7. **Sells are clamped** to the shares held: the proposal never sells more than
   the position. A target of 0 therefore proposes selling the whole position
   (action `sell`, marked "sell all").
8. The rupee amount reported is the rounded share count times the price, so the
   number shown matches the shares actually proposed, not the ideal gap.

### A held name with no target

A name held in the ledger but with no entry in `target_weights` is a **data
gap**. The proposal does not trade it — it never sells a position just because a
target line was forgotten — and lists it for you to fix. This mirrors how the
concentration view treats a missing sector: a gap to close, not a breach to act
on. To deliberately exit a name, write an explicit target of 0; that is the only
way the proposal sells a whole position.

## Checks the proposal runs

- **Targets against caps.** Each target is checked against the caps in the same
  file. A single name's target above `max_per_stock`, a sector's summed targets
  above its sector cap, or a country's summed targets above its country cap is
  reported as a cap warning. The proposal still prints; the warning tells you
  the mandate itself is asking for something the caps forbid.
- **Cash is enough.** The proposal adds up the buys and the sells. If the buys
  need more cash than the sells free plus the cash on hand, it reports a cash
  warning. It does not scale the buys down to fit — that is your call.
- **Targets add up.** When a cash target is set, the proposal checks that your
  stock targets plus the cash target sum to 100% of the book. If they fall short
  or run over, it reports an allocation warning, so an unallocated slice of the
  book is named rather than silently treated as cash.

The proposal does not pick which name to cut when a sector or market is over its
cap. The targets you set are how you express that choice; the cap warning only
tells you when those targets disagree with the limits.

## Stale-data guard

The same guard as the NAV and concentration modules: if any price or the
exchange rate used is more than 7 days older than the proposal date, the
proposal is flagged stale. A stale proposal is still written, but the flag warns
that a number leans on an old quote.

## Output

- **Printed table.** A readable summary to standard output: book value, cash
  share and its target, the no-trade band, the proposed trades sorted by size
  with cash shown as its own row, the totals (rupees to buy, rupees to sell, the
  resulting cash), then any cap warnings, cash warning, allocation warning, and
  data gaps.
- **Proposal file.** `rebalance/proposal.json`, one JSON object with the same
  content in structured form, for the dashboard or another module to read. The
  folder is gitignored, like the ledger, the NAV series, and the concentration
  snapshot, because it reveals the live positions.

Each name row carries: `ticker`, `market`, `sector`, `shares` held, `price`,
`value_inr`, current `weight`, the `target` fraction (or null when missing),
`target_weight`, the `action` (`buy`, `sell`, or `hold`), `trade_shares`,
`trade_inr`, and a short `reason`. Cash is reported alongside as
`cash_value_inr`, `cash_weight`, `cash_target_weight` (or null when unset), and a
`cash_reason`; an `allocation_warning` (or null) flags when stocks plus cash do
not sum to 100%.

## What v1 does not do

- No name picking. It does not search the wider market for ideas. It rebalances
  what you already hold, plus any stock you have set a target for in
  `internal/caps.json` - including watchlist names you do not own yet. A target
  set for a watchlist name shows up as a proposed new-position buy. Deciding
  what to track and what the target should be is a research question: ask Veda
  to help, then set the target here.
- No use chosen for your cash. Cash is a target you set, shown as its own
  position; but what to do with it (park it in gold, an index fund, or leave it)
  is a later module.
- No automatic name picking for an over-cap sector or market. It reports the
  cap warning; you choose where to cut by setting the targets.
- No order placement. It proposes; a person decides and acts.
