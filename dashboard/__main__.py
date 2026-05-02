"""CLI entrypoint: ``python -m dashboard``.

Resolves config, builds the Flask app, optionally opens the browser, then
serves on the configured port. Localhost only.
"""

from __future__ import annotations

import threading
import webbrowser

from .app import create_app
from .config import resolve_config


def _open_browser_after_delay(url: str, delay_s: float = 1.0) -> None:
    """Defer browser open until after Flask has bound the socket.

    Threading.Timer keeps this off the main thread so app.run() can take it.
    Best-effort: failures are swallowed so a missing default browser does not
    crash the dashboard.
    """
    def _open() -> None:
        try:
            webbrowser.open(url, new=2)
        except Exception:  # noqa: BLE001 -- best-effort; never crash on browser
            pass

    threading.Timer(delay_s, _open).start()


def main() -> None:
    cfg = resolve_config()
    app = create_app(cfg)
    print(f"Veda dashboard serving at {cfg.url}")
    print(f"  workspace: {cfg.workspace}")
    print(f"  event window: next {cfg.event_window_days} days")
    if cfg.auto_open:
        _open_browser_after_delay(cfg.url)
    # use_reloader=False even in debug, because the reloader spawns a child
    # process that re-runs `main()` and re-opens the browser. That is the
    # wrong UX for a local one-shot server.
    app.run(
        host=cfg.bind,
        port=cfg.port,
        debug=cfg.debug,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
