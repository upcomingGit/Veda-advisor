# nav-schema.md — NAV and performance pipeline (v1)

The NAV pipeline turns the transaction ledger into the track record: a
month-end series of the book's value per unit, in rupees, next to a fair
benchmark. It reads the ledger and nothing else of its own; prices and the
exchange rate come from yfinance at run time. It writes one series file.

This is Module 2. It reads Module 1 (the ledger). It computes; a person reads
the result and writes the story.

## What "NAV per unit" means and why

The book is run like a mutual fund. Money put in buys units at the current
price per unit; money taken out sells units. The price per unit — the NAV per
unit — moves only with investment performance, never with the timing of money
in or out. This is the only honest number to place next to an index, because
that is exactly how an index and a fund both report.

A worked example. Start the book at a NAV of ₹100 per unit (the starting
number is arbitrary; only the change matters).

| Date   | Event             | Book value | NAV/unit | Units |
|--------|-------------------|-----------:|---------:|------:|
| 1 Jan  | Add ₹1,00,000     | ₹1,00,000  | ₹100     | 1,000 |
| 31 Jan | Holdings rise 10% | ₹1,10,000  | ₹110     | 1,000 |
| 1 Feb  | Add ₹1,10,000     | ₹2,20,000  | ₹110     | 2,000 |
| 28 Feb | Holdings fall 10% | ₹1,98,000  | ₹99      | 2,000 |

The NAV per unit went ₹100 to ₹110 to ₹99, so the book is down 1% over the two
months. That −1% is the performance, whatever money came in along the way.

## Reporting choices (decided)

These were settled before any code. Each is here so a reviewer can object to a
visible choice rather than dig one out of the code.

- **Method.** Unit-based (time-weighted) NAV per unit. The headline number.
- **Reporting currency.** INR. The US sleeve is converted to rupees at the
  exchange rate as of each date.
- **Cadence.** One row per month-end, plus one row for the latest date.
- **Starting NAV per unit.** ₹100, set at inception (the first transaction).
  The NAV per unit is therefore the same as a growth-of-100 line, which makes
  the chart against the benchmark a like-for-like comparison.
- **Benchmark.** India sleeve against Nifty 50 (`^NSEI`); US sleeve against
  S&P 500 (`^GSPC`). Both are price-return indices, not total-return. They
  leave out reinvested dividends, so they understate the true bar by roughly
  the index dividend yield (about 1.2 to 1.5% a year in India, about 1.3% in
  the US). The series file labels them as price-return. A true total-return
  series can be dropped into the benchmark data file later with no code change.
- **US benchmark in rupees.** The S&P 500 level is converted to rupees at each
  date's exchange rate before its return is measured. The US sleeve's NAV moves
  with both the index and the rupee, so its benchmark must move with both too.
  Comparing an INR-reported sleeve to a USD index would be unfair.
- **Blend.** One combined book-vs-benchmark line, where the two sleeve
  benchmarks are weighted by each sleeve's holding value at the start of each
  month. Cash is left out of the benchmark weighting: holding cash is the
  book's own choice, so any drag from it should show as the book trailing the
  benchmark, not be hidden inside the benchmark.

## What the pipeline computes

It replays the ledger in date order and keeps a running state: the open lots
(shares left in each), the cash held in rupees and the cash held in dollars,
and the number of units outstanding.

**On each money-in / money-out event** (`cash_in`, `cash_out`):

- Price the whole book in rupees just before the event (needs prices and the
  exchange rate on that date).
- The NAV per unit is the book value divided by units outstanding.
- `cash_in` issues new units: `amount_in_rupees / nav_per_unit`.
- `cash_out` cancels units: `amount_in_rupees / nav_per_unit`.
- The very first `cash_in`, when the book is empty, sets units at the ₹100
  starting NAV: `units = amount_in_rupees / 100`.

**On each investing event** the units never change; only the assets move:

- `buy`: cash in that currency falls by `shares × price + fees`; a lot is
  created with that many shares.
