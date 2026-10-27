---
name: portfolio-review
description: Review Ankur's overall portfolio, then research Indian and US stocks independently and recommend Buy, Hold or Sell using personal conviction, valuation, exit rules and portfolio limits, with separate cash-only funding for each market.
---

# Portfolio review

Start with the overall portfolio, drill into India and US holdings, and bring the findings back into a holistic allocation and risk assessment. Give a My Action value of **Buy, Hold or Sell for every stock in scope**, with evidence. Assess buying opportunities as well as exits. Keep suggestions in chat.

## Inputs and evidence

Workbook entry point (Portfolio Summary): https://docs.google.com/spreadsheets/d/1vyQj_XqcAgfgwNxgBVTxP8Yps0jxYJic8dA_ltTb_2E/edit?gid=941942549#gid=941942549

Default to both India Portfolio and US Portfolio. If the owner explicitly names one market or a narrower set of stocks, respect that scope. Review every held stock in the selected tabs, including holdings across US brokers. Read metadata, locate columns by header, and read relevant cell notes using available Google Sheets tools. Use holdings, prices, market values, P/E, manual sectors, broker cash, My Thesis Conviction, My Sell Condition, personal thesis/assumption notes and any explicit owner decisions. Existing My Action values are owner context, not a substitute for assessment. Missing purchase cost does not exclude a stock from review; leave affected return calculations unassessed.

## Overall portfolio first

Read Portfolio Summary first: total value, India/US split, stocks/funds/gold/cash allocation, display currency, USD/INR rate and calculation date, and source refresh dates. Then read the underlying India Portfolio and US Portfolio tabs and reconcile their totals with the summary. The FX calculation date is not a provider quote timestamp. If FX or a source total is unavailable, qualify the consolidated assessment and continue the market reviews where their inputs permit.

Use the same exchange rate to express market values in one reporting currency and calculate overall stock and sector weights against all investments plus broker cash across both markets. Identify material concentration and overlapping sector, issuer or business exposures across the markets; aggregate duplicate issuer exposure only when identity is verified. Use the owner's sector labels, disclose unmapped or inconsistent labels, and do not invent fund look-through exposures. The India/US split identifies portfolio buckets, not each business's geographic exposure.

After the company reviews, assess how proposed buys and trims would change the overall mix, concentration and cash allocation. Report both overall and market-level implications. Do not invent target country allocations or consolidated concentration limits: the approved market-specific limits and separate cash budgets remain in force.

## Research inputs

Exclude StockClarity Thesis Status, StockClarity Signal, scores and assessments. Do not query its database or require its coverage or grades. Owner-approved thesis notes remain personal context even if originally copied from that system. Do not launch another repository's review workflow or import its unapproved policies.

Check underlying price/NAV, holdings, cash and fundamentals dates in the Last Refreshed note. Sync time is not their common source date. Distinguish actual results, management guidance, owner assumptions and your estimates. Never invent a thesis, forecast or source, or silently convert revenue growth into earnings growth.

## Company research context

Use `veda-new-research` as the source of detailed company research. Resolve `../veda-new-research` relative to the Veda-advisor checkout root, not the shell's working directory. If an isolated worktree or different layout has no sibling checkout, use an explicitly supplied research-root path. Verify read access; this skill does not grant it. Read the research in place without copying KBs, adding a register/database or changing either repository's research files.

For each holding, match the verified legal issuer, exchange/ticker and market against the KB's issuer record and authoritative identifiers; a similar name, folder name or ticker alone is not sufficient. If the match is ambiguous, do not use that KB: disclose the issue and continue the full independent research process. Do the same independent research when no KB exists or the research checkout is inaccessible; missing KB coverage is not an action signal.

For a verified match, read the relevant `companies/<identifier>/Company_KB.md`, `Research_Audit.md` and `Source_Inventory.md` where present. Identify the KB cutoff, last information update, comprehensive reassessment, dated company assessment and reference price; examine the relevant thesis assumptions, contradictions, source limitations and unresolved gaps. A later Audit addition or file modification date does not make the KB current. Use the inventory to resolve cited evidence and original sources; disclose missing or inaccessible supporting material without upgrading verification claims. Reading these files is permitted research context, not permission to launch MONITOR/UPDATE or import another repository's portfolio policies.

Use this dated evidence alongside fresh investigation for every company. Independently verify current prices, valuation, latest released results, subsequent filings and material developments under the existing research requirements. Retain contrary evidence and explain material disagreements between the KB and current findings; never substitute a stored assessment for current valuation or an exit check.

Keep the dated company-level **BUY/HOLD/SELL assessment** separate from the current portfolio-level **suggested Buy/Hold/Sell action**. Explain the latter using fresh evidence and the existing personal conviction, valuation, exit, concentration, allocation and cash-funding rules; do not mechanically translate the company conclusion into a portfolio action or change the owner's conviction or sell conditions. Cite the research file/section and cutoff alongside decisive current source links in the existing Evidence and reason column, including material limitations. Keep recommendations in chat: do not automatically write My Action, conviction, sell conditions, notes, quantities or cash, refresh the portfolio, modify StockClarity, or update company research.

