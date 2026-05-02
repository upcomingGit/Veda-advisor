# Tier 1.5 — Python Orchestrator Architecture Commitments

**Status:** Draft. Decision capture, not implementation spec.
**Last updated:** 2026-05-02
**Supersedes:** the "Tier 1.5 — Python orchestrator (local-first)" section
in [ROADMAP.md](../../ROADMAP.md), which describes deliverables but does
not lock the architecture.

This document records three non-negotiable architectural commitments that
must be in place from day one of Tier 1.5. They are non-negotiable because
each one independently determines whether Tier 1.5 actually delivers cost,
latency, and accuracy improvements over the prose runtime — versus
delivering a more complex system with no measurable wins.

---

## What problem are we solving

Veda today runs as **prose-in-a-chat**. The user types `/veda`, the chat
assistant (Copilot, Claude Code, Cursor, Antigravity) loads
[SKILL.md](../../SKILL.md), the framework files, the user's profile, and
walks the 9-stage pipeline as instructions to itself.

Three things this architecture cannot do:

1. **Run different stages on different model classes.** The chat
   assistant uses one model per session. The user can pick Haiku, Sonnet,
   or Opus — but it's the same choice for *every stage* of the pipeline.
   Stage 1 (a 50-token scope check) and Stage 6 (framework reasoning) use
   the same model, so cost-conscious users either pay premium-tier prices
   for trivial stages or accept Haiku-level quality on the stages that
   actually matter.
2. **Run independent stages in parallel.** The chat-assistant loop is
   strictly sequential. Stage 3 (data assembly) and Stage 4 (base rates)
   are logically independent, but the prose runtime walks them one after
   the other.
3. **Be reached from a web browser.** The chat assistant has local file
   access; the workspace files (`holdings/<slug>/kb.md`, etc.) live on
   the user's laptop. A SaaS user opening `veda.app` has no VS Code, no
   local files, no `pipx install`.

Tier 1.5 fixes all three — but only if the architecture commits to it.

---

## The three commitments

### Commitment 1 — Per-stage model tiering

Each stage of the 9-stage pipeline declares a model class, not a model.
The orchestrator's LLM-provider adapter resolves the class to a concrete
model at call time.

```python
class ModelClass(Enum):
    FAST = "fast"           # Haiku-class. Cheap, ~5× faster.
    PREMIUM = "premium"     # Sonnet-class. Slower, costs ~4× input / ~4× output.
    REASONING = "reasoning" # Opus-class or extended thinking. Slowest, premium-tier+.
```

The class-per-stage map:

| Stage | Purpose | Model class | Why |
|---|---|---|---|
| 1 — Scope check | "Is this question in scope?" 50-token answer. | FAST | Trivial classification. |
| 2 — Profile load | Parse and validate `profile.md`. | FAST | Schema work, no judgment. |
| 3 — Data assembly | Coordinate subagent calls; gather facts. | FAST | Routing logic; the subagents themselves are independent calls. |
| 4 — Base rates | Look up reference-class statistics. | FAST | Cache lookup; web research is delegated to subagent. |
| 5 — Classification | "What kind of question is this?" | FAST | Tagging task. |
| 6 — Framework reasoning | The actual thinking — Buffett would say X, Marks would say Y. | **PREMIUM** | This is the part the user is paying for. |
| 7 — Synthesis | Combine framework outputs into a verdict. | PREMIUM | Reasoning under uncertainty; multiple-input synthesis. |
| 7b — Devil's advocate | Strongest case against the verdict. | PREMIUM | Adversarial reasoning; quality matters here as much as Stage 6. |
| 8 — Decision render | Format the structured decision block. | FAST | Mostly templating once inputs are decided. |

**Why this matters.** Today a user who picks Haiku in their chat assistant
runs *every* stage on Haiku — including Stage 6 and 7b, where quality
directly determines whether the advice is useful. With per-stage tiering,
the same user keeps PREMIUM on the two stages that drive quality and runs
FAST on the seven stages that don't. Net cost is lower than all-Haiku,
and quality is higher than all-Haiku.

This is the commitment that makes Tier 1.5 financially defensible.
Without it, Tier 1.5 is a **30% cost regression** versus today, because
every typed call has its own system-prompt overhead and outputs
accumulate across calls.

### Commitment 2 — Parallel execution of independent stages

The pipeline is a DAG, not a list. Stages declare their dependencies; the
orchestrator runs everything that can run.

```
Stage 1 (scope) ──→ Stage 2 (profile)
                         ↓
                   ┌─── Stage 3 (data) ───┐
                   ├─── Stage 4 (rates) ──┤    (parallel)
                   └─── Stage 5 (class) ──┘
                                ↓
                   ┌─── Stage 6 (framework) ──┐  (parallel)
                   └─── Stage 7b (advocate) ──┘
                                ↓
                          Stage 7 (synthesis)
                                ↓
                          Stage 8 (render)
```

