# tax-schema.md — capital-gains awareness and tax optimization (Module 9)

Status: built. The engine is [scripts/tax.py](../scripts/tax.py) (pure arithmetic
core + a thin yfinance fetch layer, the same shape as [nav.py](../scripts/nav.py)),
with [scripts/test_tax.py](../scripts/test_tax.py) (14 golden cases, all pass) and
the dated rates in [tax-rules.yaml](tax-rules.yaml). It is wired into the
orchestrator as the read-only `tax` command (SKILL.md command table; commands.md
§ tax). The India rates are from a current source (ClearTax, 2026, reflecting the
post-23-July-2024 regime) and are treated as the working numbers; the items under
"Still open" below need a CA before the book is filed from. The user is an Indian
resident; both sleeves are taxed under Indian rules, so there is one tax law to
encode.

## What this module does

It reads the ledger and does three things with the book's capital-gains tax.
It reports what has already been booked this Indian financial year, and under
which rule. It reports what is sitting on paper in each open lot, and how long
until it turns long-term. And it advises on how to lower the tax out-go — which
loss to harvest, which gain to match against it, which lot is days away from the
long-term rate — with the rupee saving on each move shown.

## One module, built in three stages

Each stage is usable on its own and feeds the next, so
the build can stop at any stage boundary and still be worth shipping.

### Stage 1 — Holding clock and the rule that applies (covers points 1 and 2)

Replay the ledger keeping each lot's buy date, buy price, and fees. For every
open lot: days held, and whether it is short-term or long-term *today*. For
every realized sell: which rule applied, decided by the sleeve and the holding
period.

| sleeve | long-term after | short-term | long-term |
|--------|-----------------|------------|-----------|
| India listed equity (STT paid) | > 12 months | 20% (s.111A) | 12.5% after ₹1.25 lakh/yr exemption (s.112A) |
| US shares (foreign, no STT) | > 24 months | slab rate | 12.5%, no exemption (s.112) |

Both rows are the verified post-July-2024 regime (ClearTax, CA-authored, 2026).
The US sleeve is taxed as ordinary "other assets," not under 111A/112A: the
24-month long-term clock is the standard rule for non-STT assets, short-term is
taxed at slab (confirmed: all assets outside listed equity are taxed at slab),
and long-term is the flat 12.5% s.112 rate without indexation. The one open
point is whether any DTAA credit changes the *effective* US rate — a filing
matter, flagged for the CA, not a change to the gross rule here.

For each realized sell the module stores the rule it used — clock, rate bucket,
exemption applied, and the source row — so the year's position is auditable and
a rerun is identical. The rule is read from the dated rules table below, never
hard-coded, and the chosen row is recorded on the sell.

#### Surcharge and cess turn the table rates into effective rates

The rates in the table above are **base** rates. Two add-ons sit on top before a
rupee figure is real. The engine reports the base-rate tax; the advice/chat layer
applies these once the user gives an income band:

- **Health-and-education cess: 4%** on (tax + surcharge), always.
- **Surcharge by total income:** 10% above ₹50 lakh, 15% above ₹1 crore, 25%
  above ₹2 crore, 37% above ₹5 crore (the new regime caps surcharge at 25%).
  **The catch:** surcharge on gains taxed under s.111A / s.112 / s.112A is
  **capped at 15%**, but foreign short-term gains are taxed at the *slab* as
  ordinary income (not s.111A), so they carry the **full** surcharge — a high
  earner can pay 25–37% surcharge on foreign STCG while the 15% cap shields the
  same year's foreign LTCG. Worked at the ₹50L–1Cr band (10% surcharge, 4% cess):
  foreign long-term effective = 12.5 × 1.10 × 1.04 = **14.30%**; foreign
  short-term at a 30% slab = 30 × 1.10 × 1.04 = **34.32%**. Never quote the bare
  12.5% / slab rate as the out-go.

### Stage 2 — Gains, losses, set-off and carry-forward (covers point 3)

