# assets.md — schema and writing rules (reference)

This file is loaded on demand by SKILL.md Stage 1.5 when holdings or any other
tactical state (FX rates, current-concentration snapshot, today's capital split,
forced-concentration numeric snapshot, roll-up totals) need to be persisted.
Both inline writes (LLM parsing a pasted list) and the output of
[scripts/import_assets.py](../scripts/import_assets.py) must conform to this
schema so either source reads cleanly in the next session.

`assets.md` is the single home for everything that moves day-to-day. `profile.md`
holds only stable preferences and identity. See SKILL.md Hard Rule #10 per-file
boundary table.

---

## File layout (top to bottom)

````
# Assets

**As of:** YYYY-MM-DD   # top-level as-of for the holdings tables

<!-- HTML comment with schema-version / usage notes (optional but recommended) -->

```yaml
dynamic:
  # tactical state — fully specified below
```

## Holdings (equities)
### India (INR)   # or US (USD), Europe (EUR), etc. — one section per currency
| ticker | name | shares | avg_cost | current_price | current_value | sector | thesis | tags |
...

## Cash & equivalents
...

## Liabilities (loans)
...

## Watchlist / open orders
...

## Sector caps (optional)
...

## Notes
...
````

---

## The `dynamic:` YAML block

The `dynamic:` block is a single top-level fenced YAML block placed immediately
after the `**As of:**` line and any HTML comment. It bundles all tactical state
so downstream readers can parse one block instead of scraping multiple prose
fragments.

### Required fields

