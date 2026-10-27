# Portfolio tracker

One runtime file: `scripts/portfolio.py`. It reuses the existing Kite login
and US quote helpers. Dependencies are in the repo's existing `requirements.txt`.
There are no launchers, demos, example files or generated snapshots.

## Use it

From `C:\Users\ankur\Downloads\Veda-advisor`, activate the environment
already installed:

```powershell
.venv\Scripts\Activate.ps1
python scripts/portfolio.py login
python scripts/portfolio.py update
```

`login` is needed when the Kite session expires; complete its browser step.
`update` refreshes source cells and broker cash, extends the native table into blank rows when needed, and verifies calculations before advancing Last Refreshed. Running without a command previews only. Settings are read automatically.
If activation is unavailable, use `.venv\Scripts\python.exe` instead of `python`.

Two setup checks are available when needed:

```powershell
python scripts/portfolio.py check
python scripts/portfolio.py review
```

`check` verifies Google access without contacting Kite. `review` shows broker
quantity/cash components to compare with Zerodha before selecting the cash field.
The existing developer app redirect must be
`http://127.0.0.1:5000/kite/callback` for login.

Only `update` writes portfolio cells. Login updates the local session. No command places orders. The Google service account must have Editor access to the spreadsheet.

## Settings and inputs

`private/portfolio-sync/settings.json` contains the workbook ID and path to the
existing Google key. Kite credentials stay in `secrets/kite.yaml`. No credential
files are duplicated. Paths may be absolute or relative to the repository root.

After broker reconciliation, add `india_cash_field` with the confirmed value
`available.cash` or `available.live_balance`. Until then it remains unselected;
weights are unavailable. Unsupported pending/sold/pledged/MTF quantities stop for
review. CNC alone does not prove a holding is a stock rather than an ETF.

US daily updates use the existing US Portfolio tab as the source of truth. Settings contain `us_holdings: "sheet"`; no retained CSV/XLSX or duplicate per-broker inputs are required. Uploaded broker exports are one-time import sources and can be removed after import.

Maintain US quantities and USD average purchase prices in the table, combined broker cash in D5, and the confirmed Holdings & Cash As Of date in P8. Daily updates preserve those inputs and manual decisions, while refreshing prices, company market cap, trailing P/E and available StockClarity data. The input date does not advance merely because quotes refresh. If quantities, cost or cash change while the script is fetching, it stops rather than overwriting them.

The Fidelity screenshot supplied 109.0087 owned MSFT shares and $85.98 FYIXX cash; FYIXX is counted once as broker cash, not also an investment row. Combined Vested + Fidelity cash was confirmed at $8,675.98 on 26 October 2026. Microsoft is owned stock, not an unexercised-option position. Its USD cost basis was not provided, so average cost and unrealised return remain blank. Its market value and portfolio weight still calculate. Once the USD total cost is provided, divide it by the held quantity to enter the per-share average in the sheet. No INR-to-USD conversion or exercise price is inferred.

The existing standard CSV and Vested XLSX readers remain available for explicit file imports. They are not needed for daily refreshes. File-import mode validates an exact exchange-qualified listing, fractional quantities, dated inputs and export totals; Vested average cost uses total invested divided by units rather than the broker's rounded display average.

## Behaviour

Columns are located by header. Manual decisions, personal notes, additional
columns and existing formulas are protected. Missing source positions are
retained for reconciliation; exits are not inferred.

