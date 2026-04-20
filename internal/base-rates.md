# Base rates — source hierarchy and canonical examples (reference)

This file is loaded on demand by SKILL.md Stage 4 when stating a base rate. The two every-turn discipline rules (no invented percentages; widen to a range for Tier 4–5) live in SKILL.md; this file holds the source hierarchy and the canonical examples.

---

## Where the base rate comes from (priority order)

1. **Academic studies or published research** cited with source and year. "Stocks down >50% from highs continue underperforming for 12+ months in ~60% of cases (Jegadeesh & Titman 1993; confirmed in subsequent decade studies)." Only use this tier if you genuinely recall the source. Do not invent citations.
2. **Investor writings from the 11 in [CREDITS.md](../CREDITS.md).** Marks on cycles, Lynch on turnaround success rates, Klarman on value-trap rates — cite the book/letter and year.
3. **Widely-understood base rates in the canon** (IPO underperformance in year 1, M&A close rates, SPAC returns). Cite as "widely-documented" or "standard industry base rate" — still fine to use, but say so.
4. **General knowledge, not researched.** If you're reasoning from first principles or pattern-matching without a specific source, say so explicitly: *"General base rate, not researched for this specific situation. Verify before high-stakes action — this is the kind of number the `base-rate-researcher` subagent will replace."* Express the rate as an **unbounded or wide range** (e.g., "roughly 20–40%", "likely between a third and a half"), **never a point estimate**. Record `base_rate_confidence: LOW` and carry it to Stage 7.
5. **Nothing.** If you cannot find or reason to a base rate for this specific situation, say so: *"I don't have a reliable base rate for this. Proceeding without an outside view — the recommendation rests entirely on the inside-view framework analysis, which is weaker."* Record `base_rate_confidence: NONE`.

## Examples of legitimately useful base rates

- Turnarounds succeed ~20–30% of the time (Lynch, *One Up on Wall Street*, ch. 9 — labels them "the longest of long shots").
- Stocks down >50% from highs continue underperforming for 12+ months in ~60% of cases (widely-documented momentum-of-losers effect).
- M&A deals close at announced terms ~70% of the time (standard merger-arb base rate).
- IPOs underperform the market in year 1 ~60% of the time (Ritter, ongoing IPO studies).
- New-fund managers in the top quartile have ~25% probability of staying there over 5 years (persistence studies).

If the situation isn't one of these canonical ones, you are almost certainly in tier 4 or 5 above. Label it accordingly.
