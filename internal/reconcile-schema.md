# reconcile-schema.md — reconcile the ledger against assets.md (v1)

`assets.md` is the file the chat trusts for what you hold today. The ledger
(`ledger/transactions.jsonl`) is the dated record the performance, concentration,
and rebalance modules read. The two can drift apart — a trade recorded in one
place but not the other, or a hand-edit to either file.

This check compares the two, name by name, and reports where they disagree. It
changes nothing: it reads both files and prints a table.

This is the "reconcile on demand" guard named in the venture roadmap. The chat
runs it before trusting any number the ledger-based modules print, and any time
you ask whether the two books match.

## What it compares, and what it does not

- **It compares share counts only.** For each name it asks: does the ledger hold
  the same number of shares as `assets.md`? It does not compare prices, values,
  or weights, so it needs no live prices and no network.
- **It is share-count, not money.** A name can show a `match` here while its
  value in `assets.md` is stale; value freshness is Hard Rule #9's job, not this
  one. This check answers one question: are the two books holding the same
  positions.

## Where each side comes from

- **Ledger side.** The transactions are replayed to the as-of date using the
  same `current_positions` function the concentration view uses, so the two
  modules cannot drift apart on the replay math. A name fully sold (zero shares
  left) is dropped — it is not a holding.
- **assets.md side.** The `## Holdings (equities)` section is read row by row.
  Each `### India (INR)` / `### US (USD)` subsection names the market through its
  currency (INR is `india`, USD is `us`). The ticker and shares columns are read;
  the rest of the row is ignored. Stdlib only — no YAML or markdown library.

## Ticker matching

The ledger stores the bare ticker (`NTPC`); `assets.md` may store the suffixed
form (`NTPC.NS`). Both sides are normalised before matching: upper-cased, with a
trailing exchange suffix (`.NS`, `.BO`, `.BSE`, `.NSE`) dropped. So `NTPC` and
`NTPC.NS` are the same name.

## The four statuses

Every name lands in exactly one:

- **match** — both books hold it, same shares (equal within a tiny tolerance,
  so fractional mutual-fund units do not trip a false mismatch).
- **mismatch** — both books hold it, different shares.
- **in ledger only** — the ledger holds it, `assets.md` does not.
- **in assets only** — `assets.md` holds it, the ledger does not.

## Exit codes

- `0` — the two books agree (every name matches).
- `1` — they disagree (at least one name differs or is in only one book).
- `2` — a file is missing.

The chat reads the exit code: a non-zero code means warn the user before showing
any ledger-based number, because the ledger and the file you trust do not match.

## Running it

```
python scripts/reconcile.py
python scripts/reconcile.py --assets assets.md --file ledger/transactions.jsonl
python scripts/reconcile.py --as-of 2026-03-31
```

It writes nothing. It prints a table and a one-line summary.

## What v1 does not do

- **No money comparison.** Share counts only; cash, values, and weights are out
  of scope. Cash is a line-item in `assets.md` and is shown as a position by the
  `concentration` and `performance` views — it is not part of the books-match check.
- **No fix.** It reports drift; it does not edit either file. Recording the
  missing trade (ledger plus `assets.md` together) or correcting the wrong file
  is a separate, deliberate step.
- **No prices, no network.** Fully offline by design.