India and US use separate currencies. India weights include stocks + Coin mutual funds + broker cash. US weights use US stocks + ETFs + US broker cash. US quantities, average costs, combined broker cash and the confirmed holdings/cash date are maintained in the US sheet. Daily quote refreshes do not re-import or re-date those inputs. Missing cash or any held position's dated price blocks complete
weights. Quotes retain source dates; fetch time does not imply price freshness.
Older dates remain visible because a maximum-age policy has not been agreed.
Prices now use the existing free Yahoo batch fetcher for both markets. Indian
tickers map to their exact exchange suffix (.NS for NSE, .BO for BSE); unsupported
symbols remain gaps rather than being guessed. Provider currency and timestamps
are checked. Requests are split into at most 20 symbols. Kite supplies stocks, Coin units, average costs, cash and login. Live testing returned dated INR quotes for all 21
current Indian holdings; no Screener fallback is needed for that coverage.
If the table lacks space, preview still values every holding and reports the
additional rows needed; it proposes no cells beyond the existing table.

The user confirmed the live cash balance; settings now select
`available.live_balance`. Executed sales retain Kite's already-reduced quantity
when opening quantity equals remaining plus sold quantity; they are not subtracted
again. Other quantity discrepancies still stop for reconciliation.

StockClarity's 11 monitored securities are research coverage, not a confirmed
holding count. Daily thesis status and signals are matched to portfolio identifiers. Personal sell/review conditions are recorded in the sheet; the chat review applies them without changing My Action. Missing research never implies Hold.

## Test and remaining work

```powershell
python -B -m unittest discover -s scripts -p test_portfolio.py -q
```

The one self-contained test file covers 105 checks with mocked network/broker
responses. It creates and cleans its own temporary inputs. Normal runs save no
temporary output and generate no helper bytecode caches.

Google and Kite holdings/funds access have been verified. Actual Indian holdings
and the live cash field have been reconciled, including an executed partial sale.
The combined India table has been updated and verified with 21 stocks and one Coin mutual fund. Market cap and P/E were populated for all 21 stocks. The US table has nine positions (eight stocks and a gold ETF), including Fidelity MSFT, and confirmed combined broker cash of $8,675.98 dated 26 October 2026. Daily US refreshes read the sheet itself; the original export is no longer required. StockClarity research is connected as described below.

## Automatic fundamentals and Coin

The same `update` command refreshes Indian stock market cap (INR crore) and P/E from Screener.in. Consolidated figures are preferred, with standalone used when consolidated data is absent. P/E is the provider's displayed Stock P/E. These are company figures as fetched, not recalculated from the Yahoo price. BSE codes are resolved from Kite's official instrument master when a symbol route is unavailable. Missing or non-applicable figures preserve previous cells and produce a visible console gap; source URLs, fetch times and missing fields are saved in the Last Refreshed note. US company market cap (USD million) and positive trailing P/E use Yahoo's public quote endpoint with an in-memory public cookie/crumb session, using the existing requests dependency. Only public ticker symbols are sent; holdings, costs, cash and broker credentials are not. Company P/E and company market cap are not inferred for ETFs. Negative or missing P/E is a gap; the initial OKLO P/E is blank because trailing earnings are negative. Source URLs, fetch times and missing fields are retained in the Last Refreshed note. No files, CLI options or extra runtime dependencies were added.

Sector is always manual and never overwritten. Status, conviction, sell condition, action and personal notes are also preserved. Stock names fill only blank cells; quantities, average costs, prices, cash, market cap and P/E are refreshed automatically when supplied.

Coin holdings join the existing India table as `MF:<ISIN>`; no extra tab or runtime file is needed. Quantity means units and Current Market Price means NAV for these rows. Fractional units are retained. AMFI's public NAV file is matched by exact ISIN and supplies both NAV and its actual date. Coin can return an undated NAV, so it is not treated as fresh. If Coin or a matching dated AMFI NAV is unavailable, the combined refresh stops before writing. Pledged/discrepant fund holdings require reconciliation. Market cap and P/E remain blank for new fund rows; no fund-level P/E is inferred.

The Investments Value summary includes stocks and funds. Weights use their combined market value plus the single broker cash balance; cash is counted once. NAV dates can precede stock quote dates and are retained separately in the Last Refreshed cell note. Last Refreshed records successful sync time, not a common valuation date.

## StockClarity daily research

