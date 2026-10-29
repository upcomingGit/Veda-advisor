"""Single Python portfolio tracker: check, login, review, preview and update.

Only update writes Sheets; login updates the local Kite session. Settings live
in private/portfolio-sync/settings.json. Broker operations never place orders.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import math
import os
import re
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from html import unescape
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# Keep normal runs from generating local helper bytecode caches.
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "private" / "portfolio-sync" / "settings.json"
US_SHEET_SOURCE = "Google Sheets · manual holdings"

MANUAL_FIELDS = {"status", "conviction", "sell_condition", "action", "sector", "review_reason"}
DERIVED_FIELDS = {"market_value", "weight", "return"}
SOURCE_FIELDS = {"stock_name", "ticker", "quantity", "average_price", "current_price", "market_cap", "pe", "thesis_status", "signal"}
BASE_HEADERS = {
    "stock_name": ("Stock Name", "Stock"),
    "ticker": ("Exchange:Ticker", "Ticker", "NSE/BSE Ticker"),
    "status": ("Status",),
    "sector": ("Sector",),
    "quantity": ("Quantity",),
    "weight": ("Portfolio Weight (%)", "% of Portfolio"),
    "return": ("Unrealised Return (%)",),
    "pe": ("Current P/E",),
    "conviction": ("My Thesis Conviction", "Thesis Conviction"),
    "sell_condition": ("My Sell Condition", "Sell Condition"),
    "action": ("My Action", "Action (Buy/Hold/Sell)", "What Should I do? (Buy/Hold/Sell)"),
    "thesis_status": ("StockClarity Thesis Status",),
    "signal": ("StockClarity Signal",),
    "review_reason": ("Review Reason",),
}
CSV_ALIASES = {
    "ticker": ("exchange_ticker", "Exchange:Ticker", "ticker"),
    "stock_name": ("stock_name", "Stock Name"),
    "quantity": ("quantity",),
    "average_price": ("average_purchase_price", "average_price"),
    "holdings_as_of": ("holdings_as_of",),
    "current_price": ("current_price",),
    "price_as_of": ("price_as_of",),
}
US_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "NYSEAMERICAN", "NYSEARCA", "BATS", "OTC"}


class ValidationError(ValueError):
    """An input cannot produce an unambiguous preview."""


@dataclass(frozen=True)
class Holding:
    ticker: str
    stock_name: str | None
    quantity: Decimal
    average_price: Decimal | None
    current_price: Decimal | None = None
    price_as_of: str | None = None
    isin: str | None = None
    asset_type: str = "Stock"
    market_cap: Decimal | None = None
    pe: Decimal | None = None
    thesis_status: str | None = None
    signal: str | None = None
    research_as_of: str | None = None


@dataclass(frozen=True)
class PortfolioInput:
    market: str
    holdings: tuple[Holding, ...]
    holdings_as_of: str
    source: str
    cash: Decimal | None = None
    cash_as_of: str | None = None
    cash_source: str | None = None


def normalise_header(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())


def decimal_value(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None or str(value).strip() == "":
        raise ValidationError(f"{label}: a number is required.")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation as error:
        raise ValidationError(f"{label}: invalid number; use plain decimals without currency symbols or commas.") from error
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise ValidationError(f"{label}: expected a finite {'positive' if positive else 'non-negative'} number.")
    if not math.isfinite(float(number)) or (number != 0 and float(number) == 0):
        raise ValidationError(f"{label}: number exceeds the supported range.")
    return number


def iso_date(value: Any, label: str) -> str:
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError as error:
        raise ValidationError(f"{label}: use YYYY-MM-DD.") from error
    if parsed.isoformat() != str(value):
        raise ValidationError(f"{label}: use YYYY-MM-DD.")
    return parsed.isoformat()


def timestamp(value: Any, label: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValidationError(f"{label}: a timezone-aware ISO timestamp is required.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"{label}: a timezone is required.")
    return parsed.isoformat()


def security_key(value: Any, market: str) -> str:
    key = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z]+:[A-Z0-9][A-Z0-9.&_-]*", key):
        raise ValidationError("Ticker must be exchange-qualified, for example NSE:EXAMPLE or NASDAQ:EXAMPLE.")
    exchange, symbol = key.split(":", 1)
    allowed = {"NSE", "BSE", "MF"} if market == "IN" else US_EXCHANGES
    if exchange not in allowed or (market == "US" and symbol.endswith((".NS", ".BO"))):
        raise ValidationError(f"{key}: exchange/ticker does not belong to the {market} table.")
    if exchange == "MF" and not re.fullmatch(r"INF[A-Z0-9]{9}", symbol):
        raise ValidationError("Mutual funds require MF: followed by their exact ISIN.")
    return key


def _unique_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"Duplicate JSON key: {key}.")
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_json)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"Cannot read valid JSON from {path.name}.") from error
    if not isinstance(value, dict):
        raise ValidationError(f"{path.name}: expected a JSON object.")
    return value


def mapped_headers(headers: list[str], aliases: dict[str, tuple[str, ...]]) -> dict[str, int]:
    if not all(isinstance(h, str) and h.strip() for h in headers):
        raise ValidationError("Headers must be non-empty strings.")
    normalised = [normalise_header(h) for h in headers]
    if len(set(normalised)) != len(normalised):
        raise ValidationError("Duplicate column headers; resolve them before continuing.")
    mapped = {}
    for field, names in aliases.items():
        indexes = [i for i, h in enumerate(normalised) if h in {normalise_header(n) for n in names}]
        if len(indexes) > 1:
            raise ValidationError(f"Multiple columns match {field}; remove the ambiguity.")
        if indexes:
            mapped[field] = indexes[0]
    return mapped


def sheet_headers(market: str) -> dict[str, tuple[str, ...]]:
    cur = "₹" if market == "IN" else "$"
    cap = "₹ Crore" if market == "IN" else "$ Million"
    return {
        **BASE_HEADERS,
        "market_cap": (f"Market Cap ({cap})",),
        "average_price": (f"Average Purchase Price ({cur})", f"Average Price ({'INR' if market == 'IN' else 'USD'})"),
        "current_price": (f"Current Market Price ({cur})", f"Current Price ({'INR' if market == 'IN' else 'USD'})"),
        "market_value": (f"Current Market Value ({cur})",),
    }


def validate_holdings(holdings: list[Holding]) -> tuple[Holding, ...]:
    tickers: set[str] = set()
    isins: set[str] = set()
    for holding in holdings:
        if holding.ticker in tickers:
            raise ValidationError(f"Duplicate security: {holding.ticker}. Aggregate or reconcile the source first.")
        if holding.isin and holding.isin in isins:
            raise ValidationError("The same ISIN appears more than once; exchange-level aggregation needs review.")
        tickers.add(holding.ticker)
        if holding.isin:
            isins.add(holding.isin)
    return tuple(holdings)


def load_us_csv(path: Path, *, cash: Any = None, cash_as_of: str | None = None,
                holdings_as_of: str | None = None) -> PortfolioInput:
    if (cash is None) != (cash_as_of is None):
        raise ValidationError("US cash and its as-of date must be supplied together.")
    cash_value = decimal_value(cash, "US cash") if cash is not None else None
    cash_date = iso_date(cash_as_of, "US cash as of") if cash_as_of is not None else None
    dates = {iso_date(holdings_as_of, "US holdings as of")} if holdings_as_of else set()
    holdings: list[Holding] = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            headers = next(reader, None)
            if not headers:
                raise ValidationError("US CSV has no header row.")
            mapping = mapped_headers(headers, CSV_ALIASES)
            required = {"ticker", "quantity", "average_price", "holdings_as_of"}
            if not required <= mapping.keys():
                raise ValidationError("US CSV missing columns: " + ", ".join(sorted(required - mapping.keys())))
            for row_number, values in enumerate(reader, 2):
                if not any(v.strip() for v in values):
                    continue
                if len(values) != len(headers):
                    raise ValidationError(f"US CSV row {row_number}: field count does not match headers.")
                get = lambda field: values[mapping[field]].strip() if field in mapping else ""
                label = f"US CSV row {row_number}"
                dates.add(iso_date(get("holdings_as_of"), label + " holdings date"))
                price, price_date = get("current_price"), get("price_as_of")
                if bool(price) != bool(price_date):
                    raise ValidationError(f"{label}: current_price and price_as_of must be supplied together.")
                holdings.append(Holding(
                    security_key(get("ticker"), "US"), get("stock_name") or None,
                    decimal_value(get("quantity"), label + " quantity"),
                    decimal_value(get("average_price"), label + " average purchase price"),
                    decimal_value(price, label + " current price", positive=True) if price else None,
                    iso_date(price_date, label + " price date") if price_date else None,
                ))
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValidationError(f"Cannot read valid CSV from {path.name}.") from error
    if len(dates) != 1:
        raise ValidationError("US upload must represent exactly one holdings date; for an empty CSV supply --us-holdings-as-of.")
    return PortfolioInput("US", validate_holdings(holdings), dates.pop(), "standard_csv",
                          cash_value, cash_date, "user_supplied" if cash_value is not None else None)


@lru_cache(maxsize=256)
def us_profile(symbol: str) -> dict:
    """Public company identity/fundamentals, fetched once per symbol per run."""
    import requests
    # In-memory public Yahoo session only; no broker credentials or portfolio data.
    session, crumb = us_quote_session()
    response = session.get("https://query1.finance.yahoo.com/v7/finance/quote",
                           params={"symbols": symbol, "crumb": crumb}, timeout=20)
    response.raise_for_status()
    results = response.json().get("quoteResponse", {}).get("result", [])
    if len(results) != 1 or results[0].get("symbol") != symbol:
        raise ValidationError(f"{symbol}: Yahoo returned an ambiguous company identity.")
    return results[0]


@lru_cache(maxsize=1)
def us_quote_session():
    import requests
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"
    session.get("https://fc.yahoo.com", timeout=20)  # Public session cookie (404 is normal).
    response = session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=20)
    response.raise_for_status()
    if not response.text.strip() or "<" in response.text:
        raise ValidationError("Yahoo public session is unavailable.")
    return session, response.text


def us_identity(symbol: str, info: dict) -> tuple[str, str]:
    exchanges = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ",
                 "NYQ": "NYSE", "ASE": "NYSEAMERICAN", "PCX": "NYSEARCA",
                 "BTS": "BATS", "BATS": "BATS", "PNK": "OTC", "OBB": "OTC"}
    exchange = exchanges.get(info.get("exchange"))
    kind = {"EQUITY": "Stock", "ETF": "ETF"}.get(info.get("quoteType"))
    if info.get("symbol") != symbol or info.get("currency") != "USD" or not exchange or not kind:
        raise ValidationError(f"{symbol}: cannot verify an exact USD stock/ETF listing; no exchange is guessed.")
    return security_key(exchange + ":" + symbol, "US"), kind


def load_us_vested(path: Path, *, cash: Any = None, cash_as_of: str | None = None,
                   holdings_as_of: str | None = None, profile=None) -> PortfolioInput:
    """Read the original Vested XLSX by headers; never execute workbook content."""
    if (cash is None) != (cash_as_of is None):
        raise ValidationError("US cash and its as-of date must be supplied together.")
    cash_value = decimal_value(cash, "US cash") if cash is not None else None
    cash_date = iso_date(cash_as_of, "US cash as of") if cash_as_of is not None else None
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        with zipfile.ZipFile(path) as book:
            strings = []
            if "xl/sharedStrings.xml" in book.namelist():
                strings = ["".join(s.itertext()) for s in ET.fromstring(book.read("xl/sharedStrings.xml"))]
            rels = {r.attrib["Id"]: r.attrib["Target"] for r in ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))}
            tabs = {}
            for tab in ET.fromstring(book.read("xl/workbook.xml")).findall("m:sheets/m:sheet", ns):
                target = rels[tab.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
                target = target.lstrip("/") if target.startswith("/") else "xl/" + target
                rows = []
                for row in ET.fromstring(book.read(target)).findall("m:sheetData/m:row", ns):
                    cells = {}
                    for cell in row.findall("m:c", ns):
                        if cell.find("m:f", ns) is not None:
                            raise ValidationError("Vested export contains formulas; use the original broker export.")
                        value = cell.findtext("m:v", default="", namespaces=ns)
                        if cell.get("t") == "s":
                            value = strings[int(value)]
                        elif cell.get("t") == "inlineStr":
                            value = "".join(cell.find("m:is", ns).itertext())
                        cells[re.sub(r"\d", "", cell.attrib["r"])] = value
                    rows.append(cells)
                tabs[tab.attrib["name"]] = rows
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError, ValueError, IndexError) as error:
        raise ValidationError("Cannot read the Vested XLSX export.") from error
    periods = [v.removeprefix("As of ") for row in tabs.get("User Details", []) for v in row.values() if v.startswith("As of ")]
    if len(periods) != 1:
        raise ValidationError("Vested export needs one unambiguous holdings date.")
    try:
        source_date = datetime.strptime(periods[0], "%d %b %Y").date().isoformat()
    except ValueError as error:
        raise ValidationError("Vested holdings date is not recognised.") from error
    if holdings_as_of and iso_date(holdings_as_of, "US holdings as of") != source_date:
        raise ValidationError("Configured holdings date disagrees with the Vested export.")
    rows = tabs.get("Holdings", [])
    if not rows:
        raise ValidationError("Vested export has no Holdings tab.")
    labels = [normalise_header(v) for v in rows[0].values() if v]
    if len(labels) != len(set(labels)):
        raise ValidationError("Vested export contains duplicate Holdings headers.")
    headers = {normalise_header(v): c for c, v in rows[0].items() if v}
    required = ["Name", "Ticker", "Currency", "Total Shares Held", "Total Amount Invested", "Current Value"]
    if not {normalise_header(h) for h in required} <= headers.keys():
        raise ValidationError("Vested Holdings headers do not match the supported export.")
    parsed = []
    for row in rows[1:]:
        if not any(row.values()):
            continue
        get = lambda name: row.get(headers[normalise_header(name)], "").strip()
        symbol = get("Ticker").upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]*", symbol) or get("Currency") != "USD":
            raise ValidationError("Vested holdings require USD and exact public ticker symbols.")
        qty = decimal_value(get("Total Shares Held"), symbol + " quantity", positive=True)
        cost = decimal_value(get("Total Amount Invested"), symbol + " total cost")
        value = decimal_value(get("Current Value"), symbol + " current value")
        parsed.append((symbol, get("Name"), qty, cost / qty, value))
    # Reconcile the export before any public ticker lookup. Cash is not in this total.
    summary = tabs.get("Summary", [])
    value_col = next((c for c, v in (summary[0] if summary else {}).items() if v == "Current Equity Value"), None)
    reported = summary[1].get(value_col) if len(summary) == 2 else None
    if reported is None or abs(sum((r[4] for r in parsed), Decimal(0)) - decimal_value(reported.replace(",", ""), "Vested equity total")) > Decimal("0.02"):
        raise ValidationError("Vested holdings do not reconcile to its equity summary.")
    profile = profile or us_profile
    holdings = []
    for symbol, name, qty, avg, _ in parsed:
        try:
            info = profile(symbol)
        except Exception as error:
            raise ValidationError(f"{symbol}: public listing lookup failed; no holdings were written.") from error
        ticker, kind = us_identity(symbol, info)
        holdings.append(Holding(ticker, name, qty, avg, asset_type=kind))
    return PortfolioInput("US", validate_holdings(holdings), source_date, "Vested XLSX",
                          cash_value, cash_date, "user_supplied" if cash_value is not None else None)


def load_us_sheet(sheet: dict) -> PortfolioInput:
    """Daily US refresh: the sheet itself owns quantities, USD costs and cash."""
    mapping, rows = validate_sheet(sheet, "US")
    headers = sheet["headers"]
    summary = sheet.get("summary_cells", {})
    raw_date = summary.get("holdings_uploaded_on", {}).get("value")
    if isinstance(raw_date, (int, float)) and not isinstance(raw_date, bool):
        try:
            as_of = (date(1899, 12, 30) + timedelta(days=float(raw_date))).isoformat()
        except (ValueError, OverflowError) as error:
            raise ValidationError("US holdings/cash date is invalid.") from error
    else:
        as_of = iso_date(raw_date, "US Holdings & Cash As Of")
    cash = summary.get("broker_cash", {}).get("value")
    cash = decimal_value(cash, "US sheet broker cash") if cash not in (None, "") else None
    holdings = []
    for row in rows:
        get = lambda field: row["values"].get(headers[mapping[field]])
        ticker, quantity = get("ticker"), get("quantity")
        if quantity in (None, "", 0, "0"):
            if get("status") == "Invested":
                raise ValidationError(f"US row {row['row']}: Invested needs a positive quantity.")
            continue
        qty = decimal_value(quantity, f"US row {row['row']} quantity", positive=True)
        ticker = security_key(ticker, "US")
        avg = get("average_price")
        avg = decimal_value(avg, ticker + " USD average cost") if avg not in (None, "") else None
        holdings.append(Holding(ticker, get("stock_name") or None, qty, avg))
    return PortfolioInput("US", validate_holdings(holdings), as_of, US_SHEET_SOURCE,
                          cash, as_of if cash is not None else None, "US sheet · combined broker cash")


def parse_kite_payload(payload: dict[str, Any], *, funds: dict[str, Any] | None = None,
                       cash_field: str | None = None) -> PortfolioInput:
    """Validate Zerodha holdings before preparing cell updates."""
    rows = payload.get("holdings")
    if payload.get("source") != "kite" or not isinstance(rows, list):
        raise ValidationError("India input must be the JSON envelope emitted by scripts/kite.py holdings.")
    observed = timestamp(payload.get("as_of"), "Kite holdings as_of")
    if type(payload.get("count")) is not int or payload["count"] != len(rows):
        raise ValidationError("Kite count does not match the holdings list.")
    holdings = []
    for row in rows:
        if not isinstance(row, dict) or row.get("product") != "CNC":
            raise ValidationError("India input must contain CNC delivery holdings only.")
        key = security_key(f"{row.get('exchange', '')}:{row.get('tradingsymbol', '')}", "IN")
        for field in ("t1_quantity", "short_quantity", "collateral_quantity"):
            if field not in row or decimal_value(row[field], f"{key} {field}") != 0:
                raise ValidationError(f"{key}: {field} is missing or non-zero; reconcile broker quantity semantics before importing.")
        mtf = row.get("mtf", {})
        if not isinstance(mtf, dict) or decimal_value(mtf.get("quantity", 0), f"{key} MTF quantity") != 0:
            raise ValidationError(f"{key}: MTF holdings are outside this import contract.")
        qty = decimal_value(row.get("quantity"), key + " quantity")
        if qty != qty.to_integral_value():
            raise ValidationError(f"{key}: Indian delivery quantity must be whole shares.")
        used = decimal_value(row.get("used_quantity"), key + " used quantity")
        if used != used.to_integral_value():
            raise ValidationError(f"{key}: used quantity must be whole shares.")
        if used:
            opening = decimal_value(row.get("opening_quantity"), key + " opening quantity")
            # Kite quantity already reflects CNC sales. Check the opening
            # balance rather than subtracting used_quantity a second time.
            if opening != qty + used:
                raise ValidationError(f"{key}: opening, remaining and sold quantities do not reconcile.")
        if row.get("discrepancy") not in (None, False):
            raise ValidationError(f"{key}: broker reports a holdings discrepancy.")
        isin = row.get("isin") or None
        if isin and (not isinstance(isin, str) or not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin)):
            raise ValidationError(f"{key}: invalid ISIN.")
        # Holdings-envelope as_of is a fetch timestamp, not a quote timestamp.
        # Do not promote last_price to a fresh market price without quote evidence.
        name = row.get("name") or None
        if name is not None and not isinstance(name, str):
            raise ValidationError(f"{key}: stock name must be text.")
        holdings.append(Holding(key, name, qty,
                                decimal_value(row.get("average_price"), key + " average purchase price"), isin=isin))
    cash = cash_date = cash_source = None
    if (funds is not None) != bool(cash_field):
        raise ValidationError("Kite funds require an explicit cash field, and vice versa.")
    if funds is not None:
        if cash_field not in {"available.cash", "available.live_balance"}:
            raise ValidationError("Cash field must be available.cash or available.live_balance; net/collateral is not cash.")
        if funds.get("source") != "kite" or funds.get("segment") != "equity":
            raise ValidationError("India funds must be the JSON envelope emitted by scripts/kite.py funds.")
        cash_date = timestamp(funds.get("as_of"), "Kite funds as_of")
        margins = funds.get("margins")
        if not isinstance(margins, dict) or not isinstance(margins.get("available"), dict):
            raise ValidationError("Kite funds are missing available balances.")
        if margins.get("enabled") is False:
            raise ValidationError("Kite equity segment is disabled.")
        cash = decimal_value(margins["available"].get(cash_field.split(".")[1]), "Kite cash")
        cash_source = "kite." + cash_field
    return PortfolioInput("IN", validate_holdings(holdings), observed, "kite_live", cash, cash_date, cash_source)


def _column_letter(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _literal(value: str | Decimal) -> dict[str, Any]:
    # Explicit CellData types keep strings such as '=...' literal in a future writer.
    if isinstance(value, Decimal):
        return {"numberValue": float(value)}
    return {"stringValue": value}


def _text_number(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def validate_sheet(sheet: dict[str, Any], market: str) -> tuple[dict[str, int], list[dict[str, Any]]]:
    if not isinstance(sheet, dict) or sheet.get("complete") is not True:
        raise ValidationError(f"{market}: a complete local sheet snapshot is required; partial reads cannot locate free rows safely.")
    headers = sheet.get("headers")
    if not isinstance(headers, list):
        raise ValidationError(f"{market}: sheet headers are required.")
    mapping = mapped_headers(headers, sheet_headers(market))
    missing = set(sheet_headers(market)) - mapping.keys()
    if missing:
        raise ValidationError(f"{market}: sheet is missing required headers: " + ", ".join(sorted(missing)))
    for key in ("sheet_id", "header_row", "last_prepared_row"):
        if type(sheet.get(key)) is not int or sheet[key] < (0 if key == "sheet_id" else 1):
            raise ValidationError(f"{market}: invalid {key}.")
    if type(sheet.get("start_column", 1)) is not int or sheet.get("start_column", 1) < 1:
        raise ValidationError(f"{market}: invalid start_column.")
    if sheet["last_prepared_row"] <= sheet["header_row"]:
        raise ValidationError("Prepared rows must extend below the header.")
    if not isinstance(sheet.get("title"), str) or not sheet["title"].strip():
        raise ValidationError("Sheet title is required.")
    rows = sheet.get("rows")
    if not isinstance(rows, list):
        raise ValidationError("Sheet snapshot rows must be a list.")
    numbers = set()
    for row in rows:
        if not isinstance(row, dict) or type(row.get("row")) is not int or not sheet["header_row"] < row["row"] <= sheet["last_prepared_row"]:
            raise ValidationError("Snapshot row lies outside the prepared table.")
        if row["row"] in numbers:
            raise ValidationError("Duplicate sheet row number.")
        numbers.add(row["row"])
        values = row.get("values")
        if not isinstance(values, dict) or not values.keys() <= set(headers):
            raise ValidationError("Row values must be keyed by exact sheet headers; undeclared headers are not allowed.")
        notes = row.get("notes", {})
        if not isinstance(notes, dict) or not notes.keys() <= set(headers) or not all(isinstance(n, str) for n in notes.values()):
            raise ValidationError("Row notes must be text keyed by exact sheet headers.")
        for value in values.values():
            if isinstance(value, bool) or (isinstance(value, float) and not math.isfinite(value)):
                raise ValidationError("Snapshot cells must not contain booleans or non-finite numbers.")
            if value is not None and not isinstance(value, (str, int, float)):
                raise ValidationError("Snapshot cells must be strings, numbers or null; formulas use strings starting with '='.")
    return mapping, rows


def preview_market(source: PortfolioInput, sheet: dict[str, Any]) -> dict[str, Any]:
    # Only the fully fetched and validated stocks + Coin source owns India status.
    broker_authoritative = source.market == "IN" and source.source == "Zerodha + Coin"
    mapping, rows = validate_sheet(sheet, source.market)
    headers = sheet["headers"]
    field_header = {field: headers[i] for field, i in mapping.items()}
    by_ticker, by_isin, occupied = {}, {}, set()
    for row in rows:
        values = row["values"]
        if any(value not in (None, "") for name, value in values.items()
               if name not in {field_header[f] for f in DERIVED_FIELDS}) or row.get("isin") or row.get("notes"):
            occupied.add(row["row"])
        raw_ticker = values.get(field_header["ticker"])
        if raw_ticker in (None, ""):
            raw_qty = values.get(field_header["quantity"])
            if raw_qty not in (None, "", 0, "0") or values.get(field_header["status"]) == "Invested":
                raise ValidationError("A sheet row has a holding quantity or Invested status but no ticker; reconcile identity first.")
        if raw_ticker not in (None, ""):
            key = security_key(raw_ticker, source.market)
            if key in by_ticker:
                raise ValidationError(f"Duplicate sheet security: {key}.")
            by_ticker[key] = row
        if row.get("isin"):
            if row["isin"] in by_isin:
                raise ValidationError("Duplicate sheet ISIN metadata.")
            by_isin[row["isin"]] = row
    free = iter(r for r in range(sheet["header_row"] + 1, sheet["last_prepared_row"] + 1) if r not in occupied)
    changes, positions, gaps, matched_rows = [], [], [], set()
    total = Decimal(0)
    values_complete = True
    if not source.holdings and not broker_authoritative:
        gaps.append("Empty holdings input: verify the source; no existing rows will be cleared.")
    if source.cash is None:
        gaps.append("Broker cash is missing; portfolio total and weights are unavailable.")

    def propose(row_number: int, field: str, value: str | Decimal, existing: dict[str, Any]) -> None:
        broker_status = broker_authoritative and field == "status"
        if not broker_status and (field not in SOURCE_FIELDS or field in MANUAL_FIELDS | DERIVED_FIELDS):
            raise ValidationError("Attempt to change a protected field.")
        header = field_header[field]
        previous = existing.get(header)
        if value == "" and previous in (None, ""):
            return
        if isinstance(previous, str) and previous.startswith("="):
            raise ValidationError(f"{source.market} row {row_number}: {header} contains a formula; review before replacing it.")
        if previous == value or (isinstance(value, Decimal) and previous not in (None, "") and str(previous) == str(value)):
            return
        column = mapping[field] + sheet.get("start_column", 1)
        changes.append({"row": row_number, "column": column,
                        "a1": f"{_column_letter(column)}{row_number}",
                        "header": header, "previous_value": previous,
                        "value": _text_number(value) if isinstance(value, Decimal) else value,
                        "cell_value": _literal(value)})

    for holding in source.holdings:
        row = by_ticker.get(holding.ticker)
        isin_row = by_isin.get(holding.isin) if holding.isin else None
        if row and isin_row and row["row"] != isin_row["row"]:
            raise ValidationError("Ticker and ISIN resolve to different rows; reconcile identity first.")
        row = row or isin_row
        if row:
            row_number, existing = row["row"], row["values"]
        else:
            row_number = next(free, None)
            existing = {}
        if row_number is not None and row_number in matched_rows:
            raise ValidationError("Multiple input holdings resolve to one sheet row.")
        if row_number is not None:
            matched_rows.add(row_number)
        inputs = {"ticker": holding.ticker, "quantity": holding.quantity,
                  "average_price": holding.average_price if holding.average_price is not None else ""}
        if broker_authoritative:
            inputs["status"] = "Invested" if holding.quantity > 0 else "Exited"
        if holding.stock_name and not existing.get(field_header["stock_name"]):
            inputs["stock_name"] = holding.stock_name
        if holding.current_price is not None:
            inputs["current_price"] = holding.current_price
        for field in ("market_cap", "pe", "thesis_status", "signal"):
            if getattr(holding, field) is not None:
                inputs[field] = getattr(holding, field)
        if row_number is not None:
            for field, value in inputs.items():
                propose(row_number, field, value, existing)
        reasons = []
        if holding.thesis_status in {"Not covered", "Unavailable", "No snapshot", "Ambiguous match"} or holding.signal == "Unavailable":
            reasons.append("StockClarity: " + holding.thesis_status + ".")
        if holding.research_as_of and holding.research_as_of != datetime.now(IST).date().isoformat():
            reasons.append("StockClarity snapshot as of " + holding.research_as_of + "; run StockClarity for newer research.")
        if not broker_authoritative and holding.quantity > 0 and existing.get(field_header["status"]) != "Invested":
            reasons.append("Set/review manual Status: positive quantity is held.")
        if not broker_authoritative and holding.quantity == 0 and existing.get(field_header["status"]) == "Invested":
            reasons.append("Review manual Status: quantity is zero; no automatic exit is inferred.")
        value = holding.quantity * holding.current_price if holding.current_price is not None else None
        if holding.quantity == 0:
            value = Decimal(0)
        elif value is None:
            values_complete = False
            reasons.append("No independently dated market price supplied; existing sheet price is preserved, not treated as fresh.")
        if value is not None:
            total += value
        if holding.quantity > 0 and holding.average_price == 0:
            reasons.append("Average purchase price is zero; return is unavailable.")
        if holding.quantity > 0 and holding.average_price is None:
            reasons.append("USD cost basis is missing; average purchase price and return are unavailable.")
        positions.append({"ticker": holding.ticker, "sheet_row": row_number, "isin": holding.isin,
                          "quantity": _text_number(holding.quantity), "average_price": _text_number(holding.average_price),
                          "current_price": _text_number(holding.current_price), "price_as_of": holding.price_as_of,
                          "thesis_status": holding.thesis_status, "signal": holding.signal, "research_as_of": holding.research_as_of,
                          "market_value": _text_number(value), "weight_pct": None,
                          "unrealised_return_pct": _text_number((holding.current_price / holding.average_price - 1) * 100)
                          if holding.quantity > 0 and holding.current_price is not None and holding.average_price is not None and holding.average_price > 0 else None,
                          "review": reasons})
    rows_needed = sum(position["sheet_row"] is None for position in positions)
    if rows_needed:
        gaps.append(f"Table expansion needed: {rows_needed} additional holding rows; no cells are proposed for these positions yet.")
    missing = [key for key, row in by_ticker.items() if row["row"] not in matched_rows]
    if missing and not broker_authoritative:
        gaps.append("Existing securities absent from this input are retained for reconciliation; none are zeroed or marked Exited.")
    if not values_complete:
        gaps.append("At least one held security has no dated price; portfolio total and all weights are unavailable.")
    # Retained sheet positions can still carry real value. Do not publish a denominator
    # based only on the imported subset until their reconciliation is complete.
    unresolved_held = []
    for key in missing:
        row = by_ticker[key]
        raw_qty = row["values"].get(field_header["quantity"])
        state = row["values"].get(field_header["status"])
        try:
            held = decimal_value(raw_qty, "Existing quantity") > 0
        except ValidationError:
            held = state == "Invested" or raw_qty not in (None, "")
        if broker_authoritative and (held or state == "Invested"):
            propose(row["row"], "quantity", Decimal(0), row["values"])
            propose(row["row"], "status", "Exited", row["values"])
            gaps.append(f"{key}: absent from Zerodha/Coin; quantity set to zero and Status set to Exited.")
        elif held:
            unresolved_held.append(key)
    if unresolved_held:
        gaps.append("Unmatched existing holdings need reconciliation; portfolio total and all weights are unavailable.")
    complete = (bool(source.holdings) or broker_authoritative) and values_complete and not unresolved_held
    portfolio_total = total + source.cash if complete and source.cash is not None else None
    if portfolio_total is not None and portfolio_total > 0:
        for position in positions:
            position["weight_pct"] = _text_number(Decimal(position["market_value"]) / portfolio_total * 100)
    summary_updates = []
    summary_cells = sheet.get("summary_cells", {})
    if not isinstance(summary_cells, dict):
        raise ValidationError("summary_cells must be an object of named cells with a1/value metadata.")
    addresses = set()
    for entry in summary_cells.values():
        if not isinstance(entry, dict) or "value" not in entry:
            raise ValidationError("Every summary cell must include its captured a1 and value.")
        address = entry.get("a1")
        match = re.fullmatch(r"[A-Z]+([1-9][0-9]*)", address) if isinstance(address, str) else None
        if not match or int(match.group(1)) >= sheet["header_row"]:
            raise ValidationError("Summary cells must lie above the holdings header, outside the table.")
        if address in addresses:
            raise ValidationError("Summary cells must not overlap.")
        addresses.add(address)
    for field, value in [("broker_cash", source.cash), ("holdings_uploaded_on", source.holdings_as_of if source.market == "US" else None)]:
        if value is None:
            continue
        entry = summary_cells.get(field)
        if entry is None:
            raise ValidationError(f"{source.market}: explicit summary cell for {field} is required.")
        address = entry["a1"]
        if isinstance(entry["value"], str) and entry["value"].startswith("="):
            raise ValidationError(f"{source.market}: {field} contains a formula; review before replacing it.")
        if field == "holdings_uploaded_on":
            value = Decimal((date.fromisoformat(value) - date(1899, 12, 30)).days)
        summary_updates.append({"field": field, "a1": address, "previous_value": entry["value"], "cell_value": _literal(value)})
    return {"market": source.market, "currency": "INR" if source.market == "IN" else "USD",
            "sheet_title": sheet["title"], "sheet_id": sheet["sheet_id"],
            "source": source.source, "holdings_as_of": source.holdings_as_of,
            "cash": _text_number(source.cash), "cash_as_of": source.cash_as_of, "cash_source": source.cash_source,
            "equity_value": _text_number(total) if complete else None,
            "portfolio_total": _text_number(portfolio_total),
            "cash_weight_pct": _text_number(source.cash / portfolio_total * 100)
            if portfolio_total is not None and portfolio_total > 0 else None,
            "proposed_updates": changes, "proposed_summary_updates": summary_updates,
            "positions": positions, "additional_rows_needed": rows_needed,
            "retained_unmatched_tickers": [] if broker_authoritative else missing,
            "unresolved_existing_holdings": unresolved_held, "gaps": gaps}


def build_preview(layout: dict[str, Any], sources: list[PortfolioInput]) -> dict[str, Any]:
    if layout.get("schema_version") != 1 or not isinstance(layout.get("sheets"), dict):
        raise ValidationError("Expected sheet-snapshot schema_version 1 with a sheets object keyed IN/US.")
    captured = timestamp(layout.get("captured_at"), "Sheet snapshot captured_at")
    if not sources or len({s.market for s in sources}) != len(sources):
        raise ValidationError("Supply each selected market exactly once.")
    markets = [preview_market(source, layout["sheets"].get(source.market)) for source in sources]
    if len({market["sheet_id"] for market in markets}) != len(markets):
        raise ValidationError("Indian and US portfolios must resolve to different sheet IDs.")
    return {"mode": "dry_run", "live_reads": False, "sheet_writes": False,
            "sheet_snapshot_as_of": captured,
            "markets": markets}


def format_preview(preview: dict[str, Any]) -> str:
    reads = "enabled (read-only)" if preview.get("live_reads") else "none"
    lines = ["Portfolio sync preview — dry run", f"Live reads: {reads} | Sheet writes: none",
             "Sheet snapshot: " + preview["sheet_snapshot_as_of"]]
    for market in preview["markets"]:
        lines += ["", f"{market['sheet_title']} ({market['currency']})",
                  "Holdings as of: " + market["holdings_as_of"],
                  f"Cash: {market['cash'] if market['cash'] is not None else 'MISSING'} | Cash as of: {market['cash_as_of'] or 'MISSING'}",
                  f"Investments value: {market['equity_value'] or 'Unavailable'} | Portfolio total: {market['portfolio_total'] or 'Unavailable'}",
                  f"Proposed source cells: {len(market['proposed_updates'])}; summary cells: {len(market['proposed_summary_updates'])}"]
        for position in market["positions"]:
            weight = position["weight_pct"]
            shown_weight = f"{Decimal(weight):.2f}%" if weight is not None else "Unavailable"
            target = f"Row {position['sheet_row']}" if position['sheet_row'] is not None else "New row needed"
            lines.append(f"  {target}: {position['ticker']} | qty {position['quantity']} | weight {shown_weight}")
            if position["current_price"] is not None:
                lines.append(f"    Price: {position['current_price']} | Price as of: {position['price_as_of']}")
            if position.get("thesis_status"):
                lines.append(f"    StockClarity: {position['thesis_status']} | Signal: {position['signal']} | As of: {position['research_as_of'] or 'N/A'}")
            lines.extend("    Review: " + reason for reason in position["review"])
        lines.extend("  Gap: " + gap for gap in market["gaps"])
        if market["retained_unmatched_tickers"]:
            lines.append("  Retained, unmatched: " + ", ".join(market["retained_unmatched_tickers"]))
    return "\n".join(lines)


IST = timezone(timedelta(hours=5, minutes=30))
READ_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets/"
DEFAULT_SHEETS = {
    "IN": {"title": "India Portfolio", "table_name": "India_Holdings"},
    "US": {"title": "US Portfolio", "table_name": "US_Holdings"},
}


def now_iso() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


class GoogleSheets:
    """Read-only by default; update explicitly enables narrow Sheets batches."""

    def __init__(self, credentials_path: Path, *, writable: bool = False):
        self._writable = writable
        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import AuthorizedSession
        except ImportError as error:
            raise ValidationError("Google authentication support is missing; install the dependencies in requirements.txt in this Python environment.") from error
        credential = read_json(credentials_path)
        if credential.get("type") != "service_account" or credential.get("token_uri") != "https://oauth2.googleapis.com/token":
            raise ValidationError("Expected an existing Google service-account key with Google's standard token endpoint.")
        try:
            auth = service_account.Credentials.from_service_account_info(credential, scopes=[WRITE_SCOPE if writable else READ_SCOPE])
            self._session = AuthorizedSession(auth)
        except Exception as error:
            raise ValidationError("Could not load the Google credentials; no credential contents were logged.") from error

    def get(self, spreadsheet_id: str, *, ranges: list[str] | None = None) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", spreadsheet_id):
            raise ValidationError("Use a raw spreadsheet ID, not a URL.")
        fields = "spreadsheetId,sheets(properties,tables,merges)"
        if ranges is not None:
            fields = "spreadsheetId,sheets(properties,tables,merges,data(startRow,startColumn,rowData(values(userEnteredValue,effectiveValue,formattedValue,userEnteredFormat,dataValidation,chipRuns,note))))"
        params: list[tuple[str, str]] = [("fields", fields)]
        params += [("ranges", item) for item in ranges or []]
        try:
            response = self._session.get(SHEETS_BASE + spreadsheet_id, params=params, timeout=30)
        except Exception as error:
            raise ValidationError("Google read failed: check network/authentication. No credentials were logged.") from error
        if response.status_code != 200:
            raise ValidationError(f"Google read returned HTTP {response.status_code}; check API enablement and existing file access.")
        try:
            result = response.json()
        except ValueError as error:
            raise ValidationError("Google read returned invalid JSON.") from error
        if not isinstance(result, dict):
            raise ValidationError("Google read returned an unexpected response.")
        return result

    def batch_update(self, spreadsheet_id: str, requests: list[dict]) -> None:
        if not self._writable:
            raise ValidationError("Only the update command may write Google Sheets.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", spreadsheet_id):
            raise ValidationError("Use a raw spreadsheet ID, not a URL.")
        try:
            response = self._session.post(SHEETS_BASE + spreadsheet_id + ":batchUpdate",
                                          json={"requests": requests}, timeout=30)
        except Exception as error:
            raise ValidationError("Google write response was interrupted. Inspect the sheet before retrying; no request was replayed.") from error
        if response.status_code != 200:
            raise ValidationError(f"Google write returned HTTP {response.status_code}; no request was replayed. The existing service account needs editor access.")

    def close(self) -> None:
        self._session.close()


def _selected_table(resource: dict[str, Any], selection: dict[str, str]) -> tuple[dict, dict]:
    candidates = [s for s in resource.get("sheets", []) if s.get("properties", {}).get("title") == selection["title"]]
    if len(candidates) != 1:
        raise ValidationError(f"Expected exactly one visible sheet named {selection['title']}.")
    sheet = candidates[0]
    if sheet["properties"].get("hidden"):
        raise ValidationError("The selected portfolio sheet is hidden; review the configuration.")
    tables = [t for t in sheet.get("tables", []) if t.get("name") == selection["table_name"]]
    if len(tables) != 1:
        raise ValidationError(f"Expected native table {selection['table_name']}; no row capacity is guessed.")
    table = tables[0]
    bounds = table.get("range", {})
    props = sheet["properties"]
    for key in ("endRowIndex", "endColumnIndex"):
        if type(bounds.get(key)) is not int or bounds[key] < 1:
            raise ValidationError("Table must have explicit, valid row and column bounds.")
    start_row, start_col = bounds.get("startRowIndex", 0), bounds.get("startColumnIndex", 0)
    if bounds.get("sheetId") != props["sheetId"] or not 0 <= start_row < bounds["endRowIndex"] - 1 or not 0 <= start_col < bounds["endColumnIndex"]:
        raise ValidationError("Invalid native table range.")
    grid = props.get("gridProperties", {})
    if bounds["endRowIndex"] > grid.get("rowCount", 0) or bounds["endColumnIndex"] > grid.get("columnCount", 0):
        raise ValidationError("Native table exceeds the sheet grid.")
    return sheet, table


def capture_ranges(metadata: dict[str, Any], selections: dict[str, dict[str, str]]) -> list[str]:
    ranges = []
    for selection in selections.values():
        sheet, table = _selected_table(metadata, selection)
        width = sheet["properties"]["gridProperties"]["columnCount"]
        height = table["range"]["endRowIndex"]
        if height * width > 50000:
            raise ValidationError("Portfolio capture exceeds 50,000 cells per tab; narrow the live layout before capturing.")
        title = sheet["properties"]["title"].replace("'", "''")
        ranges.append(f"'{title}'!A1:{_column_letter(width)}{height}")
    return ranges


def _cells(sheet: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    cells = {}
    for block in sheet.get("data", []):
        r0, c0 = block.get("startRow", 0), block.get("startColumn", 0)
        for ri, row in enumerate(block.get("rowData", [])):
            for ci, cell in enumerate(row.get("values", [])):
                address = (r0 + ri, c0 + ci)
                if address in cells:
                    raise ValidationError("Overlapping grid blocks make the snapshot ambiguous.")
                cells[address] = cell
    return cells


def _entered(cell: dict[str, Any]) -> Any:
    value = cell.get("userEnteredValue", {})
    for field in ("formulaValue", "stringValue", "numberValue", "boolValue"):
        if field in value:
            return value[field]
    return None


SYNC_NOTE = re.compile(r"\[Portfolio sync\]\n(.*?)\n\[/Portfolio sync\]", re.S)


def sync_metadata(note: str) -> dict:
    match = SYNC_NOTE.search(note)
    if not match:
        return {}
    try:
        value = json.loads(match[1], object_pairs_hook=_unique_json)
    except (ValueError, TypeError) as error:
        raise ValidationError("The refresh note's saved source metadata is invalid; review it before updating.") from error
    if not isinstance(value, dict) or not isinstance(value.get("isins", {}), dict):
        raise ValidationError("The refresh note has invalid source metadata.")
    return value


def label_cell(sheet: dict, label: str, *, below: bool = False):
    """Find a summary value next to its merged label, or immediately below it."""
    native = sheet["native"]
    cells = _cells(native)
    found = [(r, c) for (r, c), cell in cells.items()
             if r < sheet["header_row"] - 1 and _entered(cell) == label]
    if not found:
        return None
    if len(found) != 1:
        raise ValidationError(f"Ambiguous summary label: {label}.")
    r, c = found[0]
    if below:
        r += 1
    else:
        merged = next((m for m in native.get("merges", [])
                       if m.get("startRowIndex", 0) == r and m.get("startColumnIndex", 0) == c), None)
        c = merged["endColumnIndex"] if merged else c + 1
    return r, c, cells.get((r, c), {})


def make_snapshot(metadata: dict[str, Any], grids: dict[str, Any],
                  selections: dict[str, dict[str, str]], captured_at: str) -> dict[str, Any]:
    if metadata.get("spreadsheetId") != grids.get("spreadsheetId"):
        raise ValidationError("Metadata and grid responses refer to different workbooks.")
    result = {"schema_version": 1, "spreadsheet_id": metadata["spreadsheetId"],
              "captured_at": timestamp(captured_at, "Capture timestamp"), "sheets": {}}
    for market, selection in selections.items():
        old_sheet, old_table = _selected_table(metadata, selection)
        sheet, table = _selected_table(grids, selection)
        if old_sheet["properties"] != sheet["properties"] or old_table["range"] != table["range"] or old_table.get("tableId") != table.get("tableId"):
            raise ValidationError("Sheet layout changed during capture; capture it again before previewing.")
        if "data" not in sheet:
            raise ValidationError("Google grid response is missing the requested table data.")
        bounds, cells = table["range"], _cells(sheet)
        header_row, start_col = bounds.get("startRowIndex", 0), bounds.get("startColumnIndex", 0)
        headers = [_entered(cells.get((header_row, c), {})) for c in range(start_col, bounds["endColumnIndex"])]
        captured_rows = []
        for r in range(header_row + 1, bounds["endRowIndex"]):
            values = {header: _entered(cells.get((r, start_col + c), {})) for c, header in enumerate(headers)
                      if _entered(cells.get((r, start_col + c), {})) is not None}
            notes = {header: cells[(r, start_col + c)]["note"] for c, header in enumerate(headers)
                     if cells.get((r, start_col + c), {}).get("note")}
            if values or notes:
                captured_rows.append({"row": r + 1, "values": values, "notes": notes})
        cur = "₹" if market == "IN" else "$"
        labels = {"broker_cash": f"Broker Cash ({cur})"}
        if market == "US":
            labels["holdings_uploaded_on"] = ("Holdings & Cash As Of", "Holdings Uploaded On")
        summaries = {}
        for name, label in labels.items():
            found = [(r, c) for (r, c), cell in cells.items() if r < header_row and _entered(cell) in (label if isinstance(label, tuple) else (label,))]
            if len(found) != 1:
                raise ValidationError(f"Expected one {label} label above the table.")
            r, c = found[0]
            if r + 1 >= header_row:
                raise ValidationError("Summary value does not lie above the table.")
            summaries[name] = {"a1": f"{_column_letter(c + 1)}{r + 2}",
                               "value": _entered(cells.get((r + 1, c), {}))}
        snapshot = {"complete": True, "sheet_id": sheet["properties"]["sheetId"],
                    "title": sheet["properties"]["title"], "header_row": header_row + 1,
                    "start_column": start_col + 1, "last_prepared_row": bounds["endRowIndex"],
                    "headers": headers, "summary_cells": summaries, "rows": captured_rows,
                    "table_id": table.get("tableId"), "table_name": table["name"], "native": sheet}
        validate_sheet(snapshot, market)
        refresh = label_cell(snapshot, "Last Refreshed")
        saved = sync_metadata(refresh[2].get("note", "")) if refresh else {}
        ticker_header = headers[mapped_headers(headers, sheet_headers(market))["ticker"]]
        for row in captured_rows:
            key = str(row["values"].get(ticker_header, "")).strip().upper()
            if key in saved.get("isins", {}):
                row["isin"] = saved["isins"][key]
        result["sheets"][market] = snapshot
    return result


def capture_google(reader: GoogleSheets, spreadsheet_id: str,
                   selections: dict[str, dict[str, str]]) -> dict[str, Any]:
    metadata = reader.get(spreadsheet_id)
    ranges = capture_ranges(metadata, selections)
    grids = reader.get(spreadsheet_id, ranges=ranges)
    return make_snapshot(metadata, grids, selections, now_iso())


def kite_client(credentials_path: Path | None = None) -> Any:
    import kite
    previous = kite.SECRETS_PATH
    if credentials_path is not None:
        kite.SECRETS_PATH = credentials_path
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return kite._authed_kite()
    except (SystemExit, OSError, ValueError, TypeError, ImportError, AttributeError) as error:
        raise ValidationError("Kite credentials/session are missing, invalid or expired. Complete python scripts/portfolio.py login yourself; no login was started.") from error
    finally:
        kite.SECRETS_PATH = previous


def read_kite(client: Any) -> tuple[dict, dict]:
    try:
        holdings = client.holdings()
        holdings_at = now_iso()
        funds = client.margins(segment="equity")
        funds_at = now_iso()
    except Exception as error:
        raise ValidationError("Kite read failed; check the session and permissions. No credentials or response bodies were logged.") from error
    if not isinstance(holdings, list) or not isinstance(funds, dict):
        raise ValidationError("Kite returned an unexpected holdings/funds response.")
    return ({"source": "kite", "as_of": holdings_at, "count": len(holdings), "holdings": holdings},
            {"source": "kite", "segment": "equity", "as_of": funds_at, "margins": funds})


def kite_reconciliation(holdings: dict, funds: dict) -> dict[str, Any]:
    """Show raw quantity/cash components without declaring a reconciliation policy."""
    rows = []
    for entry in holdings["holdings"]:
        if not isinstance(entry, dict):
            raise ValidationError("Invalid broker holding record.")
        rows.append({"ticker": f"{entry.get('exchange', '')}:{entry.get('tradingsymbol', '')}",
                     **{key: entry.get(key) for key in ("isin", "product", "quantity", "realised_quantity", "t1_quantity", "used_quantity", "short_quantity", "collateral_quantity", "average_price", "discrepancy")},
                     "mtf": entry.get("mtf")})
    margins = funds["margins"]
    return {"holdings_as_of": holdings["as_of"], "funds_as_of": funds["as_of"],
            "holdings": rows,
            "available": margins.get("available", {}),
            "utilised": margins.get("utilised", {}),
            "note": "Raw components only. Cash, quantity and stock-versus-ETF scope still require comparison with the broker account."}


def read_stockclarity(repo: Path) -> list[dict]:
    """Read saved daily decisions; never run StockClarity or change its database."""
    from dotenv import dotenv_values
    import psycopg2
    from psycopg2.extras import RealDictCursor
    env_path = repo / ".env"
    if not env_path.is_file():
        raise ValidationError("StockClarity .env was not found.")
    connection = None
    try:
        env = {**dotenv_values(env_path), **os.environ}
        connection = psycopg2.connect(host=env.get("DB_HOST", "localhost"), port=int(env.get("DB_PORT", "5432")),
            dbname=env.get("DB_NAME", "stockclarity"), user=env.get("DB_USER", "postgres"),
            password=env.get("DB_PASSWORD", ""), sslmode=env.get("DB_SSL_MODE", "prefer"), connect_timeout=10)
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SET LOCAL statement_timeout = '10000ms'")
            cursor.execute("""SELECT c.id AS company_id, c.nse_symbol, c.bse_code, c.us_ticker,
                    s.snapshot_date, s.thesis_status, s.decision_signal, s.created_at
                FROM companies c LEFT JOIN LATERAL (
                    SELECT snapshot_date, thesis_status, decision_signal, created_at
                    FROM thesis_snapshots WHERE company_id = c.id
                    ORDER BY snapshot_date DESC, id DESC LIMIT 1
                ) s ON true""")
            return [dict(row) for row in cursor.fetchall()]
    except Exception:
        raise ValidationError("StockClarity database could not be read; check its existing connection settings.") from None
    finally:
        if connection is not None:
            connection.close()


def add_stockclarity(source: PortfolioInput, records: list[dict] | None, evidence: dict,
                     *, bse_codes: dict[str, str] | None = None, today: str | None = None) -> tuple[PortfolioInput, list[str]]:
    """Match company research without using names, sector or inferred decisions."""
    today = today or datetime.now(IST).date().isoformat()
    updated, gaps = [], []
    for holding in source.holdings:
        research_date, matched = None, None
        if holding.asset_type in {"Mutual Fund", "ETF"}:
            status = signal = "Not applicable"
            reason = "StockClarity company research does not cover funds."
        elif records is None:
            status = signal = "Unavailable"
            reason = "StockClarity could not be read; no prior signal is presented as current."
        else:
            exchange, symbol = holding.ticker.split(":", 1)
            matches = []
            for record in records:
                nse = str(record.get("nse_symbol") or "").strip().upper()
                us = str(record.get("us_ticker") or "").strip().upper()
                code = str(record.get("bse_code") or "").strip()
                if source.market == "US":
                    match = us == symbol
                else:
                    # Research is company-level across NSE/BSE; -SM is an NSE segment suffix.
                    match = bool(nse) and nse == (symbol.removesuffix("-SM") if exchange == "NSE" else symbol)
                    match = match or (exchange == "BSE" and bool(code) and code == (bse_codes or {}).get(symbol))
                if match:
                    matches.append(record)
            if len(matches) > 1:
                status = signal = "Ambiguous match"
                reason = "Multiple StockClarity company records match; reconcile identifiers."
            elif not matches:
                status = signal = "Not covered"
                reason = "No exact StockClarity company identifier matches this holding."
            else:
                matched = matches[0]
                raw_date = matched.get("snapshot_date")
                if raw_date is None:
                    status = signal = "No snapshot"
                    reason = "Company exists but has no saved daily thesis snapshot."
                else:
                    try:
                        research_date = iso_date(str(raw_date), "StockClarity snapshot date")
                        status = matched.get("thesis_status")
                        signal = matched.get("decision_signal")
                        if research_date > today or status not in {"STRONG", "MAINTAINING", "WEAK", "BROKEN"}:
                            raise ValidationError("Invalid daily thesis snapshot.")
                        if signal not in {"Buy", "Hold", "Sell", None}:
                            raise ValidationError("Invalid daily decision signal.")
                        signal = signal or "Unavailable"
                        reason = "Saved StockClarity daily snapshot as of " + research_date + "; signal copied without recomputing."
                        if research_date != today:
                            status += " (" + research_date + ")"
                            signal += " (" + research_date + ")"
                    except ValidationError:
                        status = signal = "Unavailable"
                        research_date = None
                        reason = "Invalid or future-dated StockClarity snapshot; no signal inferred."
        evidence.setdefault(holding.ticker, {})["research"] = {
            "source": "StockClarity thesis_snapshots", "as_of": research_date,
            "company_id": matched.get("company_id") if matched else None,
            "thesis_status": status, "signal": signal, "reason": reason}
        updated.append(replace(holding, thesis_status=status, signal=signal, research_as_of=research_date))
        if status in {"Unavailable", "Ambiguous match", "No snapshot"} or signal.startswith("Unavailable"):
            gaps.append(holding.ticker + ": " + reason)
    return replace(source, holdings=tuple(updated)), gaps


def parse_amfi_navs(text: str, wanted: set[str] | None = None) -> dict[str, tuple[Decimal, str]]:
    """AMFI's public file has six-column and eight-column layouts."""
    result = {}
    for row in csv.reader(io.StringIO(text), delimiter=";"):
        if len(row) not in (6, 8) or not row[0].strip().isdigit():
            continue
        try:
            nav = decimal_value(row[-2], "AMFI NAV", positive=True)
            as_of = datetime.strptime(row[-1].strip(), "%d-%b-%Y").date().isoformat()
        except (ValidationError, ValueError):
            continue
        if as_of > datetime.now(IST).date().isoformat():
            raise ValidationError("AMFI supplied a future NAV date.")
        for isin in row[1:3]:
            if re.fullmatch(r"INF[A-Z0-9]{9}", isin) and (wanted is None or isin in wanted):
                if isin in result and result[isin] != (nav, as_of):
                    raise ValidationError("Conflicting AMFI NAV records for one ISIN.")
                result[isin] = (nav, as_of)
    return result


