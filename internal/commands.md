# Veda Commands

Full procedure, plan output formats, prompts, and narration for user-invoked administrative commands. Trigger phrases and the dispatch table live in [SKILL.md](../SKILL.md) § "Commands". Commands are distinct from the decision pipeline (Stages 0–9) — they are operations the user triggers explicitly.

---

## `sync` — reconcile holdings sources

Reconciles drift between the three holdings sources: `holdings_registry.csv` (lifecycle), `assets.md` (tactical state), and `holdings/` workspaces (qualitative knowledge).

**Two-turn pattern.** Sync is plan-then-confirm. On the first turn, Veda prints a plan showing all proposed changes. **No changes are applied until the user explicitly confirms.** The plan output ends with clear instructions telling the user what to do next.

**Turn 1 — plan output example:**

```
Sync plan:

Workspaces to scaffold (held tickers without workspaces):
  - nvda (archetype: GROWTH inferred)
  - tsmc (archetype: pending — ambiguous, will ask on apply)

Registry rows to add (held tickers without registry row):
  - nvda
  - tsmc

Orphan workspaces (workspace exists, no registry row):
  - xyz — will prompt for resolution on apply

Status mismatches:
  - (none)

Word-cap breaches (will condense/absorb on apply):
  - holdings/msft/kb.md: 2,340 words (cap 2,000) — condense in place
  - holdings/msft/news/2026-Q1.md: 1,612 words (cap 1,500) — absorb into kb.md
  - holdings/nvda/thesis.md: 612 words (cap 500) — flag for user revision

——————————————————————————————
To apply these changes, say "apply" or "yes".
To cancel, say "cancel" or "no".
```

**Word-cap breach detection.** Sync scans all markdown files in all workspaces that have word caps (kb.md, thesis.md, governance.md, risks.md, disclosures.md, news/*.md, earnings/*.md). YAML files and decision files are excluded. Word count is naive whitespace split (`len(content.split())`). Files exceeding their cap are listed in the plan with the action that will be taken on apply.

**Turn 2 — apply on confirmation.** User says `apply`, `yes`, or `confirm` → Veda executes the plan and narrates each change. User says `cancel`, `no`, or asks a different question → sync aborted, no changes made.

**Orphan resolution (interactive).** For each orphan workspace during apply, prompt:

> *"holdings/xyz/ has no registry row. Options:*
> *  - retire — move to _retired/, add registry row with status=retired*
> *  - add — add registry row with status=active (you hold this)*
> *  - skip — leave as orphan for now (not recommended)*
> *Which?"*

Wait for user response before proceeding to the next orphan.

**Bulk scaffold behavior.** Sync scaffolds all held tickers without workspaces in one pass. Archetypes are inferred where high-confidence — these are scaffolded without prompts. Ambiguous archetypes (marked "pending" in the plan) are prompted one-by-one during apply; they do not block the batch.

**What sync does NOT do:**
- Sync does not touch `assets.md` — tactical state has its own refresh paths (Stage 1.5 patterns 1–4).
- Sync does not proactively retire positions — to retire, the user must explicitly invoke `retire <ticker>`.

Full retirement procedure, reason enum, and registry update rules are in [holdings-schema.md](holdings-schema.md) § "Retirement". Full word-cap and absorption rules are in [holdings-schema.md](holdings-schema.md) § "Word caps and absorption".

---

## `retire <ticker>` — close a position

Retires a workspace and updates the registry. Used when a position is sold or exited.

**Procedure:**

1. **Check registry row exists.** If no registry row exists for `<ticker>`, prompt for `first_acquired` date (required by registry validation) before proceeding. Without a registry row, this is effectively an orphan-retire and the sync-path rules apply.

2. **Prompt for retirement reason** (enum — user picks one):
   - `thesis_broken` — kill criterion triggered, structural thesis failure
   - `rebalance` — sold for portfolio reasons, thesis intact
   - `user_exit` — user-driven sell, no framework trigger
   - `spin_off` — corporate action (position replaced by spin-off)
   - `merge` — corporate action (position absorbed by acquirer)
   - `other` — free text (user provides reason)

3. **Move workspace:** `holdings/<slug>/` → `holdings/_retired/<slug>/`

4. **Update registry row:** set `status=retired`, `last_disposed=<today>`, `reason=<selected>`. If this is an orphan-retire (no prior row), also set `first_acquired` from the prompt in Step 1.

5. **Narrate:**

> *"Retired nvda. Moved holdings/nvda/ to holdings/_retired/nvda/. Registry updated: status=retired, last_disposed=2026-04-24, reason=thesis_broken."*

**Note:** Retirement is distinct from deletion. The workspace is preserved in `_retired/` for historical reference. The decision log remains intact. To permanently delete, the user must manually remove the `_retired/<slug>/` directory.