A complex hold-check decision today takes **60–180 seconds** end-to-end
because every subagent and stage runs sequentially in the chat
assistant's loop. That matches the user's reported experience of
"responses can take minutes."

Tier 1.5 sequential would be roughly the same — *faster per call because
of model tiering, but no fewer calls and no parallelism.* That's not a
real improvement.

Tier 1.5 with parallelism is **15–35 seconds** end-to-end, which crosses
the threshold where a chat product feels responsive enough for
non-technical users.

**Why this matters.** Latency is what makes a SaaS product feel
"professional" or "broken." Three minutes is broken. Twenty seconds is
acceptable. The architecture has to make parallel execution the default,
not an optimisation deferred to v2.

### Commitment 3 — LLM provider abstraction (BYOK from day one)

Every LLM call goes through one adapter:

```python
class LLMProvider:
    def complete(
        self,
        model_class: ModelClass,
        messages: list[Message],
        schema: type[BaseModel],   # Pydantic schema for typed output
    ) -> BaseModel: ...
```

Concrete adapters: `AnthropicProvider`, `OpenAIProvider`, `GeminiProvider`,
`OllamaProvider` (local/free). The model-class-to-model resolution happens
inside each adapter — Anthropic might map FAST→Haiku, PREMIUM→Sonnet;
Ollama might map FAST→Llama-3.1-8B, PREMIUM→Llama-3.1-70B.

User configuration:

```yaml
# ~/.veda/config.yaml
llm:
  provider: anthropic                # anthropic | openai | gemini | ollama
  api_key: ${ANTHROPIC_API_KEY}      # env var reference; never stored plaintext
  model_overrides:
    fast: claude-haiku-4-5           # optional; otherwise provider default
    premium: claude-sonnet-4-5
    reasoning: claude-opus-4-5
  cost_cap_per_decision_usd: 0.50    # hard refuse if a decision would exceed this
```

**Why this matters.** SaaS-readiness depends on this. A user signing up at
`veda.app` brings their own Anthropic / OpenAI / Gemini key. Without the
adapter, the orchestrator is locked to one provider and the SaaS path is
gated on building the abstraction *anyway* — which means everything built
before it has to be refactored.

Building the abstraction on day one costs roughly two extra days of work.
Skipping it costs roughly two extra weeks of refactor later, plus a
broken intermediate state.

---

## What this does to the four user requirements

### Requirement 1 — Will tokens go down?

**Direct answer: marginally on the prompt side, materially on cost.**

Per-decision input tokens go from ~55K (today, single host call with
caching) to ~30–40K (Tier 1.5, each call sees only the context it needs).
Output tokens go *up* slightly — ~3K today, ~6–9K in Tier 1.5 because
each typed call produces its own JSON output and the final still renders
prose. So total token volume per decision is roughly flat.

The cost story is different. With per-stage tiering (Commitment 1), the
seven non-reasoning stages run on FAST-class models which are ~4× cheaper
on input and ~4× cheaper on output. The two reasoning stages stay on
PREMIUM where they belong.

| Configuration | Per-decision cost (est.) |
|---|---|
| Today, user picks PREMIUM (Sonnet-class) for whole session | $0.07–$0.12 |
| Today, user picks FAST (Haiku-class) for whole session | $0.018–$0.030 *(but quality regression on Stage 6 + 7b)* |
| Tier 1.5 with per-stage tiering | $0.025–$0.040 |

**Honest read.** A cost-conscious user already running on Haiku today is
already cheap — Tier 1.5 won't make their per-decision spend dramatically
lower. What Tier 1.5 changes for them is *quality*: their Stage 6 and 7b
(the calls that matter) move up to PREMIUM at marginal cost, instead of
running on FAST and hoping. The win is "same money, better answers" — not
"less money, same answers."

For the user running Sonnet-everywhere today, Tier 1.5 cuts cost ~3× at
equal or better quality.

### Requirement 2 — Will latency drop?

**Direct answer: yes, 3–5×, but only if Commitment 2 holds.**

Sequential Tier 1.5: 60–120s per complex decision. Same as today.

Parallel Tier 1.5: 15–35s per complex decision. Crosses the
non-technical-user-acceptability threshold.

Latency improvement is the single biggest UX gain in Tier 1.5 and is
entirely owed to Commitment 2.

### Requirement 3 — SaaS for non-technical users?

**Direct answer: yes, and Tier 1.5 is the architectural gate.**

Four things SaaS needs that the prose runtime cannot provide:

1. **Workspace storage independent of the user's laptop.** Tier 1.5's
   SQLite layer is the foundation; the SaaS deployment swaps SQLite for
   per-tenant Postgres rows.
