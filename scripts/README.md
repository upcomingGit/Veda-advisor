# Veda utility scripts

Helper scripts for Veda. Three categories:

1. **`calc.py` — required.** Veda's Hard Rule #8 forbids LLM arithmetic. Every EV, p_loss, PEG, Kelly, FX, or weight-sum number comes from this script. See SKILL.md Hard Rule #8.
2. **`validate_profile.py` — required at onboarding.** Deterministic schema check for `profile.md`. Run at the end of onboarding to catch enum typos and missing fields before they reach Stage 1.
3. **`import_portfolio.py` — optional persistence shortcut.** Only useful if you ask enough portfolio-level questions that re-pasting holdings becomes annoying.

---

## `calc.py` — arithmetic helpers (required)

LLMs miscalculate. Even a 1% miscalculation on an EV block can flip a recommendation from `pass` to `proceed` or the reverse. `calc.py` is pure stdlib Python (no dependencies, Python 3.10+) and deterministic.

### Subcommands

| Subcommand      | Purpose                                                     | Example |
|-----------------|-------------------------------------------------------------|---------|
| `ev`            | Expected value (percent) and p_loss for a scenario set      | `python scripts/calc.py ev --probs 0.35 0.40 0.25 --returns 60 15 -35` |
| `p_loss`        | p_loss and p_loss_pct only                                  | `python scripts/calc.py p_loss --probs 0.35 0.40 0.25 --returns 60 15 -35` |
| `kelly`         | Full-Kelly and half-Kelly fractions                          | `python scripts/calc.py kelly --p-win 0.6 --odds 1` |
| `peg`           | PEG ratio (P/E ÷ growth rate in %)                           | `python scripts/calc.py peg --pe 32.1 --growth 78` |
| `fx`            | Currency conversion (amount × rate)                          | `python scripts/calc.py fx --amount 5000 --rate 83.2` |
| `weights-sum`   | Sum of framework_weights (profile validation)                 | `python scripts/calc.py weights-sum --weights 0.15 0.18 0.05 ...` |

### Probability validation

`ev` and `p_loss` both call `validate_probabilities()`, which requires:
- Every probability is in [0, 1].
- Probabilities sum to 1.00 within a 1e-6 tolerance.

If the numbers don't balance, the script raises `ValueError` and you fix the scenarios — you do not round silently.

### Importing programmatically

```python
from scripts.calc import expected_value, p_loss_pct, peg, half_kelly

ev = expected_value([0.35, 0.40, 0.25], [60, 15, -35])
pl = p_loss_pct([0.35, 0.40, 0.25], [60, 15, -35])
```

### Adding a new computation

If Veda needs a number the script doesn't produce (e.g. CAGR, drawdown percentage, portfolio heat), **add a function to `calc.py` before using the number**. Do not compute it inline in the LLM. This is how miscalculations become caught bugs instead of shipped decisions.

---

## `validate_profile.py` — profile schema validator (required at onboarding)

The onboarding flow has the LLM map user free-text answers into structured YAML. That mapping is usually right and occasionally silently wrong — a `growth` instead of `balanced_growth`, a `HIGH` instead of `high`, a missing guardrails field. SKILL.md Stage 1 schema-validates on read, so a bad profile eventually fails loudly; this validator lets onboarding fail fast instead, before the user leaves the session.

Pure stdlib. No YAML parser. Regex against the known schema, so it works in any Python 3.10+ environment.

### Usage

```powershell
python scripts/validate_profile.py profile.md
```

Path argument defaults to `./profile.md`. Exit codes: `0` valid, `1` validation errors printed to stderr, `2` file missing or unreadable.

### What it checks

