# concentration-schema.md — concentration and caps view (v1)

The concentration view turns the transaction ledger into a snapshot of where
the book is concentrated today, and checks each position against the limits you
set. It answers one question: is any single name, sector, or market larger than
the mandate allows, and if so, by how much.

This is Module 3. It reads Module 1 (the ledger) for what is held, reads each
holding's `_meta.yaml` for its sector, reads the limits from `profile.md`
(`concentration.target.max_single_position_pct` plus the `limits:` block), and
fetches current prices and the exchange rate from yfinance. It writes one
snapshot file and prints a readable table.

It is a current snapshot, not a time series. It says where the book stands now.

## What "weight" means here

Every weight uses the same denominator: the total book value, which is the
rupee value of all holdings plus all cash. Cash is part of the book, so holding
cash lowers every position's weight. This is deliberate — a name is only risky
in proportion to the whole book, idle cash included.

- **Single-name weight** = that holding's value / total book value.
- **Sector weight** = the summed value of every holding in that sector / total
  book value.
- **Market weight** = the summed value of holdings in that market (india or us)
  / total book value. Cash is left out of the numerator and shown on its own
  line as the uninvested share. A market weight is the invested exposure to that
  geography, not a claim about where the cash would go.

The US sleeve is valued in rupees at the exchange rate as of the snapshot date,
the same convention the NAV pipeline uses.

## Where each input comes from

- **Holdings.** Replayed from the ledger up to the snapshot date: buys add
  shares, sells subtract, splits and bonuses rescale, and cash flows move cash.
  Shares of a name are aggregated across its lots; the view does not care which
  lot, only the total held. The split and bonus factors are the same functions
  the NAV pipeline uses, so the two modules cannot drift apart on that math.
- **Sector.** Read from each holding's `_meta.yaml`, which carries a `ticker`,
  a `market`, and a `sector` field. The view scans every `holdings/*/_meta.yaml`
  and builds a map keyed by `(market, ticker)`. The ledger writes the market as
  `india` or `us`; `_meta.yaml` writes it as `IN` or `US`, so the view
  normalises `IN` to `india` and `US` to `us` before matching. A ticker the
  ledger holds but the map does not cover gets the sector `unknown` and is
  listed as a data gap. The sector is never guessed from a folder name or from
  prose.
- **Caps.** Read from `profile.md` — the single-name ceiling from
  `concentration.target.max_single_position_pct`, the sector and country caps
  from the `limits:` block. See the schema below.

## The limits

The limits live in `profile.md` as percents (20 means twenty percent). The
single-name ceiling is `concentration.target.max_single_position_pct`; the rest
live in the `limits:` block. `load_limits()` reads them and converts to fractions.

```yaml
# profile.md
concentration:
  target:
    max_single_position_pct: 20   # the largest share any single stock may be
limits:
  max_per_sector: 30              # default cap for any one sector
  max_per_country:                # a cap per market; a market with no entry has no cap
    india: 70
    us: 50
```

- `max_single_position_pct` — one number that applies to every holding: the
  largest share any single stock may be.
- `max_per_country` — a cap per market. A market with no entry has no cap and
  is reported without a breach test.
- `max_per_sector` — a default cap for any known sector (write it as a mapping
  with per-sector overrides if you need them). The `unknown` sector is never
  capped; it is a data gap to fix by adding the missing `_meta.yaml`, not a breach.

A JSON file is used rather than YAML so the nested sector and country maps parse
with the standard library and nothing has to be hand-read.

## What a breach reports

A position breaches when its weight is above its cap. The view reports the
weight, the cap, the gap, and a number to act on.

- **Single name.** The trim is exact: sell `value - cap x book` worth of the
  name. This assumes the sale proceeds stay in the book as cash, so the total
  book value does not change and the name's new weight lands on the cap. The
  view also gives the trim in shares, using the current price. If you instead
  withdrew the proceeds, the book would shrink and the math would differ; v1
  assumes proceeds stay in.
- **Sector and market.** The view reports the overage, `value - cap x book`,
  but does not pick which name to cut — that is a judgement call across the
  names in the sector or market. The number tells you how much to take out of
  the group; you choose where.

## Stale-data guard

The same guard as the NAV pipeline: if any price or the exchange rate used is
more than 7 days older than the snapshot date, the snapshot is flagged stale.
A stale snapshot is still written, but the flag warns that a number leans on an
old quote.

## Output

- **Printed table.** A readable summary to standard output: book value, cash
  share, the names sorted by weight with breaches marked, then the sector and
  market rollups, then any data gaps.
- **Snapshot file.** `concentration/snapshot.json`, one JSON object with the
  same content as the table in structured form, for the dashboard or another
  module to read. The folder is gitignored, like the ledger and the NAV series,
  because it reveals the live positions.

## What v1 does not do

- No time series. It is today's snapshot only; drift over time is a later
  module if it is wanted.
- No automatic rebalancing. It reports overages; it does not place or stage
  trades. Rebalancing is the next module in the dependency line.
- No look-through. A holding counts in its own sector and market only; it does
  not decompose a fund or a holding company into underlying exposures.
- No currency dimension. Single name, sector, and market are checked; a
  separate INR-versus-USD currency cap can be added later if the market split
  proves too coarse.