def add_mutual_funds(source: PortfolioInput, client: Any, evidence: dict, *, nav_text: str | None = None) -> PortfolioInput:
    try:
        records = client.mf_holdings()
    except Exception as error:
        raise ValidationError("Coin holdings could not be read; combined portfolio refresh stopped.") from error
    if not isinstance(records, list):
        raise ValidationError("Unexpected Coin holdings response.")
    if not records:
        return replace(source, source="Zerodha + Coin")
    if nav_text is None:
        import requests
        try:
            response = requests.get("https://portal.amfiindia.com/spages/NAVAll.txt", timeout=30)
            response.raise_for_status()
            nav_text = response.text
        except requests.RequestException as error:
            raise ValidationError("AMFI dated NAVs could not be read; combined refresh stopped.") from error
    navs = parse_amfi_navs(nav_text, {str(r.get("tradingsymbol", "")) for r in records})
    holdings = list(source.holdings)
    for record in records:
        isin = str(record.get("tradingsymbol", ""))
        ticker = security_key("MF:" + isin, "IN")
        if record.get("discrepancy") or any(decimal_value(record.get(k, 0), k) > 0 for k in ("pledged_quantity", "las_quantity")):
            raise ValidationError("Coin discrepancy or pledged units need reconciliation before refreshing.")
        qty = decimal_value(record.get("quantity"), "MF units")
        average = decimal_value(record.get("average_price"), "MF average NAV")
        nav, as_of = navs.get(isin, (None, None))
        if nav is None:
            raise ValidationError("A Coin holding has no exact-ISIN dated AMFI NAV; refresh stopped.")
        holdings.append(Holding(ticker, record.get("fund") or None, qty, average, nav, as_of, isin, "Mutual Fund"))
        evidence[ticker] = {"source": "amfiindia.com", "price_as_of": as_of, "currency": "INR", "instrument_type": "MUTUALFUND"}
    return replace(source, holdings=validate_holdings(holdings), source="Zerodha + Coin")