Run StockClarity first, then the same `python scripts/portfolio.py update` command. The tracker reads the latest saved `thesis_snapshots` record per company, copying its thesis status and Buy/Hold/Sell decision. It neither starts analysis nor recalculates recommendations from thesis status, P/E or price.

The existing sibling `StockClarity/.env` supplies the database connection; credentials are not copied into tracker settings or printed. PostgreSQL access uses a read-only transaction with connection/query timeouts. The tracker environment needs the `psycopg2-binary` and `python-dotenv` dependencies listed in the existing requirements file. If the repo moves, `stockclarity_repo` can point to its new location in the existing private settings file.

Matching uses Indian company symbols across NSE/BSE, the official Kite BSE code mapping for numeric BSE identifiers, and the NSE SME segment suffix. US tickers are matched only to US company identifiers when US import is enabled. Company names and sectors are not used to guess identity; ambiguous matches are flagged.

The two automatic columns contain `StockClarity Thesis Status` and `StockClarity Signal`. Stocks outside coverage show `Not covered`; mutual funds and ETFs show `Not applicable`. Existing company records without daily results show `No snapshot`. An unavailable database, invalid result or missing signal shows `Unavailable` rather than carrying an old Buy/Hold/Sell forward as current. Snapshots dated before today include their source date in the visible status/signal. The actual research date, company ID and source explanation are retained in the Last Refreshed cell note alongside the separate price/NAV dates.

Sector, Status, My Thesis Conviction, My Sell Condition, My Action, notes and existing formulas remain protected. The two StockClarity columns are source-managed and will be overwritten on refresh. Research is attached to imported portfolio positions; this does not automatically add StockClarity's other monitored companies to your holdings.

## India completion review

The agreed India workflow is implemented in `scripts/portfolio.py`: stocks and Coin funds in one table, cash-inclusive weights, dated Yahoo/AMFI prices, Screener company fundamentals and saved StockClarity research. All automatic columns are resolved by header. No separate launcher, export or dashboard is needed.

Review Reason is deliberately left blank and is not a calculated field. Its legacy India template formulas were removed; future row expansion copies only the three financial calculation formulas. Any later manual content in Review Reason is preserved.

A zero-quantity source position still manually marked Invested now stops before writing, because the sheet's totals intentionally reject that status/quantity mismatch. Missing source holdings also require reconciliation; sold positions are not silently cleared. Login is still required when the Kite session expires. Pending/T1, pledged or discrepant quantities stop for review. Fundamentals gaps preserve existing cells and are reported in the console and source notes. Source fetch time is never substituted for the underlying quote/NAV/research date; no maximum quote-age policy is configured. Run StockClarity before updating the portfolio to consume its latest completed snapshot.

## India layout and original thesis notes

The India table ends with My Thesis Conviction, My Sell Condition and My Action. Review Reason is hidden immediately before those three fields. The tracker identifies every field by header, including after column moves. Native dropdowns and the financial formulas remain intact.

Seven conviction cells have one-time baseline notes from the stored StockClarity owner theses: Aartech, Astra Microwave, HBL Engineering, MapmyIndia, Qualitek Labs, Sacheerome and Zen Technologies. Hover a populated conviction cell to read the original investment thesis, four assumptions, their horizons/definitions, relevant recorded checkpoints and the baseline source date. The dropdown is your current conviction. Daily refreshes preserve these notes; they do not rewrite the original investment case. Other stocks remain without baseline notes until their original rationale is captured.

## Current conviction and chat review

