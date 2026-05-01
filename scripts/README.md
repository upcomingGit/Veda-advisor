# Veda utility scripts

Helper scripts for Veda. Eight categories:

1. **`calc.py` — required.** Veda's Hard Rule #8 forbids LLM arithmetic. Every EV, p_loss, PEG, Kelly, FX, or weight-sum number comes from this script. See SKILL.md Hard Rule #8.
2. **`validate_profile.py` — required at onboarding.** Deterministic schema check for `profile.md`. Run at the end of onboarding to catch enum typos and missing fields before they reach Stage 1.
3. **`validate_assumptions.py` — required when writing `holdings/<slug>/assumptions.yaml`.** Enforces the rules in [internal/holdings-schema.md § "Writing assumptions and checkpoints — guardrails"](../internal/holdings-schema.md#writing-assumptions-and-checkpoints--guardrails-validator-enforced) (strict 4-category enum, slot allocation by archetype, metric whitelist by market, single-metric rule, checkpoint uniqueness, mandatory transcript anchors, inline grounding, coverage).
4. **`validate_all.py` — batch wrapper.** Runs `validate_profile.py` on `profile.md` and `validate_assumptions.py` on every `holdings/<slug>/assumptions.yaml`. One command for a full sanity sweep before any commit / release.
5. **`fetch_fundamentals.py` — data fetcher.** Pulls quarterly financials and computes valuation zones. Called by the `fundamentals-fetcher` subagent (see `internal/agents/fundamentals-fetcher.md`). Sources: yfinance (US), Screener.in (India).
6. **`fetch_news.py` + `news_spam_filter.py` — data fetcher.** Pulls third-party press coverage from curated RSS feeds and Google News, applies a six-layer filter pipeline (URL dedup, 87-domain spam filter, 402-pattern title filter, name-presence filter, semantic dedup, per-publisher cap). Called by the `news-researcher` subagent (see `internal/agents/news-researcher.md`).
7. **`fetch_disclosures.py` — data fetcher.** Pulls primary-source regulator filings: SEC EDGAR 8-K (US), BSE + NSE Corporate Announcements (India). Applies a 12-pattern routine-disclosure filter (StockClarity-ported, India-only) and lightweight future-event regex extraction. Called by the `disclosure-fetcher` subagent (see `internal/agents/disclosure-fetcher.md`).
8. **`import_assets.py` — optional persistence shortcut.** Only useful if you ask enough portfolio-level questions that re-pasting holdings becomes annoying.

---

## `calc.py` — arithmetic helpers (required)

LLMs miscalculate. Even a 1% miscalculation on an EV block can flip a recommendation from `pass` to `proceed` or the reverse. `calc.py` is pure stdlib Python (no dependencies, Python 3.10+) and deterministic.

### Subcommands

| Subcommand      | Purpose                                                     | Example |
|-----------------|-------------------------------------------------------------|---------|
| `ev`            | Expected value (percent) and p_loss for a scenario set      | `python scripts/calc.py ev --probs 0.35 0.40 0.25 --returns 60 15 -35` |
| `p_loss`        | p_loss and p_loss_pct only                                  | `python scripts/calc.py p_loss --probs 0.35 0.40 0.25 --returns 60 15 -35` |
| `kelly`         | Full-Kelly and half-Kelly fractions                          | `python scripts/calc.py kelly --p-win 0.6 --odds 1` |
| `peg`           | PEG ratio (P/E ÷ growth rate in %)                           | `python scripts/calc.py peg --pe 32.1 --growth 78` |
| `margin-of-safety` | Buffett/Graham margin of safety (percent) vs. conservative intrinsic-value low | `python scripts/calc.py margin-of-safety --intrinsic-low 200 --price 165` |
| `fx`            | Currency conversion (amount × rate)                          | `python scripts/calc.py fx --amount 5000 --rate 83.2` |
| `weights-sum`   | Sum of framework_weights (profile validation)                 | `python scripts/calc.py weights-sum --weights 0.15 0.18 0.05 ...` |

### Probability validation

`ev` and `p_loss` both call `validate_probabilities()`, which requires:
- Every probability is in [0, 1].
- Probabilities sum to 1.00 within a 1e-6 tolerance.

If the numbers don't balance, the script raises `ValueError` and you fix the scenarios — you do not round silently.

### Importing programmatically

```python
from scripts.calc import expected_value, p_loss_pct, peg, half_kelly

ev = expected_value([0.35, 0.40, 0.25], [60, 15, -35])
pl = p_loss_pct([0.35, 0.40, 0.25], [60, 15, -35])
```

### Adding a new computation

If Veda needs a number the script doesn't produce (e.g. CAGR, drawdown percentage, portfolio heat), **add a function to `calc.py` before using the number**. Do not compute it inline in the LLM. This is how miscalculations become caught bugs instead of shipped decisions.

---

## `validate_profile.py` — profile schema validator (required at onboarding)

The onboarding flow has the LLM map user free-text answers into structured YAML. That mapping is usually right and occasionally silently wrong — a `growth` instead of `balanced_growth`, a `HIGH` instead of `high`, a missing guardrails field. SKILL.md Stage 1 schema-validates on read, so a bad profile eventually fails loudly; this validator lets onboarding fail fast instead, before the user leaves the session.

Pure stdlib. No YAML parser. Regex against the known schema, so it works in any Python 3.10+ environment.

### Usage

```powershell
python scripts/validate_profile.py profile.md
```

Path argument defaults to `./profile.md`. Exit codes: `0` valid, `1` validation errors printed to stderr, `2` file missing or unreadable.

### What it checks

- Required top-level fields: `schema_version`, `generated`, `profile_last_updated`, `disclosure_acknowledged`, `experience_mode`, `max_loss_probability`.
- `disclosure_acknowledged` is literally `true`.
- Date fields (`generated`, `profile_last_updated`) match `YYYY-MM-DD`.
- `max_loss_probability` is an int in `[0, 100]`.
- All enum fields are one of the exact allowed strings (see the `ENUM_VALUES` table in the script source): `experience_mode`, `goal.primary`, `risk.stated_tolerance`, `risk.calibrated_tolerance`, `concentration.target.style`, `style_lean.primary`, `experience.level`, `experience.explanation_depth`. (`concentration.current.style` is still accepted for backward compat with legacy profiles, but new profiles should put current-state concentration in `assets.md > dynamic.concentration_snapshot` per SKILL.md Hard Rule #10.)
- Boolean fields (`instruments.*`, `guardrails.block_*`, etc.) are literally `true` or `false`.
- `capital.target_split` components sum to exactly 100 when the block is present (all four buckets written). Partial blocks are tolerated. (`capital.split` — current state — is still accepted for backward compat but new profiles should put it in `assets.md > dynamic.capital_split_current`.)
- When `experience_mode: novice`, the `guardrails` block is present and every required guardrail field is filled.
- FX rate validation moved to `assets.md > dynamic.fx_rates.<pair>` per SKILL.md Hard Rule #9. This validator does not check `fx_rates` in `profile.md` — the field no longer belongs there. Staleness is enforced at runtime by the orchestrator against the assets-side copy.
- If present, `framework_weights` contains all 11 investors and the sum lies in the loose band `[0.9, 1.1]`. (Weights are ordinal tie-breakers, not probabilities — the band is deliberate.)

What it does **not** check: free-text fields (`notes`, `self_identified_weakness`, `risk.behavioral_history`), list contents beyond presence, or anything requiring judgment. Those remain the LLM's job and the read-back step's job.

### When to run it

- At the end of onboarding, before declaring the profile saved. (Step 6 of `setup/onboarding.prompt.md`.)
- After manual edits to `profile.md`.
- Before filing an issue — if the validator errors, fix the profile first.

---

## `validate_assumptions.py` — assumptions schema validator

Validates `holdings/<slug>/assumptions.yaml` against the rules in [internal/holdings-schema.md § "Writing assumptions and checkpoints — guardrails"](../internal/holdings-schema.md#writing-assumptions-and-checkpoints--guardrails-validator-enforced). Reads the workspace's `_meta.yaml` for `archetype` and `market` context.

Pure stdlib. No PyYAML — line-by-line block extraction plus regex against the known schema, matching the portability discipline of `validate_profile.py`.

### Usage

```powershell
python scripts/validate_assumptions.py holdings/<slug>/assumptions.yaml
```

Exit codes: `0` valid, `1` validation errors printed to stderr, `2` file missing or unreadable.

### What it checks

- `schema_version` is `1`.
- Sibling `_meta.yaml` exists and supplies `archetype` (one of `GROWTH | INCOME_VALUE | TURNAROUND | CYCLICAL`) and `market` (one of `US | IN`). `instrument_class` must be `equity` if present.
- Exactly four assumption keys: `A1`, `A2`, `A3`, `A4`.
- Each assumption has all six fields: `text`, `category`, `quarterly_checkpoint`, `transcript_checkpoint`, `thesis_horizon_target`, `checkpoint_metric_source`.
- `category` is one of `GROWTH | FINANCIAL_HEALTH | COMPETITIVE | GOING_CONCERN`.
- Slot allocation: category counts match the archetype's required mix exactly (see schema).
- `checkpoint_metric_source` is `consolidated` for non-GOING_CONCERN, `non_financial` for GOING_CONCERN.
- `transcript_checkpoint` is non-null for GROWTH / FINANCIAL_HEALTH / COMPETITIVE; null for GOING_CONCERN.
- `quarterly_checkpoint` target statement (text before the first parenthesis) contains no banned metrics. Indian (`market: IN`) workspaces have a tighter whitelist that additionally bans Gross Margin / Gross Profit / OCF / CapEx / FCF.
- `quarterly_checkpoint` target statement uses exactly one whitelisted primary metric (single-metric rule).
- Each non-GOING_CONCERN `quarterly_checkpoint` uses a distinct primary metric across the four assumptions (uniqueness rule).
- Non-GOING_CONCERN `quarterly_checkpoint` and `thesis_horizon_target` contain at least one citation-shaped parenthesised group (inline grounding rule). Pure unit annotations like `(₹ Cr)` do not count.
- Coverage: at least 3 of 4 assumptions have BOTH non-null `quarterly_checkpoint` AND non-null `thesis_horizon_target`.

What it does **not** check: assumption text quality, citation accuracy (whether the cited source actually says what the citation claims), specific calibration values (the per-archetype tilt rules in the schema are guidance for the writer, not regex-checkable).

### When to run it

- After any write to `holdings/<slug>/assumptions.yaml` — inline by the orchestrator, by the `earnings-grader` subagent (when shipped), or by hand.
- Before filing an issue about assumption-related behaviour — if the validator errors, fix the file first.

---

## `validate_all.py` — batch validator wrapper

Runs the profile validator on `profile.md` and the assumptions validator on every `holdings/<slug>/assumptions.yaml`. Single command for a full sanity sweep across the whole workspace.

Pure stdlib. Imports the per-validator modules directly (no subprocess overhead). Output is one line per file (`OK:` or `FAIL:` + indented error list) plus a one-line summary. Skips files that are not present rather than erroring.

### Usage

```powershell
python scripts/validate_all.py
```

No arguments. Walks from the repo root.

Exit codes: `0` everything passed (or skipped), `1` one or more validators failed (per-file errors printed to stderr), `2` a validator script itself errored on import.

### When to run it

- Before any commit you care about.
- After editing `profile.md` or any `holdings/<slug>/assumptions.yaml` by hand.
- As a release / CI gate when the Tier 1.5 service ships.

---

## `fetch_fundamentals.py` — fundamentals and valuation fetcher

Called by the `fundamentals-fetcher` subagent to fetch quarterly financials and compute valuation zones. The subagent invokes this script via Bash, parses the JSON output, and writes `fundamentals.yaml` and `valuation.yaml` to the holdings workspace.

### Data sources

| Market | Source | Fundamentals | Valuation |
|--------|--------|--------------|-----------|
| US | yfinance | quarterly_income_stmt, balance_sheet, cash_flow | PE, PB, PS, EV/EBITDA from stock.info + 5-year PE history |
| India | Screener.in | HTML scrape (#quarters section) | Chart API (PE history) |

### Usage

```powershell
python scripts/fetch_fundamentals.py \
    --ticker NVDA \
    --market US \
    --archetype GROWTH \
    --sector "Semiconductors" \
    --sector-kind OTHER \
    --history-quarters 12
```

### Parameters

| Parameter | Required | Values | Notes |
|-----------|----------|--------|-------|
| `--ticker` | yes | e.g., `NVDA`, `RELIANCE` | For India, suffix (.NS/.BO) is stripped |
| `--market` | yes | `US` \| `IN` | Routes to yfinance or Screener.in |
| `--archetype` | yes | `GROWTH` \| `INCOME_VALUE` \| `TURNAROUND` \| `CYCLICAL` | Determines primary valuation metric |
| `--sector` | no | e.g., `"Banking"` | For banking/NBFC detection (forces P/B) |
| `--sector-kind` | no | `COMMODITY` \| `CREDIT` \| `OTHER` | `COMMODITY` inverts EV/EBITDA zone; `CREDIT` forces P/B |
| `--history-quarters` | no | default: 12 | Number of quarters to fetch |

### Output

JSON to stdout per the contract in `internal/agents/fundamentals-fetcher.md`. Exit code 0 on success/partial, 1 on total failure.

### Zone computation (mirrors StockClarity)

| Archetype | Primary metric | Zone logic |
|-----------|----------------|------------|
| GROWTH (profitable) | PEG | Size-tiered thresholds: MEGA 0.8/1.5, LARGE 1.0/2.0, MID 1.2/2.5, SMALL 1.5/3.0 |
| GROWTH (unprofitable) | P/S | Percentile or default thresholds |
| INCOME_VALUE | PE | Percentile + PEG override guard |
| TURNAROUND | EV/EBITDA | Percentile |
| CYCLICAL | EV/EBITDA | Percentile; inverted for COMMODITY sector-kind |
| Banks/NBFCs | P/B | Sector override, percentile |

Guardrails: PE > 150 forces EXPENSIVE; growth > 100% capped at 100% for PEG.

---

## `fetch_news.py` + `news_spam_filter.py` — third-party press fetcher

Called by the `news-researcher` subagent to fetch and filter third-party press coverage for a single held position. The subagent invokes this script via Bash, parses the JSON envelope, and grades the kept items qualitatively against the position's `kb.md` + `assumptions.yaml`.

### Data sources

| Stage | Source | Used when |
|---|---|---|
| 1 | Curated broad-publication RSS (10 India + 8 US sources defined in the subagent contract) | Always; first port of call |
| 2 | Per-ticker Google News RSS (per-market locale templates) | When stage 1 yields < 5 ticker-specific candidates |
| 3 | `WebSearch` (handled by the subagent, not this script) | When stages 1–2 still yield < 5 candidates |

### Six-layer filter pipeline

Applied by the helper to all RSS-derived items in order:

1. **URL normalization + hash dedup** — strips `utm_*`, `fbclid`, `gclid`, lowercases domain; SHA-256 dedup.
2. **Publisher-domain spam filter** — 87 blocked domains in `news_spam_filter.py` (StockClarity-ported with per-entry rejection-rate evidence).
3. **Title-pattern spam filter** — 402 blocked patterns including Cramer commentary, "Is X a buy?" listicles, earnings-preview filler, MAG 7 listicles, analyst-stance churn, breakout/rally commentary.
4. **Name-presence filter** — (when `--require-name` passed) drops items whose title and description both lack the ticker or company name.
5. **Semantic dedup (Jaccard with 3-day date window)** — cross-publisher same-event clustering. Default threshold 0.4. Within each cluster, the highest-tier most-recent item is kept; others are surfaced via `cluster_size` / `cluster_dropped_publishers` fields.
6. **Per-publisher cap** — default 3 items per publisher domain; mitigates Yahoo-Finance-style flooding.

### Usage

```powershell
# Single curated RSS feed
python scripts/fetch_news.py `
    --feed-url "https://www.business-standard.com/rss/markets-106.rss" `
    --feed-name "Business Standard Markets" `
    --since 2026-04-22 `
    --require-name "NTPC,NTPC Limited"

# Per-ticker Google News query (per-market locale handled internally)
python scripts/fetch_news.py `
    --google-news-query '"NVIDIA" NVDA when:7d' `
    --google-news-market US `
    --since 2026-04-22 `
    --require-name "NVDA,NVIDIA"

# Multiple curated feeds in one batched invocation (1 op for the subagent's 5-op cap)
python scripts/fetch_news.py `
    --feed-url "https://feeds.bloomberg.com/markets/news.rss" `
    --feed-url "https://www.cnbc.com/id/100003114/device/rss/rss.html" `
    --since 2026-04-22
```

### Output

JSON to stdout per the contract in `internal/agents/news-researcher.md`. Exit code 0 on success/partial, 1 on total failure.

### Editing the curated source list

The canonical curated source list (10 India + 8 US RSS feeds) lives in `internal/agents/news-researcher.md` § "Curated source list". When the list needs additions or removals, update it there, then run `python scripts/sync_agents.py`. The orchestrator passes the URLs into this script via `--feed-url`; the script does not own the list.

---

## `fetch_disclosures.py` — primary-source regulator filings fetcher

Called by the `disclosure-fetcher` subagent to fetch unscheduled material announcements from primary regulator APIs. The subagent invokes this script via Bash, parses the JSON envelope, and emits `proposed_disclosures_md` (rendered file content) plus optional `proposed_calendar_entries` (future scheduled events extracted from disclosure bodies) for the orchestrator to write.

### Data sources

| Market | Source | Form/scope | Authentication |
|--------|--------|------------|----------------|
| US | SEC EDGAR submissions JSON | 8-K only (10-K / 10-Q overlap with `fundamentals-fetcher` and `earnings-grader`) | Identifying User-Agent (per SEC fair-use policy: format `"Name email@domain.com"`); CIK auto-resolved from `sec.gov/files/company_tickers.json` (cached in-process) |
| India | BSE Corporate Announcements API | All categories; 12-pattern SEBI routine-compliance filter applied | Browser-spoofed `User-Agent` + `Origin`/`Referer` headers (StockClarity-ported) |
| India | NSE Corporate Announcements API | All categories; same 12-pattern filter applied | Session cookie priming (visit `nseindia.com/` first); `Accept-Encoding: gzip, deflate` (NOT brotli — brotli breaks NSE) |

### Routine-disclosure filter (India-only)

12 regex patterns ported verbatim from StockClarity's `disclosure_fetcher.py` `_IGNORED_DISCLOSURE_PATTERNS`. Each has documented 100% LLM-rejection evidence in StockClarity production logs:

- Trading Window Closure, Loss / Duplicate Share Certificate, Investor Complaints, Compliance Certificate, Regulation 74(5), Certificate under SEBI (Depositories and Participants).
- Analysts/Institutional Investor Meet/Con. Call Updates, Shareholders meeting (schedule notices, not outcomes), Copy of Newspaper Publication, ESOP/ESOS/ESPS grants.

The filter is applied to BOTH `headline` and `category` fields, case-insensitive. **Not applied to SEC 8-K** — US 8-K is already a curated material-event form by SEC's design.

### Cross-source dedup (India)

When both BSE and NSE return announcements for the same ticker, the helper deduplicates by `(date, normalized_headline_prefix[:60])` proximity match, preferring BSE on ties (BSE's category metadata is more reliable; NSE conflates `desc` and `headline`).

### Future-event extraction

Lightweight regex set (6 event types: `board_meeting`, `agm`, `egm`, `record_date`, `ex_dividend`, `rights_issue`). Date filter requires the extracted date to be today or later. Conservative on purpose — a false positive corrupts `calendar.yaml`. The subagent forwards extracted events to the orchestrator via `proposed_calendar_entries`; the helper itself does not write to calendar files.

### Usage

```powershell
# US 8-K — CIK auto-resolved from sec.gov/files/company_tickers.json
python scripts/fetch_disclosures.py --market US --ticker MSFT --since 2026-01-30

# US 8-K — CIK provided (skips the lookup)
python scripts/fetch_disclosures.py --market US --ticker MSFT --cik 0000789019 --since 2026-01-30

# India — fetch BSE + NSE in one invocation; helper dedups across sources
python scripts/fetch_disclosures.py `
    --market India --ticker RELIANCE `
    --bse-code 500325 --nse-symbol RELIANCE `
    --since 2026-01-30

# India — single source (when only one code is available)
python scripts/fetch_disclosures.py `
    --market India --ticker NTPC --nse-symbol NTPC `
    --since 2026-01-30
```

### Parameters

| Parameter | Required | Values | Notes |
|-----------|----------|--------|-------|
| `--market` | yes | `US` \| `India` | Routes to SEC EDGAR or BSE+NSE |
| `--ticker` | yes | e.g., `MSFT`, `RELIANCE` | Used in stable `id` and logs |
| `--cik` | no (US) | 10-digit zero-padded | Auto-resolved when omitted |
| `--bse-code` | no (India) | numeric scrip code, e.g., `500325` | At least one of BSE / NSE required |
| `--nse-symbol` | no (India) | alphanumeric, e.g., `RELIANCE` | At least one of BSE / NSE required |
| `--since` | yes | `YYYY-MM-DD` | Lower bound on filing date (inclusive) |
| `--today` | no | `YYYY-MM-DD` | Override system date for testing |

### Output

JSON to stdout per the contract in `internal/agents/disclosure-fetcher.md`. Top-level fields: `ticker`, `market`, `since`, `today`, `results` (per-source counts), `items_after_dedup`, `items_dropped_in_cross_source_dedup`, `items` (normalized list, sorted by date descending), `resolved_cik` (when auto-resolved), `errors`.

Exit codes: `0` success or partial success (check `errors` array), `1` total failure (no items + at least one endpoint errored), `2` bad usage.

### Editing the routine-pattern set

The 12 patterns live in `_ROUTINE_PATTERNS_INDIA` near the top of `fetch_disclosures.py`. Each pattern carries an inline comment with StockClarity's per-pattern rejection-rate evidence. Add a new pattern only when there is comparable evidence (production-log proof that an objectively-non-substantive category produces zero useful signal). Do NOT add discretionary materiality patterns — those belong in framework-routing rules, not in the fetcher.

---

## `import_assets.py` — optional persistence shortcut

Veda's default portfolio workflow is: when it needs your holdings for a question, it asks, and you paste them in any format — a copy from your broker app, a spreadsheet dump, or rough natural language. No file generation, no CSV export, no script to run. This script exists only as a shortcut for users who ask enough portfolio-level questions that re-pasting becomes annoying.

Convert a broker CSV export into the equities-holdings section of `assets.md` (Veda's tactical-state file — see internal/assets-schema.md). The script emits a valid starter `assets.md` with stub values in the `dynamic:` block; Veda fills those (FX, totals, concentration snapshot, capital split, forced-concentration snapshot) on the first session after import.

### When to use it

- You ask portfolio-level questions frequently enough that pasting positions each time feels repetitive.
- You want Veda to remember your holdings between sessions so it can build correlation and concentration history.

### When to skip it

- You ask single-name questions mostly ("is X a good business?"). You don't need a portfolio file.
- You only check a portfolio question occasionally. Pasting the list takes 10 seconds and avoids installing Python or maintaining a file.

### Usage

```powershell
# From the Veda-advisor folder
python scripts/import_assets.py zerodha holdings.csv

# Or a generic CSV (ticker / shares / avg_cost / current_price columns)
python scripts/import_assets.py generic my_broker_export.csv

# Custom output path
python scripts/import_assets.py zerodha holdings.csv --out ~/notes/assets.md
```

### Supported brokers (v0.1)

| Broker | CSV source | Notes |
|---|---|---|
| `zerodha` | Kite → Holdings → Download CSV | Works with the current and recent column-name variants. |
| `generic` | Any CSV | Columns: `ticker`, `shares`/`quantity`, `avg_cost`/`cost_basis`, `current_price`/`price`/`ltp`. `name` and `sector` optional. |

Adding a new broker is a ~20-line function. See the docstrings at the top of `import_assets.py` and the `parse_zerodha` reference implementation.

### What the script does NOT do

- **Does not fetch live prices.** Current prices come from the CSV, which is usually end-of-day.
- **Does not ask for tags or thesis.** The `tags` column is left as a placeholder and Veda fills it *lazily* — when you ask about a specific holding, Veda asks for the tag and saves it back. Per-position thesis content lives in `holdings/<slug>/thesis.md` (a separate workspace file scaffolded the first time you ask about that ticker), not in the holdings table. You never batch-fill the file.
- **Does not commit for you.** `assets.md` is gitignored. After generating, verify with `git check-ignore -v assets.md`.

### Roadmap

- **v0.2:** More broker CSV parsers. Priority targets: Groww, ICICI Direct, Interactive Brokers, Fidelity.
- **v1.0 (partial — Zerodha done):** Live broker integration. See [`kite.py`](#kitepy--zerodha-live-holdings-optional) below for the Zerodha Kite Connect path. Remaining brokers will be added opportunistically.

---

## `kite.py` — Zerodha live holdings (optional)

Replaces the manual "export CSV, then run `import_assets.py`" flow for Zerodha users. Pulls holdings directly via the Kite Connect API so the numbers carry a fresh `as_of` stamp instead of being whatever was in yesterday's CSV. Everything else about Veda is unchanged: the LLM still reconciles the fetched positions into `assets.md` per SKILL.md Stage 1.5 update rules.

**This is optional.** If you already have `assets.md` and are fine pasting or re-importing occasionally, skip it. It exists because daily refresh of a live portfolio via CSV export gets old fast.

### Prerequisites

1. A Zerodha Kite Connect developer app at <https://developers.kite.trade/apps>.
   - **Redirect URL must be** `http://127.0.0.1:5000/kite/callback` (the script listens on this exact path).
   - The Personal tier is free and covers holdings.
2. `secrets/kite.yaml` created from `secrets/kite.example.yaml`, with `api_key` and `api_secret` filled in. **Never paste these into chat, email, or any other persistent channel.** The `secrets/` folder is gitignored.
3. `pip install -r requirements.txt` (adds `kiteconnect`).

### Subcommands

| Subcommand | Purpose                                                             | Frequency           |
|------------|---------------------------------------------------------------------|---------------------|
| `auth`     | Browser OAuth → writes `access_token` into `secrets/kite.yaml`.     | Once per day (06:00 IST expiry — Zerodha policy). |
| `holdings` | Prints long-term holdings as JSON on stdout. Fails if token expired. | Any number of times until next 06:00 IST. |

### Daily flow

```powershell
# Once per calendar day, after 06:00 IST
python scripts/kite.py auth
# -> browser opens, you log into Kite, redirect is captured silently,
#    access_token and expiry are saved to secrets/kite.yaml.

# Any number of times until expiry
python scripts/kite.py holdings > holdings.json
```

The `holdings` JSON has shape:

```json
{
  "source": "kite",
  "as_of": "2026-04-21T18:34:12+05:30",
  "count": 26,
  "holdings": [ { "tradingsymbol": "...", "quantity": 123, "average_price": 456.78, "last_price": 501.20, ... } ]
}
```

### How Veda uses the output

This is a deliberate design choice: the script only fetches. Veda (the LLM) handles reconciliation, because matching new positions against existing `assets.md` rows, preserving your tags, and dropping sold positions is a judgment task — not something to hard-code.

In-chat: say "refresh holdings from Kite". Veda will:

1. **Broker-gate.** Check `profile.md > broker.primary`. If absent, ask once and save the answer. If the value is not `zerodha`, stop and tell you live pull is Zerodha-only in v0.1; fall back to the paste path.
2. Run `python scripts/kite.py holdings` and parse the JSON.
3. Diff against `assets.md` by ticker. For each holding:
   - New ticker → add row with the default `tags` placeholder (filled lazily when you next ask about it). Per-position thesis content lives in `holdings/<slug>/thesis.md`, not in this table.
   - Existing ticker, changed quantity/price → update the numeric fields, **preserve tags**.
   - Ticker missing from Kite → move to a `closed_positions:` block (sold).
4. Update `dynamic.fx_rates.usd_inr` (via `fetch_quote.py`) and re-run `calc.py` to refresh totals and weights per SKILL.md Hard Rule #8.
5. Read back the diff before saving.

### Exit codes

`0` success · `1` runtime failure (missing creds, expired token, API error — JSON with `error:` key printed to stdout) · `2` bad CLI usage.

### Security notes

- `auth` **never echoes the access_token to stdout** — it only prints the expiry and a confirmation. The token lives in `secrets/kite.yaml`, which is gitignored by the `secrets/` rule in `.gitignore`.
- If a credential leaks (pasted, committed, shared), regenerate the secret at <https://developers.kite.trade/apps> before doing anything else. Regeneration invalidates the leaked value immediately.
- Tokens expire at 06:00 IST daily. This is a Zerodha policy, not a script limitation. The script stamps the expected expiry when you auth and refuses `holdings` past it rather than silently using a dead token.