The tax year is the Indian financial year, 1 April to 31 March, for *both*
sleeves — a resident reports worldwide gains on one Indian return, so the US
sleeve does not get its own calendar-year (Jan–Dec) clock. The US tax year is
irrelevant to this book; the only place it could matter is reconciling a US
broker statement, and that is a filing chore, not this module's job.

Group realized results by Indian financial year into four buckets: India
short-term, India long-term, foreign short-term, foreign long-term. Then apply
the rules for what nets against what and what survives into next year.

- **Set-off within the year.** A short-term capital loss offsets both short-term
  and long-term gains. A long-term capital loss offsets *only* long-term gains
  (confirmed, s.74).

  | loss type | sets off against     |
  |-----------|----------------------|
  | STCL      | STCG and LTCG        |
  | LTCL      | LTCG only            |

- **Carry-forward.** A loss not fully used this year is carried forward up to 8
  assessment years, but only if the return is filed by the original due date
  (confirmed, s.74). A carried short-term loss sets off against later short-term
  or long-term gains; a carried long-term loss against later long-term gains
  only. A *gain* is never carried — it is taxed in the year it is booked. The
  module tracks the running carry-forward balance across years.
- **Exemption.** The ₹1.25 lakh long-term listed-equity exemption is applied
  once per financial year, before the 12.5% rate.

### Stage 3 — The advice view (covers point 4)

This is the point of the module: given everything the book knows — every lot,
its clock, this year's realized gains, the exemption headroom — advise on how
to cut the tax out-go, ranked by the rupees saved.

- **Days-to-long-term countdown.** For each lot near its clock, the days until a
  sale would be taxed long-term instead of short-term, and the rupee tax
  difference between selling now and waiting. The recommendation: hold past the
  date when the saving is worth the market risk of waiting.
- **Loss harvesting.** Lots sitting at an unrealized loss whose sale would offset
  realized gains already taken this year, ranked by tax saved, respecting the
  set-off rules (a long-term loss only helps against long-term gains). The
  recommendation names the loss to book and the gain it cancels.
- **Gain/loss matching and exemption use.** The size of loss that brings the
  taxable long-term gain down to the ₹1.25 lakh free limit, so no tax is paid on
  gains the exemption would have covered; and a flag when realized long-term
  gains are still under the limit, where booking a little more gain is free.
- **Set-off ordering.** A short-term loss may be set against either short-term
  or long-term gains — direct it against the **highest-taxed** gain first (a
  slab-rate foreign STCG before a 12.5% LTCG), which saves the rate difference on
  the whole loss. Name the rupee gap between the good and the naive order.
- **Surcharge-threshold timing.** When a large realization would push total
  income past a surcharge step (₹50L / ₹1Cr / ₹2Cr / ₹5Cr), splitting it across
  two financial years to stay under the line can save more than any lot choice.
  Flag the threshold and the year-split when realized gains approach it.
- **Specific-lot identification.** When recommending a trim, name the exact lots
  (date acquired + shares + cost basis) so the broker sells the intended tax
  lots. FIFO is only the default; the tax-optimal set is usually the loss lots
  plus the lowest-gain long-term lots, not the oldest.

This layer recommends — it names the move and the saving. What it does not do is
act: it never places a trade, never files anything, and flags that a harvested
holding bought straight back has no Indian wash-sale bar today (VERIFY) but is
still a market-timing call the user owns. The number and the suggestion are the
module's; the decision and the CA sign-off stay with the user.

## The rules table (how the numbers are stored)

Rates, clocks, and the exemption live in [tax-rules.yaml](tax-rules.yaml), one
block per regime (`india_listed_equity`, `foreign_equity_resident`) plus a
`general` block, each row dated by `effective_from` and carrying its source.
`scripts/tax.py` reads the file with a small stdlib parser (no PyYAML, matching
the portability discipline of [validate_assumptions.py](../scripts/validate_assumptions.py)).
Changing a rate means editing the table, never the logic. The engine refuses to
rate a sale dated before a regime's `effective_from` rather than guess an older
rate. The set-off matrix (Section 74) is fixed law, so it lives in the engine,
not the table. This is what "store the thresholds that apply" means: the rule is
data, recorded against each sell.

