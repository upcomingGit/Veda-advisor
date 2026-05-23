"""
Veda - live quote + FX fetcher (yfinance).

Hard Rule #9 (SKILL.md) forbids LLMs from reusing prices or FX rates from
training data or prior sessions. This script is the "I have web/data tools"
path: when the host environment exposes a terminal and network, the LLM can
call this to produce a same-session, timestamped number with a source.

Design targets:
  - **Default `quotes` mode auto-routes** by reading the bundled
    `scripts/data/ticker_market.csv` (~12,700 entries: SEC + NSE). Each
    known US ticker goes to Yahoo's `spark` batch endpoint (one HTTP for
    the whole US group), each known India ticker goes to Screener.in
    (parallel HTTPs), and unknowns (rare -- fresh IPOs, obscure
    delistings) fall back to the per-ticker yfinance ladder. The three
    groups run concurrently so wall time is bounded by the slowest group.
    Single `quote` and `fx` still use yfinance unchanged.
  - **Explicit `--market us`/`--market india`** skips the lookup and
    sends the whole batch through that market's primitive. Useful when
    the caller already knows the market and wants to avoid the table
    import (or wants to fetch a US ADR for an India-wins colliding
    symbol like INFY).
  - **Why per-market primitives.** US: Yahoo's public `spark` endpoint
    returns close data for a comma-separated symbol list in one HTTP
    request, no auth, full precision. India: Screener.in's company page
    -- matches what Veda's fundamentals-fetcher and calendar-tracker
    already use, but its rendered price is rounded to the nearest rupee.
    NSE-direct was evaluated and ruled out: Akamai blocks the
    cookie-warmup handshake from this host class.
  - **India suffix dispatch.** Indian tickers on Yahoo carry `.NS` (NSE)
    or `.BO` (BSE). Suffixed inputs route to India via either the lookup
    module's suffix rule or, for the default-path yfinance ladder, the
    classic `.NS` -> `.BO` -> bare probe.
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
    python scripts/fetch_quote.py quotes --tickers MSFT TSM MU CDSL WONDERLA
    python scripts/fetch_quote.py quotes --tickers CAPLIPOINT TITANBIO WONDERLA --market india
    python scripts/fetch_quote.py fx --pair usd_inr
    python scripts/fetch_quote.py fx --pair eur_usd

Exit codes:
    0 - success; JSON with the fetched value printed to stdout
    1 - fetch failed; JSON with `error:` field printed to stdout (not stderr
        so the caller can parse it uniformly). For the `quotes` batch mode,
        exit 1 if *any* ticker in the batch errored (strict rule).
    2 - bad usage (argparse will already have printed a message)

Requires ``yfinance`` to be installed (see requirements.txt).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional


# Max parallel workers for the `quotes` batch mode. Eight covers today's US
# sleeve in one round trip and keeps the open-connection count well within
# any reasonable rate limit. yfinance is blocking I/O, so threads (not
# asyncio) are the right tool.
MAX_WORKERS = 8


# -----------------------------------------------------------------------------
# Ticker resolution -- default path (yfinance), used by the single
# `quote` command and by `quotes` when --market is not set. Unchanged
# from V1 so any caller that does not opt into --market is byte-stable.
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
# Batch endpoints -- one HTTP call shared by the whole list (US) or one
# HTTP per ticker run in parallel (India). Selected by `--market` on the
# `quotes` subcommand. These paths bypass yfinance entirely.
# -----------------------------------------------------------------------------

# Yahoo's public "spark" endpoint takes a comma-separated symbol list and
# returns price metadata + a daily-close series for every symbol in one
# JSON response. This is what powers Yahoo's own watchlist widgets; it
# does not require the crumb/cookie dance the v7 quote endpoint now
# demands. Confirmed anonymous from this host (2026-05-23).
YAHOO_SPARK_URL = "https://query1.finance.yahoo.com/v7/finance/spark"

# Screener.in is the de-facto retail-research source for Indian listings;
# Veda's fundamentals-fetcher and calendar-tracker subagents already use
# it. The company page renders the live price in the `top-ratios` block
# under the literal label "Current Price". Caveat: that displayed price
# is rounded to the nearest rupee, so sub-rupee precision is lost. The
# error on Veda's actual universe (sub-1% even on the lowest-priced
# holdings) is well below the noise of other valuation inputs.
SCREENER_BASE = "https://www.screener.in"
SCREENER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

# Anchored to the literal "Current Price" label that Screener's top-ratios
# <ul> uses on every equity page. The structure has been stable across
# the redesigns Veda's other India scrapers already rely on.
_SCREENER_PRICE_RE = re.compile(
    r'<span class="name">\s*Current Price\s*</span>'
    r'.*?<span class="number">([\d,]+(?:\.\d+)?)</span>',
    re.DOTALL,
)

# Hard per-call wall-clock cap. Generous enough to absorb a slow response
# from either source, tight enough that a stuck single request does not
# stall a whole batch.
HTTP_TIMEOUT_SECONDS = 10


def _fetch_us_batch(tickers: list[str]) -> dict[str, Any]:
    """Fetch many US tickers in ONE HTTP call via Yahoo's spark endpoint.

    The spark response's ``meta.regularMarketPrice`` is the most-recent
    traded price (intraday) or, after market close, the official closing
    print -- the same value
    ``yfinance.Ticker.history(period="5d")["Close"].iloc[-1]`` returns.
    We use it for ``last_close`` so the schema is identical to the
    default yfinance path. ``as_of`` is derived from
    ``meta.regularMarketTime`` (UTC).

    Tickers the spark response omits (or returns null for) get an error
    entry; the rest still go through. Output preserves input order.
    """
    import requests  # local import; aligns with the yfinance local-import pattern

    params = {
        "symbols": ",".join(tickers),
        "range": "5d",
        "interval": "1d",
    }
    headers = {"User-Agent": SCREENER_HEADERS["User-Agent"]}  # bare UA is enough

    try:
        r = requests.get(
            YAHOO_SPARK_URL,
            params=params,
            headers=headers,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        payload = r.json()
    except requests.RequestException as exc:
        # Whole-batch failure -- emit one error entry per ticker so the
        # strict-exit rule fires and the caller sees the full input list.
        return {"quotes": [
            {
                "input_ticker": t,
                "error": f"yahoo spark request failed: {type(exc).__name__}: {exc}",
                "source": "yahoo-spark",
                "market": "us",
            }
            for t in tickers
        ]}

    by_symbol: dict[str, dict[str, Any]] = {}
    for item in payload.get("spark", {}).get("result", []):
        symbol = item.get("symbol")
        responses = item.get("response", []) or []
        if not symbol or not responses:
            continue
        meta = responses[0].get("meta", {}) or {}
        price = meta.get("regularMarketPrice")
        market_time = meta.get("regularMarketTime")
        if price is None or market_time is None:
            continue
        as_of = datetime.fromtimestamp(
            market_time, tz=timezone.utc
        ).strftime("%Y-%m-%d")
        by_symbol[symbol] = {
            "resolved_ticker": symbol,
            "last_close": float(price),
            "as_of": as_of,
            "currency": meta.get("currency") or "USD",
        }

    results: list[dict[str, Any]] = []
    for ticker in tickers:
        entry = by_symbol.get(ticker)
        if entry is None:
            results.append({
                "input_ticker": ticker,
                "error": "yahoo spark returned no data for symbol",
                "source": "yahoo-spark",
                "market": "us",
            })
            continue
        entry["input_ticker"] = ticker
        entry["source"] = "yahoo-spark"
        entry["market"] = "us"
        results.append(entry)

    return {"quotes": results}


def _fetch_india_one_screener(ticker: str) -> dict[str, Any]:
    """Fetch one India ticker's current price from Screener.in.

    The ticker may be bare (``CDSL``), .NS-suffixed (``CDSL.NS``), or
    .BO-suffixed (``TITANBIO.BO``). The suffix is stripped before
    constructing the Screener URL since Screener keys on the bare
    NSE/BSE symbol.

    Tries the consolidated view first (which is what Veda's other India
    fetchers prefer), then falls back to standalone for companies that
    only publish standalone financials. If neither view exists, returns
    an error entry.

    The returned ``last_close`` is rounded to the nearest rupee because
    that is what Screener displays. ``precision_note`` makes the caveat
    discoverable in the JSON.
    """
    import requests

    base = ticker
    if base.endswith(".NS") or base.endswith(".BO"):
        base = base[:-3]

    shell = {
        "input_ticker": ticker,
        "resolved_ticker": base,
        "source": "screener.in",
        "market": "india",
    }

    # Screener URL patterns observed in the wild:
    #   /company/<sym>/consolidated/ : companies that report consolidated
    #     financials (most large/mid caps). Returns the rich page.
    #   /company/<sym>/              : the base view; works for every valid
    #     symbol Screener tracks. For companies WITHOUT consolidated
    #     reporting, /consolidated/ still returns HTTP 200 but with an
    #     empty top-ratios block -- the rich page only lives at the base
    #     URL. We therefore try consolidated first (to stay consistent
    #     with fundamentals-fetcher's preference), and fall through to
    #     the base URL on either a 404 or an empty-price page.
    for view_suffix in ("consolidated/", ""):
        url = f"{SCREENER_BASE}/company/{base}/{view_suffix}"
        try:
            r = requests.get(
                url,
                headers=SCREENER_HEADERS,
                timeout=HTTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            return {
                **shell,
                "error": f"screener request failed: {type(exc).__name__}: {exc}",
            }
        if r.status_code == 404:
            continue  # try next view
        if r.status_code != 200:
            return {**shell, "error": f"screener returned HTTP {r.status_code}"}
        match = _SCREENER_PRICE_RE.search(r.text)
        if not match:
            # Empty top-ratios (Screener returns 200 with blank values for
            # the consolidated view on companies that don't report
            # consolidated). Fall through to the base URL.
            continue
        price_str = match.group(1).replace(",", "")
        try:
            price = float(price_str)
        except ValueError:
            return {**shell, "error": f"screener: unparseable price {price_str!r}"}
        return {
            **shell,
            "last_close": price,
            "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "currency": "INR",
            "precision_note": (
                "Screener.in price is rupee-rounded for display; "
                "sub-rupee precision is lost"
            ),
            "view": view_suffix.rstrip("/") or "default",
        }

    return {
        **shell,
        "error": f"screener: no price found for '{base}' on any view",
    }


def _fetch_india_batch(tickers: list[str]) -> dict[str, Any]:
    """Fetch many India tickers in parallel via Screener.in.

    Each ticker is one HTTP to Screener; threads run them concurrently.
    Wall time is bounded by the slowest single page load, not the sum.
    Output preserves input order. See :func:`_fetch_india_one_screener`
    for the per-ticker behaviour and the rupee-rounding caveat.
    """
    def _one(ticker: str) -> dict[str, Any]:
        try:
            return _fetch_india_one_screener(ticker)
        except Exception as exc:  # mirror main()'s top-level catch
            return {
                "input_ticker": ticker,
                "error": f"{type(exc).__name__}: {exc}",
                "source": "screener.in",
                "market": "india",
            }

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(_one, tickers))
    return {"quotes": results}


def resolve_equities(
    tickers: list[str],
    market: Optional[str] = None,
) -> dict[str, Any]:
    """Fetch a list of equities, dispatching to the right primitive.

    Output is always shaped ``{"quotes": [<entry>, ...]}`` with one entry
    per input ticker, in input order. Each entry has either the success
    fields (input_ticker, resolved_ticker, last_close, as_of, currency,
    source, ...) or (input_ticker, error, source).

    Dispatch:
      - ``market='us'``    -> :func:`_fetch_us_batch` (Yahoo spark, one HTTP).
      - ``market='india'`` -> :func:`_fetch_india_batch` (Screener.in,
         parallel HTTPs).
      - ``market`` None    -> auto-route via the bundled ticker_market
         table (``scripts/data/ticker_market.csv``). Known US tickers go
         to the spark batch, known India tickers go to the Screener
         batch, and unknowns fall back to the per-ticker yfinance ladder.
         The three groups run in parallel so wall time is bounded by the
         slowest group, not the sum.
    """
    if market == "us":
        return _fetch_us_batch(tickers)
    if market == "india":
        return _fetch_india_batch(tickers)

    # Auto-route. Lazy-import the lookup so a missing CSV fails on first
    # call rather than blocking module import (and the `quote` / `fx`
    # subcommands, which do not need the table at all).
    from ticker_market_lookup import split_by_market
    buckets = split_by_market(tickers)

    def _yfinance_fallback(ts: list[str]) -> list[dict[str, Any]]:
        """V1 per-ticker yfinance ladder for tickers not in the lookup table."""
        if not ts:
            return []

        def _one(ticker: str) -> dict[str, Any]:
            try:
                return resolve_equity(ticker)
            except Exception as exc:  # mirror main()'s top-level catch
                return {
                    "input_ticker": ticker,
                    "error": f"{type(exc).__name__}: {exc}",
                    "source": "yfinance",
                }

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            return list(pool.map(_one, ts))

    def _us(ts: list[str]) -> list[dict[str, Any]]:
        return _fetch_us_batch(ts)["quotes"] if ts else []

    def _india(ts: list[str]) -> list[dict[str, Any]]:
        return _fetch_india_batch(ts)["quotes"] if ts else []

    # Run the three groups concurrently. Order is reconstructed from
    # `input_ticker` after the gather since each primitive emits its
    # entries in its own internal order.
    by_ticker: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_us = pool.submit(_us, buckets["us"])
        f_in = pool.submit(_india, buckets["india"])
        f_un = pool.submit(_yfinance_fallback, buckets["unknown"])
        for entry in f_us.result() + f_in.result() + f_un.result():
            by_ticker[entry["input_ticker"]] = entry

    return {"quotes": [by_ticker[t] for t in tickers]}


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
    """Print JSON to stdout. Exit code 0 if no errors anywhere, else 1.

    Two failure shapes are recognised:
      - a top-level ``error`` key (used by single-quote and fx modes), or
      - a ``quotes`` list with at least one per-item ``error`` entry
        (used by the batch ``quotes`` mode; strict rule).
    """
    # sort_keys makes outputs diff-stable across runs (useful for CI).
    print(json.dumps(payload, indent=2, sort_keys=True))
    if "error" in payload:
        return 1
    quotes = payload.get("quotes")
    if isinstance(quotes, list) and any(
        isinstance(q, dict) and "error" in q for q in quotes
    ):
        return 1
    return 0


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

    p_quotes = sub.add_parser(
        "quotes",
        help=(
            "Fetch the last close for many tickers in parallel "
            f"(up to {MAX_WORKERS} at a time)."
        ),
    )
    p_quotes.add_argument(
        "--tickers",
        required=True,
        nargs="+",
        help=(
            "One or more ticker symbols, space separated. With --market, "
            "the whole batch goes through that market's primitive. Without "
            "--market, each ticker is auto-routed via the bundled "
            "ticker_market table (scripts/data/ticker_market.csv); "
            "unknowns fall back to the per-ticker yfinance ladder."
        ),
    )
    p_quotes.add_argument(
        "--market",
        choices=["us", "india"],
        default=None,
        help=(
            "Optional market hint. When set, the whole batch goes through "
            "that market's primitive and the ticker_market table is not "
            "consulted. 'us': Yahoo's `spark` endpoint -- one HTTP for the "
            "whole list, full precision, source='yahoo-spark', "
            "currency='USD'. 'india': Screener.in company page per ticker, "
            "parallel; price is rounded to the nearest rupee "
            "(precision_note in output), source='screener.in', "
            "currency='INR'. If omitted, each ticker is auto-routed via "
            "the bundled lookup table; unknown tickers fall back to the "
            "per-ticker yfinance ladder."
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
        elif args.command == "quotes":
            payload = resolve_equities(args.tickers, market=args.market)
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