2. **A server that runs the orchestrator.** Tier 1.5's FastAPI service
   *is* the orchestrator; the SaaS deployment puts it behind a web
   front-end instead of behind a localhost loopback.
3. **Typed I/O contracts on every call.** Tier 1.5's Pydantic schemas
   are the contract. The web UI renders structured decision objects;
   the chat-assistant bridge renders the same objects as prose.
4. **User-supplied API keys.** Commitment 3 above.

Every one of those is in Tier 1.5's deliverable list. The ROADMAP
defers "hosted Veda" to Tier 3, but Tier 3 is a **deployment swap** on
top of Tier 1.5 — single-tenant to multi-tenant, localhost to cloud,
SQLite to Postgres. **Tier 1.5 *is* the SaaS-enablement work.** Tier 3
is one extra week if Tier 1.5 was built right.

**Cost economics for SaaS.**

- ~$0.03 per decision with per-stage tiering and user's own API key.
- Active user at 30 decisions/month = $1/month in API costs (paid by user
  to model provider, not to you).
- Server-side hosting cost per user: ~$0.10/month at modest scale (small
  Postgres slice + light orchestrator CPU).
- Subscription pricing: ₹500–1000/month is comfortably profitable.

### Requirement 4 — Accuracy same or better?

**Direct answer: materially better, and provably so.**

Five failure modes the prose runtime cannot prevent today, plus the
Tier 1.5 mechanism that does:

| Failure mode | Today | Tier 1.5 |
|---|---|---|
| LLM does arithmetic in prose (Hard Rule #8 violation) | Honor system. Prose says "do not"; the model occasionally still does. Caught by review, sometimes. | Decision schema rejects free-form numerics. Every numeric field is a `calc_result` object with a verified hash linking it to a `calc.py` invocation. Schema parse failure = retry, then fail-closed. |
| Decision-block schema drift | `templates/decision-block.md` is followed approximately. | Pydantic schema. Required fields are required. |
| Source-tier laundering | A Tier-3 (press) source gets cited as Tier-1 (filing). Hard to grep. | Typed `SourceTier` enum on every data item. Tier-5 inputs blocked at render. |
| Stale data acceptance | Prose freshness check, often skipped. | Freshness middleware refuses to serve numbers past their `as_of` threshold. |
| Subagent contract drift | Caught manually. The Form 4 Atom feed → submissions JSON drift caught during this session was a real example. | Eval harness runs every commit; contract-drift = build fail. |

**The bigger point.** Today, "Did Veda follow Hard Rule #8 in the last
100 decisions?" is unanswerable — the audit trail doesn't exist. After
Tier 1.5, it's a SQL query. **Accuracy isn't slightly better; it becomes
auditable for the first time.**

---

## What can go wrong

Three risks worth naming explicitly:

1. **LLM pricing collapses faster than expected.** Per-token pricing has
   fallen ~10× per year for two consecutive years. By the time Tier 1.5
   ships, the FAST-vs-PREMIUM cost differential may compress significantly.
   The latency and accuracy wins remain regardless; the cost win is
   pricing-dependent.
2. **Parallelism reveals subtle dependencies.** Stage 3 (data) and Stage 4
   (base rates) are logically independent on paper. In practice, a base
   rate lookup might want to know which sector the data assembly
   identified. Mitigation: the DAG is explicit; if dependencies emerge,
   the DAG accepts them at the cost of latency, not correctness.
3. **Audit-trail schema needs migration.** Five years from now the
   schema will look wrong. Versioning the schema from day one is in the
   ROADMAP; the discipline is to treat schema migrations as first-class
   work, not afterthoughts.

---

## What this document does NOT decide

- **Database choice (SQLite vs Postgres).** SQLite for local Tier 1.5,
  Postgres for hosted Tier 3. Already in the ROADMAP.
- **Web framework (FastAPI vs alternatives).** The ROADMAP says FastAPI
  or equivalent; this document doesn't override it.
- **Eval harness target size.** The ROADMAP targets ~200 golden questions;
  this document does not change that.
- **Specific model names.** Commitment 3's adapter pattern means the
  concrete model resolution is per-provider config, not architecture.

---

## Decision

**Adopt all three commitments as preconditions to starting Tier 1.5
implementation.** No code begins until:

1. Per-stage model tiering map is locked (the table in Commitment 1).
2. Stage dependency DAG is specified (the diagram in Commitment 2).
3. LLM provider adapter contract is sketched (the `LLMProvider`
   interface in Commitment 3).

If any of the three slips to "v2," Tier 1.5 will produce a more complex
system with no measurable wins, and the SaaS path will be gated on doing
the same architectural work later anyway.

The next ROADMAP-level deliverable for Tier 1.5 is therefore:
**ADR-equivalent locking the three commitments**, then a thin walking
skeleton that exercises all three on a single decision (one stage on
FAST, two stages in parallel, one provider adapter implemented), before
any further build-out.