## Independent research before recommendations

On every review, independently browse for **every company in scope** before finalising Buy, Hold or Sell, including Low-conviction holdings that need exit assessment. Do not reuse a previous recommendation without fresh checks or substitute the sheet, StockClarity, search snippets or a single aggregator for research. Use public company identifiers in queries; keep private portfolio information out of searches.

For each company:

- **Latest results and trend:** establish the latest results actually released as of the review date, including any new quarter or half-year. Read the issuer or exchange results and relevant presentation/transcript; compare revenue, operating margins and earnings with comparable periods and the owner's assumptions. Check the latest annual report/auditor's report for relevant qualifications or governance issues. Separate consolidated from standalone figures, operational earnings from other income/exceptionals, and organic growth from acquisitions. Respect the owner's metric definitions and horizons.
- **Filings and material events:** for Indian stocks, check NSE/BSE and issuer announcements; for US-listed stocks, check SEC EDGAR and issuer investor-relations filings, using the issuer's applicable reports (for example, 10-K/10-Q/8-K or foreign-issuer 20-F/6-K). Check events after the latest results. A US listing does not imply a US-incorporated issuer. Investigate developments relevant to the company and exit rules: auditor changes/qualifications, regulatory or legal actions, promoter pledges or transactions, dilution, capital allocation, acquisitions, order cancellations, execution delays or customer concentration. An announcement or allegation alone does not establish misconduct or a broken thesis.
- **News and independent views:** search credible recent reporting and relevant external analysis, including a contrary case. Verify material claims against filings, regulator records or other primary evidence where available. Treat analyst reviews and management commentary as viewpoints to assess, not votes to follow. Distinguish publication dates, event dates and reporting periods; do not treat recycled news as a new event. If credible independent coverage is unavailable, state that without inventing a consensus.
- **Financial and valuation checks:** examine available cash conversion, receivables/working capital, debt/liquidity, earnings quality and business-specific risks. Use the reporting period actually available; cash-flow statements need not exist for every quarter. Reconcile material valuation discrepancies and corporate actions such as bonuses or splits before relying on P/E or growth comparisons. Explain why the current price does or does not justify adding, rather than treating a low P/E as sufficient evidence.

Follow up adverse evidence and plausible buying cases in greater depth. Missing personal thesis notes do not excuse skipping company research; label any independently formed investment case as your assessment, not the owner's original thesis.

Open and read supporting sources, not just their search summaries. If a primary document fails, try an official exchange/issuer alternative and visual inspection for scanned financial tables where supported. After reasonable alternative attempts, disclose the specific gap and its decision impact. Research access failures are not evidence of an exit breach, and avoidable missing research must not become a blanket Hold recommendation. Never claim all exit conditions passed or that there is no adverse news when relevant checks remain incomplete.

Keep the output concise: give each stock dated source links for its decisive evidence and identify whether material checks are complete or limited. Link additional supporting detail only where it changes the action. If browsing is unavailable, disclose that the independent review could not be completed and qualify affected actions; do not present them as fully researched recommendations.

## Decision process

Evaluate exits first, buying second, and funding/portfolio fit before finalising actions. Explain each recommendation using conviction, valuation, relevant business evidence and portfolio fit; there is no automatic conviction-to-action mapping.

### Sell and trim rules

Apply the latest explicit owner instructions and recorded company conditions.

- **Integrity concerns:** identify concrete evidence and the owner's judgement; do not infer wrongdoing from a model signal, price fall or financing event.
- **Personal thesis broken or played out:** compare evidence with recorded assumptions and horizons. A review flag is not automatically a broken thesis. Endpoint CAGR targets are not quarterly floors. Astra's March 2027 date is a review deadline, not a mandatory exit. Zen's >30% operational EBITDA margin condition concerns sustained deterioration undermining the thesis, not an automatic quarterly exit (owner clarification, 24 October 2026).
- **P/E >150:** strong sell presumption, subject to rare, explicitly documented growth exceptions. **100<P/E<=150:** preferred sell, subject to growth judgement. Surface any exception and its evidence; do not silently assume one. An exception permitting Hold does not itself authorise additional buying.
- **Stock weight >25% or sector weight >35%:** propose a partial trim towards the limit, not a full exit solely for concentration.
- **Better opportunity:** a subjective comparison requiring a specified alternative and evidence. Under cash-only purchase funding, do not originate a sale or fund redemption to finance an otherwise attractive purchase. Independent exit-rule sells and concentration trims still apply.

Low conviction, a blank action, a missing thesis note or missing research coverage is not by itself a Sell trigger. High conviction does not override an evidenced exit rule. A generic list of sell conditions is not evidence that those events occurred.

### Buy/add assessment