def parse_fundamentals(text: str) -> dict[str, Decimal | None]:
    result = {}
    for field, label in (("market_cap", "Market Cap"), ("pe", "Stock P/E")):
        block = next((b for b in re.findall(r"<li\b[^>]*>.*?</li>", text, re.S) if label in re.sub(r"<[^>]+>", " ", b)), "")
        match = re.search(r'class="number"[^>]*>\s*([\d,.]+)\s*</span>', block)
        if field == "market_cap" and not re.search(r"\bCr\.", block):
            match = None
        result[field] = decimal_value(match[1].replace(",", ""), label, positive=True) if match else None
    return result


def add_fundamentals(source: PortfolioInput, evidence: dict, fetcher=None, *, client=None) -> tuple[PortfolioInput, list[str]]:
    """Screener India figures or Yahoo US company figures; never guess fund P/E."""
    if source.market == "US":
        updated, gaps = [], []
        for holding in source.holdings:
            if holding.quantity == 0:
                updated.append(holding)
                continue
            values = {"market_cap": None, "pe": None}
            url = "https://finance.yahoo.com/quote/" + holding.ticker.split(":", 1)[1] + "/"
            try:
                info = (fetcher or us_profile)(holding.ticker.split(":", 1)[1])
                ticker, kind = us_identity(holding.ticker.split(":", 1)[1], info)
                if ticker != holding.ticker and not ({ticker.split(":")[0], holding.ticker.split(":")[0]} <= {"AMEX", "NYSEAMERICAN"}):
                    raise ValidationError("US provider exchange disagrees with the holdings identity.")
                if kind != holding.asset_type:
                    raise ValidationError("US provider instrument type disagrees with the dated quote.")
                if kind == "Stock":
                    for field, key in (("market_cap", "marketCap"), ("pe", "trailingPE")):
                        try:
                            values[field] = decimal_value(info.get(key), key, positive=True)
                        except ValidationError:
                            pass
                    if values["market_cap"] is not None:
                        values["market_cap"] /= Decimal(1_000_000)
            except Exception:
                gaps.append(holding.ticker + ": US fundamentals/identity unavailable; previous cells preserved.")
            if holding.asset_type == "Stock" and any(v is None for v in values.values()):
                gaps.append(holding.ticker + ": missing/non-applicable company market cap or trailing P/E; previous cells preserved.")
            evidence.setdefault(holding.ticker, {})["fundamentals"] = {
                "source": url, "fetched_at": now_iso(), "pe_basis": "trailing", "market_cap_unit": "USD million",
                "not_applicable": holding.asset_type == "ETF", "missing": [k for k, v in values.items() if v is None]}
            updated.append(replace(holding, **values))
        return replace(source, holdings=tuple(updated)), gaps
    if fetcher is None:
        import requests
        def fetcher(url):
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            return response.status_code, response.text
    updated, gaps, bse_codes = [], [], None
    for holding in source.holdings:
        if holding.asset_type == "Mutual Fund" or holding.quantity == 0:
            updated.append(holding)
            continue
        symbol = holding.ticker.split(":", 1)[1]
        # NSE SME segment suffix is not part of Screener's company identifier.
        company = symbol.removesuffix("-SM") if holding.ticker.startswith("NSE:") else symbol
        values = {"market_cap": None, "pe": None}
        chosen = None
        try:
            for view in ("consolidated/", ""):
                url = "https://www.screener.in/company/" + company + "/" + view
                status, html = fetcher(url)
                if status != 200:
                    continue
                text = unescape(html)
                parsed = parse_fundamentals(text)
                if parsed["market_cap"] is not None:
                    values, chosen = parsed, url
                    break
            if chosen is None and holding.ticker.startswith("BSE:") and client is not None:
                if bse_codes is None:
                    bse_codes = {r["tradingsymbol"]: str(r["exchange_token"]) for r in client.instruments("BSE")}
                code = bse_codes.get(symbol)
                if code and code.isdigit():
                    for view in ("consolidated/", ""):
                        url = "https://www.screener.in/company/" + code + "/" + view
                        status, html = fetcher(url)
                        if status == 200:
                            parsed = parse_fundamentals(unescape(html))
                            if parsed["market_cap"] is not None:
                                values, chosen = parsed, url
                                break
        except Exception:
            # Fundamentals gaps must not erase a valid holdings/price update.
            chosen = None
        updated.append(replace(holding, **values))
        evidence.setdefault(holding.ticker, {})["fundamentals"] = {"source": chosen, "fetched_at": now_iso(),
                                                                   "missing": [k for k, v in values.items() if v is None]}
        if any(v is None for v in values.values()):
            gaps.append(holding.ticker + ": missing/non-applicable " + ", ".join(k for k, v in values.items() if v is None) + "; previous cells preserved.")
    return replace(source, holdings=tuple(updated)), gaps


