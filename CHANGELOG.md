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

### Added

- **`fundamentals-fetcher` subagent** ([internal/agents/fundamentals-fetcher.md](internal/agents/fundamentals-fetcher.md)) —
  refreshes quarterly financials and computes valuation zones for held positions.
  Called from Stage 3 data-completeness gate.
- **`scripts/fetch_fundamentals.py`** — data-fetching backend for the subagent.
  Sources: yfinance (US), Screener.in HTML scrape + Chart API (India). Zone
  computation mirrors StockClarity's archetype-aware PEG/PE/EV-EBITDA/P-B logic.

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

[Unreleased]: https://github.com/upcomingGit/Veda-advisor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/upcomingGit/Veda-advisor/releases/tag/v0.1.0
