# Changelog

All notable changes to Veda are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
Veda uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Versioning policy

Veda is a prose-and-scripts skill, not a library with a public API. The three
components are interpreted as:

- **MAJOR.** A change that makes an existing `profile.md`, `assets.md`, or
  `journal.md` fail validation under the new version; or that removes a rule or
  framework; or that alters how an existing Hard Rule is enforced in a way that
  changes user-visible behaviour. Migration notes are mandatory.
- **MINOR.** A new capability (new framework, new script, new subagent, new
  Stage 1.5 update pattern, new broker integration) that does not break
  existing state files.
- **PATCH.** Prose tightening, clarifications, typo fixes, script bug fixes
  that preserve the same output shape, and documentation-only changes.

Pre-1.0 (i.e., all 0.x releases) relaxes the above: any release may contain
breaking changes, each breaking change is called out under the **Changed**
heading with a clear migration note. The 1.0 release will be the first that
promises MAJOR-means-breaking discipline.

The authoritative version string lives in [VERSION](VERSION); [SKILL.md](SKILL.md)
front-matter and [README.md](README.md) mirror it. The [bump_version.py](scripts/bump_version.py)
script keeps all three in sync and promotes `[Unreleased]` entries in this
changelog on release.

## [Unreleased]

## [0.6.0] - 2026-05-02

### Added

