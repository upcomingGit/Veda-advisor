# portfolio.md — schema and writing rules (reference)

This file is loaded on demand by SKILL.md Stage 1.5 when holdings need to be persisted. Both inline writes (LLM parsing a pasted list) and the output of [scripts/import_portfolio.py](../scripts/import_portfolio.py) must conform to this schema so either source reads cleanly in the next session.

---

## Template

```markdown
# Portfolio

**As of:** YYYY-MM-DD

<!--
This file is gitignored by default. Do not commit it.
Veda re-reads it on every portfolio-level question.
-->

## Holdings

| ticker | name | shares | avg_cost | current_price | current_value | sector | thesis | tags |
|---|---|---:|---:|---:|---:|---|---|---|
| NVDA | NVIDIA | 50 | 420.00 | 890.00 | 44,500.00 | Semiconductors | _(add thesis)_ | core |
| ... | | | | | | | | |

**Total holdings value:** 123,456.78
**Cash:** _(update manually)_

## Watchlist / open orders

- _(tickers you're tracking but don't own yet, with trigger conditions)_

## Sector caps (optional)

- _(e.g., Semiconductors <= 30%, Financials <= 25%)_

## Notes

- _(tax lots, wash-sale windows, upcoming rebalance dates)_
```

## Writing rules

1. **Sort rows by `current_value` descending.** Largest position at the top. Matches the importer.
2. **Numeric columns use thousand separators and 2 decimal places** (`44,500.00`), *except* `shares` which uses a bare number with no trailing zeros (`50`, `12.5`, not `50.00`). Matches the importer's `{:,.2f}` and `{:g}` formats.
3. **Mandatory columns: `ticker`, `shares`, `avg_cost`, `current_price`, `current_value`.** If the user's paste is missing `avg_cost` or `current_price`, write the row anyway with the missing value as `TBD_fetch` — do not guess, do not drop the row. Flag the gaps once at the end of the response: *"I left avg_cost as TBD_fetch for AAPL, MSFT — paste or ask me to fetch before the next portfolio question."*
4. **Optional columns default to `-` (sector) or `_(add thesis)_` / `_(core/tactical/speculation)_` placeholders.** Do not invent a thesis or a tag the user did not state.
5. **Stamp `**As of:** YYYY-MM-DD`** with today's date at the top.
6. **Never mix currencies in the same table.** If the user holds both INR and USD names, write two `## Holdings` subsections — `### India (INR)` and `### US (USD)` — each with its own totals. The FX-converted combined total goes in **Notes**, with the rate cited per SKILL.md Hard Rule #9.
7. **Validate after writing.** After the file is written, re-read it back and sanity-check: all rows have ticker and shares; `current_value` ≈ `shares × current_price` within rounding. If a row fails, fix it before continuing to the main answer.
