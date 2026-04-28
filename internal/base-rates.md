# Base rates — source hierarchy and canonical examples (reference)

This file is loaded on demand by SKILL.md Stage 4 when stating a base rate. The two every-turn discipline rules (no invented percentages; widen to a range for Tier 4–5) live in SKILL.md; this file holds the source hierarchy and the curated entries.

---

## Where the base rate comes from (priority order)

1. **Academic studies or published research** cited with source and year. "Stocks down >50% from highs continue underperforming for 12+ months in ~60% of cases (Jegadeesh & Titman 1993; confirmed in subsequent decade studies)." Only use this tier if you genuinely recall the source. Do not invent citations.
2. **Investor writings from the 11 in [CREDITS.md](../CREDITS.md).** Marks on cycles, Lynch on turnaround success rates, Klarman on value-trap rates — cite the book/letter and year.
3. **Widely-understood base rates in the canon** (IPO underperformance in year 1, M&A close rates, SPAC returns). Cite as "widely-documented" or "standard industry base rate" — still fine to use, but say so.
4. **General knowledge, not researched.** If you're reasoning from first principles or pattern-matching without a specific source, say so explicitly: *"General base rate, not researched for this specific situation. Verify before high-stakes action."* This tier applies when the `base-rate-researcher` subagent has returned `status: not_found` (no Tier 1–3 source within its 3-operation budget) or the orchestrator is running inline without subagent isolation. Express the rate as an **unbounded or wide range** (e.g., "roughly 20–40%", "likely between a third and a half"), **never a point estimate**. Record `base_rate_confidence: LOW` and carry it to Stage 7.
5. **Nothing.** If you cannot find or reason to a base rate for this specific situation, say so: *"I don't have a reliable base rate for this. Proceeding without an outside view — the recommendation rests entirely on the inside-view framework analysis, which is weaker."* Record `base_rate_confidence: NONE`.

The `base-rate-researcher` subagent ([internal/agents/base-rate-researcher.md](agents/base-rate-researcher.md)) covers Tier 1–3 only. Tier 4 (general-knowledge hedged-range) and Tier 5 (NONE) remain the orchestrator's responsibility per the discipline rules in SKILL.md Stage 4.

---

## Schema for structured entries

Both sections below use the same per-entry format. The subagent reads both, writes only to `## Researched`. Each entry is a Markdown sub-heading followed by a fenced YAML block.

```
### <situation_type>_<geography_or_global>
```yaml
situation_type: <snake_case label, e.g., turnaround_success>
geography: <US | India | UK | Singapore | Global>
time_horizon: <string, e.g., "1y", "3y", "multi-year">
range_low: <number 0-100>
range_high: <number 0-100>
point_estimate: <number | null>   # only when the source itself states one
source_tier: <1 | 2 | 3>
citation: <author + work + year>
url: <string | null>
last_verified: <YYYY-MM-DD>
ttl_days: <integer>               # 1825 / 365 / 90 by ttl_class
ttl_class: <methodology_canonical | annually_updated | cycle_sensitive>
notes: <string | null>
```
```

**TTL classes:**

- `methodology_canonical` — `ttl_days: 1825` (5y). Investor-canon books and chapter-level rules; the number doesn't shift, you're caching a citation.
- `annually_updated` — `ttl_days: 365` (1y). Academic studies the author refreshes on a known cadence (Ritter, NBER trackers).
- `cycle_sensitive` — `ttl_days: 90`. Base rates that genuinely shift with the rate regime, sentiment, or recent structural changes (post-runup forward returns, current-cycle SPAC outcomes).

The subagent treats an entry as a cache hit only when `today - last_verified < ttl_days`. Stale entries are not deleted — fresh research appends a new entry alongside, and the human curator reconciles on the next manual pass.

---

## Canonical (human-curated)

Edited by humans only. The subagent reads these as cache entries but never writes to this section. If the subagent's web research contradicts an entry here, the contradicting finding is appended to `## Researched` with a `notes` field flagging the discrepancy.

### turnaround_success_global
```yaml
situation_type: turnaround_success
geography: Global
time_horizon: multi-year
range_low: 20
range_high: 30
point_estimate: null
source_tier: 2
citation: "Lynch, One Up on Wall Street, ch. 9 (1989)"
url: null
last_verified: 2026-04-28
ttl_days: 1825
ttl_class: methodology_canonical
notes: "Lynch labels turnarounds 'the longest of long shots'."
```

### post_50pct_drawdown_forward_returns_global
```yaml
situation_type: post_50pct_drawdown_forward_returns
geography: Global
time_horizon: 12m
range_low: 60
range_high: 60
point_estimate: 60
source_tier: 1
citation: "Jegadeesh & Titman (1993); confirmed in subsequent decade studies"
url: null
last_verified: 2026-04-28
ttl_days: 1825
ttl_class: methodology_canonical
notes: "Stocks down >50% from highs continue underperforming for 12+ months in ~60% of cases (momentum-of-losers effect)."
```

### ma_close_rate_global
```yaml
situation_type: ma_close_rate
geography: Global
time_horizon: deal-lifecycle
range_low: 70
range_high: 70
point_estimate: 70
source_tier: 3
citation: "Standard merger-arb base rate (widely-documented)"
url: null
last_verified: 2026-04-28
ttl_days: 365
ttl_class: annually_updated
notes: "Announced M&A deals close at announced terms roughly 70% of the time."
```

### ipo_year_1_returns_global
```yaml
situation_type: ipo_year_1_returns
geography: Global
time_horizon: 12m
range_low: 60
range_high: 60
point_estimate: 60
source_tier: 1
citation: "Ritter (University of Florida), ongoing IPO studies"
url: null
last_verified: 2026-04-28
ttl_days: 365
ttl_class: annually_updated
notes: "IPOs underperform the market in year 1 ~60% of the time. Ritter publishes annual updates."
```

### fund_persistence_top_quartile_global
```yaml
situation_type: fund_persistence_top_quartile
geography: Global
time_horizon: 5y
range_low: 25
range_high: 25
point_estimate: 25
source_tier: 1
citation: "Standard fund-persistence studies (e.g., S&P SPIVA, Morningstar)"
url: null
last_verified: 2026-04-28
ttl_days: 365
ttl_class: annually_updated
notes: "New-fund managers in the top quartile have ~25% probability of staying there over 5 years — barely better than chance."
```

If the situation isn't one of the entries above (or in `## Researched` below), and the `base-rate-researcher` subagent could not find a Tier 1–3 source within its budget, you are in Tier 4 or 5. Label accordingly per SKILL.md Stage 4.

---

## Researched (machine-curated, append-only)

The `base-rate-researcher` subagent appends entries here when web research returns a Tier 1–3 source not already present in `## Canonical`. **Append-only.** Stale entries are not deleted — a fresh refresh appends a new entry alongside; human curators reconcile on the next manual pass.

*(No researched entries yet. The subagent will populate this section as Stage 4 questions accumulate.)*

