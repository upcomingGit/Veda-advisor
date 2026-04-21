"""
Veda - live quote + FX fetcher (yfinance).

Hard Rule #9 (SKILL.md) forbids LLMs from reusing prices or FX rates from
training data or prior sessions. This script is the "I have web/data tools"
path: when the host environment exposes a terminal and network, the LLM can
call this to produce a same-session, timestamped number with a source.

Design targets:
  - **One provider (yfinance)** covers US equities, India NSE/BSE equities,
    FX pairs, and major indices. Same failure surface, same library.
  - **India suffix dispatch.** Indian tickers on Yahoo carry `.NS` (NSE) or
    `.BO` (BSE). If the user passes a bare ticker like `CAPLIPOINT`, we try
    `.NS` first and fall back to `.BO`. If the user passes an explicit
    suffix (`TITANBIO.BO`), we respect it.
  - **JSON stdout.** Output is machine-readable so the LLM or another script
    (e.g., import_assets.py) can parse it without regex. A non-zero exit
    code signals failure, and the JSON carries an `error:` field.
  - **No caching, no writes.** This script fetches and prints. Persistence
    is the caller's job (LLM writing to assets.md, or import_assets.py
    materialising a portfolio export). A caching layer is an easy future
    extension; until then, every call hits the wire, which is the correct
    default for a staleness-sensitive product.

Examples:

    python scripts/fetch_quote.py quote --ticker MSFT
    python scripts/fetch_quote.py quote --ticker CAPLIPOINT.NS
    python scripts/fetch_quote.py quote --ticker CAPLIPOINT         # auto .NS, falls back .BO
    python scripts/fetch_quote.py quote --ticker TITANBIO           # auto .NS (empty), falls back .BO
    python scripts/fetch_quote.py fx --pair usd_inr
    python scripts/fetch_quote.py fx --pair eur_usd

Exit codes:
    0 - success; JSON with the fetched value printed to stdout
    1 - fetch failed; JSON with `error:` field printed to stdout (not stderr
        so the caller can parse it uniformly)
    2 - bad usage (argparse will already have printed a message)

Requires ``yfinance`` to be installed (see requirements.txt).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Optional


# -----------------------------------------------------------------------------
# Ticker resolution
# -----------------------------------------------------------------------------

def _try_fetch(yf_ticker: str) -> Optional[dict[str, Any]]:
    """Try to fetch the last close for a specific Yahoo symbol.

    Returns a dict with ``last_close`` / ``as_of`` / ``currency`` on success,
    or ``None`` if Yahoo returns empty history for this symbol (which is how
    a delisted / wrong-suffix / non-existent ticker manifests). Exceptions
    propagate -- the caller decides whether to fall back or abort.
    """
    import yfinance as yf  # local import so --help works without yfinance

    # Silence yfinance's noisy fallback chatter. When we probe `.NS` and it
    # doesn't exist, yfinance prints an HTTP 404 line to stderr even though
    # the `None` return is all we need. Our caller (the LLM) parses stdout
    # JSON; keeping stderr clean means a single-shot fallback probe doesn't
    # look like a failure.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    ticker = yf.Ticker(yf_ticker)
    # period="5d" is enough to get at least one trading day even over a
    # long weekend; auto_adjust=True folds splits/dividends into close,
    # which is the convention for "what's the last traded price."
    with contextlib.redirect_stderr(io.StringIO()):
        hist = ticker.history(period="5d", auto_adjust=True)
    if hist is None or hist.empty or "Close" not in hist.columns:
        return None

    closes = hist["Close"].dropna()
    if closes.empty:
        return None

    last_close = float(closes.iloc[-1])
    last_date = closes.index[-1].strftime("%Y-%m-%d")

    # ticker.info is best-effort; Yahoo sometimes omits it for FX.
    currency: Optional[str] = None
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            info = ticker.info
        if isinstance(info, dict):
            currency = info.get("currency")
    except Exception:
        currency = None

    return {
        "resolved_ticker": yf_ticker,
        "last_close": last_close,
        "as_of": last_date,
        "currency": currency,
    }


def resolve_equity(ticker: str) -> dict[str, Any]:
    """Resolve a user-provided equity ticker to a Yahoo symbol and fetch it.

    Dispatch rules:
        - Ticker contains a ``.`` -> treat as an explicit Yahoo symbol
          (user knows what they want; do not probe).
        - Otherwise -> try ``<ticker>.NS`` first, then ``<ticker>.BO``, then
          the bare ticker (covers US tickers like ``MSFT`` that have no
          suffix on Yahoo).
    """
    if "." in ticker:
        candidates = [ticker]
    else:
        candidates = [f"{ticker}.NS", f"{ticker}.BO", ticker]

    tried: list[str] = []
    for candidate in candidates:
        tried.append(candidate)
        result = _try_fetch(candidate)
        if result is not None:
            result["input_ticker"] = ticker
            result["source"] = "yfinance"
            result["tried"] = tried
            return result

    return {
        "input_ticker": ticker,
        "error": f"no data found for {ticker}; tried {tried}",
        "tried": tried,
        "source": "yfinance",
    }


# -----------------------------------------------------------------------------
# FX resolution
# -----------------------------------------------------------------------------

def resolve_fx(pair: str) -> dict[str, Any]:
    """Resolve an ``<from>_<to>`` pair (e.g., ``usd_inr``) to a yfinance FX symbol.

    Yahoo encodes FX as ``FROMTO=X`` with both codes uppercase (e.g.,
    ``USDINR=X``). The ``rate`` returned converts 1 unit of ``from`` to ``to``.
    """
    pair_lower = pair.lower().strip()
    if "_" not in pair_lower:
        return {
            "pair": pair,
            "error": f"pair must be '<from>_<to>' (e.g., 'usd_inr'); got {pair!r}",
            "source": "yfinance",
        }

    from_ccy, to_ccy = pair_lower.split("_", 1)
    if not from_ccy.isalpha() or not to_ccy.isalpha():
        return {
            "pair": pair,
            "error": f"currency codes must be letters only; got {pair!r}",
            "source": "yfinance",
        }

    yf_symbol = f"{from_ccy.upper()}{to_ccy.upper()}=X"
    result = _try_fetch(yf_symbol)
    if result is None:
        return {
            "pair": pair_lower,
            "resolved_ticker": yf_symbol,
            "error": f"no data found for {yf_symbol}",
            "source": "yfinance",
        }

    return {
        "pair": pair_lower,
        "resolved_ticker": yf_symbol,
        "rate": result["last_close"],
        "as_of": result["as_of"],
        "source": "yfinance",
        # Yahoo reports FX `info.currency` as the quote currency, which is
        # the `to` side. We echo `from`/`to` for the caller's clarity.
        "from_ccy": from_ccy.lower(),
        "to_ccy": to_ccy.lower(),
    }


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def _emit(payload: dict[str, Any]) -> int:
    """Print JSON to stdout. Exit code 0 if no ``error`` key, else 1."""
    # sort_keys makes outputs diff-stable across runs (useful for CI).
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if "error" in payload else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch a live quote or FX rate via yfinance.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_quote = sub.add_parser(
        "quote",
        help="Fetch the last close for an equity / ETF / index.",
    )
    p_quote.add_argument(
        "--ticker",
        required=True,
        help=(
            "Ticker symbol. US: 'MSFT'. India: 'CAPLIPOINT' "
            "(auto .NS/.BO fallback) or explicit 'TITANBIO.BO'."
        ),
    )

    p_fx = sub.add_parser(
        "fx",
        help="Fetch an FX rate. Pair format: <from>_<to>, e.g., 'usd_inr'.",
    )
    p_fx.add_argument(
        "--pair",
        required=True,
        help="Currency pair in the form '<from>_<to>' (e.g., 'usd_inr').",
    )

    args = parser.parse_args(argv)

    # Record the wall-clock fetch time so the caller can audit staleness.
    # The `as_of` field in the payload is the *market* date (last trading
    # close); `fetched_at` is when this process ran. Both matter.
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        if args.command == "quote":
            payload = resolve_equity(args.ticker)
        elif args.command == "fx":
            payload = resolve_fx(args.pair)
        else:  # pragma: no cover -- argparse enforces `required=True`
            parser.error(f"unknown command: {args.command}")
            return 2
    except ModuleNotFoundError as exc:
        # yfinance missing is the single most likely install-time failure
        # on a fresh clone; give a precise, actionable error.
        return _emit({
            "error": (
                f"missing dependency: {exc.name}. "
                "Install with: pip install -r requirements.txt"
            ),
            "fetched_at": fetched_at,
        })
    except Exception as exc:  # defensive -- yfinance raises a grab-bag of errors
        return _emit({
            "error": f"{type(exc).__name__}: {exc}",
            "fetched_at": fetched_at,
        })

    payload["fetched_at"] = fetched_at
    return _emit(payload)


if __name__ == "__main__":
    sys.exit(main())