- Required top-level fields: `schema_version`, `generated`, `profile_last_updated`, `disclosure_acknowledged`, `experience_mode`, `max_loss_probability`.
- `disclosure_acknowledged` is literally `true`.
- Date fields (`generated`, `profile_last_updated`) match `YYYY-MM-DD`.
- `max_loss_probability` is an int in `[0, 100]`.
- All enum fields are one of the exact allowed strings (see the `ENUM_VALUES` table in the script source): `experience_mode`, `goal.primary`, `risk.stated_tolerance`, `risk.calibrated_tolerance`, `concentration.current.style`, `concentration.target.style`, `style_lean.primary`, `experience.level`, `experience.explanation_depth`.
- Boolean fields (`instruments.*`, `guardrails.block_*`, etc.) are literally `true` or `false`.
- `capital.split` and `capital.target_split` components each sum to exactly 100 when the block is present (all four buckets written). Partial blocks are tolerated so progressive profiling can leave a block absent entirely.
- When `experience_mode: novice`, the `guardrails` block is present and every required guardrail field is filled.
- `fx_rates.<pair>.rate` is a positive number and `fx_rates.<pair>.as_of` is `YYYY-MM-DD` for every pair listed. See Hard Rule #9 in SKILL.md; staleness is enforced at runtime by the orchestrator, not by this script.
- If present, `framework_weights` contains all 11 investors and the sum lies in the loose band `[0.9, 1.1]`. (Weights are ordinal tie-breakers, not probabilities — the band is deliberate.)

What it does **not** check: free-text fields (`notes`, `self_identified_weakness`, `risk.behavioral_history`), list contents beyond presence, or anything requiring judgment. Those remain the LLM's job and the read-back step's job.

### When to run it

- At the end of onboarding, before declaring the profile saved. (Step 6 of `setup/onboarding.prompt.md`.)
- After manual edits to `profile.md`.
- Before filing an issue — if the validator errors, fix the profile first.

---

## `import_portfolio.py` — optional persistence shortcut

Veda's default portfolio workflow is: when it needs your holdings for a question, it asks, and you paste them in any format — a copy from your broker app, a spreadsheet dump, or rough natural language. No file generation, no CSV export, no script to run. This script exists only as a shortcut for users who ask enough portfolio-level questions that re-pasting becomes annoying.

Convert a broker CSV export into `portfolio.md` (the structured holdings file Veda reads for portfolio-level questions).

### When to use it

- You ask portfolio-level questions frequently enough that pasting positions each time feels repetitive.
- You want Veda to remember your holdings between sessions so it can build correlation and concentration history.

### When to skip it

- You ask single-name questions mostly ("is X a good business?"). You don't need a portfolio file.
- You only check a portfolio question occasionally. Pasting the list takes 10 seconds and avoids installing Python or maintaining a file.

### Usage

```powershell
# From the Veda-advisor folder
python scripts/import_portfolio.py zerodha holdings.csv

# Or a generic CSV (ticker / shares / avg_cost / current_price columns)
python scripts/import_portfolio.py generic my_broker_export.csv

# Custom output path
python scripts/import_portfolio.py zerodha holdings.csv --out ~/notes/portfolio.md
```

### Supported brokers (v0.1)

| Broker | CSV source | Notes |
|---|---|---|
| `zerodha` | Kite → Holdings → Download CSV | Works with the current and recent column-name variants. |
| `generic` | Any CSV | Columns: `ticker`, `shares`/`quantity`, `avg_cost`/`cost_basis`, `current_price`/`price`/`ltp`. `name` and `sector` optional. |

Adding a new broker is a ~20-line function. See the docstrings at the top of `import_portfolio.py` and the `parse_zerodha` reference implementation.

### What the script does NOT do

- **Does not fetch live prices.** Current prices come from the CSV, which is usually end-of-day.
- **Does not ask for theses.** The `thesis` and `tags` columns are left blank and Veda fills them *lazily* — when you ask about a specific holding, Veda asks for the one-line thesis and saves it back. You never batch-fill the file.
- **Does not commit for you.** `portfolio.md` is gitignored. After generating, verify with `git check-ignore -v portfolio.md`.

### Roadmap

- **v0.2:** More broker CSV parsers. Priority targets: Groww, ICICI Direct, Interactive Brokers, Fidelity.
- **v1.0:** MCP-based live broker integration. Zerodha already has an MCP server; when that matures and other brokers follow, Veda will read positions directly without manual CSV export.