- **Local workspace dashboard** ([dashboard/](dashboard/)) — a single-command,
  locally-running Flask + Jinja2 web UI that reads every artifact in the user's
  workspace and renders them in one place. Strictly read-only; offline by
  default. Routes: `/` (portfolio overview with India/US holdings tables, totals
  and concentration, capital deployed vs target, cross-position upcoming
  events, journal link), `/position/<slug>` (per-company page with valuation
  zone from `valuation.yaml`, twelve-quarter `fundamentals.yaml` table with
  derived OPM% and FCF, four-anchor `assumptions.yaml` grade chips and
  miss-streak counts, `news/<quarter>.md`, `disclosures.md`, `calendar.yaml`
  upcoming + past split, `decisions/`, `insiders.yaml`,
  `shareholding.yaml`, `governance.md`, `risks.md`, `indicators.yaml`, the
  rendered `kb.md` and `thesis.md`, and the `_absorption_log.md`),
  `/journal`, `/settings`, and `POST /api/quote` (live-price refresh,
  shells out to `scripts/fetch_quote.py`, **gated to tickers already
  present in `assets.md`** so the endpoint cannot become an open relay,
  result returned inline — never written back). Theme picker
  (light/dark/system) persisted in `localStorage`. Single-process server
  bound to `127.0.0.1:8765` by default; configurable via
  `python -m dashboard --port N --theme {system,light,dark} --no-open
  --workspace PATH --event-window-days N`. New runtime dependencies:
  `Flask`, `markdown`, `PyYAML` (added to [requirements.txt](requirements.txt)).
  Setup notes in [INSTALL.md](INSTALL.md); user-facing settings in
  [docs/customization.md](docs/customization.md). Resolves Q-dash-1
  (dashboard lives in the same repo as the orchestrator) per
  [ROADMAP.md](ROADMAP.md#tier-14--richer-ux-surfaces).

- **Tier 1.5 architecture commitments**
  ([docs/design/tier-1.5-architecture.md](docs/design/tier-1.5-architecture.md)) —
  records the required per-stage model tiering, DAG-based parallelism, and
  BYOK LLM-provider abstraction before the Python orchestrator work begins.

## [0.5.0] - 2026-05-02

### Added

- **`ownership-tracker` subagent**
  ([internal/agents/ownership-tracker.md](internal/agents/ownership-tracker.md))
  + **[scripts/fetch_ownership.py](scripts/fetch_ownership.py)** — pulls
  insider/promoter transactions and quarterly shareholding-pattern
  snapshots into `holdings/<slug>/insiders.yaml` and
  `holdings/<slug>/shareholding.yaml`. Sources: SEC EDGAR submissions
  JSON for Form 4 (US — issuer-CIK lookup, then per-filing
  `index.json` scrape to locate the raw ownership XML, then
  namespace-stripped XML parse with lot aggregation across same-day
  same-direction transactions); NSE PIT API + NSE corp-shp master
  endpoint with BSE shareholding-pattern fallback (India — homepage→cookie
  bootstrap with `Accept-Encoding: gzip, deflate` rather than brotli).
  Tool grant: `Read, Bash, WebFetch`. Helper applies the
  StockClarity-ported 5-filter pipeline for India insiders
  (`secType=="Equity Shares"` → `tdpTransactionType in (Buy, Sell)` →
  `acqMode in (Market Purchase, Market Sale)` → `secVal > 0` → value
  threshold ₹1 Cr buy / ₹5 Cr sell) and the value+price floor for US
  Form 4 ($500K buy / $2M sell, with lots aggregated by accession +
  insider + direction). Stable transaction IDs for cross-run dedup: US
  `<accession>-<insider-slug>-<P|S>`, India
  `<YYYY-MM-DD>-NSE-<acqName-slug>-<B|S>-<secAcq>`. **Split-TTL
  cache gating** — 7 days for `insiders.yaml` (event-driven, mirrors
  `news-researcher`), 30 days for `shareholding.yaml` (quarterly
  snapshot, mirrors `calendar-tracker`); both bypassed on
  `decision_context: high_stakes` (Stage 9a buy/sell hold-checks). Hard
  5-operation cap on web-touching tool calls; hard cap of 50
  transactions per `insiders.yaml` and 8 quarters per
  `shareholding.yaml > history`. Refuses user-pasted insider
  transactions or shareholding text in v1 (closes the injection
  surface; primary-source fetches only); the narrow `pasted_pledging`
  channel is **US-only** and accepts a single validated number
  (`{ promoter_pledged_pct, as_of, source }`) — India has the
  structured NSE feed and pasted text would not authoritatively
  override it. Filesystem-read-only — emits `proposed_insiders_yaml`
  and `proposed_shareholding_yaml` for the orchestrator to write
  (same pattern as `disclosure-fetcher` and `calendar-tracker`).
  Smoke-tested against NVDA US Form 4 (13+ aggregated transactions
  over 90 days), NTPC India shareholding (8-quarter history), INFY NSE
  PIT (129 raw → 2 kept after 5-filter), NTPC NSE PIT empty
  (correctly surfaced as honest miss for a govt-owned promoter).
  Twelve regression-test anchors live in the canonical contract
  covering US fresh build, India fresh build, India insufficient input
  (no `nse_symbol`), cache-hit, split-TTL behaviour, high-stakes
  bypass, valid pasted-pledging (US), India-rejected pasted-pledging,
  malformed pasted-pledging, US Form 4 lot aggregation, India 5-filter
  ESOP drop, 50-row cap, and 8-quarter history cap. Brings the
  `internal/subagents.md` shipped-count to **9 of 11**; two remain
  (`earnings-grader`, `indicators-researcher`).
- **v1 documented limitations for `ownership-tracker`** — surfaced
  honestly in the contract, helper docs, and ROADMAP rather than
  silently producing approximations:
  - **India FII/DII split** lives inside the per-filing XBRL document
    (linked from each NSE corp-shp row's `xbrl` field); XBRL parsing
    is parked for v2. Helper emits `fii_pct: null`, `dii_pct: null`
    explicitly so the orchestrator can distinguish "missing" from
    "forgotten."
  - **India promoter pledging** lives on a separate NSE
    corporate-pledge endpoint, not the corp-shp master; pledging-channel
    implementation is parked for v2. Subagent contract returns
    `pledging_status: not_fetched_v1` so the orchestrator treats
    absence as "unknown", not "0%".

### Changed

- **README.md** — tightened three capability-table rows (news tracking,
  regulator filings, and calendar tracking) so the homepage stays readable
  while preserving the core capability claims and sample questions.
- **README.md, SKILL.md, ROADMAP.md, internal/subagents.md,
  docs/how-veda-thinks.md, scripts/README.md** — updated subagent
  inventory and Stage 3 delegation rules for the new `ownership-tracker`
  subagent: README adds the *"Watches who's buying and selling on the
  inside"* capability row plus a status flip from "eight" to "nine"
  shipped subagents; SKILL.md adds the Stage 3 delegation block, the
  source-hierarchy row, and the Subagents-inventory entry; ROADMAP flips
  build-order step 7 to shipped and updates the live count; subagents.md
  flips row 10 to **Shipped** and rewrites the prose entry plus the
  write-target matrix.

## [0.4.0] - 2026-05-01

### Added

- **`calendar-tracker` subagent**
  ([internal/agents/calendar-tracker.md](internal/agents/calendar-tracker.md))
  + **[scripts/fetch_calendar.py](scripts/fetch_calendar.py)** — maintains
  scheduled corporate and macro event calendars in two modes via a
  `mode: position | global` input flag. **Per-position**
  (`mode: position`): fetches earnings dates / ex-dividend / splits via
  yfinance (`Ticker.calendar` for US tickers; sometimes empty for India
  via `.NS` suffix) and Screener.in HTML scrape (India position,
  opportunistic — Screener publishes forward-looking dates only when
  available). Indian AGMs come via `disclosure-fetcher`'s BSE/NSE channel
  (board-meeting filings) and are out of scope here; US AGMs handled by
  an opt-in `WebFetch` fallback (capped at 1 call per invocation) on the
  company's IR page. **Global** (`mode: global`): v1 auto-fetches FOMC
  meeting dates from federalreserve.gov (parsing H4 `<year> FOMC Meetings`
  headers and date-range tokens like `June 16-17`; uses day 1 of the
  range as the canonical event date for a 1-day pre-meeting heads-up).
  Three macro sources deferred to v2 and surfaced honestly via the
  helper's `deferred_v2` envelope: BLS US CPI (HTTP 403 on bot
  User-Agents even with browser headers), RBI MPC schedule (buried in
  dated press-release listings; brittle parsing), MoSPI India CPI / IIP
  (page format varies). v1 fallback for all three: users supply dates
  via the subagent's `pasted_dates` channel (strict-parsed with
  injection refusal). Tool grant: `Read, Bash, WebFetch`. Hard
  5-operation cap on web-touching tool calls. Cache-hit skip 30 days
  (calendar data changes slowly; 7-day floor on
  `decision_context: recency_explicit`). **Strict dedup with
  co-writers**: matches by `(event-type, date ±2 days)` proximity and
  preserves any existing row whose source starts with
  `disclosure-fetcher (auto):`, `earnings-grader (auto)`, or has no
  auto-tag (user-owned) — calendar-tracker is the *complement* to
  disclosure-fetcher, never overwrites tier-1 regulator-filing-sourced
  rows. **Past-event auto-sweep** on every invocation: rows whose date
  is < today move from `upcoming:` to `past:` (capped at 12 entries;
  oldest pruned). Filesystem-read-only — emits
  `proposed_calendar_yaml` (mode: position) or
  `proposed_global_calendar_yaml` (mode: global) for the orchestrator
  to write. 12 regression-test anchors. v2 deferrals tracked as
  `Q-cal-1` in [ROADMAP.md](ROADMAP.md) Tier 5.

