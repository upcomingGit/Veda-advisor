"""Portfolio regression checks. Test inputs are generated and cleaned locally."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import types
import unittest
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio as tracker

# Synthetic records are test data only; no example/template files are needed.
FIXTURES = json.loads(r'''{
  "kite-funds.example.json": {
    "source": "kite",
    "segment": "equity",
    "as_of": "2026-10-23T16:30:01+05:30",
    "margins": {
      "enabled": true,
      "available": {
        "cash": 25000,
        "live_balance": 25000,
        "collateral": 0
      }
    }
  },
  "kite-holdings.example.json": {
    "source": "kite",
    "as_of": "2026-10-23T16:30:00+05:30",
    "count": 1,
    "holdings": [
      {
        "exchange": "NSE",
        "tradingsymbol": "DEMOIND",
        "name": "Synthetic Indian Company",
        "isin": "INE000A01010",
        "product": "CNC",
        "quantity": 10,
        "t1_quantity": 0,
        "used_quantity": 0,
        "short_quantity": 0,
        "collateral_quantity": 0,
        "mtf": {
          "quantity": 0
        },
        "discrepancy": false,
        "average_price": 100,
        "last_price": 120
      }
    ]
  },
  "sheet-snapshot.example.json": {
    "schema_version": 1,
    "captured_at": "2026-10-23T16:29:00+05:30",
    "sheets": {
      "IN": {
        "complete": true,
        "sheet_id": 1,
        "title": "India Portfolio",
        "header_row": 10,
        "last_prepared_row": 110,
        "headers": [
          "Stock Name",
          "Exchange:Ticker",
          "Status",
          "Market Cap (₹ Crore)",
          "Sector",
          "Quantity",
          "Average Purchase Price (₹)",
          "Current Market Price (₹)",
          "Current Market Value (₹)",
          "Portfolio Weight (%)",
          "Unrealised Return (%)",
          "Current P/E",
          "My Thesis Conviction",
          "My Sell Condition",
          "My Action",
          "StockClarity Thesis Status",
          "StockClarity Signal",
          "Review Reason"
        ],
        "summary_cells": {
          "broker_cash": {
            "a1": "D5",
            "value": null
          }
        },
        "rows": [
          {
            "row": 11,
            "isin": "INE000A01010",
            "values": {
              "Stock Name": "Synthetic Indian Company",
              "Exchange:Ticker": "NSE:DEMOIND",
              "Status": "Invested",
              "Quantity": 8,
              "Average Purchase Price (₹)": 90,
              "Current Market Price (₹)": 112,
              "Current Market Value (₹)": "=F11*H11",
              "My Thesis Conviction": "High",
              "My Sell Condition": "Synthetic manual condition; preserve verbatim",
              "My Action": "Hold"
            }
          }
        ]
      },
      "US": {
        "complete": true,
        "sheet_id": 2,
        "title": "US Portfolio",
        "header_row": 10,
        "last_prepared_row": 110,
        "headers": [
          "Stock Name",
          "Exchange:Ticker",
          "Status",
          "Market Cap ($ Million)",
          "Sector",
          "Quantity",
          "Average Purchase Price ($)",
          "Current Market Price ($)",
          "Current Market Value ($)",
          "Portfolio Weight (%)",
          "Unrealised Return (%)",
          "Current P/E",
          "My Thesis Conviction",
          "My Sell Condition",
          "My Action",
          "StockClarity Thesis Status",
          "StockClarity Signal",
          "Review Reason"
        ],
        "summary_cells": {
          "broker_cash": {
            "a1": "D5",
            "value": null
          },
          "holdings_uploaded_on": {
            "a1": "P5",
            "value": "Not yet uploaded"
          }
        },
        "rows": [
          {
            "row": 11,
            "values": {
              "Stock Name": "Synthetic US Company",
              "Exchange:Ticker": "NASDAQ:DEMOUS",
              "Status": "Invested",
              "Quantity": 1,
              "Average Purchase Price ($)": 70,
              "Current Market Price ($)": 90,
              "My Thesis Conviction": "Medium",
              "My Sell Condition": "Synthetic manual condition; preserve verbatim",
              "My Action": "Hold"
            }
          }
        ]
      }
    }
  },
  "us-holdings.example.csv": "exchange_ticker,stock_name,quantity,average_purchase_price,holdings_as_of,current_price,price_as_of\nNASDAQ:DEMOUS,Synthetic US Company,2,80,2026-10-23,100,2026-10-23\nNYSE:DEMOFRAC,Synthetic Fractional Holding,0.5,250,2026-10-23,200,2026-10-23\n",
  "us-holdings.template.csv": "exchange_ticker,stock_name,quantity,average_purchase_price,holdings_as_of,current_price,price_as_of\n"
}''')


class FixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, value in FIXTURES.items():
            text = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value
            (self.root / name).write_text(text, encoding="utf-8")


def load_kite_json(path, *, funds_path=None, cash_field=None):
    return tracker.parse_kite_payload(tracker.read_json(path),
                                      funds=tracker.read_json(funds_path) if funds_path else None,
                                      cash_field=cash_field)


class PortfolioSyncTests(FixtureTests):
    def setUp(self) -> None:
        super().setUp()
        self.layout = tracker.read_json(self.root / "sheet-snapshot.example.json")
        self.us = tracker.load_us_csv(self.root / "us-holdings.example.csv",
                                   cash="500", cash_as_of="2026-10-23")

    def csv(self, text: str) -> Path:
        path = self.root / "holdings.csv"
        path.write_text(text, encoding="utf-8-sig")
        return path

    def json(self, value: dict, name: str = "input.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def preview(self, source=None, sheet=None):
        return tracker.preview_market(source or self.us, sheet or self.layout["sheets"]["US"])

    def test_fractional_shares_and_cash_inclusive_weights(self):
        result = self.preview()
        self.assertEqual(Decimal(result["equity_value"]), Decimal("300"))
        self.assertEqual(Decimal(result["portfolio_total"]), Decimal("800"))
        self.assertEqual(Decimal(result["positions"][0]["weight_pct"]), Decimal("25"))
        self.assertEqual(Decimal(result["positions"][1]["weight_pct"]), Decimal("12.5"))
        self.assertEqual(Decimal(result["cash_weight_pct"]), Decimal("62.5"))
        self.assertEqual(Decimal(result["positions"][1]["unrealised_return_pct"]), Decimal("-20"))

    def test_zero_cash_is_distinct_from_missing_cash(self):
        zero = self.preview(replace(self.us, cash=Decimal(0)))
        missing = self.preview(replace(self.us, cash=None, cash_as_of=None))
        self.assertEqual(Decimal(zero["portfolio_total"]), Decimal("300"))
        self.assertEqual(Decimal(zero["cash_weight_pct"]), 0)
        self.assertIsNone(missing["portfolio_total"])
        self.assertTrue(all(p["weight_pct"] is None for p in missing["positions"]))
        self.assertFalse(any(u["field"] == "broker_cash" for u in missing["proposed_summary_updates"]))

    def test_missing_one_price_blocks_all_weights(self):
        holdings = (self.us.holdings[0], replace(self.us.holdings[1], current_price=None, price_as_of=None))
        result = self.preview(replace(self.us, holdings=holdings))
        self.assertIsNone(result["equity_value"])
        self.assertIsNone(result["portfolio_total"])
        self.assertTrue(all(p["weight_pct"] is None for p in result["positions"]))

    def test_zero_cost_has_no_fabricated_return(self):
        source = replace(self.us, holdings=(replace(self.us.holdings[0], average_price=Decimal(0)),))
        result = self.preview(source)
        self.assertIsNone(result["positions"][0]["unrealised_return_pct"])
        self.assertIn("zero", " ".join(result["positions"][0]["review"]))

    def test_reordered_columns_and_extra_notes_map_by_header(self):
        sheet = copy.deepcopy(self.layout["sheets"]["US"])
        sheet["headers"].insert(0, "Personal Notes")
        sheet["headers"].remove("Quantity")
        sheet["headers"].append("Quantity")
        sheet["rows"][0]["values"]["Personal Notes"] = "Keep this private note"
        before = copy.deepcopy(sheet)
        result = self.preview(sheet=sheet)
        qty = next(u for u in result["proposed_updates"] if u["header"] == "Quantity" and u["row"] == 11)
        self.assertEqual((qty["column"], qty["a1"]), (19, "S11"))
        self.assertEqual((qty["previous_value"], qty["value"]), (1, "2"))
        self.assertEqual(sheet, before)
        self.assertFalse(any(u["header"] == "Personal Notes" for u in result["proposed_updates"]))

    def test_manual_computed_and_monitoring_cells_are_never_proposed(self):
        result = self.preview()
        allowed = {"Stock Name", "Exchange:Ticker", "Quantity", "Average Purchase Price ($)", "Current Market Price ($)"}
        self.assertTrue(all(u["header"] in allowed for u in result["proposed_updates"]))
        self.assertTrue(any("manual Status" in reason for reason in result["positions"][1]["review"]))
        self.assertEqual(self.layout["sheets"]["US"]["rows"][0]["values"]["My Action"], "Hold")

    def test_reserved_manual_row_is_not_overwritten(self):
        sheet = self.layout["sheets"]["US"]
        sheet["rows"].append({"row": 12, "values": {"My Action": "Hold"}})
        result = self.preview()
        self.assertEqual(result["positions"][1]["sheet_row"], 13)

    def test_missing_existing_holding_is_retained_and_blocks_denominator(self):
        sheet = self.layout["sheets"]["US"]
        sheet["rows"].append({"row": 14, "values": {"Exchange:Ticker": "NYSE:OTHER", "Status": "Invested", "Quantity": 3}})
        result = self.preview()
        self.assertEqual(result["unresolved_existing_holdings"], ["NYSE:OTHER"])
        self.assertIsNone(result["portfolio_total"])
        self.assertFalse(any(u["row"] == 14 for u in result["proposed_updates"]))

    def test_update_includes_us_only_after_explicit_confirmation(self):
        india = tracker.PortfolioInput("IN", (), "2026-10-23", "Zerodha + Coin", Decimal(500), "2026-10-23")
        settings = {"spreadsheet_id": "test", "google_credentials": "key.json", "us_holdings": "sheet"}
        for answer, included in (("yes", True), (" Y ", True), ("no", False), ("", False), ("maybe", False), (EOFError(), False), (OSError(), False)):
            with self.subTest(answer=answer), contextlib.ExitStack() as stack:
                prompt = stack.enter_context(patch("builtins.input", **({"side_effect": answer} if isinstance(answer, Exception) else {"return_value": answer})))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                stack.enter_context(patch.object(tracker, "GoogleSheets"))
                capture = stack.enter_context(patch.object(tracker, "capture_google", return_value=self.layout))
                load_us = stack.enter_context(patch.object(tracker, "load_us_sheet", return_value=self.us))
                stack.enter_context(patch.object(tracker, "kite_client"))
                stack.enter_context(patch.object(tracker, "read_kite", return_value=({}, {})))
                stack.enter_context(patch.object(tracker, "kite_reconciliation", return_value={}))
                stack.enter_context(patch.object(tracker, "parse_kite_payload", return_value=india))
                stack.enter_context(patch.object(tracker, "add_mutual_funds", side_effect=lambda s, *a: s))
                stack.enter_context(patch.object(tracker, "add_market_quotes", side_effect=lambda s, **kw: (s, [])))
                stack.enter_context(patch.object(tracker, "add_fundamentals", side_effect=lambda s, *a, **kw: (s, [])))
                stack.enter_context(patch.object(tracker, "read_stockclarity", return_value=[]))
                stack.enter_context(patch.object(tracker, "add_stockclarity", side_effect=lambda s, *a, **kw: (s, [])))
                write = stack.enter_context(patch.object(tracker, "apply_updates"))
                self.assertEqual(tracker.run_live(settings, "update"), 0)
                prompt.assert_called_once()
                markets = [s.market for s in write.call_args.args[3]]
                self.assertEqual(markets, ["IN", "US"] if included else ["IN"])
                self.assertEqual("US" in capture.call_args.args[2], included)
                self.assertEqual(load_us.called, included)
                self.assertEqual(settings["us_holdings"], "sheet")

    def test_missing_watchlist_does_not_block_denominator(self):
        self.layout["sheets"]["US"]["rows"].append({"row": 14, "values": {"Exchange:Ticker": "NYSE:WATCH", "Status": "Watchlist", "Quantity": 0}})
        result = self.preview()
        self.assertEqual(result["unresolved_existing_holdings"], [])
        self.assertIsNotNone(result["portfolio_total"])

    def test_zerodha_authority_exits_absent_holdings_and_preserves_decisions(self):
        sheet = self.layout["sheets"]["IN"]
        sheet["rows"].append({"row": 14, "values": {
            "Exchange:Ticker": "NSE:SOLD", "Status": "Invested", "Quantity": 3,
            "My Action": "Hold", "My Thesis Conviction": "High"}})
        sheet["rows"][0]["values"]["Status"] = "Exited"
        source = tracker.PortfolioInput("IN", (
            tracker.Holding("NSE:DEMOIND", "Demo", Decimal(10), Decimal(100), Decimal(120), "2026-10-23"),
        ), "2026-10-23", "Zerodha + Coin", Decimal(500), "2026-10-23")
        result = tracker.preview_market(source, sheet)
        changes = {(u["row"], u["header"]): u["value"] for u in result["proposed_updates"]}
        self.assertEqual(changes[(14, "Quantity")], "0")
        self.assertEqual(changes[(14, "Status")], "Exited")
        self.assertEqual(changes[(11, "Status")], "Invested")
        self.assertEqual(result["portfolio_total"], "1700")
        self.assertEqual(result["unresolved_existing_holdings"], [])
        self.assertFalse(any(u["header"] in {"My Action", "My Thesis Conviction"} for u in result["proposed_updates"]))

    def test_validated_empty_zerodha_portfolio_exits_holdings_and_keeps_cash(self):
        source = tracker.PortfolioInput("IN", (), "2026-10-23", "Zerodha + Coin",
                                        Decimal(500), "2026-10-23")
        result = tracker.preview_market(source, self.layout["sheets"]["IN"])
        self.assertEqual(result["portfolio_total"], "500")
        self.assertTrue(any(u["header"] == "Quantity" and u["value"] == "0" for u in result["proposed_updates"]))

    def test_empty_coin_response_still_confirms_authoritative_broker_source(self):
        client = Mock()
        client.mf_holdings.return_value = []
        source = tracker.PortfolioInput("IN", (), "2026-10-23", "kite_live")
        self.assertEqual(tracker.add_mutual_funds(source, client, {}).source, "Zerodha + Coin")

    def test_source_formula_is_preserved_by_rejecting_replacement(self):
        self.layout["sheets"]["US"]["rows"][0]["values"]["Current Market Price ($)"] = '=GOOGLEFINANCE("NASDAQ:DEMOUS")'
        with self.assertRaisesRegex(tracker.ValidationError, "contains a formula"):
            self.preview()

    def test_review_reason_remains_manual_and_is_not_updated(self):
        self.layout["sheets"]["US"]["rows"][0]["values"]["Review Reason"] = "My note"
        changes = self.preview()["proposed_updates"]
        self.assertIn("review_reason", tracker.MANUAL_FIELDS)
        self.assertNotIn("review_reason", tracker.DERIVED_FIELDS)
        self.assertFalse(any(u["header"] == "Review Reason" for u in changes))

    def test_zero_quantity_invested_status_stops_before_any_write(self):
        source = replace(self.us, holdings=(replace(self.us.holdings[0], quantity=Decimal("0.0")), self.us.holdings[1]))
        self.layout["sheets"]["US"]["rows"][0]["values"]["Status"] = "Invested"
        reader = Mock()
        with self.assertRaisesRegex(tracker.ValidationError, "zero-quantity"):
            tracker.update_requests(reader, "test", self.layout["sheets"]["US"], source, {})
        reader.batch_update.assert_not_called()

    def test_table_expansion_copies_only_three_calculation_formulas(self):
        sheet = copy.deepcopy(self.layout["sheets"]["US"])
        mapping = tracker.mapped_headers(sheet["headers"], tracker.sheet_headers("US"))
        values = {sheet["headers"][mapping["ticker"]]: self.us.holdings[0].ticker}
        values.update({sheet["headers"][mapping[field]]: "=1" for field in tracker.DERIVED_FIELDS})
        sheet.update(rows=[{"row": 11, "values": values}], last_prepared_row=11, table_id="1",
                     native={"properties": {"gridProperties": {"rowCount": 100, "columnCount": 19}}, "tables": []})
        reader = Mock()
        reader.get.return_value = {"sheets": [{"properties": {"sheetId": sheet["sheet_id"]}}]}
        evidence = {h.ticker: {"instrument_type": "EQUITY"} for h in self.us.holdings}
        with patch.object(tracker, "label_cell", return_value=(2, 2, {})):
            requests, expanded, plan = tracker.update_requests(reader, "test", sheet, self.us, evidence)
        copies = [r["copyPaste"] for r in requests if r.get("copyPaste", {}).get("pasteType") == "PASTE_FORMULA"]
        self.assertEqual(len(copies), 3)
        self.assertNotIn(mapping["review_reason"], {r["source"]["startColumnIndex"] for r in copies})
        self.assertEqual(expanded["last_prepared_row"], 12)

    def research_record(self, **changes):
        return {"company_id": 1, "nse_symbol": "DEMOIND", "bse_code": None, "us_ticker": None,
                "snapshot_date": "2026-10-23", "thesis_status": "STRONG", "decision_signal": "Buy", **changes}

    def india_source(self):
        return load_kite_json(self.root / "kite-holdings.example.json", funds_path=self.root / "kite-funds.example.json", cash_field="available.cash")

    def test_stockclarity_copies_saved_signal_without_recomputing(self):
        evidence = {}
        result, gaps = tracker.add_stockclarity(self.india_source(), [self.research_record(decision_signal="Sell")], evidence, today="2026-10-23")
        self.assertEqual(result.holdings[0].thesis_status, "STRONG")
        self.assertEqual(result.holdings[0].signal, "Sell")
        self.assertEqual(evidence["NSE:DEMOIND"]["research"]["as_of"], "2026-10-23")
        self.assertFalse(gaps)

    def test_stockclarity_bse_codes_and_nse_sme_segment(self):
        source = self.india_source()
        for ticker, record, codes in (("BSE:DEMOBSE", self.research_record(nse_symbol=None, bse_code="500001"), {"DEMOBSE": "500001"}),
                                      ("NSE:DEMOIND-SM", self.research_record(), {}),
                                      ("BSE:DEMOIND", self.research_record(), {})):
            with self.subTest(ticker=ticker):
                result, _ = tracker.add_stockclarity(replace(source, holdings=(replace(source.holdings[0], ticker=ticker),)), [record], {}, bse_codes=codes, today="2026-10-23")
                self.assertEqual(result.holdings[0].signal, "Buy")

    def test_stockclarity_uncovered_and_funds_do_not_imply_hold(self):
        source = self.india_source()
        fund = tracker.Holding("MF:INF000A01010", "Fund", Decimal(2), Decimal(10), asset_type="Mutual Fund")
        result, _ = tracker.add_stockclarity(replace(source, holdings=source.holdings + (fund,)), [], {}, today="2026-10-23")
        self.assertEqual(result.holdings[0].thesis_status, "Not covered")
        self.assertEqual(result.holdings[0].signal, "Not covered")
        self.assertEqual(result.holdings[1].signal, "Not applicable")

    def test_stockclarity_unavailable_invalid_future_and_missing_snapshot(self):
        for records, expected in ((None, "Unavailable"), ([self.research_record(snapshot_date=None)], "No snapshot"),
                                  ([self.research_record(snapshot_date="2026-10-24")], "Unavailable"),
                                  ([self.research_record(thesis_status="DEFAULT")], "Unavailable"),
                                  ([self.research_record(decision_signal="Maybe")], "Unavailable")):
            with self.subTest(expected=expected):
                result, gaps = tracker.add_stockclarity(self.india_source(), records, {}, today="2026-10-23")
                self.assertEqual(result.holdings[0].signal, expected)
                self.assertTrue(gaps)

    def test_stockclarity_old_snapshot_is_visibly_dated(self):
        result, _ = tracker.add_stockclarity(self.india_source(), [self.research_record(snapshot_date="2026-10-22")], {}, today="2026-10-23")
        self.assertEqual(result.holdings[0].thesis_status, "STRONG (2026-10-22)")
        self.assertEqual(result.holdings[0].signal, "Buy (2026-10-22)")

    def test_stockclarity_ambiguous_identifiers_never_choose_first(self):
        record = self.research_record()
        result, gaps = tracker.add_stockclarity(self.india_source(), [record, {**record, "company_id": 2}], {})
        self.assertEqual(result.holdings[0].signal, "Ambiguous match")
        self.assertTrue(gaps)

    def test_stockclarity_india_us_symbol_collision_is_not_matched(self):
        result, _ = tracker.add_stockclarity(self.india_source(), [self.research_record(nse_symbol=None, us_ticker="DEMOIND")], {})
        self.assertEqual(result.holdings[0].signal, "Not covered")
        us = replace(self.us, holdings=(replace(self.us.holdings[0], ticker="NASDAQ:DEMOIND"),))
        result, _ = tracker.add_stockclarity(us, [self.research_record(nse_symbol=None, us_ticker="DEMOIND")], {}, today="2026-10-23")
        self.assertEqual(result.holdings[0].signal, "Buy")

    def test_stockclarity_missing_signal_not_defaulted_to_hold(self):
        result, gaps = tracker.add_stockclarity(self.india_source(), [self.research_record(decision_signal=None)], {})
        self.assertTrue(result.holdings[0].signal.startswith("Unavailable"))
        self.assertTrue(gaps)

    def test_stockclarity_only_proposes_two_automatic_research_fields(self):
        source = replace(self.us, holdings=(replace(self.us.holdings[0], thesis_status="STRONG", signal="Sell"),))
        fields = {u["header"] for u in self.preview(source)["proposed_updates"]}
        self.assertTrue({"StockClarity Thesis Status", "StockClarity Signal"} <= fields)
        self.assertFalse(fields & {"Sector", "My Thesis Conviction", "My Sell Condition", "My Action", "Status"})

    def test_stockclarity_db_connection_is_read_only_and_closed(self):
        import psycopg2
        (self.root / ".env").write_text("DB_NAME=test_db\n", encoding="utf-8")
        connection = Mock()
        cursor = connection.cursor.return_value.__enter__ = Mock(return_value=Mock())
        connection.cursor.return_value.__exit__ = Mock(return_value=False)
        cursor.return_value.fetchall.return_value = [self.research_record()]
        with patch.object(psycopg2, "connect", return_value=connection):
            rows = tracker.read_stockclarity(self.root)
        self.assertEqual(rows[0]["decision_signal"], "Buy")
        connection.set_session.assert_called_once_with(readonly=True, autocommit=False)
        connection.close.assert_called_once()
        query = cursor.return_value.execute.call_args_list[-1].args[0]
        self.assertIn("thesis_snapshots", query)
        self.assertNotIn("c.thesis_status", query)

    def test_fundamentals_uses_exact_bse_instrument_code_fallback(self):
        source = load_kite_json(self.root / "kite-holdings.example.json")
        source = replace(source, holdings=(replace(source.holdings[0], ticker="BSE:DEMO"),))
        client = Mock()
        client.instruments.return_value = [{"tradingsymbol": "DEMO", "exchange_token": "500001"}]
        calls = []
        def fetch(url):
            calls.append(url)
            return (200, '<li>Market Cap <span class="number">100</span> Cr.</li><li>Stock P/E <span class="number">10</span></li>') if '/500001/' in url else (404, '')
        result, gaps = tracker.add_fundamentals(source, {}, fetch, client=client)
        self.assertEqual(result.holdings[0].market_cap, Decimal(100))
        self.assertEqual(result.holdings[0].pe, Decimal(10))
        self.assertFalse(gaps)
        client.instruments.assert_called_once_with("BSE")

    def test_mutual_funds_are_never_sent_to_yahoo(self):
        fund = tracker.Holding("MF:INF000A01010", "Demo", Decimal("1.5"), Decimal(80), Decimal(100), "2026-10-22", "INF000A01010", "Mutual Fund")
        source = replace(self.us, market="IN", holdings=(fund,))
        fetcher = Mock(side_effect=AssertionError("MF must not go to Yahoo"))
        result, gaps = tracker.add_market_quotes(source, fetcher)
        self.assertEqual(result.holdings, (fund,))
        self.assertFalse(gaps)
        fetcher.assert_not_called()

    def test_amfi_accepts_both_file_layouts_and_exact_isin(self):
        text = "1;INF000A01010;-;Demo;43.5315;22-Oct-2026\n2;INF000B01010;-;Demo;Direct;Growth;20.1234;22-Oct-2026"
        values = tracker.parse_amfi_navs(text)
        self.assertEqual(values["INF000A01010"], (Decimal("43.5315"), "2026-10-22"))
        self.assertEqual(values["INF000B01010"][0], Decimal("20.1234"))
        self.assertEqual(set(tracker.parse_amfi_navs(text, {"INF000B01010"})), {"INF000B01010"})

    def test_amfi_conflicting_held_isin_stops(self):
        text = "1;INF000A01010;-;Demo;43;22-Oct-2026\n2;INF000A01010;-;Demo;44;22-Oct-2026"
        with self.assertRaisesRegex(tracker.ValidationError, "Conflicting"):
            tracker.parse_amfi_navs(text)

    def test_coin_fractional_units_use_amfi_nav_and_combined_weight(self):
        client = Mock()
        client.mf_holdings.return_value = [{"tradingsymbol": "INF000A01010", "fund": "Demo Fund", "quantity": "2.5", "average_price": "80", "last_price_date": "", "last_price": 1}]
        # Use India fixture with complete stock prices, plus a dated fund NAV.
        india = load_kite_json(self.root / "kite-holdings.example.json", funds_path=self.root / "kite-funds.example.json", cash_field="available.cash")
        india = replace(india, holdings=tuple(replace(h, current_price=Decimal(120), price_as_of="2026-10-22") for h in india.holdings))
        evidence = {}
        result = tracker.add_mutual_funds(india, client, evidence, nav_text="1;INF000A01010;-;Demo;100;22-Oct-2026")
        self.assertEqual(result.holdings[-1].quantity, Decimal("2.5"))
        self.assertEqual(result.holdings[-1].current_price, Decimal(100))
        self.assertEqual(result.holdings[-1].price_as_of, "2026-10-22")
        preview = tracker.preview_market(result, self.layout["sheets"]["IN"])
        self.assertEqual(Decimal(preview["portfolio_total"]), Decimal(26450))
        self.assertEqual(evidence["MF:INF000A01010"]["instrument_type"], "MUTUALFUND")

    def test_missing_amfi_nav_stops_before_sheet_writes(self):
        client = Mock()
        client.mf_holdings.return_value = [{"tradingsymbol": "INF000A01010", "quantity": 2, "average_price": 10}]
        with self.assertRaisesRegex(tracker.ValidationError, "no exact-ISIN"):
            tracker.add_mutual_funds(self.us, client, {}, nav_text="")

    def test_screener_parses_crore_cap_and_pe(self):
        text = '<li><span>Market Cap</span><span class="number">24,840</span> Cr.</li><li><span>Stock P/E</span><span class="number">52.7</span></li>'
        self.assertEqual(tracker.parse_fundamentals(text), {"market_cap": Decimal(24840), "pe": Decimal("52.7")})
        self.assertEqual(tracker.parse_fundamentals('<li>Market Cap <span class="number">10</span> Million</li>'), {"market_cap": None, "pe": None})

    def test_fundamentals_updates_never_include_manual_sector(self):
        source = replace(self.us, holdings=(replace(self.us.holdings[0], market_cap=Decimal(100), pe=Decimal(15)),))
        self.layout["sheets"]["US"]["rows"][0]["values"]["Sector"] = "My classification"
        changes = self.preview(source)["proposed_updates"]
        self.assertEqual({u["header"] for u in changes} & {"Sector"}, set())
        self.assertTrue(any(u["header"] == "Current P/E" for u in changes))
        self.assertTrue(any(u["header"].startswith("Market Cap") for u in changes))

    def test_fundamentals_missing_keeps_existing_cells(self):
        source = replace(self.us, holdings=(self.us.holdings[0],))
        changes = self.preview(source)["proposed_updates"]
        self.assertFalse(any(u["header"] == "Current P/E" or u["header"].startswith("Market Cap") for u in changes))

    def test_existing_stock_name_is_preserved(self):
        result = self.preview(replace(self.us, holdings=(replace(self.us.holdings[0], stock_name="Provider name"),)))
        self.assertFalse(any(u["header"] == "Stock Name" for u in result["proposed_updates"]))

    def test_cell_request_preserves_format_and_validation(self):
        request = tracker.cell_request(7, 10, 2, {"stringValue": "=literal"})["updateCells"]
        self.assertEqual(request["fields"], "userEnteredValue")
        self.assertEqual(request["range"]["sheetId"], 7)
        self.assertEqual(request["rows"][0]["values"][0], {"userEnteredValue": {"stringValue": "=literal"}})

    def test_update_refuses_missing_equity_evidence_before_writes(self):
        reader = Mock()
        with self.assertRaisesRegex(tracker.ValidationError, "instrument type"):
            tracker.update_requests(reader, "test", self.layout["sheets"]["US"], self.us, {})
        reader.batch_update.assert_not_called()

    def test_update_refuses_incomplete_prices_before_writes(self):
        reader = Mock()
        source = replace(self.us, holdings=(replace(self.us.holdings[0], current_price=None, price_as_of=None),))
        with self.assertRaisesRegex(tracker.ValidationError, "complete dated price"):
            tracker.update_requests(reader, "test", self.layout["sheets"]["US"], source, {})
        reader.batch_update.assert_not_called()

    def test_sync_metadata_preserves_identity(self):
        note = 'User note\n[Portfolio sync]\n{"isins":{"NSE:DEMO":"INE000A01010"}}\n[/Portfolio sync]'
        self.assertEqual(tracker.sync_metadata(note)["isins"]["NSE:DEMO"], "INE000A01010")
        self.assertEqual(tracker.sync_metadata("User note"), {})

    def test_literal_string_is_not_encoded_as_formula(self):
        self.layout["sheets"]["US"]["rows"][0]["values"]["Stock Name"] = ""
        source = replace(self.us, holdings=(replace(self.us.holdings[0], stock_name="=not_a_formula"),))
        result = self.preview(source)
        name = next(u for u in result["proposed_updates"] if u["header"] == "Stock Name")
        self.assertEqual(name["cell_value"], {"stringValue": "=not_a_formula"})

    def test_partial_snapshot_duplicate_headers_and_aliases_fail(self):
        for change in ("partial", "duplicate", "alias", "missing"):
            with self.subTest(change=change):
                sheet = copy.deepcopy(self.layout["sheets"]["US"])
                if change == "partial":
                    sheet["complete"] = False
                elif change == "duplicate":
                    sheet["headers"].append(" QUANTITY ")
                elif change == "alias":
                    sheet["headers"].append("Ticker")
                else:
                    sheet["headers"].remove("My Action")
                with self.assertRaises(tracker.ValidationError):
                    self.preview(sheet=sheet)

    def test_duplicate_sheet_security_and_missing_identity_fail(self):
        for values in ({"Exchange:Ticker": "NASDAQ:DEMOUS"}, {"Quantity": 5}, {"Status": "Invested"}):
            sheet = copy.deepcopy(self.layout["sheets"]["US"])
            sheet["rows"].append({"row": 12, "values": values})
            with self.assertRaises(tracker.ValidationError):
                self.preview(sheet=sheet)

    def test_no_space_requires_expansion_instead_of_out_of_table_updates(self):
        self.layout["sheets"]["US"]["last_prepared_row"] = 11
        result = self.preview()
        self.assertEqual(result["additional_rows_needed"], 1)
        self.assertEqual(len(result["positions"]), 2)
        self.assertIsNone(result["positions"][1]["sheet_row"])
        self.assertEqual(Decimal(result["portfolio_total"]), Decimal(800))
        self.assertTrue(all(update["row"] <= 11 for update in result["proposed_updates"]))
        self.assertTrue(any("Table expansion" in gap for gap in result["gaps"]))

    def test_summary_targets_cannot_overwrite_table_or_formulas(self):
        for entry in ({"a1": "O11", "value": "Hold"}, {"a1": "G5", "value": "=SUM(1,2)"}):
            sheet = copy.deepcopy(self.layout["sheets"]["US"])
            sheet["summary_cells"]["broker_cash"] = entry
            with self.assertRaises(tracker.ValidationError):
                self.preview(sheet=sheet)

    def test_csv_requires_qualified_ticker_and_single_snapshot_date(self):
        header = "exchange_ticker,quantity,average_purchase_price,holdings_as_of\n"
        for body in ("DEMOUS,2,80,2026-10-23\n", "NSE:DEMOUS,2,80,2026-10-23\n",
                     "NASDAQ:ONE,1,10,2026-10-22\nNYSE:TWO,2,20,2026-10-23\n"):
            with self.subTest(body=body):
                with self.assertRaises(tracker.ValidationError):
                    tracker.load_us_csv(self.csv(header + body))

    def test_csv_duplicates_bad_numbers_and_truncated_rows_fail(self):
        header = "exchange_ticker,quantity,average_purchase_price,holdings_as_of\n"
        bodies = ["NASDAQ:ONE,1,10,2026-10-23\nNASDAQ:ONE,2,20,2026-10-23\n",
                  "NASDAQ:ONE,1,10\n"]
        bodies += [f"NASDAQ:ONE,{q},10,2026-10-23\n" for q in ("NaN", "Infinity", "-1", "", "1e999", "1e-999")]
        for body in bodies:
            with self.subTest(body=body):
                with self.assertRaises(tracker.ValidationError):
                    tracker.load_us_csv(self.csv(header + body))

    def test_csv_price_requires_its_own_date(self):
        path = self.csv("exchange_ticker,quantity,average_purchase_price,holdings_as_of,current_price,price_as_of\nNASDAQ:ONE,1,10,2026-10-23,20,\n")
        with self.assertRaisesRegex(tracker.ValidationError, "supplied together"):
            tracker.load_us_csv(path)

    def test_cash_requires_date_and_missing_is_not_defaulted(self):
        path = self.root / "us-holdings.example.csv"
        with self.assertRaises(tracker.ValidationError):
            tracker.load_us_csv(path, cash="0")
        self.assertIsNone(tracker.load_us_csv(path).cash)

    def test_empty_csv_requires_explicit_date_and_never_proposes_deletions(self):
        path = self.root / "us-holdings.template.csv"
        with self.assertRaises(tracker.ValidationError):
            tracker.load_us_csv(path)
        source = tracker.load_us_csv(path, holdings_as_of="2026-10-23")
        result = self.preview(source)
        self.assertEqual(result["proposed_updates"], [])
        self.assertIn("NASDAQ:DEMOUS", result["retained_unmatched_tickers"])

    def test_saved_kite_helper_output_preserves_price_provenance(self):
        source = load_kite_json(self.root / "kite-holdings.example.json")
        self.assertEqual(source.holdings[0].quantity, Decimal(10))
        self.assertIsNone(source.holdings[0].current_price)
        self.assertIsNone(source.cash)

    def test_kite_pending_sold_pledged_short_mtf_and_fractional_fail(self):
        original = tracker.read_json(self.root / "kite-holdings.example.json")
        changes = [{field: 1} for field in ("t1_quantity", "used_quantity", "short_quantity", "collateral_quantity")]
        changes += [{"mtf": {"quantity": 1}}, {"quantity": 0.5}, {"discrepancy": True}, {"product": "MIS"}]
        for changed in changes:
            with self.subTest(changed=changed):
                value = copy.deepcopy(original)
                value["holdings"][0].update(changed)
                with self.assertRaises(tracker.ValidationError):
                    load_kite_json(self.json(value))

    def test_kite_count_timezone_and_duplicate_isin_fail(self):
        original = tracker.read_json(self.root / "kite-holdings.example.json")
        for change in ("count", "timezone", "isin"):
            value = copy.deepcopy(original)
            if change == "count":
                value["count"] = 99
            elif change == "timezone":
                value["as_of"] = "2026-10-23T16:30:00"
            else:
                value["holdings"].append({**value["holdings"][0], "tradingsymbol": "OTHER"})
                value["count"] = 2
            with self.assertRaises(tracker.ValidationError):
                load_kite_json(self.json(value))

    def test_executed_sale_keeps_already_reduced_remaining_quantity(self):
        value = tracker.read_json(self.root / "kite-holdings.example.json")
        value["holdings"][0].update(quantity=60, opening_quantity=100, used_quantity=40, realised_quantity=0)
        source = tracker.parse_kite_payload(value)
        self.assertEqual(source.holdings[0].quantity, Decimal(60))

    def test_unreconciled_sale_is_not_subtracted_or_imported(self):
        for opening in (None, 99, 20):
            value = tracker.read_json(self.root / "kite-holdings.example.json")
            value["holdings"][0].update(quantity=60, opening_quantity=opening, used_quantity=40)
            with self.subTest(opening=opening), self.assertRaises(tracker.ValidationError):
                tracker.parse_kite_payload(value)

    def test_kite_cash_policy_is_explicit_and_never_uses_collateral(self):
        holdings = self.root / "kite-holdings.example.json"
        funds = self.root / "kite-funds.example.json"
        with self.assertRaises(tracker.ValidationError):
            load_kite_json(holdings, funds_path=funds)
        for invalid in ("net", "available.collateral"):
            with self.assertRaises(tracker.ValidationError):
                load_kite_json(holdings, funds_path=funds, cash_field=invalid)
        source = load_kite_json(holdings, funds_path=funds, cash_field="available.live_balance")
        self.assertEqual(source.cash, Decimal(25000))

    def test_isin_can_match_ticker_change_without_duplicate_append(self):
        source = load_kite_json(self.root / "kite-holdings.example.json")
        source = replace(source, holdings=(replace(source.holdings[0], ticker="NSE:RENAMED"),))
        result = tracker.preview_market(source, self.layout["sheets"]["IN"])
        self.assertEqual(result["positions"][0]["sheet_row"], 11)
        self.assertEqual(result["retained_unmatched_tickers"], [])

    def test_market_cash_and_updates_do_not_cross_tables(self):
        india = load_kite_json(self.root / "kite-holdings.example.json")
        result = tracker.build_preview(self.layout, [india, self.us])
        self.assertIsNone(result["markets"][0]["cash"])
        self.assertEqual(result["markets"][1]["cash"], "500")
        self.assertEqual([m["sheet_id"] for m in result["markets"]], [1, 2])

    def test_two_markets_cannot_target_one_sheet(self):
        india = load_kite_json(self.root / "kite-holdings.example.json")
        self.layout["sheets"]["US"]["sheet_id"] = 1
        with self.assertRaisesRegex(tracker.ValidationError, "different sheet IDs"):
            tracker.build_preview(self.layout, [india, self.us])

    def test_zero_quantity_requests_status_review_but_does_not_change_status(self):
        source = replace(self.us, holdings=(replace(self.us.holdings[0], quantity=Decimal(0)),))
        result = self.preview(source)
        self.assertTrue(any("quantity is zero" in reason for reason in result["positions"][0]["review"]))
        self.assertFalse(any(u["header"] == "Status" for u in result["proposed_updates"]))

    def test_wrong_market_header_units_fail(self):
        with self.assertRaisesRegex(tracker.ValidationError, "missing required headers"):
            self.preview(sheet=self.layout["sheets"]["IN"])

    def test_csv_duplicate_aliases_and_invalid_date_fail(self):
        for content in (
            "exchange_ticker,ticker,quantity,average_purchase_price,holdings_as_of\nNASDAQ:ONE,NASDAQ:ONE,1,10,2026-10-23\n",
            "exchange_ticker,quantity,average_purchase_price,holdings_as_of\nNASDAQ:ONE,1,10,2026-02-30\n",
        ):
            with self.assertRaises(tracker.ValidationError):
                tracker.load_us_csv(self.csv(content))

    def test_calculation_has_no_network_auth_or_file_writes(self):
        output = io.StringIO()
        with patch("socket.socket", side_effect=AssertionError("Unexpected network access")), \
             patch("webbrowser.open", side_effect=AssertionError("Unexpected auth browser")), \
             patch.object(Path, "write_text", side_effect=AssertionError("Unexpected file write")), \
             contextlib.redirect_stdout(output):
            result = tracker.build_preview(self.layout, [load_kite_json(self.root / "kite-holdings.example.json"), self.us])
        self.assertFalse(result["sheet_writes"])
        self.assertFalse(result["live_reads"])
        self.assertEqual(len(result["markets"]), 2)

    def test_cli_rejects_unrecognised_commands_and_write_flags(self):
        for args in (["unknown"], ["preview", "--apply"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                tracker.main(args)
            self.assertEqual(caught.exception.code, 2)

    def test_cli_missing_settings_fails_without_authentication(self):
        output = io.StringIO()
        with patch.object(tracker, "SETTINGS", self.root / "missing.json"), \
             patch.object(tracker, "kite_client", side_effect=AssertionError("Unexpected broker access")), \
             contextlib.redirect_stderr(output):
            status = tracker.main(["check"])
        self.assertEqual(status, 1)
        self.assertIn("Cannot read valid JSON", output.getvalue())

    def test_duplicate_json_keys_are_not_silently_discarded(self):
        path = self.root / "duplicate.json"
        path.write_text('{"cash": 1, "cash": 2}', encoding="utf-8")
        with self.assertRaisesRegex(tracker.ValidationError, "Duplicate JSON"):
            tracker.read_json(path)



def resource():
    sheets = []
    for market, height, sid in (("IN", 27, 1), ("US", 21, 2)):
        title, table = tracker.DEFAULT_SHEETS[market].values()
        headers = [names[0] for names in tracker.sheet_headers(market).values()]
        # Exercise a moved table and reordered columns, rather than template offsets.
        headers.reverse()
        rows = [{"values": []} for _ in range(height)]
        cur = "₹" if market == "IN" else "$"
        rows[3]["values"] = [{}, {}, {"userEnteredValue": {"stringValue": f"Broker Cash ({cur})"}}]
        if market == "US":
            rows[3]["values"] += [{}, {"userEnteredValue": {"stringValue": "Holdings Uploaded On"}}]
            rows[4]["values"] = [{}, {}, {}, {}, {"userEnteredValue": {"stringValue": "Not yet uploaded"}}]
        rows[9]["values"] = [{}] + [{"userEnteredValue": {"stringValue": h}} for h in headers]
        rows[10]["values"] = [{}] + [{"userEnteredValue": {"formulaValue": "=1+1"}}]
        sheets.append({"properties": {"title": title, "sheetId": sid,
                                      "gridProperties": {"rowCount": 917, "columnCount": 21}},
                       "tables": [{"name": table, "tableId": str(sid), "range": {
                           "sheetId": sid, "startRowIndex": 9, "endRowIndex": height,
                           "startColumnIndex": 1, "endColumnIndex": 19}}],
                       "data": [{"rowData": rows}]})
    return {"spreadsheetId": "test_workbook", "sheets": sheets}


class LiveTests(FixtureTests):
    def setUp(self):
        super().setUp()
        self.grid = resource()
        self.metadata = copy.deepcopy(self.grid)
        for sheet in self.metadata["sheets"]:
            del sheet["data"]
        self.us = tracker.load_us_csv(self.root / "us-holdings.example.csv", cash="500", cash_as_of="2026-10-23")
        self.india = load_kite_json(self.root / "kite-holdings.example.json")

    def snapshot(self):
        return tracker.make_snapshot(self.metadata, self.grid, tracker.DEFAULT_SHEETS, "2026-10-23T14:00:00+05:30")

    def test_capture_uses_current_native_table_sizes(self):
        self.assertEqual(tracker.capture_ranges(self.metadata, tracker.DEFAULT_SHEETS),
                         ["'India Portfolio'!A1:U27", "'US Portfolio'!A1:U21"])
        snapshot = self.snapshot()
        self.assertEqual(snapshot["sheets"]["IN"]["last_prepared_row"], 27)
        self.assertEqual(snapshot["sheets"]["US"]["last_prepared_row"], 21)
        self.assertEqual(snapshot["sheets"]["US"]["start_column"], 2)
        self.assertEqual(snapshot["sheets"]["US"]["summary_cells"]["broker_cash"], {"a1": "C5", "value": None})
        self.assertEqual(snapshot["sheets"]["US"]["rows"][0]["values"]["Current Market Value ($)"], "=1+1")

    def test_input_date_resolves_by_label_after_moving_to_p8(self):
        rows = self.grid["sheets"][1]["data"][0]["rowData"]
        rows[3]["values"][4] = {}
        rows[4]["values"][4] = {}
        rows[6]["values"] = [{} for _ in range(16)]
        rows[7]["values"] = [{} for _ in range(16)]
        rows[6]["values"][15] = {"userEnteredValue": {"stringValue": "Holdings & Cash As Of"}}
        rows[7]["values"][15] = {"userEnteredValue": {"numberValue": 46321}}
        captured = self.snapshot()["sheets"]["US"]["summary_cells"]["holdings_uploaded_on"]
        self.assertEqual(captured, {"a1": "P8", "value": 46321})

    def test_moved_headers_resolve_absolute_preview_cells(self):
        sheet = self.snapshot()["sheets"]["US"]
        preview = tracker.preview_market(self.us, sheet)
        ticker = next(u for u in preview["proposed_updates"] if u["header"] == "Exchange:Ticker")
        expected_col = sheet["headers"].index("Exchange:Ticker") + 2
        self.assertEqual(ticker["column"], expected_col)
        self.assertEqual(ticker["a1"], f"{tracker._column_letter(expected_col)}11")

    def test_note_only_row_is_reserved(self):
        self.grid["sheets"][1]["data"][0]["rowData"][10]["values"][1] = {"note": "Personal research"}
        snapshot = self.snapshot()
        row = snapshot["sheets"]["US"]["rows"][0]
        self.assertEqual(row["notes"], {"Current Market Value ($)": "Personal research"})
        preview = tracker.preview_market(self.us, snapshot["sheets"]["US"])
        self.assertEqual(preview["positions"][0]["sheet_row"], 12)

    def test_changed_layout_is_rejected(self):
        self.grid["sheets"][0]["tables"][0]["range"]["endRowIndex"] = 28
        with self.assertRaisesRegex(tracker.ValidationError, "changed during capture"):
            self.snapshot()

    def test_missing_or_ambiguous_summary_is_rejected(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                self.grid = resource()
                rows = self.grid["sheets"][0]["data"][0]["rowData"]
                rows[2]["values"] = copy.deepcopy(rows[3]["values"]) if duplicate else []
                if not duplicate:
                    rows[3]["values"] = []
                with self.assertRaisesRegex(tracker.ValidationError, "Expected one Broker Cash"):
                    self.snapshot()

    def test_partial_or_oversized_capture_is_rejected(self):
        del self.grid["sheets"][0]["data"]
        with self.assertRaisesRegex(tracker.ValidationError, "missing the requested table data"):
            self.snapshot()
        self.metadata["sheets"][0]["properties"]["gridProperties"]["columnCount"] = 2000
        with self.assertRaisesRegex(tracker.ValidationError, "50,000"):
            tracker.capture_ranges(self.metadata, tracker.DEFAULT_SHEETS)

    def test_google_reader_only_gets_fixed_endpoint_with_bounded_ranges(self):
        reader = tracker.GoogleSheets.__new__(tracker.GoogleSheets)
        reader._session = Mock()
        reader._session.get.return_value.status_code = 200
        reader._session.get.return_value.json.return_value = self.grid
        ranges = tracker.capture_ranges(self.metadata, tracker.DEFAULT_SHEETS)
        self.assertEqual(reader.get("test_workbook", ranges=ranges), self.grid)
        args, kwargs = reader._session.get.call_args
        self.assertEqual(args, (tracker.SHEETS_BASE + "test_workbook",))
        self.assertEqual([v for k, v in kwargs["params"] if k == "ranges"], ranges)
        self.assertEqual(reader._session.method_calls[0][0], "get")
        with self.assertRaises(tracker.ValidationError):
            reader.get("https://attacker.example/key")

    def test_google_failure_does_not_echo_provider_body(self):
        reader = tracker.GoogleSheets.__new__(tracker.GoogleSheets)
        reader._session = Mock()
        reader._session.get.return_value.status_code = 403
        reader._session.get.return_value.text = "sensitive provider response"
        with self.assertRaises(tracker.ValidationError) as failure:
            reader.get("test_workbook")
        self.assertNotIn("sensitive", str(failure.exception))

    def test_capture_makes_metadata_then_grid_reads(self):
        reader = Mock()
        reader.get.side_effect = [self.metadata, self.grid]
        tracker.capture_google(reader, "test_workbook", tracker.DEFAULT_SHEETS)
        self.assertEqual(reader.get.call_count, 2)
        self.assertEqual(reader.method_calls[0][0], "get")
        self.assertEqual(reader.method_calls[1][0], "get")

    def test_kite_helper_no_login_or_session_write(self):
        import kite
        previous = kite.SECRETS_PATH
        with patch.object(kite, "_authed_kite", return_value="existing session"), patch.object(kite, "_cmd_auth", side_effect=AssertionError("login")), patch.object(kite, "_save", side_effect=AssertionError("write")):
            self.assertEqual(tracker.kite_client(Path("alternative.yaml")), "existing session")
        self.assertEqual(kite.SECRETS_PATH, previous)
        with patch.object(kite, "_authed_kite", side_effect=SystemExit("sensitive detail")):
            with self.assertRaises(tracker.ValidationError) as failure:
                tracker.kite_client()
            self.assertNotIn("sensitive", str(failure.exception))

    def test_kite_reads_and_reconciliation_do_not_choose_cash_or_quantity_policy(self):
        holding = tracker.read_json(self.root / "kite-holdings.example.json")["holdings"][0]
        holding["t1_quantity"] = 2
        client = Mock()
        client.holdings.return_value = [holding]
        client.margins.return_value = {"available": {"cash": 100, "live_balance": 80, "collateral": 500}}
        holdings, funds = tracker.read_kite(client)
        report = tracker.kite_reconciliation(holdings, funds)
        self.assertEqual(report["holdings"][0]["t1_quantity"], 2)
        self.assertEqual(report["available"]["cash"], 100)
        self.assertEqual(report["available"]["live_balance"], 80)
        self.assertNotIn("cash", report)
        self.assertEqual([c[0] for c in client.method_calls], ["holdings", "margins"])
        with self.assertRaisesRegex(tracker.ValidationError, "reconcile broker quantity"):
            tracker.parse_kite_payload(holdings)

    def india_quotes(self, source=None):
        source = source or self.india
        epoch = datetime(2026, 10, 22, 10, tzinfo=timezone.utc).timestamp()
        quotes = []
        for holding in source.holdings:
            exchange, symbol = holding.ticker.split(":")
            symbol += ".NS" if exchange == "NSE" else ".BO"
            quotes.append({"input_ticker": symbol, "resolved_ticker": symbol, "last_close": 100,
                           "as_of": "2026-10-22", "currency": "INR", "currency_verified": True,
                           "provider_timestamp": epoch, "source": "yahoo-spark"})
        return {"quotes": quotes}

    def test_india_quotes_keep_exchange_identity_dates_and_quantities(self):
        first = self.india.holdings[0]
        source = replace(self.india, holdings=(first, replace(first, ticker="BSE:DEMOBSE", isin=None)))
        fetcher = Mock(return_value=self.india_quotes(source))
        evidence = {}
        with patch.object(tracker, "now_iso", return_value="2026-10-23T14:00:00+05:30"):
            priced, gaps = tracker.add_market_quotes(source, fetcher, evidence=evidence)
        self.assertFalse(gaps)
        fetcher.assert_called_once_with([first.ticker.split(":")[1] + ".NS", "DEMOBSE.BO"])
        self.assertEqual(priced.holdings[0].quantity, first.quantity)
        self.assertEqual(priced.holdings[0].price_as_of, "2026-10-22T10:00:00+00:00")
        self.assertEqual(evidence["BSE:DEMOBSE"]["currency"], "INR")

    def test_india_quotes_reject_wrong_currency_symbol_or_dates(self):
        for field, value in (("currency", "USD"), ("currency_verified", False),
                             ("resolved_ticker", "OTHER.NS"), ("provider_timestamp", 9999999999),
                             ("as_of", "2026-10-21")):
            with self.subTest(field=field):
                payload = self.india_quotes()
                payload["quotes"][0][field] = value
                result, gaps = tracker.add_market_quotes(self.india, lambda _: payload)
                self.assertIsNone(result.holdings[0].current_price)
                self.assertTrue(gaps)

    def test_price_request_failure_is_visible_and_preserves_holdings(self):
        source = replace(self.india, holdings=(replace(self.india.holdings[0], current_price=Decimal(100), price_as_of="2026-10-22"),))
        fetcher = Mock(side_effect=RuntimeError("private provider detail"))
        result, gaps = tracker.add_market_quotes(source, fetcher)
        self.assertEqual(result.holdings[0].quantity, source.holdings[0].quantity)
        self.assertIsNone(result.holdings[0].current_price)
        self.assertEqual(len(gaps), 1)
        self.assertIn("request failed", gaps[0])
        self.assertNotIn("private provider detail", gaps[0])

    def us_quotes(self):
        epoch = datetime(2026, 10, 22, 20, tzinfo=timezone.utc).timestamp()
        return {"quotes": [{"input_ticker": h.ticker.split(":")[1], "resolved_ticker": h.ticker.split(":")[1],
                            "last_close": 120, "as_of": "2026-10-22", "currency": "USD", "currency_verified": True,
                            "provider_timestamp": epoch, "source": "yahoo-spark", "instrument_type": "EQUITY"} for h in self.us.holdings]}

    def test_us_quotes_preserve_timestamp_and_fractional_quantities(self):
        with patch.object(tracker, "now_iso", return_value="2026-10-23T14:00:00+05:30"):
            result, gaps = tracker.add_market_quotes(self.us, lambda _: self.us_quotes())
        self.assertFalse(gaps)
        self.assertEqual(result.holdings[1].quantity, Decimal("0.5"))
        self.assertEqual(result.holdings[0].price_as_of, "2026-10-22T20:00:00+00:00")

    def test_us_etf_quote_is_classified_and_allowed_by_update(self):
        payload = self.us_quotes()
        payload["quotes"][0]["instrument_type"] = "ETF"
        evidence = {}
        source, gaps = tracker.add_market_quotes(self.us, lambda _: payload, evidence=evidence)
        self.assertFalse(gaps)
        self.assertEqual(source.holdings[0].asset_type, "ETF")
        self.assertEqual(evidence[source.holdings[0].ticker]["instrument_type"], "ETF")
        # The same guard used immediately before writes accepts the verified ETF.
        sheet = self.snapshot()["sheets"]["US"]
        with patch.object(tracker, "label_cell", side_effect=RuntimeError("past instrument check")):
            with self.assertRaisesRegex(RuntimeError, "past instrument check"):
                tracker.update_requests(Mock(), "test", sheet, source, evidence)

    def test_unrecognised_us_instrument_never_becomes_a_stock(self):
        payload = self.us_quotes()
        payload["quotes"][0]["instrument_type"] = "FUTURE"
        source, gaps = tracker.add_market_quotes(self.us, lambda _: payload)
        self.assertIsNone(source.holdings[0].current_price)
        self.assertTrue(gaps)

    def test_unverified_currency_wrong_identity_or_future_quotes_leave_gaps(self):
        for field, value in (("currency_verified", False), ("currency", "INR"), ("resolved_ticker", "OTHER"),
                             ("provider_timestamp", 9999999999), ("as_of", "2026-10-21")):
            with self.subTest(field=field):
                payload = self.us_quotes()
                payload["quotes"][0][field] = value
                result, gaps = tracker.add_market_quotes(self.us, lambda _: payload)
                self.assertIsNone(result.holdings[0].current_price)
                self.assertIsNone(result.holdings[0].price_as_of)
                self.assertTrue(gaps)

    def test_us_duplicate_bare_symbols_stop_before_fetch(self):
        h = self.us.holdings[0]
        source = replace(self.us, holdings=(h, replace(h, ticker="NYSE:" + h.ticker.split(":")[1])))
        fetcher = Mock()
        with self.assertRaisesRegex(tracker.ValidationError, "different exchanges"):
            tracker.add_market_quotes(source, fetcher)
        fetcher.assert_not_called()

    def test_bad_quote_payloads_fail_cleanly(self):
        for payload in ({"quotes": [None]}, {"quotes": [{"input_ticker": "UNKNOWN"}]}, {}):
            with self.subTest(payload=payload), self.assertRaises(tracker.ValidationError):
                tracker.add_market_quotes(self.us, lambda _: payload)

    def test_existing_us_fetcher_exposes_missing_currency_without_fabricating_evidence(self):
        import fetch_quote
        epoch = datetime(2026, 10, 22, 20, tzinfo=timezone.utc).timestamp()
        for currency in (None, "USD"):
            with self.subTest(currency=currency):
                meta = {"regularMarketPrice": 100, "regularMarketTime": epoch}
                if currency:
                    meta["currency"] = currency
                response = Mock()
                response.json.return_value = {"spark": {"result": [{"symbol": "DEMOUS", "response": [{"meta": meta}]}]}}
                requests = types.SimpleNamespace(get=Mock(return_value=response), RequestException=RuntimeError)
                with patch.dict(sys.modules, {"requests": requests}):
                    quote = fetch_quote._fetch_yahoo_batch(["DEMOUS"])["quotes"][0]
                self.assertEqual(quote["currency_verified"], currency is not None)
                self.assertEqual(quote["provider_timestamp"], epoch)

    def test_yahoo_splits_21_symbols_without_losing_order_or_currency(self):
        import fetch_quote
        symbols = [f"DEMO{i}.NS" for i in range(21)]
        epoch = datetime(2026, 10, 22, 10, tzinfo=timezone.utc).timestamp()
        def response(_url, *, params, **_kwargs):
            requested = params["symbols"].split(",")
            self.assertLessEqual(len(requested), 20)
            result = Mock()
            result.json.return_value = {"spark": {"result": [
                {"symbol": symbol, "response": [{"meta": {"regularMarketPrice": 100,
                  "regularMarketTime": epoch, "currency": "INR"}}]} for symbol in requested]}}
            return result
        requests = types.SimpleNamespace(get=Mock(side_effect=response), RequestException=RuntimeError)
        with patch.dict(sys.modules, {"requests": requests}):
            quotes = fetch_quote._fetch_yahoo_batch(symbols, market="india")["quotes"]
        self.assertEqual(requests.get.call_count, 2)
        self.assertEqual([q["input_ticker"] for q in quotes], symbols)
        self.assertTrue(all(q["currency"] == "INR" and q["currency_verified"] for q in quotes))

    def test_us_cash_without_date_stops_before_live_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "settings.json"
            config.write_text(json.dumps({"spreadsheet_id": "test_workbook", "google_credentials": "key.json", "us_holdings": str(self.root / "us-holdings.example.csv"), "us_cash": 0}))
            with patch.object(tracker, "SETTINGS", config), patch.object(tracker, "GoogleSheets", side_effect=AssertionError("Unexpected Google access")), patch.object(tracker, "kite_client", side_effect=AssertionError("Unexpected broker access")), contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(tracker.main(["preview"]), 1)
            self.assertIn("cash and its as-of date must be supplied together", output.getvalue())

    def test_cli_capture_never_contacts_broker_or_writes_sheet(self):
        snapshot = self.snapshot()
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "settings.json"
            config.write_text(json.dumps({"spreadsheet_id": "test_workbook", "google_credentials": "key.json"}))
            reader = Mock(spec=tracker.GoogleSheets)
            with patch.object(tracker, "SETTINGS", config), patch.object(tracker, "GoogleSheets", return_value=reader), patch.object(tracker, "capture_google", return_value=snapshot), patch.object(tracker, "kite_client", side_effect=AssertionError("broker")), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(tracker.main(["check"]), 0)
            self.assertFalse(json.loads(output.getvalue())["sheet_writes"])
            reader.close.assert_called_once()

    def test_cli_reconciliation_survives_unsettled_holdings(self):
        snapshot = self.snapshot()
        holdings = tracker.read_json(self.root / "kite-holdings.example.json")
        holdings["holdings"][0]["t1_quantity"] = 2
        funds = tracker.read_json(self.root / "kite-funds.example.json")
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "settings.json"
            config.write_text(json.dumps({"spreadsheet_id": "test_workbook", "google_credentials": "key.json"}))
            with patch.object(tracker, "SETTINGS", config), patch.object(tracker, "GoogleSheets"), patch.object(tracker, "capture_google", return_value=snapshot), patch.object(tracker, "kite_client"), patch.object(tracker, "read_kite", return_value=(holdings, funds)), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(tracker.main(["preview"]), 1)
            report = json.loads(output.getvalue())
            self.assertFalse(report["sheet_writes"])
            self.assertIn("reconcile broker quantity", report["preview_blocked"])
            self.assertEqual(report["kite_reconciliation"]["holdings"][0]["t1_quantity"], 2)

    def test_default_short_command_previews_prices_without_selecting_cash_or_logging_in(self):
        import kite
        import fetch_quote
        holdings = tracker.read_json(self.root / "kite-holdings.example.json")["holdings"]
        client = Mock()
        client.mf_holdings.return_value = []
        client.holdings.return_value = holdings
        client.margins.return_value = {"available": {"cash": 100, "live_balance": 80}}
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "settings.json"
            config.write_text(json.dumps({"spreadsheet_id": "test_workbook", "google_credentials": "key.json", "india_cash_field": None, "us_holdings": None}))
            with patch.object(tracker, "SETTINGS", config), patch.object(tracker, "GoogleSheets"), patch.object(tracker, "capture_google", return_value=self.snapshot()), patch.object(tracker, "kite_client", return_value=client), patch.object(tracker, "read_stockclarity", return_value=[]), patch.object(tracker, "add_fundamentals", side_effect=lambda src, evidence, **kwargs: (src, [])), patch.object(fetch_quote, "_fetch_yahoo_batch", return_value=self.india_quotes()), patch.object(kite, "_cmd_auth", side_effect=AssertionError("Unexpected login")), patch.object(kite, "_save", side_effect=AssertionError("Unexpected credentials write")), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(tracker.main([]), 0)
            text = output.getvalue()
            self.assertIn("India Portfolio", text)
            self.assertNotIn("US Portfolio", text)
            self.assertIn("Cash: MISSING", text)
            self.assertIn("Price as of: 2026-10-22", text)
            self.assertIn("Sheet writes: none", text)
            self.assertEqual([c[0] for c in client.method_calls], ["holdings", "margins", "mf_holdings"])

    def test_short_command_reads_configured_us_csv_and_preserves_confirmed_zero_cash(self):
        import fetch_quote
        holdings = tracker.read_json(self.root / "kite-holdings.example.json")["holdings"]
        client = Mock()
        client.mf_holdings.return_value = []
        client.holdings.return_value = holdings
        client.margins.return_value = {"available": {"live_balance": 80}}
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "settings.json"
            config.write_text(json.dumps({"spreadsheet_id": "test_workbook", "google_credentials": "key.json", "india_cash_field": "available.live_balance", "us_holdings": str(self.root / "us-holdings.example.csv"), "us_cash": 0, "us_cash_as_of": "2026-10-23"}))
            with patch.object(tracker, "SETTINGS", config), patch.object(tracker, "GoogleSheets"), patch.object(tracker, "capture_google", return_value=self.snapshot()), patch.object(tracker, "kite_client", return_value=client), patch.object(tracker, "read_stockclarity", return_value=[]), patch.object(tracker, "add_fundamentals", side_effect=lambda src, evidence, **kwargs: (src, [])), patch.object(fetch_quote, "_fetch_yahoo_batch", side_effect=lambda symbols, *, market: self.india_quotes() if market == "india" else self.us_quotes()), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(tracker.main(["preview"]), 0)
            text = output.getvalue()
            self.assertIn("India Portfolio", text)
            self.assertIn("US Portfolio", text)
            self.assertIn("Cash: 80", text)
            self.assertIn("Cash: 0", text)
            self.assertIn("Portfolio total: 300.0", text)

    def test_short_login_uses_configured_file_and_never_reads_google(self):
        import kite
        original = kite.SECRETS_PATH
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "settings.json"
            credentials = Path(folder) / "kite.yaml"
            config.write_text(json.dumps({"kite_credentials": str(credentials)}))
            def login(_args):
                self.assertEqual(kite.SECRETS_PATH, credentials)
                return 0
            with patch.object(tracker, "SETTINGS", config), patch.object(kite, "_cmd_auth", side_effect=login), patch.object(tracker, "GoogleSheets", side_effect=AssertionError("Unexpected Google access")):
                self.assertEqual(tracker.main(["login"]), 0)
        self.assertEqual(kite.SECRETS_PATH, original)

    def test_daily_sheet_mode_runs_without_reading_a_us_export(self):
        import fetch_quote
        layout = self.snapshot()
        layout["sheets"]["US"]["rows"] = tracker.read_json(self.root / "sheet-snapshot.example.json")["sheets"]["US"]["rows"]
        layout["sheets"]["US"]["summary_cells"]["broker_cash"]["value"] = 8675.98
        layout["sheets"]["US"]["summary_cells"]["holdings_uploaded_on"]["value"] = "2026-10-26"
        client = Mock()
        client.mf_holdings.return_value = []
        client.holdings.return_value = tracker.read_json(self.root / "kite-holdings.example.json")["holdings"]
        client.margins.return_value = {"available": {"live_balance": 80}}
        def quotes(symbols, *, market):
            if market == "india": return self.india_quotes()
            epoch = datetime(2026,10,23,20,tzinfo=timezone.utc).timestamp()
            return {"quotes": [{"input_ticker": s, "resolved_ticker": s, "last_close": 100, "as_of": "2026-10-23",
                               "currency": "USD", "currency_verified": True, "provider_timestamp": epoch,
                               "instrument_type": "EQUITY", "source": "test"} for s in symbols]}
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "settings.json"
            config.write_text(json.dumps({"spreadsheet_id": "test_workbook", "google_credentials": "key.json", "india_cash_field": "available.live_balance", "us_holdings": "sheet"}))
            with patch.object(tracker, "SETTINGS", config), patch.object(tracker, "GoogleSheets"), patch.object(tracker, "capture_google", return_value=layout), patch.object(tracker, "kite_client", return_value=client), patch.object(tracker, "read_stockclarity", return_value=[]), patch.object(tracker, "load_us_vested", side_effect=AssertionError("Unexpected XLSX read")), patch.object(tracker, "load_us_csv", side_effect=AssertionError("Unexpected CSV read")), patch.object(tracker, "add_fundamentals", side_effect=lambda src, evidence, **kw: (src, [])), patch.object(fetch_quote, "_fetch_yahoo_batch", side_effect=quotes), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(tracker.main(["preview"]), 0)
            self.assertIn("Portfolio total: 8775.98", output.getvalue())

    def test_missing_login_dependency_shows_environment_command_and_restores_path(self):
        import kite
        original = kite.SECRETS_PATH
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "settings.json"
            config.write_text(json.dumps({"kite_credentials": str(Path(folder) / "kite.yaml")}))
            with patch.object(tracker, "SETTINGS", config), patch.object(kite, "_cmd_auth", side_effect=ModuleNotFoundError(name="kiteconnect")), contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(tracker.main(["login"]), 1)
            self.assertIn("kiteconnect", output.getvalue())
            self.assertIn("python.exe", output.getvalue())
            self.assertIn("portfolio.py", output.getvalue())
            self.assertNotIn("Traceback", output.getvalue())
        self.assertEqual(kite.SECRETS_PATH, original)



class USSheetTests(FixtureTests):
    def setUp(self):
        super().setUp()
        self.layout = tracker.read_json(self.root / "sheet-snapshot.example.json")
        self.us = tracker.load_us_csv(self.root / "us-holdings.example.csv", cash="500", cash_as_of="2026-10-23")

    def preview(self, source=None, sheet=None):
        return tracker.preview_market(source or self.us, sheet or self.layout["sheets"]["US"])

    def test_unknown_usd_cost_clears_a_previous_cost_and_keeps_weights_available(self):
        source = replace(self.us, holdings=(replace(self.us.holdings[0], average_price=None), self.us.holdings[1]))
        sheet = copy.deepcopy(self.layout["sheets"]["US"])
        sheet["rows"][0]["values"]["Average Purchase Price ($)"] = 123
        result = self.preview(source, sheet)
        self.assertIsNotNone(result["portfolio_total"])
        self.assertIsNone(result["positions"][0]["unrealised_return_pct"])
        self.assertTrue(any("USD cost basis is missing" in r for r in result["positions"][0]["review"]))
        change = next(u for u in result["proposed_updates"] if u["header"] == "Average Purchase Price ($)" and u["row"] == 11)
        self.assertEqual(change["cell_value"], {"stringValue": ""})

    def test_daily_sheet_mode_keeps_fractional_holdings_cash_and_their_date(self):
        sheet = copy.deepcopy(self.layout["sheets"]["US"])
        sheet["summary_cells"]["broker_cash"]["value"] = 8675.98
        sheet["summary_cells"]["holdings_uploaded_on"]["value"] = (tracker.date(2026,10,26)-tracker.date(1899,12,30)).days
        row = sheet["rows"][0]["values"]
        row["Quantity"] = 109.0087
        row["Average Purchase Price ($)"] = None
        actual = tracker.load_us_sheet(sheet)
        self.assertEqual(actual.cash, Decimal("8675.98"))
        self.assertEqual(actual.cash_as_of, "2026-10-26")
        self.assertEqual(actual.holdings_as_of, "2026-10-26")
        self.assertEqual(actual.holdings[0].quantity, Decimal("109.0087"))
        self.assertIsNone(actual.holdings[0].average_price)
        self.assertIsNone(actual.holdings[0].current_price)  # Existing sheet prices are not treated as fresh.

    def test_sheet_edits_supply_cost_cash_and_quantity_without_any_broker_file(self):
        sheet = copy.deepcopy(self.layout["sheets"]["US"])
        sheet["summary_cells"]["broker_cash"]["value"] = 1234
        sheet["summary_cells"]["holdings_uploaded_on"]["value"] = "2026-10-23"
        sheet["rows"][0]["values"].update({"Quantity": 50.25, "Average Purchase Price ($)": 300})
        with patch.object(tracker, "load_us_vested", side_effect=AssertionError("Unexpected file read")):
            actual = tracker.load_us_sheet(sheet)
        self.assertEqual(actual.holdings[0].quantity, Decimal("50.25"))
        self.assertEqual(actual.holdings[0].average_price, Decimal(300))
        self.assertEqual(actual.cash, Decimal(1234))
        self.assertEqual(actual.cash_as_of, "2026-10-23")

    def test_sheet_mode_rejects_undated_or_invalid_invested_positions(self):
        for changed in ("date", "quantity", "ticker"):
            sheet = copy.deepcopy(self.layout["sheets"]["US"])
            sheet["summary_cells"]["holdings_uploaded_on"]["value"] = "2026-10-26"
            if changed == "date": sheet["summary_cells"]["holdings_uploaded_on"]["value"] = "Not yet uploaded"
            if changed == "quantity": sheet["rows"][0]["values"]["Quantity"] = None
            if changed == "ticker": sheet["rows"][0]["values"]["Exchange:Ticker"] = "NSE:WRONG"
            with self.subTest(changed=changed), self.assertRaises(tracker.ValidationError):
                tracker.load_us_sheet(sheet)

    def test_sheet_changes_during_quotes_stop_before_overwriting_inputs(self):
        sheet = copy.deepcopy(self.layout["sheets"]["US"])
        sheet["summary_cells"]["holdings_uploaded_on"]["value"] = "2026-10-26"
        source = tracker.load_us_sheet(sheet)
        sheet["rows"][0]["values"]["Quantity"] = 999
        reader = Mock()
        with self.assertRaisesRegex(tracker.ValidationError, "changed during the fetch"):
            tracker.update_requests(reader, "test", sheet, source, {})
        reader.batch_update.assert_not_called()


class VestedTests(unittest.TestCase):
    def export(self, folder, *, currency="USD", total="100.00", formulas=False, duplicate=False):
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        def xml(rows):
            root = ET.Element("worksheet", xmlns=ns)
            data = ET.SubElement(root, "sheetData")
            for i, values in enumerate(rows, 1):
                row = ET.SubElement(data, "row", r=str(i))
                for j, value in enumerate(values):
                    cell = ET.SubElement(row, "c", r=chr(65+j)+str(i), t="str")
                    ET.SubElement(cell, "v").text = str(value)
                    if formulas and i == 2:
                        ET.SubElement(cell, "f").text = "1+1"
            return ET.tostring(root)
        path = Path(folder) / "holdings.xlsx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("xl/workbook.xml", '<workbook xmlns="'+ns+'" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="User Details" r:id="r1"/><sheet name="Summary" r:id="r2"/><sheet name="Holdings" r:id="r3"/></sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels", '<Relationships>'+''.join(f'<Relationship Id="r{i}" Target="worksheets/sheet{i}.xml"/>' for i in range(1,4))+'</Relationships>')
            z.writestr("xl/worksheets/sheet1.xml", xml([["Period", "As of 26 Oct 2026"]]))
            z.writestr("xl/worksheets/sheet2.xml", xml([["Currency", "Current Equity Value"], [currency, total]]))
            # Deliberately reordered; average cost uses the precise total cost/units.
            row = ["TEST", "Synthetic company", currency, "0.12345678", "50.00", "100.00"]
            rows = [["Ticker", "Name", "Currency", "Total Shares Held", "Total Amount Invested", "Current Value"], row]
            z.writestr("xl/worksheets/sheet3.xml", xml(rows + ([row] if duplicate else [])))
        return path

    def profile(self, symbol):
        return {"symbol": symbol, "exchange": "NMS", "currency": "USD", "quoteType": "EQUITY",
                "marketCap": 2500000000, "trailingPE": 25}

    def test_original_xlsx_retains_fractional_units_and_total_cost(self):
        with tempfile.TemporaryDirectory() as folder:
            source = tracker.load_us_vested(self.export(folder), cash=8590, cash_as_of="2026-10-26", profile=self.profile)
        h = source.holdings[0]
        self.assertEqual(h.ticker, "NASDAQ:TEST")
        self.assertEqual(h.quantity, Decimal("0.12345678"))
        self.assertAlmostEqual(h.quantity * h.average_price, Decimal(50))
        self.assertIsNone(h.current_price)  # An export date is not a quote timestamp.
        self.assertEqual(source.cash, Decimal(8590))
        self.assertEqual(source.holdings_as_of, "2026-10-26")

    def test_bad_export_never_contacts_provider(self):
        for kwargs in ({"currency": "INR"}, {"total": "101.00"}, {"formulas": True}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as folder:
                profile = Mock(side_effect=AssertionError("Unexpected public lookup"))
                with self.assertRaises(tracker.ValidationError):
                    tracker.load_us_vested(self.export(folder, **kwargs), profile=profile)
                profile.assert_not_called()

    def test_duplicate_positions_and_conflicting_dates_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(tracker.ValidationError, "Duplicate security"):
                tracker.load_us_vested(self.export(folder, duplicate=True, total="200"), profile=self.profile)
            with self.assertRaisesRegex(tracker.ValidationError, "date disagrees"):
                tracker.load_us_vested(self.export(folder), holdings_as_of="2026-10-25", profile=self.profile)

    def test_us_identity_checks_symbol_currency_exchange_and_type(self):
        for key, value in (("symbol", "OTHER"), ("currency", "INR"), ("exchange", "UNKNOWN"), ("quoteType", "FUTURE")):
            with self.subTest(key=key), self.assertRaises(tracker.ValidationError):
                tracker.us_identity("TEST", {**self.profile("TEST"), key: value})

    def test_us_fundamentals_use_usd_millions_and_trailing_pe(self):
        h = tracker.Holding("NASDAQ:TEST", "Test", Decimal(1), Decimal(10))
        source = tracker.PortfolioInput("US", (h,), "2026-10-26", "test")
        evidence = {}
        actual, gaps = tracker.add_fundamentals(source, evidence, self.profile)
        self.assertFalse(gaps)
        self.assertEqual(actual.holdings[0].market_cap, Decimal(2500))
        self.assertEqual(actual.holdings[0].pe, Decimal(25))
        self.assertEqual(evidence[h.ticker]["fundamentals"]["pe_basis"], "trailing")
        actual, gaps = tracker.add_fundamentals(source, {}, lambda s: {**self.profile(s), "trailingPE": -12})
        self.assertIsNone(actual.holdings[0].pe)
        self.assertTrue(gaps)

    def test_etf_has_no_company_pe_or_market_cap_or_research(self):
        h = tracker.Holding("BATS:TEST", "Gold ETF", Decimal(1), Decimal(10), asset_type="ETF")
        source = tracker.PortfolioInput("US", (h,), "2026-10-26", "test")
        profile = lambda s: {**self.profile(s), "exchange": "BTS", "quoteType": "ETF"}
        actual, gaps = tracker.add_fundamentals(source, {}, profile)
        self.assertFalse(gaps)
        self.assertIsNone(actual.holdings[0].market_cap)
        self.assertIsNone(actual.holdings[0].pe)
        actual, _ = tracker.add_stockclarity(actual, [], {})
        self.assertEqual(actual.holdings[0].signal, "Not applicable")


if __name__ == "__main__":
    unittest.main()