## Cost basis and corporate actions

- **Lot matching.** The headline number matches each sell to the oldest open lot
  first (FIFO, the usual Indian demat default). A cross-check matches each sell
  to the specific lot its ledger line names; the report shows both and flags any
  disagreement.
- **Splits.** A split scales each open lot's shares and per-share cost in step
  (total cost unchanged) and keeps the original buy date, so the holding clock is
  unaffected.
- **Bonus shares.** Treated as nil cost of acquisition with the holding clock
  starting at allotment (Section 55(2)(aa)). The report notes this and flags it
  for the CA.
- **US gains in INR.** Cost is converted at the buy-date rate and proceeds at the
  sell-date rate. The report states this convention; confirm the prescribed rate
  with a CA. See the traps below.

## Foreign-currency lots — three traps the broker statement sets

A resident's US (or any foreign) shares are taxed in **rupees**, and the broker
statement is in dollars. Three general traps follow, none specific to any one
book:

1. **The native-currency gain/loss column is not the taxable figure — and can
   have the opposite sign.** Recompute every lot in INR: cost at the
   acquisition-date rate, proceeds at the sale-date rate. Because the rupee has
   trended weaker, a lot that shows a **loss in dollars can be a gain in rupees**
   (the sale-date rate lifts the proceeds leg more than the cost leg), and a
   strengthening rupee does the reverse. Loss-harvesting is judged on the INR
   sign, never the broker's dollar column.
2. **The broker's "holding period / long-term" flag is that country's rule, not
   India's.** A US broker marks a lot long-term after **12 months**; India's
   foreign-share clock is **24 months**. Reclassify every foreign lot on the
   24-month test before bucketing — lots the broker calls "Long" are routinely
   still short-term for the Indian return.
3. **The prescribed rate is the SBI TT buying rate on the relevant date**
   (Rule 115), not the interbank/market rate. A market rate (yfinance and the
   like) is an **estimate** — fine for planning, not for filing — and historical
   SBI TTBR is not cleanly fetchable, so flag the gap rather than fabricate a
   rate.

## Out of scope

- Advance-tax estimate. Needs full-income data the book does not hold.
- Dividend tax, STT, and other transaction taxes. Recorded in the ledger, not
  computed here.
- US tax. The user is an Indian resident; US capital-gains tax does not apply to
  this book. US dividend withholding and any treaty credit are a tax-filing
  matter the engine does not compute — the awareness facts (Form 67, W-8BEN,
  1042-S) are recorded under "Cross-border filing awareness" below.
- Filing, forms, and any standalone "what should I do" answer divorced from the
  numbers. Out of scope for good — that is tax advice.

- Filing and forms. Veda never files. The advice view always attaches the rupee
  figure and the CA caveat; a bare "what should I do" with no numbers is not the
  product.

## Cross-border filing awareness (US brokers — gains, dividends, the forms) — not computed here

The engine computes India capital-gains tax only. It does **not** compute the
dividend / foreign-tax-credit side and files nothing, but the advisor is asked
about the mechanics often enough that they are recorded here as **awareness** —
always with the "not a chartered accountant — verify before filing" caveat,
never as a filing instruction. **Every US broker is handled the same way and
each account is treated on its own:** Fidelity and Vested (and any other US
broker) each need their own US certification and each issue their own year-end
statement, but all of it lands on **one** Indian return.

### What each form is, by side and by income type