def add_market_quotes(source: PortfolioInput, fetcher=None, *, evidence: dict | None = None) -> tuple[PortfolioInput, list[str]]:
    """Exact-symbol, dated Yahoo prices for India and US; no paid Kite quotes."""
    if source.market not in {"IN", "US"}:
        raise ValidationError("Unsupported quote market.")
    market, currency = ("india", "INR") if source.market == "IN" else ("us", "USD")
    symbols = {}
    for holding in source.holdings:
        if holding.quantity > 0 and holding.asset_type != "Mutual Fund":
            exchange, symbol = holding.ticker.split(":", 1)
            symbols[holding.ticker] = symbol + ({"NSE": ".NS", "BSE": ".BO"}[exchange] if source.market == "IN" else "")
    if not symbols:
        return source, []
    if len(set(symbols.values())) != len(symbols):
        raise ValidationError("Holdings repeat a provider symbol on different exchanges; confirm provider mapping before fetching quotes.")
    if fetcher is None:
        from fetch_quote import _fetch_yahoo_batch
        fetcher = lambda tickers: _fetch_yahoo_batch(tickers, market=market)
    try:
        payload = fetcher(list(symbols.values()))
    except Exception:
        missing = tuple(replace(h, current_price=None, price_as_of=None) if h.quantity > 0 and h.asset_type != "Mutual Fund" else h for h in source.holdings)
        return replace(source, holdings=missing), ["Yahoo quote request failed; dated prices and portfolio weights are unavailable."]
    quotes = payload.get("quotes") if isinstance(payload, dict) else None
    if not isinstance(quotes, list):
        raise ValidationError("Quote provider returned an unexpected response.")
    by_symbol = {}
    for quote in quotes:
        if not isinstance(quote, dict):
            raise ValidationError("Quote provider returned an invalid quote record.")
        key = quote.get("input_ticker")
        if key not in symbols.values() or key in by_symbol:
            raise ValidationError("Quote response has duplicate or unexpected symbols.")
        by_symbol[key] = quote
    updated, gaps = [], []
    for holding in source.holdings:
        if holding.asset_type == "Mutual Fund":
            updated.append(holding)
            continue
        if holding.quantity == 0:
            updated.append(holding)
            continue
        symbol = symbols[holding.ticker]
        quote = by_symbol.get(symbol, {})
        try:
            if quote.get("error") or quote.get("resolved_ticker") != symbol or quote.get("currency") != currency or quote.get("currency_verified") is not True:
                raise ValidationError("Missing quote or unverified currency/security identity.")
            price = decimal_value(quote.get("last_close"), "Quote", positive=True)
            epoch = decimal_value(quote.get("provider_timestamp"), "Quote timestamp", positive=True)
            as_of = datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()
            if datetime.fromisoformat(as_of) > datetime.fromisoformat(now_iso()) + timedelta(minutes=5):
                raise ValidationError("Quote is future dated.")
            if as_of[:10] != iso_date(quote.get("as_of"), "Quote as_of"):
                raise ValidationError("Quote date disagrees with its provider timestamp.")
            kind = holding.asset_type
            if source.market == "US":
                kind = {"EQUITY": "Stock", "ETF": "ETF"}.get(quote.get("instrument_type"))
                if kind is None:
                    raise ValidationError("US quote must identify a stock or ETF.")
            name = quote.get("stock_name")
            updated.append(replace(holding, current_price=price, price_as_of=as_of,
                                   asset_type=kind,
                                   stock_name=holding.stock_name or (name if isinstance(name, str) else None)))
            if evidence is not None:
                evidence.setdefault(holding.ticker, {}).update({"source": quote.get("source"), "resolved_symbol": symbol,
                                            "provider_timestamp": float(epoch), "price_as_of": as_of, "currency": currency,
                                            "instrument_type": quote.get("instrument_type")})
        except (ValidationError, OverflowError, OSError, ValueError):
            updated.append(replace(holding, current_price=None, price_as_of=None))
            gaps.append(holding.ticker + ": no dated, exact-symbol, provider-verified " + currency + " quote.")
    return replace(source, holdings=tuple(updated)), gaps