### Changed

- **SKILL.md** — added Stage 3 delegation block for `calendar-tracker`
  with handle-the-response branches for `ok` / `partial` /
  `cache_hit` / `no_changes` / `insufficient_input`. Added
  upcoming-events row to Stage 3 source-hierarchy table. Added
  `calendar-tracker` to the Subagents-section inventory.
- **internal/subagents.md** — status flipped to **Shipped** (8 of 11
  subagents now shipped); inventory bullet, write-target matrix, and
  status table all updated to match the actual contract.
- **ROADMAP.md** — added `Q-cal-1` to Tier 5 documenting the v2 macro
  sources (BLS / RBI / MoSPI) deferral with their exact failure
  reasons captured during the v1 build, and proposed v2 path (FRED
  JSON adapter as the first step, since FRED is a stable upstream
  for US macro releases including BLS data).
- **scripts/README.md** — added documentation for `fetch_calendar.py`
  with usage, parameters, source list, and v2 deferrals.
- **README.md** — added a "Tracks the dates that will move your
  stocks" row to the capability table covering `calendar-tracker`,
  and updated Status to "eight shipped subagents" (also lists
  `disclosure-fetcher`, which the v0.3.0 Status block had missed).
- **docs/how-veda-thinks.md** — Stage 3 (Data check) now lists
  `disclosure-fetcher` and `calendar-tracker` as fetchers alongside
  `fundamentals-fetcher` and `news-researcher`. Both were missing
  from this user-facing walkthrough; `disclosure-fetcher`'s entry
  is back-filled here from v0.3.0.