| Path | Type | Source | Notes |
|---|---|---|---|
| `dynamic.fx_rates.<pair>.rate` | number | `scripts/fetch_quote.py fx --pair <pair>` OR user | `<pair>` is `<from>_<to>` lowercase (e.g., `usd_inr`). `rate` converts 1 unit of from to to. |
| `dynamic.fx_rates.<pair>.as_of` | YYYY-MM-DD | same | Market date, not fetched_at wall clock. |
| `dynamic.fx_rates.<pair>.source` | string | same | Free text; prefer Tier 1–2 (e.g., "yfinance", "RBI reference"). |
| `dynamic.concentration_snapshot.style` | enum | derived | One of `index_like \| diversified \| focused \| concentrated`. Based on position_count + largest_position_pct, not user preference. |
| `dynamic.concentration_snapshot.position_count` | int | count of holdings rows | Count unique tickers across all `## Holdings` subsections. |
| `dynamic.concentration_snapshot.largest_position_pct` | number | `calc.py pct` | Required. Never typed by hand. |
| `dynamic.concentration_snapshot.largest_position_ticker` | string | derived | Ticker of the largest position by `current_value` (after FX conversion to the user's base currency). |
| `dynamic.capital_split_current.core_long_term` | int | sum of `core`-tagged positions / grand_total | 0–100. Four buckets MUST sum to 100. |
| `dynamic.capital_split_current.tactical` | int | same | |
| `dynamic.capital_split_current.short_term_trades` | int | same | |
| `dynamic.capital_split_current.speculation` | int | same | |
| `dynamic.forced_concentration_snapshot[]` | list | per forced-concentration ticker in `profile.md > constraints.forced_concentration` | One entry per forced name. |
| `dynamic.forced_concentration_snapshot[].ticker` | string | required | Must match a ticker in profile.md's forced_concentration list. |
| `dynamic.forced_concentration_snapshot[].cur_val_<ccy>` | number | required | Current market value in the position's native currency (e.g., `cur_val_usd`). |
| `dynamic.forced_concentration_snapshot[].cur_val_<base_ccy>` | number | `calc.py fx` | Converted via the matching `dynamic.fx_rates` entry. |
| `dynamic.forced_concentration_snapshot[].weight_pct` | number | `calc.py pct` | % of grand_total. |
| `dynamic.forced_concentration_snapshot[].as_of` | YYYY-MM-DD | required | When this snapshot was taken. |
| `dynamic.forced_concentration_snapshot[].note` | string | optional | Free text — why the position is forced-concentrated *today*. For the stable constraint itself see profile.md. |
| `dynamic.totals.<sleeve>_total_<ccy>` | number | `calc.py sum` or `calc.py fx` | Roll-ups per sleeve and currency. Include a `grand_total_<base_ccy>` line. |
| `dynamic.totals.<sleeve>_weight_pct` | number | `calc.py pct` | % of grand_total per sleeve. Must sum to 100 within rounding. |

### Calc-trail rule

Every numeric field in `dynamic.*` that is not a direct user input MUST carry a
trailing comment showing the `calc.py` invocation that produced it. Example:

```yaml
    cur_val_inr: 8406000     # calc: fx --amount 90000 --rate 93.40
    weight_pct: 51.67        # calc: pct --part 8406000 --whole 16269569.30
```

Per Hard Rule #8, the LLM never produces these numbers by head arithmetic. The
trail is auditable evidence that `calc.py` ran. If you find a `dynamic.*`
numeric field without a calc trail, treat it as unverified and recompute.

### Stale-field rule

If any `dynamic.fx_rates.<pair>.as_of` is older than 1 trading day at session
start, re-fetch it and propagate the update to every dependent `dynamic.totals`
and `dynamic.forced_concentration_snapshot` field *in the same turn*, per
SKILL.md Hard Rule #9 same-turn propagation clause. Do not ship a decision
with a fresh FX rate but stale derived totals.

---

## Holdings tables

### Template per currency

```markdown
### <Region> (<CCY>)

| ticker | name | shares | avg_cost | current_price | current_value | sector | thesis | tags |
|---|---|---:|---:|---:|---:|---|---|---|
| NVDA | NVIDIA | 50 | 420.00 | 890.00 | 44,500.00 | Semiconductors | _(add thesis)_ | core |
| ... | | | | | | | | |

**Total holdings value (<Region>):** <total in native CCY>
```

### Writing rules

1. **Sort rows by `current_value` descending** within each currency subsection. Matches the importer.
2. **Numeric columns use thousand separators and 2 decimal places** (`44,500.00`), *except* `shares` which uses a bare number with no trailing zeros (`50`, `12.5`, not `50.00`). Matches the importer's `{:,.2f}` and `{:g}` formats.
3. **Mandatory columns: `ticker`, `shares`, `avg_cost`, `current_price`, `current_value`.** If the user's paste is missing `avg_cost` or `current_price`, write the row anyway with the missing value as `TBD_fetch` — do not guess, do not drop the row. Flag the gaps once at the end of the response: *"I left avg_cost as TBD_fetch for AAPL, MSFT — paste or ask me to fetch before the next portfolio question."*
4. **Optional columns default to `-` (sector) or `_(add thesis)_` / `_(core/tactical/speculation)_` placeholders.** Do not invent a thesis or a tag the user did not state.
5. **Stamp `**As of:** YYYY-MM-DD`** with today's date at the top of the file.
6. **Never mix currencies in the same table.** One `### <Region> (<CCY>)` subsection per currency, each with its own total. The FX-converted combined total lives in `dynamic.totals.grand_total_<base_ccy>`, not in the holdings section.
7. **Validate after writing.** After the file is written, re-read it back and sanity-check: all rows have ticker and shares; `current_value` ≈ `shares × current_price` within rounding. If a row fails, fix it before continuing to the main answer.
8. **Re-run dependent calc.py after any row change.** A delta edit to even one row invalidates `dynamic.totals`, `dynamic.concentration_snapshot`, `dynamic.capital_split_current`, and any `dynamic.forced_concentration_snapshot[].weight_pct`. Recompute and write back in the same turn.

---

## Non-equity sections

Each section below is a first-class part of `assets.md`. Follow the same
calc-trail and currency-separation rules as the equities tables. Leave the
section header in place even when no data has been captured yet — the stub
row in the user's file documents the row schema, and the header acts as the
capture target when new data arrives.

### Ordering

Keep sections in this order, liquid → illiquid → liabilities:

1. `## Holdings (equities)` — listed equities, ETFs, equity mutual funds. Currency-split subsections.
2. `## Cash & equivalents` — savings, current, liquid funds, money-market, sweep-in FDs.
3. `## Fixed deposits & bonds` — term deposits, corporate FDs, RBI bonds, G-secs, debt MFs.
4. `## Retirement & tax-advantaged accounts` — PPF, EPF, NPS, Sukanya Samriddhi (IN); 401(k), IRA, HSA (US); ISA, SIPP (UK).
5. `## Unvested equity grants (stock options, RSUs, ESPP)` — contingent claims, not current assets.
6. `## Precious metals` — physical gold/silver, SGBs, gold ETFs, digital gold.
7. `## Real estate` — primary, rental, land.
8. `## Other assets (loans given, private holdings, alternatives)` — loans receivable, private equity, collectibles, off-exchange crypto.
9. `## Liabilities (loans taken)` — mortgages, auto, personal, education, credit cards, LAS, margin.
10. `## Watchlist / open orders`, `## Sector caps (optional)`, `## Notes` — reference / free-text.

### What belongs in `dynamic.totals.grand_total_<base_ccy>`

Only assets the user can deploy into market equity on reasonable notice:
`Holdings (equities)` + `Cash & equivalents` + `Fixed deposits & bonds` liquid
portion (next-maturity within 12 months) + `Precious metals` paper forms (SGB,
ETF, digital gold).

**Excluded** from `grand_total_<base_ccy>` by default:
- `Retirement & tax-advantaged accounts` — lock-until date matters.
- `Unvested equity grants` — contingent claim.
- `Real estate` — illiquid; user must explicitly authorise inclusion.
- `Other assets` items with `liquidity: illiquid` or locked.

Veda may quote a separate `dynamic.totals.net_worth_<base_ccy>` that includes
everything minus `Liabilities (loans taken)` when the user asks a net-worth
question, but that line is distinct from the portfolio-roll-up total used for
sizing and concentration math. When both are present, clearly label each.

### Row schemas

Row shapes are documented in [assets.md](../assets.md) alongside each section's
stub row — the stub IS the schema. Update both files together if a column is
added or renamed.

**Cross-section integrity rules:**

- If a `Real estate` row has a non-zero `outstanding_loan`, a matching row
  must exist in `Liabilities (loans taken)` with `secured_against` pointing
  back to the property. Cross-check on every write.
- `Unvested equity grants` rows do NOT increment `dynamic.concentration_snapshot.position_count`
  or `dynamic.totals.*` but DO inform `dynamic.forced_concentration_snapshot`
  forward projections (the next-vest bump).
- `Retirement & tax-advantaged accounts` are surfaced in retirement-runway
  questions via their own calc: `FIRE-projected balance = current_value ×
  (1 + r)^years_to_access`. Growth assumption `r` is user-supplied; never
  baked in by Veda.
- Precious-metal rows split physical vs paper: physical has a
  making-charges/assay haircut; paper (SGB, ETF) does not. Veda uses the
  `current_value` as-given but references the form in any liquidity question.

---

## Post-write validation (inline check)

Before closing the turn in which `assets.md` was written or updated:

1. File exists and is readable.
2. Top-level `**As of:**` date is today (full refresh) or was preserved (delta).
3. `dynamic:` YAML block parses as valid YAML.
4. Every `dynamic.fx_rates.<pair>.as_of` is ≤ 1 trading day old.
5. `dynamic.capital_split_current` buckets sum to 100 (if populated).
6. `dynamic.concentration_snapshot.position_count` equals the count of unique tickers across all `## Holdings (equities)` subsections — **unvested grants are excluded** from this count.
7. Every `dynamic.*` numeric field has a `# calc:` trail (excluding direct user inputs like `fx_rates.<pair>.rate` and per-row `shares`/`avg_cost`).
8. Every `Real estate` row with a non-zero `outstanding_loan` has a matching `Liabilities (loans taken)` row whose `secured_against` points back to the property.
9. All ten section headers (Holdings, Cash, FDs/bonds, Retirement, Unvested, Precious metals, Real estate, Other, Liabilities, Watchlist/Sector caps/Notes) are present in the expected order, even if empty. Missing headers indicate a partial write — fix before continuing.

Any failure: fix in the same turn before proceeding to the main answer. Do not
defer "I'll tidy it up later" — stale tactical state is how wrong decisions get
shipped.