def cell_request(sheet_id: int, row: int, column: int, value: dict, **extra) -> dict:
    """Write one explicit value without touching its formatting or validation."""
    return {"updateCells": {"range": {"sheetId": sheet_id, "startRowIndex": row, "endRowIndex": row + 1,
                                     "startColumnIndex": column, "endColumnIndex": column + 1},
                            "rows": [{"values": [{"userEnteredValue": value, **extra}]}],
                            "fields": ",".join(["userEnteredValue", *extra])}}


def update_requests(reader: GoogleSheets, spreadsheet_id: str, sheet: dict,
                    source: PortfolioInput, evidence: dict) -> tuple[list, dict, dict]:
    """Plan only source cells, safe blank-row expansion and existing formulas."""
    if source.source == US_SHEET_SOURCE:
        current_inputs = load_us_sheet(sheet)
        keys = lambda s: [(h.ticker, h.quantity, h.average_price) for h in s.holdings]
        if keys(current_inputs) != keys(source) or (current_inputs.cash, current_inputs.holdings_as_of) != (source.cash, source.holdings_as_of):
            raise ValidationError("US holdings/cost/cash inputs changed during the fetch; rerun instead of overwriting them.")
    current = preview_market(source, sheet)
    if current["portfolio_total"] is None:
        raise ValidationError("A complete dated price set and confirmed cash are required before updating.")
    if any(Decimal(p["quantity"]) == 0 and any("quantity is zero" in reason for reason in p["review"]) for p in current["positions"]):
        raise ValidationError("A zero-quantity position is still marked Invested. Review its manual Status before updating; no cells were written.")
    if any(evidence.get(h.ticker, {}).get("instrument_type") != ("MUTUALFUND" if h.asset_type == "Mutual Fund" else "ETF" if source.market == "US" and h.asset_type == "ETF" else "EQUITY")
           for h in source.holdings if h.quantity > 0):
        raise ValidationError("Stock/fund instrument type is not verified for every holding; no cells were written.")
    refresh = label_cell(sheet, "Last Refreshed")
    if not refresh or "formulaValue" in refresh[2].get("userEnteredValue", {}):
        raise ValidationError("A writable Last Refreshed summary cell is required.")
    native, sid = sheet["native"], sheet["sheet_id"]
    mapping, _ = validate_sheet(sheet, source.market)
    start_col = sheet.get("start_column", 1) - 1
    old_end = sheet["last_prepared_row"]
    new_end = old_end + current["additional_rows_needed"]
    expanded = {**sheet, "last_prepared_row": new_end}
    plan = preview_market(source, expanded)
    requests = []
    if new_end > old_end:
        if new_end > native["properties"]["gridProperties"]["rowCount"]:
            raise ValidationError("The sheet grid needs more rows before its native table can be expanded.")
        width = native["properties"]["gridProperties"]["columnCount"]
        title = sheet["title"].replace("'", "''")
        area = reader.get(spreadsheet_id, ranges=[f"'{title}'!A{old_end + 1}:{_column_letter(width)}{new_end}"])
        extra_sheet = next(s for s in area["sheets"] if s["properties"]["sheetId"] == sid)
        if any(c.get("userEnteredValue") or c.get("note") or c.get("chipRuns") for c in _cells(extra_sheet).values()):
            raise ValidationError("Cells below the table contain data or notes; expansion would overwrite them.")
        bounds = {"sheetId": sid, "startRowIndex": sheet["header_row"] - 1, "endRowIndex": new_end,
                  "startColumnIndex": start_col, "endColumnIndex": start_col + len(sheet["headers"])}
        for table in native.get("tables", []):
            other = table["range"]
            if table["tableId"] != sheet["table_id"] and other.get("startRowIndex", 0) < new_end and other["endRowIndex"] > old_end:
                if other.get("startColumnIndex", 0) < bounds["endColumnIndex"] and other["endColumnIndex"] > start_col:
                    raise ValidationError("Another native table blocks expansion.")
        requests.append({"updateTable": {"table": {"tableId": sheet["table_id"], "range": bounds}, "fields": "range"}})
        exemplar = next((row for row in reversed(sheet["rows"])
                         if all(str(row["values"].get(sheet["headers"][mapping[f]], "")).startswith("=") for f in DERIVED_FIELDS)), None)
        if exemplar is None:
            raise ValidationError("A complete formula row is required to extend the table.")
        source_range = {**bounds, "startRowIndex": exemplar["row"] - 1, "endRowIndex": exemplar["row"]}
        destination = {**bounds, "startRowIndex": old_end}
        for paste in ("PASTE_FORMAT", "PASTE_DATA_VALIDATION"):
            requests.append({"copyPaste": {"source": source_range, "destination": destination, "pasteType": paste}})
        for field in sorted(DERIVED_FIELDS):
            column = start_col + mapping[field]
            requests.append({"copyPaste": {
                "source": {**source_range, "startColumnIndex": column, "endColumnIndex": column + 1},
                "destination": {**destination, "startColumnIndex": column, "endColumnIndex": column + 1},
                "pasteType": "PASTE_FORMULA"}})
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": old_end, "endIndex": new_end},
            "properties": {"pixelSize": 32}, "fields": "pixelSize"}})
        requests.append({"repeatCell": {"range": source_range | {"startRowIndex": sheet["header_row"] - 1,
            "endRowIndex": sheet["header_row"]}, "cell": {"userEnteredFormat": {"textFormat": {
            "foregroundColorStyle": {"rgbColor": {"red": 0.12, "green": 0.2, "blue": 0.18}}}}},
            "fields": "userEnteredFormat.textFormat.foregroundColorStyle"}})
    for update in plan["proposed_updates"]:
        requests.append(cell_request(sid, update["row"] - 1, update["column"] - 1, update["cell_value"]))
    for update in plan["proposed_summary_updates"]:
        match = re.fullmatch(r"([A-Z]+)([0-9]+)", update["a1"])
        column = 0
        for char in match[1]:
            column = column * 26 + ord(char) - 64
        requests.append(cell_request(sid, int(match[2]) - 1, column - 1, update["cell_value"]))
    for holding, position in zip(source.holdings, plan["positions"]):
        column = start_col + mapping["quantity"]
        pattern = "#,##0.########" if source.market == "US" else "#,##0.0000" if holding.asset_type == "Mutual Fund" else "#,##0"
        requests.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": position["sheet_row"] - 1,
            "endRowIndex": position["sheet_row"], "startColumnIndex": column, "endColumnIndex": column + 1},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": pattern}}},
            "fields": "userEnteredFormat.numberFormat"}})
    # Match financial display precision without changing any manual columns.
    for field in ("average_price", "current_price", "market_value", "weight", "return"):
        column = start_col + mapping[field]
        fmt = {"type": "PERCENT", "pattern": "0.00%"} if field in {"weight", "return"} else {"type": "NUMBER", "pattern": "#,##0.00"}
        requests.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": sheet["header_row"], "endRowIndex": new_end,
                                                   "startColumnIndex": column, "endColumnIndex": column + 1},
                                          "cell": {"userEnteredFormat": {"numberFormat": fmt}}, "fields": "userEnteredFormat.numberFormat"}})
    # Preserve four-decimal NAV display after applying the common financial format.
    for position in plan["positions"]:
        if position["ticker"].startswith("MF:"):
            for field in ("average_price", "current_price"):
                column = start_col + mapping[field]
                requests.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": position["sheet_row"] - 1,
                    "endRowIndex": position["sheet_row"], "startColumnIndex": column, "endColumnIndex": column + 1},
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.0000"}}},
                    "fields": "userEnteredFormat.numberFormat"}})
    return requests, expanded, plan


