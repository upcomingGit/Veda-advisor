# ledger-schema.md — transaction ledger (v1)

The ledger is the dated, append-only record of every money event in the
family book: shares bought and sold, cash added and taken out, dividends,
splits, and bonus shares. It is the source data the NAV and performance
pipeline (the next module) reads. Nothing else in the book is the record of
what happened — this file is.

## File

- Path: `ledger/transactions.jsonl`
- Format: one transaction per line, written as a single JSON object (JSONL).
- Append-only: new transactions are added at the end. Lines are never edited
  or removed. A mistake is fixed by adding a correcting transaction, not by
  changing an old line.
- Order: lines are kept in the order they were added. The `date` field on each
  line is the record of when the event happened, so the chronological history
  lives inside the file itself.
- Privacy: the file is local and gitignored, like `assets.md`. It is not
  committed.

## Transaction types

| type       | meaning                                  |
|------------|------------------------------------------|
| `buy`      | bought shares; creates a lot             |
| `sell`     | sold shares; names the lot it sells from |
| `cash_in`  | money added to the book                  |
| `cash_out` | money taken out of the book              |
| `dividend` | cash received from a holding             |
| `split`    | share count changes by a ratio           |
| `bonus`    | free extra shares, given at a ratio      |

Merger and rights events are not in v1. They are added later as new types in
this same file, with no change to the existing lines.

## Fields

Each line carries only the fields its type needs. Common fields are on every
line.

| field      | type   | used by                          | meaning                                            |
|------------|--------|----------------------------------|----------------------------------------------------|
| `id`       | string | all                              | auto id, like `tx-00001`; unique; set on add       |
| `date`     | string | all                              | `YYYY-MM-DD`, the day the event happened           |
| `type`     | string | all                              | one of the types above                             |
| `market`   | string | all                              | `india` or `us`                                    |
| `currency` | string | all                              | `INR` or `USD`                                      |
| `ticker`   | string | buy, sell, dividend, split, bonus| the holding, e.g. `NTPC`, `MSFT`                   |
| `shares`   | number | buy, sell                        | number of shares; greater than 0                   |
| `price`    | number | buy, sell                        | price per share; greater than 0                    |
| `fees`     | number | buy, sell (optional)             | charges; 0 or more                                 |
| `amount`   | number | cash_in, cash_out, dividend      | cash moved; greater than 0                         |
| `lot_id`   | string | buy, sell                        | a buy makes a lot id; a sell names the lot to sell |
| `ratio`    | string | split, bonus                     | like `2:1` (two whole numbers, both greater than 0)|
| `note`     | string | all (optional)                   | free text                                          |

### Lot ids and specific-lot accounting

Cost basis is tracked by specific lot. Every `buy` creates one lot with its own
`lot_id`. The id is made from the ticker and date, like `ntpc-2026-06-03-1`. If
two buys of the same ticker happen on the same day, the trailing number tells
them apart (`-1`, `-2`).

A `sell` names the `lot_id` it sells from. One sell line sells from one lot. If
a sale draws down two lots, record it as two sell lines, one per lot. This keeps
the lot history exact, which India long-term and short-term capital-gains tax
needs.

The profit and tax math is not done here. It is done in the next module, which
reads this file. v1 only records, loads, and validates transactions.

## Validation

`scripts/validate_ledger.py` checks the whole file. It confirms:

- every line is valid JSON,
- `type`, `market`, and `currency` hold allowed values,
- `date` is a real date in `YYYY-MM-DD` form,
- each type has the fields it needs and no required number is missing,
- `shares`, `price`, and `amount` are greater than 0; `fees` is 0 or more,
- `ratio` is two whole numbers greater than 0, like `2:1`,
- every `id` is unique, and every buy `lot_id` is unique,
- every `sell` names a `lot_id` that an earlier `buy` created.

Exit codes: `0` valid, `1` invalid (reasons printed), `2` file missing.

## Adding transactions

`scripts/ledger.py` adds one transaction at a time. It sets the `id`, and for a
`buy` it sets the `lot_id` if one is not given. It checks the single
transaction before writing it. Both hand entry and the Kite import use this same
add step, so everything that enters the ledger is checked the same way.
