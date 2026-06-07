# screen-schema.md — cohort screen (v1)

The cohort screen takes a list of companies in one sector — the cohort — and
turns it into a shortlist. It answers one question: of all the names in this
sector, which ones clear my rules.

This is Module 5. It is the last step of the idea-to-candidate funnel: an idea
or theme gives you a sector, the sector gives you a cohort of names, and the
screen narrows that cohort to the few worth a closer read first. It does not
pick a stock to buy, and it does not rank the survivors. It narrows a long list
to a short one.

This is research support, not a buy list. **The screen never proposes a trade.**
It lists names for you to read. A person reads the shortlist, researches the
names in Veda, and only then decides anything.

## The two files you own

- `user-config/cohorts/<sector>.json` — the cohort: the list of names in one
  sector, each with the archetype labels research assigned it. You create one of
  these per sector you want to screen. The names and labels come from a sector
  dossier in the research work; the bridge can fill the per-name data for you
  (see "Where the numbers come from" below).
- `user-config/screen.json` — your rules: the hard filters that exclude a name. You
  edit this file directly. It is your screen, the same way `user-config/caps.json`
  is your mandate.
- `user-config/research.json` — where the Veda-research repository lives, so the
  bridge can ask it for each name's fundamentals. A path and an optional Python
  command; the default assumes the two repositories sit side by side.

## The cohort file

```json
{
  "sector": "airlines-india",
  "names": [
    { "ticker": "INDIGO", "market": "india", "primary": "GROWTH", "secondary": "CYCLICAL" },
    { "ticker": "SPICEJET", "market": "india", "primary": "TURNAROUND" }
  ]
}
```

- `sector` — a short name for the cohort. It names the output file.
- `names` — the companies, each a bare ticker (the form you actually type:
  `INDIGO`, not `INDIGO.NS`). The `.NS` / `.BO` suffix is a yfinance convention
  no one sees in normal use; leave it off.
- `market` — where the name trades: `india` or `us`. You state it plainly next
  to the ticker, the same way holdings do, so the bridge fetches the name from
  the right place. (Without it the bridge guesses from the bundled ticker table,
  then from the currency research returns — set it to be sure.)
- `primary` — the archetype research judged best fits the name: one of `GROWTH`,
  `INCOME_VALUE`, `TURNAROUND`, or `CYCLICAL`. The bridge forwards it so research
  knows which valuation lens to place the name in.
- `secondary` — an optional second archetype, when a name plausibly fits two
  lenses. It produces a second valuation zone, shown beside the first. Leave it
  out when there is only one sensible lens.

The labels are research's call, not the advisor's. The advisor only forwards
them; it does not decide which archetype a name is.

The cohort and the per-name research data both come from Veda-research. The
advisor does not gather either; it applies your rules to what research has
already produced (see "Where the numbers come from" below).

## The rules file

```json
{
  "filters": {
    "min_roce_pct": null,
    "max_debt_to_equity": null
  }
}
```

### Filters — the names to exclude

A filter throws a name out of the shortlist. The numbers start as `null`, which
means "not set, do not apply." A filter with `null` is skipped, so an empty
rules file keeps the whole cohort and excludes nothing. You fill in the numbers
that match your standard.

- `min_roce_pct` — exclude a name whose return on capital employed is below this
  many percent. `null` means the filter is off.
- `max_debt_to_equity` — exclude a name whose debt-to-equity is above this.
  `null` means off.