def verify_update(before: dict, actual: dict, expected: dict, plan: dict) -> None:
    """Check exact source writes, protected content and recalculated values."""
    def same(got, want):
        if want == "":
            return got in (None, "")
        if isinstance(want, (float, int)):
            return isinstance(got, (float, int)) and math.isclose(got, want, rel_tol=1e-12, abs_tol=1e-8)
        return got == want
    cells = _cells(actual)
    changed = {(u["row"] - 1, u["column"] - 1): next(iter(u["cell_value"].values())) for u in plan["proposed_updates"]}
    for address, value in changed.items():
        if not same(_entered(cells.get(address, {})), value):
            raise ValidationError("Source-cell verification failed after the write. No refresh timestamp was advanced.")
    for update in plan["proposed_summary_updates"]:
        match = re.fullmatch(r"([A-Z]+)([0-9]+)", update["a1"])
        column = 0
        for char in match[1]:
            column = column * 26 + ord(char) - 64
        if not same(_entered(cells.get((int(match[2]) - 1, column - 1), {})), next(iter(update["cell_value"].values()))):
            raise ValidationError("Summary source-cell verification failed; freshness was not advanced.")
    old_cells = _cells(before["native"])
    for address, old in old_cells.items():
        if address[0] >= before["header_row"] and address not in changed:
            if _entered(cells.get(address, {})) != _entered(old):
                raise ValidationError("Protected content changed during the refresh. Inspect the sheet before retrying.")
        if cells.get(address, {}).get("note") != old.get("note"):
            raise ValidationError("A cell note changed during the data write. Inspect the sheet before retrying.")
    mapping = mapped_headers(expected["headers"], sheet_headers(plan["market"]))
    start = expected.get("start_column", 1) - 1
    for position in plan["positions"]:
        for field, key, divisor in (("market_value", "market_value", 1), ("weight", "weight_pct", 100), ("return", "unrealised_return_pct", 100)):
            cell = cells.get((position["sheet_row"] - 1, start + mapping[field]), {})
            value = position[key]
            if value is not None and not same(cell.get("effectiveValue", {}).get("numberValue"), float(Decimal(value) / divisor)):
                raise ValidationError("A calculated value/weight/return does not match the preview. No refresh timestamp was advanced.")
    table = next(t for t in actual.get("tables", []) if t["tableId"] == expected["table_id"])
    if table["range"]["endRowIndex"] != expected["last_prepared_row"]:
        raise ValidationError("Native table expansion was not verified.")


