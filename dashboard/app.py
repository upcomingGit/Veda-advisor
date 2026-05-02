"""Flask app factory + routes.

Routes (all GET except /api/quote which is POST so the browser does not
prefetch it):

    /                          portfolio overview
    /position/<slug>           per-position page
    /journal                   rendered journal.md
    /settings                  active config + theme picker
    /api/quote (POST)          live-price refresh -- shells out to
                               scripts/fetch_quote.py and returns its JSON

The route handlers stay thin: they call readers, hand off to derived for
shaping, and pass dicts to templates. No business logic in the routes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import markdown as md_lib
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
)

from . import derived, formatters, readers
from .config import Config


# ---------------------------------------------------------------------------
# Markdown renderer (single instance, configured once)
# ---------------------------------------------------------------------------

# Extensions chosen to match the actual content of the Veda artifacts:
#   tables       - decision and earnings docs use pipe tables
#   fenced_code  - YAML / shell snippets quoted in kb / decisions
#   sane_lists   - mixed bullet styles in user-edited markdown
#   nl2br is intentionally NOT enabled -- the source files use blank lines
#   between paragraphs, not single newlines.
_MD_EXTENSIONS = ["tables", "fenced_code", "sane_lists"]


def _render_md(text: str | None) -> str:
    if not text:
        return ""
    return md_lib.markdown(text, extensions=_MD_EXTENSIONS, output_format="html")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(config: Config) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.config["VEDA_CONFIG"] = config

    # ---- Jinja filters --------------------------------------------------
    app.jinja_env.filters["inr"] = formatters.fmt_inr
    app.jinja_env.filters["usd"] = formatters.fmt_usd
    app.jinja_env.filters["money"] = formatters.fmt_money
    app.jinja_env.filters["pct"] = formatters.fmt_pct
    app.jinja_env.filters["num"] = formatters.fmt_number
    app.jinja_env.filters["dt"] = formatters.fmt_date
    app.jinja_env.filters["shares"] = formatters.fmt_shares
    app.jinja_env.filters["zone_class"] = formatters.zone_class
    app.jinja_env.filters["grade_class"] = formatters.grade_class
    app.jinja_env.filters["category_class"] = formatters.category_class
    app.jinja_env.filters["archetype_class"] = formatters.archetype_class
    app.jinja_env.filters["md"] = _render_md
    app.jinja_env.filters["spark"] = derived.sparkline_svg

    @app.context_processor
    def _inject_globals() -> dict[str, Any]:
        return {
            "veda_version": _read_version(config.workspace),
            "today": date.today().isoformat(),
            "initial_theme": config.initial_theme,
        }

    # ---- Routes ---------------------------------------------------------

    @app.route("/")
    def overview() -> str:
        assets = readers.read_assets(config.assets_path)
        registry = readers.read_registry(config.registry_path)
        slugs = readers.list_workspace_slugs(config.holdings_dir)
        upcoming = derived.derive_portfolio_calendar(
            config.holdings_dir, slugs, config.event_window_days
        )
        overview_summary = derived.derive_overview_summary(assets)
        calendar_month = derived.derive_portfolio_calendar_month(upcoming)
        # Per-currency, per-row enrichment so every row knows whether a
        # workspace exists for it (drives the [view] link).
        registry_keyset = {r.instance_key for r in registry}
        # Index slug-by-slug so we can render the position table even for
        # workspace folders whose ticker is not in any holdings table
        # (pre-buy research, dropped positions kept around for audit).
        workspace_only = sorted(
            s for s in slugs
            if not any(
                derived.slug_for_ticker(row.ticker, registry) == s
                for rows in assets.holdings_by_currency.values()
                for row in rows
            )
        )
        # Pre-resolve each row's slug once so the template stays declarative.
        enriched_by_ccy: dict[str, list[dict[str, Any]]] = {}
        for ccy, rows in assets.holdings_by_currency.items():
            enriched_by_ccy[ccy] = [
                {
                    "row": r,
                    "slug": derived.slug_for_ticker(r.ticker, registry),
                }
                for r in rows
            ]

        return render_template(
            "overview.html",
            assets=assets,
            registry=registry,
            slugs=slugs,
            workspace_only_slugs=workspace_only,
            enriched_by_ccy=enriched_by_ccy,
            upcoming=upcoming,
            overview_summary=overview_summary,
            calendar_month=calendar_month,
            event_window_days=config.event_window_days,
            registry_keyset=registry_keyset,
        )

    @app.route("/position/<slug>")
    def position(slug: str) -> str:
        if "/" in slug or "\\" in slug or slug.startswith("."):
            abort(404)
        wdir = config.holdings_dir / slug
        if not wdir.is_dir():
            abort(404)

        registry = readers.read_registry(config.registry_path)
        registry_row = next(
            (r for r in registry if r.instance_key == slug), None
        )
        meta = readers.read_meta(wdir)
        valuation = readers.read_valuation(wdir)
        fundamentals = readers.read_fundamentals(wdir)
        fund_rows = derived.derive_fundamentals_rows(fundamentals)
        spark_revenue = derived.derive_fundamentals_series(fund_rows, "revenue_mm")
        spark_opm = derived.derive_fundamentals_series(fund_rows, "opm_pct")
        spark_fcf = derived.derive_fundamentals_series(fund_rows, "fcf_mm")
        assumptions_view = derive_assumptions_or_none(wdir)
        indicators = readers.read_indicators(wdir)
        insiders = readers.read_insiders(wdir)
        shareholding = readers.read_shareholding(wdir)
        calendar_split = derived.derive_calendar_split(readers.read_calendar(wdir))
        calendar_month = derived.derive_portfolio_calendar_month(calendar_split["upcoming"])
        performance = readers.read_performance(wdir)
        decisions = readers.read_decisions(wdir)
        news = readers.read_news(wdir)
        news_cards = readers.read_news_cards(wdir)
        earnings = readers.read_earnings(wdir)
        kb = readers.read_kb(wdir)
        thesis = readers.read_thesis(wdir)
        governance = readers.read_governance(wdir)
        risks = readers.read_risks(wdir)
        disclosures = readers.read_disclosures(wdir)
        disclosure_cards = readers.read_disclosure_cards(wdir)
        absorption_log = readers.read_absorption_log(wdir)

        # Resolve the row from assets.md so the top-of-page card can show
        # shares / current_value / weight without re-deriving.
        assets = readers.read_assets(config.assets_path)
        assets_row, assets_currency = _find_assets_row(assets, slug, registry)

        return render_template(
            "position.html",
            slug=slug,
            registry_row=registry_row,
            meta=meta or {},
            valuation=valuation,
            fundamentals=fundamentals,
            fund_rows=fund_rows,
            spark_revenue=spark_revenue,
            spark_opm=spark_opm,
            spark_fcf=spark_fcf,
            assumptions=assumptions_view,
            indicators=indicators,
            insiders=insiders,
            shareholding=shareholding,
            calendar=calendar_split,
            calendar_month=calendar_month,
            performance=performance,
            decisions=decisions,
            news=news,
            news_cards=news_cards,
            earnings=earnings,
            kb_md=kb,
            thesis_md=thesis,
            governance_md=governance,
            risks_md=risks,
            disclosures_md=disclosures,
            disclosure_cards=disclosure_cards,
            absorption_log_md=absorption_log,
            assets_row=assets_row,
            assets_currency=assets_currency,
        )

    @app.route("/journal")
    def journal() -> str:
        text = readers.read_journal(config.journal_path)
        entries = readers.read_journal_entries(config.journal_path)
        return render_template(
            "journal.html",
            journal_md=text,
            journal_entries=entries,
            journal_updated=_file_updated_date(config.journal_path),
        )

    @app.route("/settings")
    def settings() -> str:
        return render_template("settings.html", config=config)

    @app.route("/api/quote", methods=["POST"])
    def api_quote() -> tuple[Response, int]:
        """Shell out to scripts/fetch_quote.py and return its JSON.

        Strict input handling: the ticker MUST match a slug in the
        holdings_registry. We do NOT pass arbitrary user input to a
        subprocess. The script's exit code is preserved as the HTTP status:
        200 on success, 502 on fetch failure (caller can show the JSON's
        ``error`` field). 400 on validation failure.
        """
        payload = request.get_json(silent=True) or {}
        ticker = (payload.get("ticker") or "").strip()
        if not ticker or not _is_safe_ticker(ticker):
            return _quote_error("ticker missing or invalid", status=400)

        # Constrain to known tickers from the user's holdings tables; this
        # closes the door on the API being used as a generic Yahoo proxy.
        assets = readers.read_assets(config.assets_path)
        all_tickers = {
            r.ticker.upper()
            for rows in assets.holdings_by_currency.values()
            for r in rows
        }
        if ticker.upper() not in all_tickers:
            return _quote_error(
                f"ticker {ticker!r} is not in assets.md holdings; refusing fetch",
                status=400,
            )

        if not config.fetch_quote_script.exists():
            return _quote_error(
                f"fetch_quote.py not found at {config.fetch_quote_script}",
                status=500,
            )

        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(config.fetch_quote_script),
                    "quote",
                    "--ticker",
                    ticker,
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _quote_error("fetch_quote.py timed out (20s)", status=504)
        except OSError as exc:
            return _quote_error(f"failed to invoke fetch_quote.py: {exc}", status=500)

        try:
            data = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return _quote_error(
                "fetch_quote.py returned non-JSON; check stderr", status=502
            )

        # fetch_quote.py contract: exit 0 = success, exit 1 = JSON with `error`.
        status = 200 if proc.returncode == 0 else 502
        return jsonify(data), status

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def derive_assumptions_or_none(wdir: Path) -> dict[str, Any] | None:
    return derived.derive_assumptions_view(readers.read_assumptions(wdir))


def _file_updated_date(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()


def _find_assets_row(
    assets: readers.AssetsView,
    slug: str,
    registry: list[readers.RegistryRow],
) -> tuple[readers.HoldingRow | None, str | None]:
    """Find the assets.md holdings row for a workspace slug.

    Returns (row, currency) or (None, None) when the slug has no row in
    assets.md (e.g., research-only workspace).
    """
    for ccy, rows in assets.holdings_by_currency.items():
        for r in rows:
            if derived.slug_for_ticker(r.ticker, registry) == slug:
                return r, ccy
    return None, None


def _is_safe_ticker(ticker: str) -> bool:
    """Permit the character set legitimately used by assets.md tickers.

    Allowed: ASCII letters, digits, dot (Yahoo suffix), hyphen (US class shares).
    Rejects shell metacharacters before subprocess argv even sees the value.
    """
    if not ticker or len(ticker) > 32:
        return False
    return all(c.isalnum() or c in ".-" for c in ticker)


def _quote_error(message: str, status: int) -> tuple[Response, int]:
    return jsonify({"error": message}), status


def _read_version(workspace: Path) -> str:
    vp = workspace / "VERSION"
    if vp.exists():
        try:
            return vp.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return "unknown"
