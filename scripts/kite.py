"""
scripts/kite.py — Zerodha Kite Connect integration (v0.2).

Subcommands:

    auth      Daily browser-based OAuth. Writes access_token to
              secrets/kite.yaml and stamps next-6AM-IST expiry.
    holdings  Fetch long-term holdings as JSON.
    funds     Fetch equity-segment margins / available cash as JSON.
    trades    Fetch today's executed trades as JSON. NOTE: the Kite
              Connect API does not expose a historical tradebook —
              `trades()` returns only the current trading day. For
              historical cost-basis audits, export the Tradebook CSV
              from Zerodha Console (Reports → Tradebook).

All data-fetch subcommands fail loudly if the access_token is missing
or expired.

Per SKILL.md Hard Rules #5 and #9: every number sourced from Kite
carries an `as_of` stamp; access tokens expire at 06:00 IST each day
and must never be reused past that window. This script enforces both
at the edge so downstream code (the LLM in chat, or any caller) cannot
silently use stale creds.

Credentials live in secrets/kite.yaml (gitignored). Never paste them
into chat, email, or any other persistent channel.

Examples:

    python scripts/kite.py auth       # run once per day
    python scripts/kite.py holdings   # any number of times until expiry

Exit codes:
    0  success
    1  runtime failure (missing creds, expired token, API error); JSON
       with `error:` printed to stdout
    2  bad CLI usage (argparse prints its own message)

Requires: kiteconnect  (see requirements.txt).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse


IST = timezone(timedelta(hours=5, minutes=30))
REPO_ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = REPO_ROOT / "secrets" / "kite.yaml"

# Must match the Redirect URL registered in the Zerodha Kite Connect app.
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 5000
CALLBACK_PATH = "/kite/callback"

# Browser may take a while; user may need to log in to Zerodha first.
AUTH_TIMEOUT_SEC = 180


# -----------------------------------------------------------------------------
# Flat-YAML round-trip (stdlib only; kite.yaml is strictly `key: value`).
# -----------------------------------------------------------------------------

_KEYS = ("api_key", "api_secret", "access_token", "access_token_expires")


def _load() -> dict[str, Optional[str]]:
    if not SECRETS_PATH.exists():
        raise SystemExit(
            f"secrets/kite.yaml not found at {SECRETS_PATH}. Copy "
            f"secrets/kite.example.yaml to secrets/kite.yaml and paste "
            f"your api_key and api_secret."
        )
    data: dict[str, Optional[str]] = {k: None for k in _KEYS}
    for raw in SECRETS_PATH.read_text(encoding="utf-8").splitlines():
        # Strip inline and full-line comments; skip blank lines.
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip() or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        if key in _KEYS:
            data[key] = val.strip() or None
    return data


def _save(data: dict[str, Optional[str]]) -> None:
    """Write the four tracked keys back. Existing comments are replaced
    with a short header; the source of truth is the key/value pairs."""
    header = (
        "# Kite Connect credentials. Updated by scripts/kite.py.\n"
        "# NEVER paste these values into chat, email, or any other "
        "persistent channel.\n"
        "# Regenerate the secret at developers.kite.trade if a credential "
        "leaks.\n"
        "\n"
    )
    body = "\n".join(f"{k}: {data.get(k) or ''}" for k in _KEYS) + "\n"
    SECRETS_PATH.write_text(header + body, encoding="utf-8")


# -----------------------------------------------------------------------------
# Expiry — Kite tokens expire at 06:00 IST each day (Zerodha policy).
# -----------------------------------------------------------------------------

def _next_expiry(now: datetime) -> datetime:
    """Next 06:00 IST strictly after ``now``."""
    now = now.astimezone(IST)
    six_am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now < six_am:
        return six_am
    return six_am + timedelta(days=1)


def _is_expired(iso_str: Optional[str]) -> bool:
    """True if the stamped expiry is missing, unparseable, or already past."""
    if not iso_str:
        return True
    try:
        expiry = datetime.fromisoformat(iso_str)
    except ValueError:
        return True
    return datetime.now(tz=IST) >= expiry


# -----------------------------------------------------------------------------
# `auth` subcommand — local OAuth callback capture.
# -----------------------------------------------------------------------------

class _CallbackHandler(BaseHTTPRequestHandler):
    """Single-shot HTTP handler: captures ``?request_token=...`` once.

    State lives on the class (``captured``) because the server instantiates a
    new handler per request; we need the captured value visible to the main
    thread after the request returns.
    """

    captured: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API.
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        qs = parse_qs(parsed.query)
        token = qs.get("request_token", [""])[0]
        status = qs.get("status", [""])[0]
        _CallbackHandler.captured["request_token"] = token
        _CallbackHandler.captured["status"] = status

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = (
            "<h2>Kite auth received.</h2><p>You can close this tab.</p>"
            if token
            else "<h2>Kite auth failed.</h2><p>No request_token in callback.</p>"
        )
        self.wfile.write(msg.encode("utf-8"))

    def log_message(self, *_args: Any) -> None:
        # Silence default stderr access logs; stdout stays clean for JSON callers.
        return


def _cmd_auth(_: argparse.Namespace) -> int:
    data = _load()
    api_key = data.get("api_key")
    api_secret = data.get("api_secret")
    if not api_key or not api_secret:
        print(json.dumps({
            "error": "api_key and api_secret must be set in secrets/kite.yaml",
        }, indent=2))
        return 1

    # Local import so `--help` works without the SDK installed.
    from kiteconnect import KiteConnect

    kite = KiteConnect(api_key=api_key)
    login_url = kite.login_url()

    # Start the callback server BEFORE opening the browser so the redirect
    # lands on something already listening.
    try:
        server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler)
    except OSError as e:
        print(json.dumps({
            "error": (
                f"could not bind http://{CALLBACK_HOST}:{CALLBACK_PORT}: {e}. "
                "Another process may be using port 5000."
            ),
        }, indent=2))
        return 1

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Messages go to stderr so stdout remains a clean JSON emission point.
    print(f"Opening browser: {login_url}", file=sys.stderr)
    print(
        f"Listening for callback on "
        f"http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}",
        file=sys.stderr,
    )
    webbrowser.open(login_url)

    started = time.monotonic()
    try:
        while "request_token" not in _CallbackHandler.captured:
            if time.monotonic() - started > AUTH_TIMEOUT_SEC:
                break
            time.sleep(0.2)
    finally:
        server.shutdown()
        thread.join(timeout=2)

    request_token = _CallbackHandler.captured.get("request_token")
    if not request_token:
        print(json.dumps({
            "error": f"no request_token captured within {AUTH_TIMEOUT_SEC}s",
        }, indent=2))
        return 1

    try:
        session = kite.generate_session(request_token, api_secret=api_secret)
    except Exception as e:
        print(json.dumps({"error": f"generate_session failed: {e}"}, indent=2))
        return 1

    access_token = session.get("access_token")
    if not access_token:
        print(json.dumps({
            "error": f"generate_session returned no access_token: {session}",
        }, indent=2))
        return 1

    expiry = _next_expiry(datetime.now(tz=IST))
    data["access_token"] = access_token
    data["access_token_expires"] = expiry.isoformat()
    _save(data)

    # Deliberately NOT echoing the access_token back to stdout.
    print(json.dumps({
        "ok": True,
        "access_token_expires": expiry.isoformat(),
        "note": "access_token written to secrets/kite.yaml",
    }, indent=2))
    return 0


# -----------------------------------------------------------------------------
# Authenticated-call helper — shared by holdings / funds / trades.
# -----------------------------------------------------------------------------

def _authed_kite() -> Any:
    """Return a KiteConnect client with a non-expired access_token bound,
    or raise SystemExit(1) after emitting a structured JSON error to stdout.

    Consolidates the three credential-state checks (missing api_key,
    missing access_token, expired access_token) so each data-fetch
    subcommand stays thin.
    """
    data = _load()
    api_key = data.get("api_key")
    access_token = data.get("access_token")
    expires = data.get("access_token_expires")

    if not api_key:
        print(json.dumps({
            "error": "api_key missing in secrets/kite.yaml",
        }, indent=2))
        raise SystemExit(1)
    if not access_token:
        print(json.dumps({
            "error": "no access_token; run `python scripts/kite.py auth`",
        }, indent=2))
        raise SystemExit(1)
    if _is_expired(expires):
        print(json.dumps({
            "error": "access_token expired; run `python scripts/kite.py auth`",
            "expired_at": expires,
        }, indent=2))
        raise SystemExit(1)

    # Use a lightweight REST wrapper instead of importing the full kiteconnect
    # SDK, which drags in twisted + OpenSSL (broken on Python 3.13 due to
    # importlib frozen-module issue). The Kite Connect v3 REST API is stable
    # and all three subcommands only need GET endpoints.
    import requests

    class _KiteRest:
        """Minimal Kite Connect v3 REST client using requests."""
        _BASE = "https://api.kite.trade"
        _HEADERS = {
            "X-Kite-Version": "3",
            "Authorization": f"token {api_key}:{access_token}",
        }

        def _get(self, path: str) -> Any:
            resp = requests.get(self._BASE + path, headers=self._HEADERS, timeout=15)
            resp.raise_for_status()
            body = resp.json()
            if body.get("status") != "success":
                raise RuntimeError(body.get("message", "Kite API error"))
            return body["data"]

        def holdings(self) -> list:
            return self._get("/portfolio/holdings")

        def margins(self, segment: str = "equity") -> dict:
            return self._get(f"/user/margins/{segment}")

        def trades(self) -> list:
            return self._get("/orders/trades")

    return _KiteRest()


def _emit(payload: dict[str, Any]) -> int:
    # Kite returns datetime / Decimal in a few fields; default=str round-trips
    # them losslessly as ISO / decimal strings for JSON consumers.
    print(json.dumps(payload, indent=2, default=str))
    return 0


# -----------------------------------------------------------------------------
# `holdings` subcommand.
# -----------------------------------------------------------------------------

def _cmd_holdings(_: argparse.Namespace) -> int:
    kite = _authed_kite()
    try:
        rows = kite.holdings()
    except Exception as e:
        # Common cause: token invalidated on Zerodha's side even before our
        # stamped expiry (e.g., user logged out of Kite web). Point the user
        # at re-auth rather than at the opaque SDK exception.
        print(json.dumps({
            "error": f"holdings() failed: {e}",
            "hint": "if this persists, run `python scripts/kite.py auth`",
        }, indent=2))
        return 1

    return _emit({
        "source": "kite",
        "as_of": datetime.now(tz=IST).isoformat(),
        "count": len(rows),
        "holdings": rows,
    })


# -----------------------------------------------------------------------------
# `funds` subcommand — equity-segment margins / available cash.
# -----------------------------------------------------------------------------

def _cmd_funds(_: argparse.Namespace) -> int:
    kite = _authed_kite()
    try:
        margins = kite.margins(segment="equity")
    except Exception as e:
        print(json.dumps({
            "error": f"margins() failed: {e}",
            "hint": "if this persists, run `python scripts/kite.py auth`",
        }, indent=2))
        return 1

    return _emit({
        "source": "kite",
        "segment": "equity",
        "as_of": datetime.now(tz=IST).isoformat(),
        "margins": margins,
    })


# -----------------------------------------------------------------------------
# `trades` subcommand — today's trades only. Historical tradebook is NOT
# exposed by Kite Connect; use Zerodha Console CSV export for that.
# -----------------------------------------------------------------------------

def _cmd_trades(_: argparse.Namespace) -> int:
    kite = _authed_kite()
    try:
        rows = kite.trades()
    except Exception as e:
        print(json.dumps({
            "error": f"trades() failed: {e}",
            "hint": "if this persists, run `python scripts/kite.py auth`",
        }, indent=2))
        return 1

    return _emit({
        "source": "kite",
        "as_of": datetime.now(tz=IST).isoformat(),
        "count": len(rows),
        "trades": rows,
        "note": (
            "Kite Connect returns only today's trades. For a historical "
            "tradebook (e.g., FY cost-basis audit), export the CSV from "
            "Zerodha Console → Reports → Tradebook."
        ),
    })


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="kite",
        description="Zerodha Kite integration: auth + holdings + funds + trades.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth", help="daily OAuth flow; writes access_token to secrets/kite.yaml")
    sub.add_parser("holdings", help="fetch holdings as JSON")
    sub.add_parser("funds", help="fetch equity-segment margins / available cash as JSON")
    sub.add_parser("trades", help="fetch today's trades as JSON (not historical; use Console CSV for that)")
    args = parser.parse_args()

    if args.cmd == "auth":
        return _cmd_auth(args)
    if args.cmd == "holdings":
        return _cmd_holdings(args)
    if args.cmd == "funds":
        return _cmd_funds(args)
    if args.cmd == "trades":
        return _cmd_trades(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