def apply_updates(reader: GoogleSheets, spreadsheet_id: str, selections: dict,
                  sources: list[PortfolioInput], evidence: dict) -> None:
    selected = {source.market: selections[source.market] for source in sources}
    layout = capture_google(reader, spreadsheet_id, selected)  # Re-read immediately before planning writes.
    requests, plans = [], []
    for source in sources:
        before = layout["sheets"][source.market]
        batch, expanded, plan = update_requests(reader, spreadsheet_id, before, source, evidence)
        requests.extend(batch)
        plans.append((source, before, expanded, plan))
    reader.batch_update(spreadsheet_id, requests)
    ranges = [f"'{s['title'].replace(chr(39), chr(39)*2)}'!A1:{_column_letter(s['native']['properties']['gridProperties']['columnCount'])}{s['last_prepared_row']}"
              for _, _, s, _ in plans]
    result = reader.get(spreadsheet_id, ranges=ranges)
    stamps = []
    for source, before, expanded, plan in plans:
        actual = next(s for s in result["sheets"] if s["properties"]["sheetId"] == before["sheet_id"])
        verify_update(before, actual, expanded, plan)
        # Advance freshness only after source cells and dependent formulas verify.
        r, c, cell = label_cell(before, "Last Refreshed")
        metadata = sync_metadata(cell.get("note", ""))
        metadata.update(holdings_as_of=source.holdings_as_of, cash_as_of=source.cash_as_of, cash_source=source.cash_source,
                        isins={**metadata.get("isins", {}), **{h.ticker: h.isin for h in source.holdings if h.isin}},
                        prices={h.ticker: evidence.get(h.ticker) for h in source.holdings if h.quantity > 0})
        base = SYNC_NOTE.sub("", cell.get("note", "")).rstrip()
        note = base + "\n\n[Portfolio sync]\n" + json.dumps(metadata, ensure_ascii=False) + "\n[/Portfolio sync]"
        instant = datetime.now(IST)
        serial = (instant.replace(tzinfo=None) - datetime(1899, 12, 30)).total_seconds() / 86400
        stamps.append(cell_request(before["sheet_id"], r, c, {"numberValue": serial}, note=note))
        research_incomplete = any(h.thesis_status in {None, "Unavailable", "No snapshot", "Ambiguous match"}
                                  or not h.signal or h.signal.startswith("Unavailable")
                                  or (h.research_as_of and h.research_as_of != datetime.now(IST).date().isoformat())
                                  for h in source.holdings)
        for label, below, text in (("Holdings source", False, source.source),
                                    ("Sync Status", True, "Updated · research needs review" if research_incomplete else "Updated · research linked")):
            target = label_cell(before, label, below=below)
            if target and "formulaValue" not in target[2].get("userEnteredValue", {}):
                stamps.append(cell_request(before["sheet_id"], target[0], target[1], {"stringValue": text}))
        if source.market == "IN" and source.cash_as_of:
            target = label_cell(before, "Holdings & Cash As Of", below=True)
            if target and "formulaValue" not in target[2].get("userEnteredValue", {}):
                confirmed = min(source.holdings_as_of[:10], source.cash_as_of[:10])
                serial_date = (date.fromisoformat(confirmed) - date(1899, 12, 30)).days
                stamps.append(cell_request(before["sheet_id"], target[0], target[1], {"numberValue": serial_date}))
        if any(h.asset_type == "Mutual Fund" for h in source.holdings):
            for (row, column), cell in _cells(before["native"]).items():
                if row < before["header_row"] and _entered(cell) == "Equity Value (₹)":
                    stamps.append(cell_request(before["sheet_id"], row, column, {"stringValue": "Investments Value (₹)"}))
    reader.batch_update(spreadsheet_id, stamps)
    final = reader.get(spreadsheet_id, ranges=ranges)
    for request in stamps:
        change = request["updateCells"]
        bounds = change["range"]
        actual = next(s for s in final["sheets"] if s["properties"]["sheetId"] == bounds["sheetId"])
        cell = _cells(actual).get((bounds["startRowIndex"], bounds["startColumnIndex"]), {})
        wanted = change["rows"][0]["values"][0]
        if cell.get("userEnteredValue") != wanted["userEnteredValue"] or ("note" in wanted and cell.get("note") != wanted["note"]):
            raise ValidationError("Refresh metadata verification failed; inspect the sheet before retrying.")
    print("Sheets updated and verified: " + ", ".join(f"{s['title']} ({len(plan['positions'])} positions)" for _, _, s, plan in plans))