| | **US side** | **India side** |
|---|---|---|
| **Set up / certify** | **W-8BEN** to each broker (not the IRS): certifies Indian residency, claims the DTAA 25% dividend rate vs 30%. Uses your **PAN** as the foreign TIN. **Expires end of the 3rd calendar year** after signing — renew, or a lapse reverts to 30% / 24% backup. | PAN + the income-tax e-filing login; no separate US-facing setup. |
| **Dividends** | Withheld at source (25% under DTAA Art. 10). You **receive Form 1042-S** from each broker (the nonresident 1099) — proof of income and tax withheld. Nothing is filed in the US. | Report the dividend (Income from Other Sources); claim the US tax withheld as a **Foreign Tax Credit** via **Form 67** (Rule 128), reported in **Schedule FSI** + **Schedule TR**. Credit = lower of the Indian tax on it or the US tax paid. |
| **Capital gains / losses** | **Not US-taxable** for a nonresident alien (unless in the US 183+ days, effectively-connected income, or a US real-property interest). No US form, no withholding — the statement shows "backup withholding: 0". | Compute in **rupees** (per-date FX, 24-month clock — the `tax.py` engine). Report gains in **Schedule CG**; losses in **Schedule CFL** to carry forward. |
| **Holdings disclosure** | — | **Schedule FA** — every foreign holding across **both** brokers, mandatory for a resident regardless of any gain. |
| **Do NOT** | file a **W-9** (that is for US persons) or expect a 1099; a **1040-NR** arises only to reclaim excess / backup withholding or for US-connected income. | file ITR-1 (no Schedule FA/CG) — use **ITR-2**, or ITR-3 if there is business income. |

**How Form 67, Schedule FSI, Schedule TR and Schedule FA fit together.** They do
four different jobs:

- **Schedule FA** — pure *disclosure* of the foreign holdings (ownership),
  mandatory even with zero income or tax. (It reports the calendar-year holding —
  a period quirk to check.)
- **Schedule FSI** — declares the foreign *income* and the foreign *tax paid* on
  it, country by country (US = country code 2).
- **Schedule TR** — totals the *relief* (the foreign tax credit) drawn from FSI.
- **Form 67** — the standalone online statement (Rule 128) that *unlocks* that
  relief; it must be filed **before / with** the return, or the FTC can be denied.

Routing by income type: US **dividends** bore US tax, so they flow to **FSI →
TR → Form 67** (to claim the credit) and also sit in Schedule OS. US **capital
gains** bore **no** US tax, so there is nothing to relieve — they go to
**Schedule CG** only, with the shares still disclosed in **Schedule FA**. Chain:
Form 67 first → FTC → detailed in FSI → summed in TR → reduces the India tax;
FA runs alongside as disclosure.

### The process, step by step

**US side — once per account, then every ~3 years:**
1. In each broker portal (Fidelity, then Vested), open the tax-certification / W-8BEN section and submit it: legal name, country **India**, foreign TIN = **PAN**, address, and claim treaty benefits (Article 10, 25%). Sign and date.
2. Confirm withholding drops to 25% on the next dividend (a Fidelity statement already showing 25% means its W-8BEN is live; check Vested the same way).
3. Set a **renewal reminder** for the end of the third calendar year.
4. Each year (~March), **download the 1042-S** from each broker and keep it as the FTC proof.

**India side — every financial year:**
1. Pull from **both** brokers: realized gains/losses per lot (in INR), dividend income and US tax withheld, and year-end holding values for Schedule FA.
2. **File Form 67 online before / with the ITR** (verify the current Rule 128(9) deadline — it has been amended).
3. File **ITR-2/3** with Schedule CG (gains), Schedule CFL (losses to carry), Schedule OS/FSI (dividends), Schedule TR (FTC), Schedule FA (all foreign holdings).

### Reminders Veda must surface to the user

