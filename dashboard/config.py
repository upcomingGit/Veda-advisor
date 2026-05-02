"""Dashboard configuration.

Resolves CLI flags into a single Config object that the app and templates
read from. Nothing here writes to the workspace.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


# Default port. 8765 was chosen because it is in IANA's user/dynamic range,
# unlikely to clash with common dev servers (3000/5000/8000/8080), and easy
# to remember. Override with --port if the port is occupied.
DEFAULT_PORT = 8765

# Default cross-position upcoming-events window. Matches the holdings-schema
# guidance for the orchestrator's portfolio-wide derived view.
DEFAULT_EVENT_WINDOW_DAYS = 30

# Theme choices. ``system`` defers to the browser's prefers-color-scheme.
# Whatever value is picked here is only the *initial* attribute on <html>;
# the in-browser theme picker can override and persists in localStorage.
THEME_CHOICES = ("system", "light", "dark")
DEFAULT_THEME = "system"


@dataclass(frozen=True)
class Config:
    workspace: Path                 # path to the Veda-advisor repo root
    port: int                       # localhost bind port
    auto_open: bool                 # whether to open the browser on startup
    debug: bool                     # Flask debug + reloader
    event_window_days: int          # cross-position upcoming-events window
    bind: str                       # always 127.0.0.1 in v1; surfaced for visibility
    initial_theme: str              # one of THEME_CHOICES; sets <html data-theme=...>

    @property
    def url(self) -> str:
        return f"http://{self.bind}:{self.port}/"

    @property
    def holdings_dir(self) -> Path:
        return self.workspace / "holdings"

    @property
    def assets_path(self) -> Path:
        return self.workspace / "assets.md"

    @property
    def journal_path(self) -> Path:
        return self.workspace / "journal.md"

    @property
    def profile_path(self) -> Path:
        return self.workspace / "profile.md"

    @property
    def registry_path(self) -> Path:
        return self.workspace / "holdings_registry.csv"

    @property
    def fetch_quote_script(self) -> Path:
        return self.workspace / "scripts" / "fetch_quote.py"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m dashboard",
        description=(
            "Veda local dashboard. Read-only web UI that renders every artifact "
            "in your Veda workspace. No network calls except the opt-in live-price "
            "refresh button."
        ),
    )
    p.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help=(
            "Path to the Veda-advisor repo root (the directory containing "
            "assets.md, holdings/, profile.md). Default: current working directory."
        ),
    )
    p.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Localhost port to bind. Default: {DEFAULT_PORT}.",
    )
    p.add_argument(
        "--no-open",
        action="store_true",
        help="Do not auto-open the browser on startup. Default: open.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Enable Flask debug mode (auto-reload, traceback page).",
    )
    p.add_argument(
        "--event-window-days",
        type=int,
        default=DEFAULT_EVENT_WINDOW_DAYS,
        help=(
            "Days ahead to include in the cross-position upcoming-events list "
            f"on the overview page. Default: {DEFAULT_EVENT_WINDOW_DAYS}."
        ),
    )
    p.add_argument(
        "--theme",
        choices=THEME_CHOICES,
        default=DEFAULT_THEME,
        help=(
            "Initial theme written into the <html data-theme=...> attribute. "
            "The in-browser picker (top-right or /settings) can override and "
            "persists the choice in localStorage. Default: "
            f"{DEFAULT_THEME}."
        ),
    )
    return p


def resolve_config(argv: list[str] | None = None) -> Config:
    args = build_parser().parse_args(argv)
    workspace = args.workspace.expanduser().resolve()
    if not workspace.is_dir():
        raise SystemExit(
            f"--workspace must point to an existing directory; got {workspace}"
        )
    return Config(
        workspace=workspace,
        port=args.port,
        auto_open=not args.no_open,
        debug=args.debug,
        event_window_days=args.event_window_days,
        # Hard-bound to localhost in v1. The dashboard reads tactical state
        # (assets.md is gitignored for a reason) and a 0.0.0.0 bind would
        # expose holdings on a LAN. Surfaced as a config field for visibility
        # so the settings page can display it honestly, not so it can change.
        bind="127.0.0.1",
        initial_theme=args.theme,
    )
