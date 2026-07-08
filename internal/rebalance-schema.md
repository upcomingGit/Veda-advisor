# rebalance-schema.md — rebalancing proposal (v1)

The rebalancing proposal turns the transaction ledger and your target weights
into a list of trades that would move the book toward those targets. It answers
one question: to reach the weights I want, what should I buy and sell, and how
much.

This is Module 4. It reads Module 1 (the ledger) for what is held, reads each
holding's `_meta.yaml` for its sector, reads your **limits** from `profile.md`
and your **target weights** from `assets.md`, and fetches current prices and the
exchange rate from yfinance. It writes one proposal file and prints a readable
table.

Where the plan lives (as of the 2026-07 consolidation — there is no `caps.json`):

- **Limits** live in `profile.md`. The single-name ceiling is
  `concentration.target.max_single_position_pct`; the sector cap, the per-market
  (country) caps, and the no-trade band (`ignore_drift_below`) live in the
  `limits:` block. All are percents.
- **Target weights** — the share of the book you want each name to be — live in
  `assets.md > dynamic.target_weights`, grouped by market with an optional
  `cash:` line, also as percents. These are set by portfolio formation (Job 2),
  or edited via chat.

`scripts/concentration.py > load_limits()` reads both and hands the rebalancer a
single caps dict (fractions). Missing limits mean no cap there; a held name with
no target is reported as a data gap, never traded.

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

## The limits (profile.md) and the targets (assets.md)

**Limits** live in `profile.md` as percents. The single-name ceiling is
`concentration.target.max_single_position_pct`; the rest live in the `limits:`
block:

```yaml
# profile.md
concentration:
  target:
    max_single_position_pct: 20   # most in any one stock
limits:
  max_per_sector: 30              # most in any one sector
  max_per_country:                # most in each market
    india: 70
    us: 50
  ignore_drift_below: 2           # the no-trade band
```

**Target weights** live in `assets.md > dynamic.target_weights` as percents,
grouped by market with an optional `cash:` line:

```yaml
# assets.md > dynamic
  target_weights:
    cash: 20
    india: { NTPC: 8 }
    us: { MSFT: 6 }
```

- `target_weights` — a target weight per name, grouped by market (`india` / `us`)
  then ticker, plus an optional `cash` line. Set by portfolio formation (Job 2)
  or edited via chat; they are your mandate.
- `cash` — the cash target, treated as an equal position. Optional: leave it out
  and cash is whatever the stock trades leave. When set, your stock targets plus
  the cash target should sum to 100% of the book, or the proposal warns.
- `ignore_drift_below` — the no-trade band. A name already within this many
  percentage points of its target is left alone (default 2%). The band stops the
  proposal churning a name over a small gap.

`load_limits()` reads both files and converts the percents to fractions.

## Where each input comes from

- **Holdings.** Replayed from the ledger up to the proposal date, the same way
  the concentration view does it: buys add shares, sells subtract, splits and
  bonuses rescale, cash flows move cash. Shares of a name are aggregated across
  lots. The split and bonus factors are the same functions the NAV pipeline
  uses, so the modules cannot drift apart on that math.
- **Targets.** Read from `assets.md > dynamic.target_weights`. **Caps and the
  band.** Read from `profile.md` (`concentration.target.max_single_position_pct`
  plus the `limits:` block), via `load_limits()`.
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
2. **Target weight** = the target from `assets.md > dynamic.target_weights`.
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
  `assets.md > dynamic.target_weights` - including watchlist names you do not own yet. A target
  set for a watchlist name shows up as a proposed new-position buy. Deciding
  what to track and what the target should be is a research question: ask Veda
  to help, then set the target here.
- No use chosen for your cash. Cash is a target you set, shown as its own
  position; but what to do with it (park it in gold, an index fund, or leave it)
  is a later module.
- No automatic name picking for an over-cap sector or market. It reports the
  cap warning; you choose where to cut by setting the targets.
- No order placement. It proposes; a person decides and acts.