- **Losses carry forward up to 8 assessment years — but only if the return is filed by the original due date** (section 139(1)); a belated return **forfeits** the carry-forward (in-year set-off still applies). A short-term loss carries against future short- **or** long-term gains; a long-term loss against future long-term gains **only**, and it must be reported in **Schedule CG / CFL** of the loss year to survive. **File on time to keep the loss alive**, and each later year re-enter the brought-forward loss so it is actually used.
- **Schedule FA is mandatory** for a resident holding any foreign asset — omitting it carries Black Money Act penalties, independent of any tax due. Remind every year, for both brokers.
- **W-8BEN is per broker and expires ~every 3 years** — renew both Fidelity and Vested, or withholding jumps back to 30%.
- **Form 67 goes in before / with the ITR**, not after.
- **RSU / ESPP vesting** can carry its own US-workday sourcing rules, separate from dividends and sales — a CA question.
- **Not a chartered accountant** — verify the current rules and your facts before filing.

## Return-filing checklist (awareness — Veda never files)

A resident files **one** ITR covering worldwide income. This is the
document-and-schedule gathering list for that return — awareness only, not
computed by the engine, always under the "not a chartered accountant — verify
before filing" caveat. **Regime matters first:** under the **new regime** most
Chapter VI-A deductions (80C, 80TTA, 80CCD(1)/(1B), and the PPF / EPF / NPS
*employee* contributions) are **not** available — only employer NPS 80CCD(2)
and the standard deduction — so the deduction rows below apply mainly to the
**old** regime. Confirm the regime before relying on any deduction.

| Source | Document to gather | Where it goes on the ITR |
|---|---|---|
| **Salary (employer)** | **Form 16** + Form 12BA (perquisites, incl. RSU / ESPP value at vest) | Schedule S (salary); perquisite already inside Form 16 |
| **Employer computation** | **Tax Computation Sheet** | cross-check TDS and perquisite against Form 16 |
| **Master reconciliation** | **Form 26AS + AIS / TIS** (e-filing portal) | reconcile every TDS, dividend and interest **before** filing |
| **Bank interest (HDFC)** | Interest certificate (savings + FD); FD TDS in 26AS | Schedule OS; 80TTA on savings interest (old regime only) |
| **PPF** | Passbook / statement | interest **exempt** → Schedule EI; contribution 80C (old regime only) |
| **EPF** | Passbook / annual statement | via Form 16 / Schedule S; interest exempt, but interest on employee contribution above Rs 2.5L/yr is taxable; contribution 80C (old regime only) |
| **NPS** | Contribution / transaction statement | 80CCD(1)+(1B) employee (old regime only); **80CCD(2) employer — both regimes** |
| **Zerodha (India equity)** | Tradewise **Capital Gains** statement; **dividend** summary | Schedule CG (STCG s.111A 20%, LTCG s.112A 12.5% after Rs 1.25L); dividends → Schedule OS |
| **Fidelity + Vested (US equity)** | Realized / open-lots **Capital Gains** (→ INR via `tax.py`); **dividends** + **1042-S** | Schedule CG (foreign, 24-month clock); dividends → Schedule OS + FSI; US tax → **Form 67** + Schedule TR |
| **All foreign holdings** | Fidelity + Vested year-end statements | **Schedule FA** (mandatory, both brokers) |
| **Carried-forward losses** | prior-year return / CFL schedule | Schedule CFL — only if each loss year's return was filed on time |

**If you traded F&O or intraday** this year, that is **business income**
(Schedule BP, **ITR-3**), taxed at slab — not capital gains — and can trip
tax-audit thresholds; a CA question. Otherwise a salaried resident with capital
gains and foreign assets files **ITR-2**.

Sequence: reconcile Form 16 + 26AS / AIS first; compute the two capital-gains
sleeves (India via the ledger, US via the open-lots path); file **Form 67 before
the ITR**; then file the return with every schedule above. **File by the due
date** to preserve any carry-forward loss.

## Decisions (made)

1. One staged module, not v1/v2 — built as a single module with all three stages
   shipped (holding clock, set-off / carry-forward, advice).