Edit current personal conviction in India Portfolio's My Thesis Conviction dropdown. The six matching Indian rows in Ideas Invested In use direct cell links, such as `='India Portfolio'!P14` for Astra; their earlier explanations are preserved as cell notes. If you sort the source portfolio rows, recheck these six links because they follow cell addresses. The US table now has the same final three columns and hidden Review Reason. Alibaba, Qualys, Frequency Electronics and M-tron carry High conviction, explicitly approved as the equivalent of their existing Strong entries. US ideas rows 23-26 use direct links to the corresponding portfolio conviction cells; earlier explanations are preserved as notes. The four portfolio conviction notes retain those explanations and existing monitoring checkpoints, without inventing additional original thesis text. Other convictions, sectors and all My Action values remain manual. The agreed company sell/review rules are populated for the seven stocks. AAAU is a physical gold ETF: company P/E and the single-stock limit are not applied, and no gold-specific allocation/exit rule has been supplied.

The single-file Codex skill lives in this repository at [.agents/skills/portfolio-review/SKILL.md](../.agents/skills/portfolio-review/SKILL.md), so it can be committed with the tracker. Open Veda-advisor in Codex and, after the normal daily update, ask: `Use $portfolio-review to review my India portfolio. Give a Buy, Hold or Sell value for every stock, with evidence.`

The review evaluates buying opportunities, exit-rule breaches and portfolio balance. High and Medium personal conviction are eligible for Buy, with High preferred and stronger supporting evidence required for Medium. Valuation, business evidence and portfolio fit must support adding; P/E below 100 alone is not a Buy signal. Proposed purchases use current broker cash only, shared across all candidates; sales or mutual-fund redemptions must not be proposed to finance purchases, and proposed sale proceeds are excluded from the purchase budget. Independent exit-rule sells and concentration trims still apply. Trade proposals show amounts, funding and resulting weights. An unresolved material fact qualifies a Hold as provisional instead of claiming that the investment case passed.

Each review independently researches every company, including Low-conviction holdings, before recommending an action. It checks the latest released results and relevant annual-report/audit evidence, subsequent filings, material news and credible outside analysis, including contrary views. Cash conversion, debt, earnings quality, valuation and corporate actions are checked where relevant. Recommendations cite dated evidence and disclose material research gaps; an inaccessible filing or incomplete search is not treated as a passed exit check.

StockClarity thesis status, signals and grading are excluded; the automatic sheet columns remain informational. Your own thesis notes, conviction, conditions and stated judgements provide the personal context for the independent assessment. My Action stays manual and suggestions stay in chat. This adds no Python command or StockClarity integration. The skill requires access to the sheet and web research tools; it does not grant ordinary ChatGPT access to local files.

## Shared portfolio layout

Both tabs use the same 18-column order, common summary cards (Investments Value, Broker Cash, Total Value, Cash Weight, Sync Status, Holdings), column widths, readable headers and compact 32-pixel rows. Review Reason stays hidden before the final three manual decision columns. Full sell conditions remain unchanged in the cells and are also available in their hover notes.

Holdings & Cash As Of is at P8 in both tabs. India refreshes it from the older broker holdings/cash date after a verified update. US users maintain it manually; daily US price refreshes do not advance it. Currency/cap units, integer Indian stock quantities, four-decimal fund units/NAVs and fractional US quantities keep their respective meanings. Yellow cells identify manual inputs; India holdings/cost/cash remain automatic, while US quantities/cost/cash/date remain manual.

## Consolidated summary

Portfolio Summary is a three-column formula view of the India and US tabs. B2 selects INR or USD; all amounts and currency labels follow the selection, while allocation percentages stay the same. No amounts or formulas need to be maintained in this tab. Existing source-tab inputs and the daily `update` command remain unchanged.

B15 uses `GOOGLEFINANCE("CURRENCY:USDINR")` for automatic conversion. The workbook recalculates on changes and hourly. Google controls the external quote's availability and timing; B16 is the calculation date, not a guaranteed quote timestamp. Missing rates or incomplete source totals display Unavailable instead of a partial portfolio total. Source refresh dates remain visible separately.

Mutual funds are identified by MF: tickers. The current gold allocation covers BATS:AAAU. If another ETF or a new asset class is introduced, its classification must be added; the current residual stocks calculation does not distinguish other ETF types.