- `sell`: the named lot's shares fall; cash in that currency rises by
  `shares × price − fees`.
- `dividend`: cash in that currency rises by `amount`. This lifts the NAV,
  which is correct — a dividend is part of the return.
- `split` with ratio `a:b`: every `b` old shares become `a` new shares, so each
  open lot of that ticker has its shares multiplied by `a / b`. (A US 2:1 split
  doubles the shares.)
- `bonus` with ratio `a:b`: `a` free shares are granted for every `b` held, so
  each open lot of that ticker has its shares multiplied by `1 + a / b`. (An
  India 1:1 bonus doubles the shares.)

**On each valuation date** (every month-end, plus the latest date):

- India lots: `shares × price` in rupees.
- US lots: `shares × price` in dollars, then × the exchange rate.
- Cash in rupees: rupee cash plus dollar cash × the exchange rate.
- Book value = India holdings + US holdings + cash, all in rupees.
- NAV per unit = book value ÷ units outstanding.

**Prices on a date** use the last close on or before that date, so weekends and
holidays resolve to the previous trading day. If the newest close available for
a ticker is more than 7 calendar days before the date asked for, that row is
flagged as using a stale price. This is the stale-data guard: the run never
silently reports on prices that are too old.

## The benchmark line

For each step from one valuation date to the next:

- Weights come from the India and US holding values at the start of the step
  (cash excluded). All-cash steps carry a benchmark return of 0.
- Nifty 50 return = end level ÷ start level − 1.
- S&P 500 return in rupees = (end level × end rate) ÷ (start level × start rate)
  − 1.
- Blended return = `india_weight × nifty_return + us_weight × sp500_inr_return`.
- The benchmark line starts at 100 at inception and grows by the blended return
  each step.

The NAV per unit also starts at 100 at inception, so the two lines are directly
comparable: both answer "what would 100 rupees have become."

## Data sources (run time)

- Per-ticker daily closes from yfinance. India tickers are tried as `.NS`
  (NSE), then `.BO` (BSE). US tickers are used as given.
- Nifty 50 from `^NSEI`, S&P 500 from `^GSPC`.
- The exchange rate (USD to INR) from `USDINR=X`.

The arithmetic core takes these as plain lookups, so the tests feed fixed
numbers and never touch the network. Only the command-line run fetches.

## Output

- Path: `nav/nav-series.jsonl`, one JSON object per line, oldest first. Local
  and gitignored, like the ledger.
- One row per month-end plus the latest date. Each row carries:

| field               | meaning                                              |
|---------------------|------------------------------------------------------|
| `date`              | the valuation date, `YYYY-MM-DD`                     |
| `units`             | units outstanding                                    |
| `nav_per_unit`      | book value ÷ units, in rupees                        |
| `book_value_inr`    | total book value in rupees                           |
| `india_value_inr`   | India holdings value in rupees                       |
| `us_value_inr`      | US holdings value in rupees                          |
| `cash_value_inr`    | rupee cash plus dollar cash converted to rupees      |
| `benchmark_indexed` | the blended price-return benchmark, 100 at inception |
| `stale`             | `true` if any price used for the row was stale       |

The NAV per unit is itself the growth-of-100 NAV line (it starts at 100), so no
separate indexed NAV column is stored.

## What is not in v1

- Realized and unrealized profit, and capital-gains tax lots. The ledger keeps
  the specific-lot detail these need; the math is a later module.
- True total-return benchmarks. The hook (a benchmark data file) is left for
  when the series is sourced.
- A money-weighted (XIRR) personal-return footnote. A small later addition.
- Rights and merger corporate actions. Added as ledger types later.

## Checks

`scripts/test_nav.py` runs golden cases with fixed prices and exchange rates,
so the math is pinned and reruns are identical: a single buy held across a
month, a money-in then a market move (the units example above), a sell, a
dividend lifting the NAV, a split and a bonus changing share counts, a two
sleeve book with the exchange rate moving, and the benchmark blend.
