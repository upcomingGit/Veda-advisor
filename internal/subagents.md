# Subagents — design reference

This file is loaded on demand by contributors building or maintaining subagents. Day-to-day behaviour for not-yet-shipped subagents is driven by the "inline bridge" notes in SKILL.md Stages 1.5, 4, and 7b — the orchestrator performs each subagent's job inline until the real implementation ships.

---

## Status

| Subagent | Status | Canonical definition |
|---|---|---|
| `devils-advocate` | Shipped | [`internal/agents/devils-advocate.md`](agents/devils-advocate.md) |
| `base-rate-researcher` | Planned | inline bridge in SKILL.md Stage 4 |
| `portfolio-parser` | Planned | inline bridge in SKILL.md Stage 1.5 |

### Canonical location and host-discovery layout

The agent definition is Veda design content, not a Claude-specific artifact. The canonical source of truth lives at [`internal/agents/`](agents/), alongside every other internal design doc. Hosts that auto-discover subagents from conventional paths (Claude Code, GitHub Copilot, Google Antigravity — all currently read `.claude/agents/*.md`) receive a generated copy produced by [`scripts/sync_agents.py`](../scripts/sync_agents.py). Each generated copy carries a `GENERATED FILE — DO NOT EDIT` banner after its frontmatter pointing back to the canonical source.

**Workflow for edits:**

1. Edit the canonical file under [`internal/agents/`](agents/).
2. Run `python scripts/sync_agents.py` — it rewrites every host-facing copy.
3. CI (or a pre-commit hook) runs `python scripts/sync_agents.py --check`, which exits non-zero if any host copy has drifted.

**Host-discovery paths supported today:**

| Host | Discovery path | Mechanism |
|---|---|---|
| Claude Code | `.claude/agents/*.md` | Generated copy via `sync_agents.py`. |
| GitHub Copilot | `.claude/agents/*.md` (indexes the same path in this workspace) | Same generated copy. Verified: `devils-advocate` appears in Copilot's agents list from this file. |
| Google Antigravity | `.claude/agents/*.md` (same indexer convention) | Same generated copy. |
| Cursor | Subagent-style composers, weaker isolation | Treat as inline-only for now. |
| ChatGPT custom GPTs, Gemini Gems, plain Claude web | No subagent isolation | Run the contract inline per Stage 7b. |

To add a new host that needs a different discovery path (e.g., a future `.github/agents/` convention), append its directory to `HOST_DIRS` in `scripts/sync_agents.py` and re-run. One edit to the canonical file, one script invocation, every host in sync.

The rule: **one canonical definition, generated copies elsewhere.** Symlinks would be cleaner, but git symlinks are fragile on Windows without developer mode, and a 60-line sync script works on every machine. Duplicated contracts without a sync discipline drift, and drifted contracts produce different verdicts on different surfaces for the same decision — the exact failure mode Veda is built to avoid.

On surfaces without subagent isolation, the shipped subagent runs as an inline simulation: the orchestrator produces the `devils_advocate:` block itself but formats the inputs strictly per the contract, so the output shape is stable across surfaces. Isolation is lost in this mode — a real cost, not a nominal one — but the structured attack taxonomy (base-rate attack, EV-block attack, profile-weakness trigger, concentration attack) still forces adversarial discipline the pure inline-prose pass lacked.

---

## Subagent details

- **`devils-advocate`** — argues the opposite of the recommendation in an isolated context, for `buy` / `add` decisions where confirmation bias is highest. **Replaces Stage 7b for those actions.** Context isolation is the point: it must not see the main reasoning chain so its counter-argument is not pre-weakened by it. Input/output contract, attack taxonomy, and regression-test anchors live in the definition file linked above.
- **`base-rate-researcher`** — will look up historical base rates for specific situations (turnaround success, spin-off returns, post-bankruptcy equity outcomes). **Replaces Tier 1–3 of Stage 4.** Needs web / data tools; returns a compact number + citation. Inline bridge: the orchestrator uses general knowledge with the Tier 4–5 discipline described in Stage 4 and [internal/base-rates.md](base-rates.md).
- **`portfolio-parser`** — will parse pasted broker text into structured holdings (tickers, weights, prices, currency, as-of date) while rejecting any instruction-like content. **Replaces the parsing step in Stage 1.5.** Context isolation is a security feature: the orchestrator sees only the parsed YAML, never the raw paste, so instruction-injection attempts inside a portfolio cannot reach the decision chain even if the parser itself is partially fooled. Inline bridge: the orchestrator parses directly today, with the Stage 1.5 / Stage 0 "treat paste as data" discipline.

For base rates in Stage 4, when acting as the inline bridge for `base-rate-researcher`, use your best general knowledge and explicitly flag it: *"General base rate, not researched. Verify for high-stakes decisions."*