The owner approved these policies on 24 October 2026:

- **High or Medium conviction may qualify for Buy.** Prefer High; require stronger corroboration and a more compelling valuation case for Medium. **Low conviction is not eligible for adding** unless the owner revises that judgement; it does not imply Sell.
- **Use current broker cash only.** Do not propose sales, fund redemptions, proposed sale proceeds, leverage or new deposits to fund purchases.

Recommend Buy only when there is a positive, evidenced case for adding at the current price: the personal thesis/business case is supported, valuation offers a defensible return relative to growth and risk, no unresolved material exit concern takes priority, and a feasible funded addition fits portfolio limits. Fair valuation may support Buy where durable growth and business quality justify it; low P/E alone does not.

Use suitable valuation measures for the business: earnings and cash conversion, balance-sheet risk, growth quality, relevant historical/peer valuations or other appropriate measures. Disclose comparability and cyclical/exceptional-earnings issues. Missing or negative P/E is unassessable on that measure, not cheap. P/E below 100 merely avoids the encoded P/E sell band; it is not a buy threshold. Do not invent hard PEG cutoffs, return hurdles or numeric conviction scores. A growth assumption must have a source, basis and horizon.

Investigate plausible High-conviction add candidates and compelling Medium-conviction candidates before concluding there are no Buys. Rank candidates by conviction, valuation case, supporting evidence and portfolio fit. Do not recommend Buy for every eligible stock or force a Buy to produce a mixed list.

### Hold

Recommend Hold where retaining the existing position is supported but an addition or sale is not justified now: for example, acceptable business evidence but insufficient valuation upside, Medium conviction without enough evidence to add, Low conviction without an exit trigger, or a buy candidate deferred by cash or concentration constraints.

If a decisive fact cannot be verified, use **Hold, provisional** in the explanation, with My Action still **Hold**. Identify the specific unresolved fact and what would change the decision. Do not present provisional retention as a positive business endorsement or claim the exit rule passed. Do not replace every action with Review because information is incomplete.

## Allocation and funding

Calculate weights separately for each market using its investments plus its broker cash: India includes stocks and mutual funds; US includes stocks and ETFs across its brokers. Use INR for India and USD for US. Keep cash budgets separate and do not assume cross-market transfers. The consolidated assessment is required for a review covering both markets, but the summary's display-currency selection does not change these market-specific concentration denominators or purchase budgets. Use the owner's sector labels and identify ambiguity.

Separate valuation attractiveness from portfolio suitability. Allocate the shared starting broker cash across proposed Buys once, leaving room for applicable costs. Do not count cash again for each candidate, assume all cash must be spent, or treat concentration ceilings as target allocations. If a proposal needs a target size, explain it as a discretionary proposal, not an approved standing rule. An attractive candidate without a feasible funded addition stays Hold with its priority explained.

Show proposed amounts/units, remaining cash and resulting stock/sector weights when recommending trades. Check whole-unit/lot constraints and post-trade limits. Purchases funded from cash, and sales retained as cash, leave total value unchanged before costs. Do not double-count overlapping stock/sector trims. Proposed sale proceeds are excluded from this run's purchase budget.

Mutual funds and ETFs count in their market's denominator. Do not apply company P/E or single-stock rules directly to funds or ETFs; use only recorded instrument-specific conditions. Do not add cash-reserve targets, equal weights, stock-count limits, stop-losses or minimum position sizes without owner approval.

## Output and boundaries

Lead with the overall portfolio outcome: total value in the reporting currency, India/US and asset/cash mix, material combined concentrations or shared risks, and the principal implications of the proposed actions. Then present separate India and US per-stock tables, exit-rule results, and portfolio balance/funding assessments when both markets are in scope. Explicitly identify any stock or overall exposure that could not be fully assessed. Always include:

1. **Per-stock table:** Stock | My Thesis Conviction | Suggested My Action | Evidence and reason. My Action must be exactly Buy, Hold or Sell. Put valuation context, dated source links and material limitations in the reasons, including any incomplete independent checks. For Sell, state whether it is a full exit or partial trim. For provisional Hold, say why.
2. **Exit-rule result:** identify actual breaches, unresolved owner judgements and documented exceptions. Distinguish unassessed conditions from conditions checked and not breached.
3. **Portfolio balance and funding:** Within approved limits, Outside approved limits, or Cannot fully verify; show largest stock/sector weights, any proposed corrections, and the cash-only purchase plan when Buys are recommended.

Do not mechanically produce all Hold because entry thresholds are not numeric; make the evidence-based judgement requested. An all-Hold result is valid only when the assessment supports it, with provisional cases clearly qualified. Do not guarantee returns or fabricate precise upside.

Keep everything in chat. Do not change My Action, conviction, notes or Review Reason, refresh holdings, change StockClarity or place orders. If the owner explicitly asks to save selected decisions, write only those agreed cells and verify them. Never send private holdings, balances, notes or credentials to public research services.