def local_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a local file path in private/portfolio-sync/settings.json.")
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def run_live(settings: dict[str, Any], command: str) -> int:
    spreadsheet_id = settings.get("spreadsheet_id")
    if not isinstance(spreadsheet_id, str) or not spreadsheet_id:
        raise ValidationError("Settings require spreadsheet_id.")
    credential_path = local_path(settings.get("google_credentials"), "google_credentials")
    selections = settings.get("sheets", DEFAULT_SHEETS)
    if not isinstance(selections, dict) or not selections or not selections.keys() <= DEFAULT_SHEETS.keys():
        raise ValidationError("sheets must map IN and/or US to explicit title/table_name settings.")
    if any(not isinstance(v, dict) or not all(isinstance(v.get(k), str) and v[k] for k in ("title", "table_name")) for v in selections.values()):
        raise ValidationError("Each selected market needs title and table_name.")
    if command == "update" and "US" in selections and settings.get("us_holdings") is not None:
        try:
            answer = input("Update US portfolio market values too? Holdings, purchase costs and cash remain your sheet inputs. [y/N]: ")
        except (EOFError, OSError):
            answer = ""
        if answer.strip().casefold() not in {"y", "yes"}:
            print("US portfolio skipped; updating India only.")
            selections = {market: selection for market, selection in selections.items() if market != "US"}
            settings = {key: value for key, value in settings.items()
                        if key not in {"us_holdings", "us_cash", "us_cash_as_of", "us_holdings_as_of"}}
    cash_field, us_source = None, None
    us_from_sheet = settings.get("us_holdings") == "sheet"
    if command != "check" and "IN" not in selections:
        raise ValidationError("The current broker workflow requires the IN sheet configuration.")
    if command in {"preview", "update"}:
        cash_field = settings.get("india_cash_field")
        if cash_field is not None and (not isinstance(cash_field, str) or cash_field not in {"available.cash", "available.live_balance"}):
            raise ValidationError("india_cash_field must be null, available.cash or available.live_balance; confirm it using python scripts/portfolio.py review.")
        us_path = settings.get("us_holdings")
        if us_path is None and any(settings.get(k) is not None for k in ("us_cash", "us_cash_as_of", "us_holdings_as_of")):
            raise ValidationError("US cash/dates require a us_holdings CSV or Vested XLSX path in settings.")
        if us_path is not None:
            if "US" not in selections:
                raise ValidationError("The US input requires its own sheet configuration.")
            if us_from_sheet:
                if any(settings.get(k) is not None for k in ("us_cash", "us_cash_as_of", "us_holdings_as_of")):
                    raise ValidationError("US sheet mode reads quantities/costs/cash from the sheet; remove duplicate US cash/date settings.")
            else:
                # Optional broker-file import; daily sheet mode needs no local file.
                path = local_path(us_path, "us_holdings")
                loader = load_us_vested if path.suffix.lower() == ".xlsx" else load_us_csv
                us_source = loader(path, cash=settings.get("us_cash"), cash_as_of=settings.get("us_cash_as_of"),
                                   holdings_as_of=settings.get("us_holdings_as_of"))
    reader = GoogleSheets(credential_path, writable=True) if command == "update" else GoogleSheets(credential_path)
    try:
        layout = capture_google(reader, spreadsheet_id, selections)
        if command == "check":
            print(json.dumps({
                "mode": "read_only_capture", "sheet_writes": False,
                "captured_at": layout["captured_at"], "spreadsheet_id": spreadsheet_id,
                "sheets": {market: {"title": sh["title"], "header_row": sh["header_row"],
                                    "prepared_rows": sh["last_prepared_row"] - sh["header_row"],
                                    "columns": len(sh["headers"])} for market, sh in layout["sheets"].items()},
            }, indent=2, ensure_ascii=False))
            return 0
        if us_from_sheet and command in {"preview", "update"}:
            us_source = load_us_sheet(layout["sheets"]["US"])
        client = kite_client(local_path(settings.get("kite_credentials", "secrets/kite.yaml"), "kite_credentials"))
        holdings, funds = read_kite(client)
        reconciliation = kite_reconciliation(holdings, funds)
        report = {"mode": "read_only_reconciliation", "live_reads": True, "sheet_writes": False,
                  "sheet_snapshot_as_of": layout["captured_at"], "kite_reconciliation": reconciliation}
        if command == "review":
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        try:
            india = parse_kite_payload(holdings, funds=funds if cash_field is not None else None,
                                       cash_field=cash_field)
        except ValidationError as error:
            report["preview_blocked"] = str(error)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 1
        evidence, quote_gaps = {}, {}
        india = add_mutual_funds(india, client, evidence)
        india, quote_gaps["IN"] = add_market_quotes(india, evidence=evidence)
        india, fundamental_gaps = add_fundamentals(india, evidence, client=client)
        quote_gaps["IN"].extend(fundamental_gaps)
        sources = [india]
        if us_source is not None:
            us_source, quote_gaps["US"] = add_market_quotes(us_source, evidence=evidence)
            us_source, us_gaps = add_fundamentals(us_source, evidence)
            quote_gaps["US"].extend(us_gaps)
            sources.append(us_source)
        try:
            records = read_stockclarity(local_path(settings.get("stockclarity_repo", str(ROOT.parent / "StockClarity")), "stockclarity_repo"))
            bse_codes = {}
            if any(r.get("bse_code") for r in records) and any(h.ticker.startswith("BSE:") for h in india.holdings):
                bse_codes = {r["tradingsymbol"]: str(r["exchange_token"]) for r in client.instruments("BSE")}
        except Exception:
            records, bse_codes = None, {}
        research_sources = []
        for source in sources:
            source, research_gaps = add_stockclarity(source, records, evidence, bse_codes=bse_codes)
            quote_gaps.setdefault(source.market, []).extend(research_gaps)
            research_sources.append(source)
        sources = research_sources
        preview = build_preview(layout, sources)
        preview.update(live_reads=True, kite_reconciliation=reconciliation, quote_evidence=evidence)
        for market in preview["markets"]:
            market["gaps"].extend(quote_gaps.get(market["market"], []))
        output = format_preview(preview)
        if command == "update":
            output = output.replace("Portfolio sync preview — dry run", "Portfolio sync — pre-update preview").replace("Live reads: enabled (read-only) | Sheet writes: none", "Live data read; sheet update follows after validation")
        print(output)
        if command == "update":
            apply_updates(reader, spreadsheet_id, selections, sources, evidence)
        return 0
    finally:
        reader.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="portfolio.py",
                                     description="Portfolio tracker. Only update writes Sheets; other portfolio commands are read-only.")
    parser.add_argument("command", nargs="?", default="preview",
                        choices=["check", "login", "review", "preview", "update"],
                        help="check: Google connection; login: Kite login; review: quantities/cash; preview (default): read-only values; update: refresh Sheets.")
    args = parser.parse_args(argv)
    try:
        settings = read_json(SETTINGS)
        if args.command == "login":
            import kite
            previous = kite.SECRETS_PATH
            kite.SECRETS_PATH = local_path(settings.get("kite_credentials", "secrets/kite.yaml"), "kite_credentials")
            try:
                return kite._cmd_auth(argparse.Namespace())
            finally:
                kite.SECRETS_PATH = previous
        return run_live(settings, args.command)
    except ModuleNotFoundError as error:
        print(f"Portfolio: this Python environment is missing '{error.name}'.\n"
              f'Use the installed tracker environment:\n"{ROOT / ".venv" / "Scripts" / "python.exe"}" '
              f'"{Path(__file__).resolve()}" {args.command}', file=sys.stderr)
        return 1
    except (ValidationError, OSError) as error:
        print("Portfolio: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
