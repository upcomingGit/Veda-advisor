"""Refresh scripts/data/ticker_market.csv from authoritative sources.

Pulls the full active equity universe for both markets and writes a single
unified CSV that maps every bare ticker to its market and its issuer name:

    Schema: ticker,market,name
            (uppercase ticker, lowercase market in {us, india}, raw name).

Data sources
-------------
US:    SEC's public ticker file -- https://www.sec.gov/files/company_tickers.json
       (no auth, no rate limit beyond SEC's "identify yourself in User-Agent"
       request). One row per active SEC-registered listing. ~10,000 tickers.
India: NSE's official daily equity master --
       https://archives.nseindia.com/content/equities/EQUITY_L.csv
       (the archives subdomain is NOT Akamai-protected; the www.nseindia.com
       domain is). One row per actively-listed NSE equity. ~2,300 tickers.

BSE is intentionally NOT fetched. NSE covers every name a Veda user is
plausibly going to ask about; the BSE-only universe is mostly micro-caps
and inactive listings. If a future need arises, add a third fetch here.

Symbol normalization
--------------------
SEC's ticker file uses '.' for share-class separators ("BRK.B"). Yahoo
and yfinance use '-' for the same ("BRK-B"). Veda's fetch_quote.py talks
to Yahoo's spark endpoint, so we normalise dots to dashes on the US side
to keep the lookup consistent with what fetch_quote.py will send. India
symbols pass through unchanged (NSE uses '&' and '-' natively; never '.').

Collision policy
----------------
A symbol can in theory exist on both markets (e.g. "TCS" is Tata
Consultancy on NSE and Container Store on US, "L" was Loews until
delisting). Veda's primary user is Indian, so India wins on collision
and the colliding US entry is dropped from the bundled table. Users who
explicitly want the US ADR still pass `--market us` at the call site,
which bypasses the table entirely. All collisions are logged to stderr
during the refresh so they can be eyeballed.

Output ordering
---------------
US block first (alphabetical), then India block (alphabetical). Identical
input -> identical output, so re-running the refresh produces a clean
diff if any source data changed.

Run
---
    python scripts/refresh_ticker_market.py

Network: ~1 MB total. Wall time: ~2 s with both fetches in parallel.
"""

from __future__ import annotations

import csv
import io
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

SEC_URL = "https://www.sec.gov/files/company_tickers.json"
NSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

# SEC's fair-access policy asks every caller to identify itself in the
# User-Agent. They do not enforce this hard, but it's the documented norm.
SEC_HEADERS = {"User-Agent": "Veda Research veda@example.com"}

# NSE's archives subdomain serves static CSVs without the bot-protection
# the www.nseindia.com endpoints sit behind. A plain browser UA is enough.
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

HTTP_TIMEOUT_SECONDS = 20

OUT_PATH = Path(__file__).parent / "data" / "ticker_market.csv"


def _fetch_sec() -> list[tuple[str, str]]:
    """Return list of (ticker, name) for US listings from SEC.

    Normalises class separators '.' -> '-' so the symbol matches the form
    Yahoo / yfinance accept. Drops blank tickers (very rare but seen).
    """
    r = requests.get(SEC_URL, headers=SEC_HEADERS, timeout=HTTP_TIMEOUT_SECONDS)
    r.raise_for_status()
    payload = r.json()
    rows: list[tuple[str, str]] = []
    for entry in payload.values():
        ticker = (entry.get("ticker") or "").strip().upper().replace(".", "-")
        name = (entry.get("title") or "").strip()
        if not ticker or not name:
            continue
        rows.append((ticker, name))
    return rows


def _fetch_nse() -> list[tuple[str, str]]:
    """Return list of (ticker, name) for India listings from NSE archives.

    Only the EQ series (regular equity) is kept; BE / BZ / SM (trade-to-trade,
    SME, etc.) are filtered out because they are illiquid surveillance
    segments and not what a normal Veda decision references.
    """
    r = requests.get(NSE_URL, headers=NSE_HEADERS, timeout=HTTP_TIMEOUT_SECONDS)
    r.raise_for_status()
    rows: list[tuple[str, str]] = []
    reader = csv.reader(io.StringIO(r.text))
    header = next(reader, None)
    if header is None:
        raise RuntimeError("NSE EQUITY_L.csv returned an empty body")
    # Header observed in the wild:
    #   SYMBOL, NAME OF COMPANY,  SERIES,  DATE OF LISTING, ...
    # Some columns carry a leading space; strip to be safe.
    cols = [c.strip().upper() for c in header]
    try:
        idx_sym = cols.index("SYMBOL")
        idx_name = cols.index("NAME OF COMPANY")
        idx_series = cols.index("SERIES")
    except ValueError as exc:
        raise RuntimeError(f"NSE CSV header changed: {header!r}") from exc

    for row in reader:
        if len(row) <= max(idx_sym, idx_name, idx_series):
            continue
        series = row[idx_series].strip().upper()
        if series != "EQ":
            continue  # skip surveillance / SME / illiquid segments
        ticker = row[idx_sym].strip().upper()
        name = row[idx_name].strip()
        if not ticker or not name:
            continue
        rows.append((ticker, name))
    return rows