Valuation is not a filter. A name is never excluded for being expensive; its
valuation is shown for you to weigh, not used to throw it out (see "Valuation is
shown, not filtered" below).

A name that is missing the number a filter needs is **not** thrown out silently.
It is set aside as a data gap — "I could not check this rule for this name" —
and listed for you to fix. A gap is never read as a pass and never as a fail.

## Where the numbers come from

The advisor does no research of its own. It reads the fundamentals the
Veda-research agent has already produced and applies your filters to them. The
boundary is the firm's rule: research finds and gathers; the advisor takes your
preferences and applies them to what research produced.

For each name the screen looks for a saved data file under
`screen/data/<TICKER>.json` holding the few numbers it needs: return on capital
(`roce_pct`, with `roe_pct` as a fallback), `debt_to_equity`,
`trailing_growth_pct`, `fcf_yield_pct`, a `market`, an `as_of` date, and a
`valuation` block (raw multiples and one or two zones; see the next section).
These files are Veda-research output; the advisor reads them and only writes them
through the bridge.

The bridge — `scripts/research_bridge.py` — is the one step that crosses to the
research repository. For each name in a cohort it asks Veda-research for that
name's fundamentals, maps the answer into the shape above, and writes
`screen/data/<TICKER>.json`. It carries the numbers across; it does not filter
or judge. That keeps the boundary intact: research gathers, the advisor filters.
Refresh a cohort's data once, then screen it:

- In chat: `refresh cohort airlines-india`, then `screen airlines-india`.
- The chat runs these underneath:

```
python scripts/research_bridge.py --cohort airlines-india
python scripts/screen.py --cohort airlines-india
```

Both are wired as chat commands (see [commands.md § refresh cohort](commands.md#refresh-cohort-name--pull-research-data-for-a-cohort)
and [§ screen](commands.md#screen-name--filter-a-cohort)); you do not run the
scripts by hand.

A name with no data file, or an unreadable one, is a **data gap**. The screen
does not fetch it — gathering that data is the bridge's job. It reports the
gap as "run the bridge on this cohort first," so you know the fix is to run the
bridge, not to change the screen.

The filtering itself never touches disk or the network. It is a plain function
that takes the saved numbers and the rules and returns the surviving list, so it
can be tested with fixed numbers.

## Valuation is shown, not filtered

Valuation does not filter a name. It is shown so you can read each name on
whichever lens fits it, and judge for yourself. A name can plausibly fit more
than one archetype — a growth lens and a cyclical lens can disagree on whether
it is cheap — so the screen shows every zone research worked out rather than
collapsing them into one verdict.

For each name the `valuation` block in its data file carries:

- `multiples` — the raw numbers: `pe`, `pb`, `ps`, `peg`, `ev_ebitda`. Shown as
  given; any that research did not produce is left out.
- `zones` — one entry per archetype label on the cohort name (the `primary`, and
  the `secondary` if set). Each entry names the `archetype`, its `role`
  (`primary` or `secondary`), the `zone` (`CHEAP`, `FAIR`, or `EXPENSIVE`), the
  `primary_metric` and its value the zone was read from, and the `thresholds`
  used. The thresholds are shown so how the zone was reached is visible, not
  hidden.

When research returns no zone for a name — it could not place it — the entry is
carried with a null zone and the name is reported as a zone gap, so a missing
zone is named, never quietly dropped.

## Stale-data guard

The same idea as the other modules, on a longer clock: if a name's saved numbers
are more than the freshness window old (90 days by default) relative to the run
date, that name is flagged stale. The screen still lists it, but the flag warns
the read leans on old fundamentals. Fundamentals are quarterly, so the window is
wider than the 7-day price guard the NAV, concentration, and rebalance modules
use. A stale name is the cue to refresh it in Veda-research.

## Output

- **Printed table.** A readable summary to standard output: the cohort and its
  sector, the rules in force, the names that cleared the filters, then the
  excluded names with the rule each failed, and the data gaps.
- **Screen file.** `screen/<sector>.json`, one JSON object with the same content
  in structured form, for the dashboard or another module to read. The folder is
  gitignored, because the cohort and shortlist reveal what is being researched.

Each survivor row carries: `ticker`, `market`, the four numbers (return on
capital, debt-to-equity, growth, free-cash-flow yield), the `valuation` block
shown beneath the row, and a `stale` flag. Each excluded row carries the
`reason` it failed. Each data-gap row carries which number was missing.

## What v1 does not do

- No idea generation. It ranks a cohort you hand it; it does not find the
  sector or build the cohort. That is upstream research work.
- No buy or sell call. It orders names to read; it never proposes a trade, sizes
  a position, or sets a target. To act on a name, research it in Veda and, if you
  decide to hold it, set a target in `user-config/caps.json`.
- No absolute verdict. The score ranks within the cohort, not against the whole
  market. A high score means "best of this list," not "cheap" or "good" on its
  own.
- No research. It does not fetch fundamentals, prices, or zones. The bridge asks
  Veda-research for them and the screen applies your rules. A name with no
  research data is a data gap that says run the bridge, not a number for the
  advisor to compute.
