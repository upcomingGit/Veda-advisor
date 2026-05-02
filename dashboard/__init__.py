"""Veda local dashboard.

A read-only Flask app that renders every artifact the chat-side subagents have
written into a Veda workspace. Filesystem-only — no network calls except the
opt-in `[refresh live price]` button which shells out to scripts/fetch_quote.py.

See ROADMAP.md Tier 14 ("Local workspace dashboard") and the dashboard's own
README inline below for entry points.

Run with:

    python -m dashboard [--port 8765] [--no-open] [--workspace .] [--debug]

The package is structured so each module has one job:

    config.py      CLI parsing + resolved Config object passed to the app.
    readers.py     Filesystem readers — one function per artifact shape.
    derived.py     On-read computations (sparkline data, OPM%, FCF, sleeve
                   roll-ups, cross-position event windows). No persistence.
    formatters.py  Display helpers (INR lakh/crore, percent, date, slug<->ticker).
    app.py         Flask app factory + routes. Thin glue.
    __main__.py    CLI entrypoint.
"""

__version__ = "0.1.0"