def _merge(
    us_rows: list[tuple[str, str]],
    in_rows: list[tuple[str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Combine the two sets, resolving collisions with India-wins.

    Returns (merged_rows, colliding_tickers). Merged rows are sorted
    alphabetically within each market block (US first, India second)
    for stable diffs across refreshes.
    """
    in_tickers = {t for t, _ in in_rows}
    collisions: list[str] = []
    kept_us: list[tuple[str, str]] = []
    for ticker, name in us_rows:
        if ticker in in_tickers:
            collisions.append(ticker)
            continue
        kept_us.append((ticker, name))

    kept_us.sort(key=lambda x: x[0])
    in_sorted = sorted(in_rows, key=lambda x: x[0])

    merged: list[tuple[str, str, str]] = []
    merged.extend((t, "us", n) for t, n in kept_us)
    merged.extend((t, "india", n) for t, n in in_sorted)
    return merged, sorted(collisions)


def _write_csv(
    rows: list[tuple[str, str, str]],
    us_count: int,
    in_count: int,
    collisions: list[str],
) -> None:
    """Emit the CSV with a human-readable comment header."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header_block = [
        f"# ticker_market.csv -- generated by scripts/refresh_ticker_market.py",
        f"# Last refreshed (UTC): {today}",
        f"# Sources:",
        f"#   US    : SEC company_tickers.json -- {us_count} tickers fetched, "
        f"{us_count - len(collisions)} kept after India-wins collision resolution",
        f"#   India : NSE archives EQUITY_L.csv (SERIES=EQ only) -- {in_count} tickers",
        f"# Schema: ticker,market,name",
        f"# Market values are lowercase {{us, india}} -- matches "
        f"scripts/fetch_quote.py --market.",
        f"# Tickers are bare uppercase (no .NS/.BO yfinance suffix). The "
        f"lookup module routes",
        f"# any suffixed input via a separate suffix-rule -- the table "
        f"holds bare symbols only.",
        f"# Symbol normalisation: SEC '.' separators replaced with '-' "
        f"(BRK.B -> BRK-B) to match",
        f"# Yahoo / yfinance conventions used by fetch_quote.py.",
        f"# Collision policy: India wins. {len(collisions)} symbols dropped "
        f"from the US block:",
    ]
    if collisions:
        # Wrap at ~80 chars for readability; one line per chunk.
        chunk: list[str] = []
        chunk_len = 0
        for sym in collisions:
            if chunk and chunk_len + len(sym) + 2 > 70:
                header_block.append("#   " + ", ".join(chunk))
                chunk = []
                chunk_len = 0
            chunk.append(sym)
            chunk_len += len(sym) + 2
        if chunk:
            header_block.append("#   " + ", ".join(chunk))
    else:
        header_block.append("#   (none)")
    header_block.append("# Lines beginning with '#' and blank lines are "
                        "ignored by the loader.")
    header_block.append("# Regenerate with: python scripts/refresh_ticker_market.py")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8", newline="") as f:
        for line in header_block:
            f.write(line + "\n")
        f.write("\n")
        writer = csv.writer(f)
        writer.writerow(["ticker", "market", "name"])
        writer.writerow([])  # blank for visual separation
        # US block
        f.write("# --- US listings (SEC) ---\n")
        for t, m, n in rows:
            if m != "us":
                continue
            writer.writerow([t, m, n])
        f.write("\n# --- India listings (NSE, SERIES=EQ) ---\n")
        for t, m, n in rows:
            if m != "india":
                continue
            writer.writerow([t, m, n])


def main() -> int:
    print("Fetching SEC + NSE in parallel...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_us = pool.submit(_fetch_sec)
        f_in = pool.submit(_fetch_nse)
        us_rows = f_us.result()
        in_rows = f_in.result()
    print(
        f"  SEC: {len(us_rows)} US tickers, NSE: {len(in_rows)} India tickers",
        file=sys.stderr,
    )

    merged, collisions = _merge(us_rows, in_rows)
    if collisions:
        print(
            f"Collision policy applied (India wins). "
            f"{len(collisions)} US tickers dropped:",
            file=sys.stderr,
        )
        # Print at most the first 20 for visibility; the full list goes in
        # the CSV header.
        print("  " + ", ".join(collisions[:20])
              + (f", ... ({len(collisions) - 20} more)" if len(collisions) > 20 else ""),
              file=sys.stderr)

    _write_csv(merged, len(us_rows), len(in_rows), collisions)
    print(
        f"Wrote {len(merged)} rows to {OUT_PATH} "
        f"({sum(1 for r in merged if r[1] == 'us')} us, "
        f"{sum(1 for r in merged if r[1] == 'india')} india)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
