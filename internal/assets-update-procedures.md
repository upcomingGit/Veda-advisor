# assets.md Update Procedures

Full procedure bodies for the four `assets.md` update patterns referenced in [SKILL.md](../SKILL.md) Stage 1.5. The orchestrator identifies which pattern applies (see dispatch table in Stage 1.5) and follows the corresponding section here.

---

## Pattern 1 — Full refresh (re-paste)

**Trigger:** User pastes a new complete holdings list or uploads a fresh broker export.

**Procedure:**

1. Overwrite the holdings tables in `assets.md` wholesale.
2. Stamp a new top-level `As of:` date.
3. **Tag preservation:** Preserve any non-default `tags` values (e.g., `core`, `tactical`, `speculation`) from the old file by ticker match; do not silently drop them. If a ticker is in the new paste but not the old, its tag is the default placeholder. If a ticker is in the old but not the new, it was sold — drop the row. Per-position thesis content lives in `holdings/<slug>/thesis.md` and is unaffected by `assets.md` refreshes.
4. Re-run `scripts/calc.py` for every affected `dynamic.totals`, `dynamic.concentration_snapshot`, `dynamic.capital_split_current`, and `dynamic.forced_concentration_snapshot` field and write the new numbers back in the same turn.

**Narration:** *"Updated `assets.md` (full refresh). Totals recomputed via calc.py. As of: 2026-04-21."*

---

## Pattern 2 — Delta edit

**Trigger:** User describes a change in natural language: *"I sold 50 NVDA and bought 100 AMD at $165 avg cost."*

**Procedure:**

1. Read the current `assets.md`.
2. Apply the delta to the holdings rows.
3. Run arithmetic through `scripts/calc.py` (share counts, new current_value, updated totals, updated concentration snapshot) per Hard Rule #8.
4. Write the updated file back.
5. **Ambiguity gate:** Do not apply a delta if you are not certain which row it refers to — ask: *"You have two NVDA-linked entries (direct and via QQQ). Which one?"*

**Narration:** *"Updated `assets.md` (delta: -50 NVDA, +100 AMD @ 165.00). Totals recomputed via calc.py. As of: 2026-04-21."*

---

## Pattern 3 — Direct file edit by user

**Trigger:** User edits `assets.md` in their editor between sessions.

**Procedure:**

Veda re-reads the file on next session. No Veda action needed beyond the normal stale-data check (see Stage 1.5). If your working memory from a prior turn disagrees with the on-disk file, **the on-disk file wins**.

**Narration:** None required — acknowledge the updated date on load if relevant.

---

## Pattern 4 — Live broker pull (Zerodha Kite)

**Trigger phrases:** *"refresh holdings from Kite"*, *"pull from Zerodha"*, *"refresh from broker"*, or similar.

### Broker-gate (first)

1. Read `profile.md > broker.primary`.
2. If the field is absent, ask once: *"Which broker do you use for this portfolio? (zerodha / other)"*
3. Write the answer to `profile.md > broker.primary`. Valid values: `zerodha`, `other`, `none`.
4. **Gate check:**
   - If `zerodha` → proceed with pull below.
   - If `other` or `none` → stop and respond: *"Live broker pull is Zerodha-only in v0.1. For your broker, please use pattern 1 (paste holdings) or pattern 3 (edit `assets.md` directly). I'll add your broker to the roadmap — what is it?"* Log the requested broker name in the reply so it surfaces in [ROADMAP.md](../ROADMAP.md) review later. Do not attempt the Kite script for non-Zerodha users — it will fail.

### Pull procedure (after gate passes)

1. Run `python scripts/kite.py holdings` in the terminal and parse the JSON on stdout.
2. Apply the same reconciliation rules as pattern 1 (full refresh): preserve non-default `tags` values by ticker match, add new tickers with the default tag placeholder, drop tickers absent from the pull (sold). Per-position thesis content lives in `holdings/<slug>/thesis.md` and is unaffected.
3. Refresh `dynamic.fx_rates.usd_inr` via `scripts/fetch_quote.py` in the same turn.
4. Re-run `scripts/calc.py` for every affected total / snapshot per Hard Rule #8.
5. Stamp the new top-level `As of:` from the `as_of` field in the Kite JSON.

### Error handling

On any error from the script, **stop and surface the error verbatim**. Two common cases:

| Error | Response |
|---|---|
| `access_token expired` | *"Kite access token expired. Run `python scripts/kite.py auth` in your terminal and confirm when done — I'll re-pull."* |
| `no access_token` (first-time use) | Same response as above. |

Do not retry silently. Do not fall back to the old `assets.md` numbers.

### Security

Never echo `api_key`, `api_secret`, or `access_token` back to chat. The script is designed not to emit the access_token, and the JSON output contains only holdings, not credentials.

**Narration:** *"Refreshed `assets.md` from Kite (26 holdings, 3 new, 1 closed). FX and totals recomputed via calc.py. As of: 2026-04-21."*

---

## General rule

Do not write both a full refresh and a delta in the same turn; pick one pattern.