- **README.md** — Status block: replaced the stale "v0.1 — early
  preview" generation label with "v0.3.0 — early preview" so the
  body matches the version badge at the top of the file. Caveat
  that non-Lynch framework files are first-pass distillations is
  preserved.
- **SKILL.md** — Versioning section: same "v0.1" → "v0.3.0"
  alignment, including the example narration string the orchestrator
  is expected to emit when a framework rule isn't yet documented.
- **CONTRIBUTING.md** — "New frameworks" section: removed the stale
  "Eight of the eleven investor frameworks ... are unwritten" claim
  (all eleven now ship as first-pass distillations). Section is now
  guidance for proposing a twelfth investor; deepen-an-existing-one
  is steered into section 2 (Framework edits).

## [0.3.0] - 2026-05-01

### Added

- **`disclosure-fetcher` subagent**
  ([internal/agents/disclosure-fetcher.md](internal/agents/disclosure-fetcher.md))
  + **[scripts/fetch_disclosures.py](scripts/fetch_disclosures.py)** —
  fetches unscheduled material announcements from primary regulator
  APIs into `holdings/<slug>/disclosures.md`. Sources: SEC EDGAR
  submissions JSON filtered to Form 8-K (US — 10-K and 10-Q overlap
  with `fundamentals-fetcher` and `earnings-grader` and are
  deliberately out of scope), BSE Corporate Announcements API + NSE
  Corporate Announcements API (India — fetched in parallel and
  deduped by `(date, normalized_headline_prefix[:60])` proximity
  match preferring BSE on ties). 12-pattern SEBI routine-disclosure
  regex filter ported verbatim from StockClarity's
  `_IGNORED_DISCLOSURE_PATTERNS` (each pattern with documented 100%
  LLM-rejection evidence in StockClarity production logs) drops
  Trading Window Closure / Investor Complaints / ESOP grants etc.
  at the helper layer; not applied to SEC 8-K (already curated by
  SEC's design). CIK auto-resolution from
  `sec.gov/files/company_tickers.json` (cached in-process per
  invocation). Conservative future-event regex extraction (board
  meeting, AGM, EGM, record date, ex-dividend, rights issue) operates
  on headline only — deliberately ignores the summary to avoid
  false-positive future events on dated past-tense outcomes — and
  emits `proposed_calendar_entries` (calendar.yaml-shaped) for the
  orchestrator to append to `holdings/<slug>/calendar.yaml`
  `upcoming:` block. Hard 5-operation cap on web-touching tool
  calls; hard 20-row cap per invocation; cache-hit skip 24 hours
  (tighter than `news-researcher`'s 7-day cache because regulator
  filings drop unpredictably on any business day). Refuses
  user-pasted disclosures (closes the injection surface;
  primary-source fetches only). Filesystem-read-only — emits
  `proposed_disclosures_md` for the orchestrator to write. Tool
  grant: `Read, Bash, WebFetch` (WebFetch is a content-enrichment
  fallback for SEC 8-K Items 2.02 / 5.02 only, capped at 2 calls
  per invocation).
- **`_meta.yaml.exchange_codes` block** — optional per-workspace
  mapping of ticker → exchange-native identifiers (`cik` for SEC,
  `bse_code` for BSE, `nse_symbol` for NSE). Lazily populated by
  `disclosure-fetcher`: CIK is auto-resolved on first US-ticker
  invocation; BSE/NSE codes are user-supplied once on first
  India-ticker invocation (no reliable public BSE/NSE search API).
  Schema documented in
  [internal/holdings-schema.md](internal/holdings-schema.md). Backwards
  compatible: existing workspaces without the block continue to work;
  the orchestrator persists resolved values on first disclosure-fetcher
  invocation.

### Changed

- **README.md** — added a new "Pulls primary regulator filings,
  not just news about them" capability row in the "How Veda can help
  you today" table, with three sample questions covering SEC 8-K
  (US) and BSE/NSE corporate announcements (India).
- **ROADMAP.md** — added two roadmap items:
  - **Tier 5: Disclosure PDF body extraction (v2 of `fetch_disclosures`).**
    The shipped v1 captures regulator-supplied attachment URLs but
    does not download or parse the PDF body — the substance of an
    Indian board-meeting outcome is in the PDF, not in the JSON.
    A `--fetch-pdfs` flag on the helper (default off, opt-in per
    invocation) with `pypdf` text extraction is the natural v2;
    sequenced after a week or two of real BSE/NSE flow informs
    which categories warrant the parsing cost.
  - **Tier 14: Local workspace dashboard.** A locally-running web UI
    invoked with `veda dashboard` that reads every artifact the chat-
    side subagents have written into the user's workspace and renders
    them in one place — sparklines for assumption-grade history,
    valuation-zone tiles, calendar timeline, decisions audit trail.
    Read-only; chat surfaces remain the only path to mutate state.
  Both items have open questions captured inline (Q-disc-1 for PDF
  body extraction; Q-dash-1 for repo layout).
- **SKILL.md** — added Stage 3 delegation block for `disclosure-fetcher`
  with full handle-the-response branch coverage (`ok`, `cache_hit`,
  `no_disclosures`, `partial`, `insufficient_input`), including
  orchestrator-side persistence of `resolved_codes.cik` to
  `_meta.yaml` and append-to-`upcoming:` semantics for
  `proposed_calendar_entries`.
- **internal/subagents.md** — status flipped to **Shipped** (7 of
  11 subagents now shipped); inventory bullet, write-target matrix,
  and narration example all updated to match the actual contract.
- **scripts/README.md** — added documentation for `fetch_news.py`
  + `news_spam_filter.py` (the news-researcher helper, previously
  undocumented despite shipping in 0.2.0) and `fetch_disclosures.py`.
- **internal/commands.md** — updated the `refresh portfolio news`
  command's "What this command does NOT do" section to reflect that
  `disclosure-fetcher` and `fundamentals-fetcher` are now shipped
  (not future), with their own per-question Stage 3 freshness gates
  rather than batch refresh today.

## [0.2.0] - 2026-04-30

### Added

- **Company workspaces** — per-ticker directories at `holdings/<slug>/`
  containing `kb.md` (qualitative research), `thesis.md` (current investment
  thesis), `assumptions.yaml` (structured grading anchor),
  `governance.md`, `risks.md`, `fundamentals.yaml`, `valuation.yaml`, and a
  `news/` quarterly archive. Design rationale in
  [docs/design/company-workspaces.md](docs/design/company-workspaces.md).
- **`company-kb-builder` subagent**
  ([internal/agents/company-kb-builder.md](internal/agents/company-kb-builder.md)) —
  one-shot per ticker. Produces business model with revenue mix, named
  competitors, addressable market, partitioned macro sensitivity map,
  historical-shock verification, governance assessment, position-risk
  register, and a first-draft thesis with archetype classification
  (GROWTH / INCOME_VALUE / TURNAROUND / CYCLICAL). Cache-skips if `kb.md` is
  fresh (< 365 days) and `thesis.md` is not a stub. Invoked from Stage 1.5
  on stub `kb.md`.
- **`fundamentals-fetcher` subagent**
  ([internal/agents/fundamentals-fetcher.md](internal/agents/fundamentals-fetcher.md))
  + **[scripts/fetch_fundamentals.py](scripts/fetch_fundamentals.py)** —
  refreshes 12 quarters of P&L / cash-flow / balance-sheet data and
  computes a current valuation-zone snapshot. Sources: yfinance (US),
  Screener.in HTML + Chart API (India). Zone logic mirrors StockClarity's
  archetype-aware PEG / PE / EV-EBITDA / P-B model. Called from Stage 3's
  data-completeness gate.
- **`news-researcher` subagent**
  ([internal/agents/news-researcher.md](internal/agents/news-researcher.md))
  + **[scripts/fetch_news.py](scripts/fetch_news.py)** +
  **[scripts/news_spam_filter.py](scripts/news_spam_filter.py)** —
  fetches, dedups, and qualitatively grades current news per held
  position into `holdings/<slug>/news/<quarter>.md`. Six-layer filter
  pipeline: URL dedup, StockClarity-derived spam filter (87 blocked
  domains, 402 title patterns), name-presence filter, semantic dedup
  (Jaccard with 3-day date window), per-publisher cap. Grades events as
  STRENGTHENS / WEAKENS / NEUTRAL against the position's `kb.md` +
  `assumptions.yaml`. Hard 5-operation cap on web-touching calls. Refuses
  user-pasted articles (closes injection surface).
- **`base-rate-researcher` subagent**
  ([internal/agents/base-rate-researcher.md](internal/agents/base-rate-researcher.md)) —
  Stage 4 outside-view step. Looks up reference-class base rates
  (turnaround success, IPO underperformance, M&A close rates,
  post-runup forward returns). Reads
  [internal/base-rates.md](internal/base-rates.md) first; falls back to
  web research with a hard 3-operation cap. Returns Tier 1–3 sources
  only; Tier 4 hedged-range and Tier 5 NONE fallbacks remain with the
  orchestrator.
- **`portfolio-parser` subagent**
  ([internal/agents/portfolio-parser.md](internal/agents/portfolio-parser.md)) —
  parses untrusted user-pasted broker exports into structured holdings
  YAML. Security boundary: the orchestrator never sees raw paste text,
  only sanitized output. Strips instruction-like content. Invoked from
  Stage 1.5 on portfolio paste.
- **Structured assumptions** + **[scripts/validate_assumptions.py](scripts/validate_assumptions.py)** —
  per-position `assumptions.yaml` schema (claim, evidence, expected_metric,
  watch-trigger) with strict validator. Becomes the grading anchor that
  `news-researcher` uses to decide thesis-impact direction.
- **[scripts/validate_all.py](scripts/validate_all.py)** — top-level
  validator that runs `validate_profile`, `validate_assumptions`, and
  schema checks for `assets.md` and `holdings/` in one shot.
- **[internal/holdings-schema.md](internal/holdings-schema.md)**,
  **[internal/assets-update-procedures.md](internal/assets-update-procedures.md)**,
  **[internal/commands.md](internal/commands.md)** — operational schemas
  and command reference extracted from SKILL.md.
- **User-facing documentation hub** at [docs/](docs/). Plain-English
  guides written for finance people, not coders. Pages:
  [how-veda-thinks.md](docs/how-veda-thinks.md) (the 9-stage pipeline),
  [customization.md](docs/customization.md) (profile / weights /
  guardrails), [design/company-workspaces.md](docs/design/company-workspaces.md),
  and an [extending/](docs/extending/) section with end-to-end guides
  for adding a framework or a subagent. Linked from the README.
- **[holdings_registry.template.csv](holdings_registry.template.csv)** —
  template for the cross-position registry consumed by company-workspace
  bootstrapping.

### Changed

- **Stage 1.5 onboarding flow** — broker-integration prompts and profile
  template refreshed to capture broker primary/fallback choice up front
  and surface it to downstream stages.
- **Orchestrator KB-creation path** — bug fix: orchestrator now correctly
  invokes `fundamentals-fetcher` and the valuation step when
  `company-kb-builder` creates a new workspace (previously skipped on
  fresh KB creation).
- **Zerodha Kite integration** — fixed a holdings-fetch error path that
  surfaced an opaque API exception instead of a clean re-auth prompt.
- **README.md** — added the "Tracks your companies for you" capability
  (news pipeline), Documentation section linking the new docs hub,
  shipped-subagents list in Status, and a duplicate Quick-start step
  fix.
- **ROADMAP.md** — added a "User-facing documentation parity"
  cross-cutting requirement: any new capability behind a Hard Rule,
  profile field, routing change, script, or subagent must update the
  corresponding doc page in the same PR.

### Fixed

- **KB stub replacement** — `company-kb-builder` was leaving `{{stub}}`
  placeholders in `kb.md` when source research hit certain edge cases;
  now overwrites stubs in all paths.
- **Zerodha Kite holdings call** — surfaced a clean error rather than a
  raw API trace when the access token had expired mid-session.

## [0.1.0] - 2026-04-22

Initial public release. The repository has existed privately; this is the
first version stamped for public consumption.

### Added

- **11 investor frameworks** in [frameworks/](frameworks/): Buffett, Lynch,
  Munger, Fisher, Druckenmiller, Marks, Klarman, Thorp, Dalio, Templeton,
  Taleb. Each with explicit rules, kill criteria, and boundary statements.
- **9-stage orchestration pipeline** in [SKILL.md](SKILL.md) covering scope
  gating, profile load, holdings load, progressive profiling, framework
  routing, decision synthesis, arithmetic, read-back, and journaling.
- **Ten Hard Rules** enforcing profile-first answers, fresh market data, no
  LLM arithmetic, and per-file boundary discipline (`profile.md` for stable
  preferences, `assets.md` for tactical state, `journal.md` for decisions).
- **Deterministic scripts** ([scripts/calc.py](scripts/calc.py),
  [scripts/validate_profile.py](scripts/validate_profile.py),
  [scripts/fetch_quote.py](scripts/fetch_quote.py),
  [scripts/import_assets.py](scripts/import_assets.py)) for all arithmetic,
  schema validation, live quote/FX fetch, and broker-CSV ingestion.
- **Zerodha Kite live broker integration** ([scripts/kite.py](scripts/kite.py))
  with `auth` and `holdings` subcommands, daily-re-auth discipline enforced at
  the script boundary, and a chat-native refresh flow via SKILL.md Stage 1.5
  pattern 4. Broker-gated: `profile.md > broker.primary` must be `zerodha`
  before the live-pull path runs; other brokers fall back to paste or direct
  edit.
- **Onboarding flow** in [setup/onboarding.prompt.md](setup/onboarding.prompt.md)
  with progressive profiling (profile fields captured only when they become
  load-bearing for the question being asked).
- **Assets schema** in [internal/assets-schema.md](internal/assets-schema.md)
  covering the `dynamic:` block (FX rates, totals, concentration snapshots,
  capital split), holdings-row format, and currency split.
- **Example worked question** in [examples/](examples/) demonstrating the
  Lynch framework end-to-end against a real portfolio decision.
- **Scope-and-abuse perimeter** in [internal/scope-and-abuse.md](internal/scope-and-abuse.md)
  with prompt-injection defences, regulated-advice decline scripts, and the
  distress-phrasing escalation path.

### Security

- **Secrets isolation.** The `secrets/` directory is gitignored by contents
  (`secrets/*`), with a negation (`!secrets/*.example.yaml`) that keeps only
  `*.example.yaml` templates tracked. The Kite integration writes credentials
  exclusively to `secrets/kite.yaml`; access tokens are never echoed to stdout
  or chat.

[Unreleased]: https://github.com/upcomingGit/Veda-advisor/compare/v0.3.0...HEAD
[0.1.0]: https://github.com/upcomingGit/Veda-advisor/releases/tag/v0.1.0
[0.2.0]: https://github.com/upcomingGit/Veda-advisor/releases/tag/v0.2.0
[0.3.0]: https://github.com/upcomingGit/Veda-advisor/releases/tag/v0.3.0
[0.4.0]: https://github.com/upcomingGit/Veda-advisor/releases/tag/v0.4.0
[0.5.0]: https://github.com/upcomingGit/Veda-advisor/releases/tag/v0.5.0
[0.6.0]: https://github.com/upcomingGit/Veda-advisor/releases/tag/v0.6.0