2. Advice line — "advise, don't act": Stage 3 recommends the move with the rupee
   saving, but never files and never places a trade, and every answer carries the
   "not a CA — verify" line. SKILL.md Hard Rule #7 and Stage 0 were amended to put
   tax optimization *on the user's own book* in scope.
3. Lot matching — FIFO is the headline; the named-lot view (the ledger's `lot_id`)
   is the cross-check, shown beside it with any disagreement flagged.
4. Home — this file is the contract; the engine is [scripts/tax.py](../scripts/tax.py),
   matching [ledger-schema.md](ledger-schema.md) and [nav-schema.md](nav-schema.md).

## Still open (CA sign-off gate)

The core rules are now sourced from current CA-authored material (ClearTax,
2026) and treated as confirmed: the India listed-equity numbers (> 12-month
clock, 20% STCG, 12.5% LTCG after ₹1.25 lakh); the foreign-share treatment
(> 24-month clock, slab short-term, 12.5% long-term under s.112); and the loss
rules (STCL offsets STCG and LTCG, LTCL offsets LTCG only, 8-year carry-forward
if the return is filed on time, s.74). Still open:

- Whether any US DTAA credit changes the *effective* tax on the US sleeve (a
  filing matter, but worth the CA's note).
- Whether FIFO is required for demat-held listed shares.
- Which date's exchange rate applies to a foreign gain, in INR — the prescribed
  convention is the SBI TT buying rate (Rule 115) on the relevant date, but
  whether that is a per-date rate on each acquisition and sale or a single
  Rule-115 month-end rate on the net gain is a CA call that moves the number.
- Whether any Indian wash-sale-style bar applies to a harvested-and-rebought
  holding (assumed none today).

## Where it plugs in

The engine ([scripts/tax.py](../scripts/tax.py)) replays the ledger keeping each
lot's buy date, buy price, and fees, matches each sell to its lot (FIFO headline,
named-lot cross-check), classifies it under the dated rules table, and runs the
set-off and carry-forward. Module 2 (NAV) and the concentration view drop this
lot-level detail; this is the first module to read it. It is a read-only,
reconcile-first ledger view like `performance` and `concentration`, run via the
`tax` command. The arithmetic core takes prices, the exchange rate, and the
parsed rules as plain arguments, so the tests feed fixed numbers; only the
command-line run fetches current prices and the USD/INR rate from yfinance for
the unrealized and advice views. US short-term gains are taxed at the user's
income slab, which the book does not hold — pass `--slab-rate` to include them,
else the report shows the gain and leaves its tax out.
## Broker open-lots path (pasted statements)

The views above replay the ledger. When the input is instead a pasted broker
open-lots export - a Fidelity "View open lots" CSV, which already carries each
lot's cost and current value - the same engine runs a second entry point:
`python scripts/tax.py --open-lots <file> --market us --ticker MSFT`. It
reconverts every lot into rupees at per-date FX, reclassifies each on the Indian
24-month clock (ignoring the broker's 12-month "Long" flag), lifts the base
rates by `--surcharge` / `--income` and `--cess` into effective rates, and -
given `--target-weight` and `--other-book` - ranks a least-tax trim (loss lots
first, then the lowest-gain long-term lots), directing harvested short-term
losses at the highest-taxed prior gains (`--prior-foreign-st` and the like).
No price fetch is needed (the statement carries value); only USD-INR is fetched.
Pure core: `build_statement_report`; golden cases in `scripts/test_tax.py`.
## Checks

`scripts/test_tax.py` runs golden cases with fixed prices, dates, and rule rows,
so the math is pinned and reruns are identical: a short-term India sell, a
long-term India sell crossing the ₹1.25 lakh exemption, a foreign short-term
sell taxed at slab, a foreign long-term sell, a short-term loss offsetting a
long-term gain, a long-term loss restricted to long-term gains only, a loss
carried into the next financial year, a days-to-long-term countdown on an open
lot, and a harvesting recommendation ranked against a realized gain.
