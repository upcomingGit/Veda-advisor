"""Display formatters for the dashboard.

Pure functions. Registered as Jinja2 filters in ``app.py``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

def fmt_inr(value: Any) -> str:
    """Format an INR amount using the Indian lakh/crore convention.

    >>> fmt_inr(7681755.88)
    '\u20b976.82L'
    >>> fmt_inr(17767743)
    '\u20b91.78Cr'
    >>> fmt_inr(213597.70)
    '\u20b92.14L'
    """
    if value is None or not isinstance(value, (int, float)):
        return "\u2014"
    v = float(value)
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1_00_00_000:
        return f"{sign}\u20b9{a / 1_00_00_000:.2f}Cr"
    if a >= 1_00_000:
        return f"{sign}\u20b9{a / 1_00_000:.2f}L"
    if a >= 1_000:
        return f"{sign}\u20b9{a:,.0f}"
    return f"{sign}\u20b9{a:.2f}"


def fmt_usd(value: Any) -> str:
    if value is None or not isinstance(value, (int, float)):
        return "\u2014"
    return f"${float(value):,.2f}"


def fmt_money(value: Any, currency: str) -> str:
    """Currency-aware. INR uses lakh/crore; USD uses commas; others fall back."""
    if currency == "INR":
        return fmt_inr(value)
    if currency == "USD":
        return fmt_usd(value)
    if value is None or not isinstance(value, (int, float)):
        return "\u2014"
    return f"{currency} {float(value):,.2f}"


# ---------------------------------------------------------------------------
# Other
# ---------------------------------------------------------------------------

def fmt_pct(value: Any, decimals: int = 1) -> str:
    if value is None or not isinstance(value, (int, float)):
        return "\u2014"
    return f"{float(value):.{decimals}f}%"


def fmt_number(value: Any, decimals: int = 0) -> str:
    if value is None or not isinstance(value, (int, float)):
        return "\u2014"
    return f"{float(value):,.{decimals}f}"


def fmt_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return "\u2014"


def fmt_shares(value: Any) -> str:
    """Match assets-schema.md: bare numbers, no trailing zeros."""
    if value is None or not isinstance(value, (int, float)):
        return "\u2014"
    v = float(value)
    if v.is_integer():
        return f"{int(v):,}"
    return f"{v:g}"


# ---------------------------------------------------------------------------
# Categorical -> CSS class
# ---------------------------------------------------------------------------

def zone_class(zone: Optional[str]) -> str:
    z = (zone or "").upper()
    if z == "CHEAP":
        return "zone-cheap"
    if z == "EXPENSIVE":
        return "zone-expensive"
    if z == "FAIR":
        return "zone-fair"
    return "zone-unknown"


def grade_class(grade: Optional[str]) -> str:
    g = (grade or "").upper()
    if g == "BEAT":
        return "grade-beat"
    if g == "MEET":
        return "grade-meet"
    if g == "MISS":
        return "grade-miss"
    return "grade-unknown"


def category_class(cat: Optional[str]) -> str:
    c = (cat or "").upper()
    if c == "GROWTH":
        return "cat-growth"
    if c == "FINANCIAL_HEALTH":
        return "cat-financial"
    if c == "COMPETITIVE":
        return "cat-competitive"
    if c == "GOING_CONCERN":
        return "cat-going-concern"
    return "cat-unknown"


def archetype_class(arch: Optional[str]) -> str:
    a = (arch or "").upper()
    if a == "GROWTH":
        return "arch-growth"
    if a == "INCOME_VALUE":
        return "arch-income"
    if a == "TURNAROUND":
        return "arch-turnaround"
    if a == "CYCLICAL":
        return "arch-cyclical"
    return "arch-unknown"
