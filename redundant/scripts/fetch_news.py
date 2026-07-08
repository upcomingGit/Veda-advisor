"""
Veda — news fetcher and normalizer.

Fetches RSS feeds (curated broad-publication and Google News per-ticker queries),
parses items, normalizes to a single JSON envelope, and emits source-tier hints
based on the redirect-target publisher (for Google News items).

Called by the news-researcher subagent (see internal/agents/news-researcher.md)
via the `Bash` tool. The subagent does NOT parse RSS or follow redirects itself;
those messy parts live here.

Why a helper script (not LLM-inline parsing):
  - RSS schema variation (RSS 2.0 / Atom / custom) needs feedparser.
  - Date normalization across RFC 822, ISO 8601, and custom formats is
    unreliable in LLM context.
  - Google News URLs are tracking redirects (news.google.com/articles/...).
    Resolving them inline burns the subagent's 5-op web cap; doing it here is
    one HTTP HEAD per item with a shared connection pool.
  - HTML stripping inside <description> tags needs BeautifulSoup.
  - WebFetch behavior across hosts (Claude Code / Copilot / Antigravity) is
    not deterministic for raw XML feeds.

Same pattern as scripts/fetch_fundamentals.py — Bash-invoked, JSON to stdout,
exit codes documented.

Usage:
    # Fetch a single curated RSS feed:
    python scripts/fetch_news.py \\
        --feed-url "https://www.business-standard.com/rss/markets-106.rss" \\
        --feed-name "Business Standard Markets" \\
        --since 2026-04-22

    # Fetch a Google News per-ticker query:
    python scripts/fetch_news.py \\
        --google-news-query '"NVIDIA" NVDA when:7d' \\
        --google-news-market US \\
        --resolve-redirects \\
        --since 2026-04-22

    # Fetch multiple feeds in one invocation (one HTTP request each, parallel safe):
    python scripts/fetch_news.py \\
        --feed-url "https://feeds.bloomberg.com/markets/news.rss" \\
        --feed-url "https://www.cnbc.com/id/100003114/device/rss/rss.html" \\
        --since 2026-04-22

Exit codes:
    0 - success or partial success (check JSON `errors` array)
    1 - complete failure (no items returned across all sources)
    2 - bad usage (argparse)

Requires `feedparser`, `requests`, `beautifulsoup4` (see requirements.txt).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# Force UTF-8 stdout so non-Latin characters (e.g., ₹ in Indian press headlines)
# don't crash the script on Windows consoles that default to cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Third-party — listed in requirements.txt
try:
    import feedparser
except ImportError:
    print(json.dumps({
        "errors": ["feedparser not installed. Run: pip install -r requirements.txt"],
        "items": [],
    }), file=sys.stdout)
    sys.exit(1)

try:
    import requests
except ImportError:
    print(json.dumps({
        "errors": ["requests not installed. Run: pip install -r requirements.txt"],
        "items": [],
    }), file=sys.stdout)
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

# Sibling module — ported from StockClarity, see news_spam_filter.py.
try:
    from news_spam_filter import is_spam as _is_spam
    _SPAM_FILTER_AVAILABLE = True
except ImportError:
    # Fallback when invoked from a context where the scripts/ dir isn't on sys.path.
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from news_spam_filter import is_spam as _is_spam
        _SPAM_FILTER_AVAILABLE = True
    except ImportError:
        _SPAM_FILTER_AVAILABLE = False
        def _is_spam(url, title):  # type: ignore
            return False, ""


# =============================================================================
# Constants
# =============================================================================

# Tier 2 publishers — these are the domains in our curated source list (or
# known equivalents). A Google News redirect to one of these returns the same
# tier as if the article came from the curated RSS directly.
TIER_2_PUBLISHER_DOMAINS = frozenset([
    # India
    "business-standard.com",
    "livemint.com",
    "economictimes.indiatimes.com",
    "thehindu.com",
    "hindustantimes.com",
    "cnbctv18.com",
    "indianexpress.com",
    "moneycontrol.com",
    # US / Global
    "reuters.com",
    "bloomberg.com",
    "cnbc.com",
    "finance.yahoo.com",
    "yahoo.com",
    "marketwatch.com",
    "seekingalpha.com",
    "wsj.com",
    "ft.com",
    # Other commonly-trusted tier-2 publishers
    "nytimes.com",
    "washingtonpost.com",
    "barrons.com",
    "forbes.com",
    "businessinsider.com",
])

# Domains that are aggregators or low-trust — drop entirely if a Google News
# redirect lands here (per news-researcher contract Rule 1).
TIER_4_DROP_DOMAINS = frozenset([
    "msn.com",
    "news.google.com",
    "flipboard.com",
    "smartnews.com",
    "tradingview.com",  # mostly user-generated
])

GOOGLE_NEWS_BASE = "https://news.google.com/rss/search"

GOOGLE_NEWS_LOCALES = {
    "India":     {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
    "US":        {"hl": "en-US", "gl": "US", "ceid": "US:en"},
    "UK":        {"hl": "en-GB", "gl": "GB", "ceid": "GB:en"},
    "Singapore": {"hl": "en-SG", "gl": "SG", "ceid": "SG:en"},
    "Global":    {"hl": "en-US", "gl": "US", "ceid": "US:en"},
}

DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_USER_AGENT = (
    # Match StockClarity's browser-like UA — Google News and several Indian press
    # sites return CAPTCHA pages or 403 to non-browser UAs.
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)
DEFAULT_HTTP_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

# Google RPC endpoint for resolving aggregator links — ported from StockClarity
# src/workflow/google_news_fetcher.py.
_GOOGLE_NEWS_RPC_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
_FORM_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    **DEFAULT_HTTP_HEADERS,
}

# Tracking parameters to strip during URL normalization.
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "_hsenc", "_hsmi",
    "icid", "ref", "ref_src", "ref_url",
}


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class NewsItem:
    """Normalized news item — output schema for the subagent."""
    title: str
    url: str
    url_normalized: str
    url_hash: str           # sha256(url_normalized)[:16]
    publisher: str          # domain of the (resolved) URL
    publisher_tier_hint: int  # 2, 3, or 0 (drop) — see TIER_*_DOMAINS
    published_iso: Optional[str]  # ISO 8601 UTC, may be None if unparseable
    description_text: str   # plain text, ≤ 500 chars
    source_feed: str        # name of the RSS feed or "google_news"
    google_news_redirected: bool  # True if URL was a Google News redirect we resolved


@dataclass
class FetchResult:
    """Return shape for one feed fetch."""
    items: List[NewsItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    feed_name: str = ""
    raw_count: int = 0      # before any filtering
    kept_count: int = 0     # after since-date and dedup
    spam_filtered_domain: int = 0   # dropped by BLOCKED_DOMAINS
    spam_filtered_title: int = 0    # dropped by BLOCKED_TITLE_PATTERNS


# =============================================================================
# Semantic dedup — same-story clustering across publishers
# =============================================================================
#
# News-rich tickers (e.g., NTPC, MSFT) often produce 50+ items where the same
# event is covered by 8 different publishers. The per-publisher cap reduces
# *within*-publisher flooding (Yahoo's 33 articles → 3) but doesn't address
# *cross*-publisher duplication. This module adds a lightweight Jaccard-based
# clustering step that groups items reporting the same event and keeps one
# representative per cluster (highest tier, then most recent).
#
# Why Jaccard on filtered tokens (not MinHash, not embeddings):
#   - n is small (10-100 items per invocation). O(n^2) Jaccard is trivial cost.
#   - Embeddings would require a model dependency we don't otherwise need.
#   - StockClarity's 5-layer pipeline (MinHash + cosine on embeddings) is
#     designed for thousands of articles per day across a 36-company cohort.
#     Per-ticker on-demand needs much less.
#
# Threshold and stop-word list calibrated empirically on April 2026 NTPC/MSFT
# data: 0.4 captures genuine same-event clusters (NTPC-EDF MoU reported by 8
# publishers; NTPC Rajasthan solar commissioning reported by 5) while keeping
# distinct events apart (jaccard < 0.15 on unrelated NTPC stories).

# Stop words: 4+ char tokens that carry no event signature. Tokens shorter
# than 4 chars are filtered by length regardless of content.
_SEMANTIC_STOP_WORDS = frozenset({
    # Articles, conjunctions, prepositions
    "with", "this", "that", "into", "from", "after", "before", "during", "between",
    "above", "below", "their", "there", "these", "those", "where", "while", "they",
    "them", "what", "when", "such", "than", "then", "also", "only", "just", "still",
    "your", "yours", "ours",
    # Modals and auxiliaries
    "would", "could", "should", "might", "must", "will", "shall", "been", "being",
    "have", "does", "doing", "many", "much", "more", "most",
    # Generic news-noise
    "today", "week", "weeks", "month", "months", "year", "years", "news",
    "stock", "stocks", "shares", "share",
    "company", "companies", "limited", "ltd", "inc",
    # Misc fillers
    "some", "very", "good", "great", "best", "worst", "long", "short",
    "amid", "over", "under", "down",
    # Punctuated artifacts after strip
    "said", "says", "saying",
})


def _semantic_tokens(title: str) -> set:
    """Extract event-signature tokens from a headline.

    Steps:
      1. Strip the trailing publisher suffix (everything after the last " - ")
         since it carries publisher info, not event info.
      2. Lowercase, strip punctuation.
      3. Tokenize on whitespace.
      4. Drop tokens shorter than 4 chars or in the stop-word list.
      5. Light suffix stem: strip 'ing' / 'ed' / 'es' / trailing 's' so
         "explores" / "exploring" / "explored" all collapse to "explor"-ish.

    Returns a set of canonical tokens for Jaccard comparison.
    """
    if not title:
        return set()
    t = title
    # Strip Google News-style publisher suffix " - Reuters", " - Bloomberg" etc.
    if " - " in t:
        t = t.rsplit(" - ", 1)[0]
    t = t.lower()
    # Replace non-word chars (handles apostrophes, hyphens, punctuation) with space.
    t = re.sub(r"[^\w\s]", " ", t)
    raw = t.split()
    tokens = set()
    for w in raw:
        if len(w) < 4 or w in _SEMANTIC_STOP_WORDS:
            continue
        # Light stemming — collapse common verb / plural suffixes.
        if w.endswith("ing") and len(w) >= 7:
            w = w[:-3]
        elif w.endswith("ed") and len(w) >= 6:
            w = w[:-2]
        elif w.endswith("es") and len(w) >= 6:
            w = w[:-2]
        elif w.endswith("s") and len(w) >= 5 and not w.endswith("ss"):
            w = w[:-1]
        tokens.add(w)
    return tokens


def _date_distance_days(iso_a: Optional[str], iso_b: Optional[str]) -> float:
    """Distance in days between two ISO 8601 strings; inf if either is missing/unparseable."""
    if not iso_a or not iso_b:
        return float("inf")
    try:
        a = datetime.fromisoformat(iso_a.replace("Z", "+00:00"))
        b = datetime.fromisoformat(iso_b.replace("Z", "+00:00"))
        return abs((a - b).total_seconds()) / 86400.0
    except (ValueError, TypeError):
        return float("inf")


def _semantic_cluster(
    items: List[Dict[str, Any]],
    threshold: float,
    date_window_days: float,
) -> Tuple[List[Dict[str, Any]], int, List[Dict[str, Any]]]:
    """Cluster items by Jaccard similarity on title tokens; keep one rep per cluster.

    Uses union-find for transitive linking (single-link clustering) with two
    constraints per pair:
      1. Token-set Jaccard >= ``threshold`` (default 0.4 in main()).
      2. Published dates within ``date_window_days`` (default 3.0 in main()).
         Items with missing dates are NEVER clustered with anything (date
         distance treated as infinite).

    The date constraint prevents the classic single-link chaining failure where
    two distinct events with similar templates get merged via overlapping but
    unrelated tokens. E.g., HBL's PLW ₹84 Cr order (Apr 9) and BLW ₹179.79 Cr
    order (Apr 2) share {hbl, engineer, kavach, order} but are 7 days apart —
    a 3-day window keeps them separate.

    Within a cluster, the representative is the item with the lowest
    publisher_tier_hint (Tier 2 beats Tier 3) tie-broken by most-recent date.
    The kept representative gets two new fields:
      - ``cluster_size``: number of items the rep replaced (1 = singleton, no merge)
      - ``cluster_dropped_publishers``: list of publisher domains of merged-in items

    Returns ``(kept_items, drops_count, cluster_log)`` where ``cluster_log`` is
    one entry per multi-item cluster for diagnostic reporting.
    """
    n = len(items)
    if n <= 1 or threshold <= 0:
        return items, 0, []

    # Pre-compute token sets and date strings once.
    token_sets = [_semantic_tokens(item.get("title", "")) for item in items]
    dates = [item.get("published_iso") for item in items]

    # Union-find for clustering.
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # O(n²) pairwise comparisons. Cheap for n < 200.
    for i in range(n):
        ti = token_sets[i]
        if not ti:
            continue
        for j in range(i + 1, n):
            tj = token_sets[j]
            if not tj:
                continue
            # Date-window gate — cheaper than Jaccard, do first.
            if _date_distance_days(dates[i], dates[j]) > date_window_days:
                continue
            inter = len(ti & tj)
            if inter == 0:
                continue
            union_size = len(ti | tj)
            if union_size > 0 and (inter / union_size) >= threshold:
                union(i, j)

    # Group items by cluster root.
    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    kept: List[Dict[str, Any]] = []
    cluster_log: List[Dict[str, Any]] = []
    drops = 0

    for member_ids in groups.values():
        if len(member_ids) == 1:
            # Singleton — keep as-is.
            kept.append(items[member_ids[0]])
            continue

        # Multi-item cluster. Pick the best representative.
        # Sort: lower tier_hint first (Tier 2 beats Tier 3), then later date first.
        # Two-pass stable sort keeps the logic readable.
        by_date_desc = sorted(
            member_ids,
            key=lambda i: items[i].get("published_iso") or "",
            reverse=True,
        )
        by_tier_then_date = sorted(
            by_date_desc,
            key=lambda i: items[i].get("publisher_tier_hint", 9),
        )
        best_id = by_tier_then_date[0]
        best_item = dict(items[best_id])  # shallow copy so we don't mutate input
        best_item["cluster_size"] = len(member_ids)
        best_item["cluster_dropped_publishers"] = sorted(
            items[m].get("publisher", "") for m in member_ids if m != best_id
        )
        kept.append(best_item)
        drops += len(member_ids) - 1

        cluster_log.append({
            "representative_publisher": best_item.get("publisher", ""),
            "representative_title": best_item.get("title", ""),
            "cluster_size": len(member_ids),
            "merged_publishers": sorted(
                items[m].get("publisher", "") for m in member_ids if m != best_id
            ),
        })

    return kept, drops, cluster_log



# =============================================================================
# URL helpers
# =============================================================================

def normalize_url(url: str) -> str:
    """Strip tracking params, lowercase domain, drop trailing slash."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        # Strip leading "www."
        if netloc.startswith("www."):
            netloc = netloc[4:]
        # Filter tracking query params
        query_pairs = parse_qs(parsed.query, keep_blank_values=False)
        filtered = {k: v for k, v in query_pairs.items() if k.lower() not in TRACKING_PARAMS}
        new_query = urlencode(filtered, doseq=True)
        # Drop trailing slash from path (unless path is just "/")
        path = parsed.path
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        normalized = urlunparse((
            parsed.scheme.lower() or "https",
            netloc,
            path,
            parsed.params,
            new_query,
            "",  # drop fragment
        ))
        return normalized
    except Exception:
        return url


def url_hash(url_normalized: str) -> str:
    """Short stable hash for dedup keying."""
    return hashlib.sha256(url_normalized.encode("utf-8")).hexdigest()[:16]


def extract_publisher(url: str) -> str:
    """Return the registrable domain (no www) for tier classification."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def classify_publisher_tier(publisher: str) -> int:
    """Return 2, 3, or 0 based on domain. 0 means drop."""
    if not publisher:
        return 0
    if publisher in TIER_4_DROP_DOMAINS:
        return 0
    if publisher in TIER_2_PUBLISHER_DOMAINS:
        return 2
    # Match subdomains of tier-2 publishers (e.g., "in.reuters.com" → reuters.com)
    for tier_2_domain in TIER_2_PUBLISHER_DOMAINS:
        if publisher.endswith("." + tier_2_domain):
            return 2
    return 3


def resolve_google_news_publisher(
    entry: Any,
    session: requests.Session,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Tuple[str, str, str, bool]:
    """Extract the actual publisher for a Google News RSS item.

    Two-stage resolution:
      1. **Fast path — ``entry.source`` element.** Google News RSS items include a
         per-item ``<source url="...">Publisher Name</source>`` element. feedparser
         exposes this as ``entry.source = {'href': '...', 'title': '...'}``.
         For ~95% of items, this is enough.
      2. **Fallback — StockClarity's URL resolver** (``_resolve_google_news_url``
         ported below). Used when ``entry.source`` is missing or empty. Performs
         an HTTP GET on the Google News tracking URL, follows redirects, and
         falls back to meta-refresh / first-anchor / RPC-endpoint parsing if
         the redirect chain doesn't escape ``news.google.com``.

    Returns ``(publisher_domain, publisher_name, resolved_url, was_resolved)``.
    ``resolved_url`` is the original Google News tracking URL when the fast path
    succeeds (we don't follow redirects we don't need to); it's the resolved
    publisher URL when the fallback path was used.
    """
    # Stage 1 — fast path via entry.source
    source = getattr(entry, "source", None)
    if source and isinstance(source, dict):
        href = source.get("href", "") or ""
        name = source.get("title", "") or ""
        if href:
            domain = extract_publisher(href)
            if domain:
                # Use the original Google News link as the source_url — we have
                # not actually resolved the article URL, only identified the
                # publisher. The Google News URL is still clickable.
                original_link = (getattr(entry, "link", "") or "").strip()
                return domain, name, original_link, True

    # Stage 2 — StockClarity-ported HTTP resolver
    original_link = (getattr(entry, "link", "") or "").strip()
    if not original_link:
        return "", "", "", False
    resolved_url = _resolve_google_news_url(original_link, session, timeout=timeout)
    if resolved_url and "news.google." not in (urlparse(resolved_url).netloc or ""):
        domain = extract_publisher(resolved_url)
        return domain, "", resolved_url, True

    # Last resort: title-suffix heuristic. Returns publisher name only; tier
    # classification will fall back to Tier 3.
    title = (getattr(entry, "title", "") or "").strip()
    if " - " in title:
        possible_publisher = title.rsplit(" - ", 1)[-1].strip()
        if possible_publisher and len(possible_publisher) < 80:
            return "", possible_publisher, original_link, False

    return "", "", original_link, False


# =============================================================================
# StockClarity-ported URL resolution helpers
# =============================================================================
#
# The following two functions are ported verbatim (with light style edits) from
# StockClarity's ``src/workflow/google_news_fetcher.py``. They handle the
# stubborn long-tail of Google News URLs whose publisher cannot be identified
# from feedparser's ``entry.source`` element — typically items where Google's
# aggregator wraps the destination in a JavaScript redirect.
#
# Resolution order tried by ``_resolve_google_news_url``:
#   1. HTTP GET with ``allow_redirects=True``. If the final URL escapes
#      ``news.google.com``, return it.
#   2. Parse the response HTML for ``<meta http-equiv="refresh">``.
#   3. Parse the first ``<a href>`` in the response HTML.
#   4. Fall through to ``_resolve_via_google_rpc`` — Google's internal RPC
#      endpoint for resolving aggregator links.
#
# Reference: StockClarity src/workflow/google_news_fetcher.py:215–255
# (``_resolve_google_news_url``) and 165–210 (``_resolve_via_google_rpc``).
# Pulled at commit visible in the local checkout on 2026-04-29.

def _resolve_via_google_rpc(
    session: requests.Session,
    soup: "BeautifulSoup",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Optional[str]:
    """Fallback to Google RPC endpoint when redirects/meta tags fail.

    Verbatim port from StockClarity ``src/workflow/google_news_fetcher.py``.
    """
    if not _BS4_AVAILABLE:
        return None

    data_p = soup.select_one("c-wiz[data-p]")
    if not data_p:
        return None

    raw_payload = data_p.get("data-p", "")
    if not raw_payload:
        return None

    try:
        payload = json.loads(raw_payload.replace("%.@.", '["garturlreq",'))
        request_args = payload[:-6] + payload[-2:]
        body = {
            "f.req": json.dumps([[ ["Fbv4je", json.dumps(request_args), "null", "generic"] ]])
        }
        rpc_resp = session.post(
            _GOOGLE_NEWS_RPC_URL,
            headers=_FORM_HEADERS,
            data=body,
            timeout=timeout,
        )
        rpc_resp.raise_for_status()
        cleaned = rpc_resp.text.replace(")]}'", "")
        article_blob = json.loads(cleaned)[0][2]
        article_url = json.loads(article_blob)[1]
        if article_url:
            return article_url
    except Exception:
        # Intentionally swallowed — RPC fallback is best-effort.
        pass
    return None


def _resolve_google_news_url(
    url: str,
    session: requests.Session,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Optional[str]:
    """Resolve a Google News aggregator URL to the actual article URL.

    Verbatim port from StockClarity ``src/workflow/google_news_fetcher.py``.
    Tries HTTP redirect, then meta-refresh, then first-anchor, then RPC.
    """
    if not _BS4_AVAILABLE:
        return None
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()

        final_url = resp.url
        parsed = urlparse(final_url)

        # If redirected to non-Google domain, we found the real URL
        if parsed.netloc and "news.google." not in parsed.netloc:
            return final_url

        # Try parsing HTML for meta refresh or first link
        soup = BeautifulSoup(resp.text or "", "html.parser")

        # Check meta refresh
        meta = soup.select_one("meta[http-equiv='refresh']")
        if meta and "url=" in (meta.get("content", "") or ""):
            resolved = meta["content"].split("url=")[-1]
            return resolved

        # Try first anchor link
        first_link = soup.select_one("a[href]")
        if first_link:
            return first_link["href"]

        # Last resort: Google RPC endpoint
        rpc_url = _resolve_via_google_rpc(session, soup, timeout=timeout)
        if rpc_url:
            return rpc_url

    except Exception:
        # Intentionally swallowed — caller treats None as "could not resolve".
        pass

    return None


# =============================================================================
# Date helpers
# =============================================================================

def parse_published_to_iso(entry: Any) -> Optional[str]:
    """Best-effort published date → ISO 8601 UTC."""
    # feedparser exposes structured time tuples for both 'published' and 'updated'.
    for attr in ("published_parsed", "updated_parsed"):
        timetuple = getattr(entry, attr, None)
        if timetuple:
            try:
                dt = datetime(*timetuple[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except (TypeError, ValueError):
                continue
    # Fallback: try parsing the raw string fields
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                # Try ISO 8601
                if "T" in raw:
                    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    return dt.astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                continue
    return None


def is_after_since(published_iso: Optional[str], since_iso: Optional[str]) -> bool:
    """True if published_iso is on or after since_iso. None published → keep."""
    if since_iso is None:
        return True
    if published_iso is None:
        return True  # don't drop on missing date; let the subagent see it
    try:
        return published_iso >= since_iso  # ISO 8601 strings compare lexicographically
    except Exception:
        return True


# =============================================================================
# Description / summary cleanup
# =============================================================================

def clean_description(raw: str, max_chars: int = 500) -> str:
    """Strip HTML, normalize whitespace, truncate."""
    if not raw:
        return ""
    # Step 1: HTML strip
    if _BS4_AVAILABLE:
        try:
            text = BeautifulSoup(raw, "html.parser").get_text(separator=" ")
        except Exception:
            text = raw
    else:
        text = re.sub(r"<[^>]+>", " ", raw)
    # Step 2: HTML entity unescape
    text = html.unescape(text)
    # Step 3: collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Step 4: truncate
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


# =============================================================================
# Feed fetching
# =============================================================================

def make_session(user_agent: str = DEFAULT_USER_AGENT) -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HTTP_HEADERS)
    if user_agent != DEFAULT_USER_AGENT:
        s.headers["User-Agent"] = user_agent
    return s


def fetch_one_feed(
    feed_url: str,
    feed_name: str,
    since_iso: Optional[str],
    session: requests.Session,
    is_google_news: bool = False,
    resolve_redirects: bool = False,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    apply_spam_filter: bool = True,
) -> FetchResult:
    """Fetch and normalize one RSS / Atom feed."""
    result = FetchResult(feed_name=feed_name)
    try:
        resp = session.get(feed_url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        result.errors.append(f"feed_fetch_failed: {feed_name} → {exc.__class__.__name__}")
        return result

    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        # bozo + zero entries = truly broken feed
        bozo_exc = getattr(parsed, "bozo_exception", "unknown")
        result.errors.append(f"feed_parse_failed: {feed_name} → {bozo_exc}")
        return result

    seen_hashes = set()
    for entry in parsed.entries:
        result.raw_count += 1

        title = (getattr(entry, "title", "") or "").strip()
        link = (getattr(entry, "link", "") or "").strip()
        if not title or not link:
            continue

        # For Google News, the link is a tracking URL we cannot HTTP-follow.
        # Identify the publisher via the per-item <source> element first; fall
        # back to StockClarity's URL resolver if needed (resolve_google_news_publisher).
        google_news_redirected = False
        publisher_name_hint = ""
        publisher = ""
        if is_google_news:
            publisher, publisher_name_hint, resolved_link, was_resolved = (
                resolve_google_news_publisher(entry, session, timeout=timeout)
            )
            google_news_redirected = was_resolved
            # If the resolver promoted the link to a non-Google URL, use that
            # as the canonical link going forward.
            if resolved_link and "news.google." not in (urlparse(resolved_link).netloc or ""):
                link = resolved_link
        else:
            publisher = extract_publisher(link)

        url_norm = normalize_url(link)
        url_h = url_hash(url_norm)
        if url_h in seen_hashes:
            continue
        seen_hashes.add(url_h)

        tier_hint = classify_publisher_tier(publisher)
        # Drop tier-0 (untrusted aggregators / unknown publishers) immediately
        # for Google News results. For curated feeds, keep them — the feed
        # itself is the trust signal.
        if is_google_news and tier_hint == 0:
            continue

        # Apply StockClarity-ported spam filter (publisher domain blocklist +
        # title regex blocklist). Runs on BOTH curated RSS items and Google
        # News items — a known-spam publisher (e.g., upstox.com) is spam
        # whether it surfaced via Google News or via a curated feed.
        # Pass `publisher` explicitly so the filter checks the resolved
        # publisher domain, not the Google News tracking URL's news.google.com.
        if apply_spam_filter:
            spam, reason = _is_spam(link, title, publisher_override=publisher)
            if spam:
                if reason == "blocked_domain":
                    result.spam_filtered_domain += 1
                elif reason == "blocked_title_pattern":
                    result.spam_filtered_title += 1
                continue

        published_iso = parse_published_to_iso(entry)
        if not is_after_since(published_iso, since_iso):
            continue

        description_raw = (
            getattr(entry, "summary", None)
            or getattr(entry, "description", None)
            or ""
        )
        description_text = clean_description(description_raw)

        item = NewsItem(
            title=title,
            url=link,
            url_normalized=url_norm,
            url_hash=url_h,
            publisher=publisher,
            publisher_tier_hint=tier_hint,
            published_iso=published_iso,
            description_text=description_text,
            source_feed=feed_name if not is_google_news else "google_news",
            google_news_redirected=google_news_redirected,
        )
        result.items.append(item)
        result.kept_count += 1

    return result


def build_google_news_url(query: str, market: str) -> str:
    """Construct a Google News RSS URL with per-market locale parameters."""
    locale = GOOGLE_NEWS_LOCALES.get(market, GOOGLE_NEWS_LOCALES["Global"])
    params = {"q": query, **locale}
    return f"{GOOGLE_NEWS_BASE}?{urlencode(params)}"


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and normalize RSS / Google News feeds for the news-researcher subagent.",
    )
    parser.add_argument(
        "--feed-url",
        action="append",
        default=[],
        help="Curated RSS feed URL. May be repeated to fetch multiple feeds in one invocation.",
    )
    parser.add_argument(
        "--feed-name",
        action="append",
        default=[],
        help="Human-readable name aligned positionally with --feed-url. If omitted, the URL is used.",
    )
    parser.add_argument(
        "--google-news-query",
        type=str,
        default=None,
        help='Google News query string, e.g., \'"NVIDIA" NVDA when:7d\'.',
    )
    parser.add_argument(
        "--google-news-market",
        type=str,
        default="US",
        choices=sorted(GOOGLE_NEWS_LOCALES.keys()),
        help="Market for Google News locale parameters. Default: US.",
    )
    parser.add_argument(
        "--resolve-redirects",
        action="store_true",
        help="Follow Google News redirects to identify the publisher domain. "
             "Adds 1 HEAD per item; required for accurate source-tier hints.",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Earliest published date to keep (YYYY-MM-DD). Items older are filtered.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-request timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}.",
    )
    parser.add_argument(
        "--no-spam-filter",
        action="store_true",
        help="Disable the StockClarity-ported spam filter (BLOCKED_DOMAINS + "
             "BLOCKED_TITLE_PATTERNS). Use for debugging only; production "
             "invocations should keep the filter enabled.",
    )
    parser.add_argument(
        "--max-per-publisher",
        type=int,
        default=3,
        help="Cap on items per publisher domain after the global merge. Sorted by "
             "published_iso descending; older items beyond the cap are dropped. "
             "Default: 3. Set to 0 to disable.",
    )
    parser.add_argument(
        "--require-name",
        type=str,
        default=None,
        help="Drop items whose title and description both lack any of the "
             "comma-separated tokens (case-insensitive). Use to enforce ticker "
             "or company-name presence. Example: --require-name 'MSFT,Microsoft'. "
             "Pass at least one token to enable; omit to disable.",
    )
    parser.add_argument(
        "--semantic-dedup-threshold",
        type=float,
        default=0.4,
        help="Jaccard threshold for clustering same-event items across "
             "publishers. Items with token-set Jaccard >= threshold are "
             "clustered (single-link transitive); within each cluster the "
             "highest-tier most-recent item is kept. Default: 0.4. Set to 0 "
             "to disable semantic dedup.",
    )
    parser.add_argument(
        "--semantic-dedup-date-window-days",
        type=float,
        default=3.0,
        help="Maximum date distance (in days) between two items for them to be "
             "in the same semantic cluster. Items with missing dates never "
             "cluster with anything. Default: 3.0. Set to a large value "
             "(e.g., 365) to disable the date constraint.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Validate inputs
    if not args.feed_url and not args.google_news_query:
        print(json.dumps({
            "errors": ["No --feed-url or --google-news-query provided"],
            "results": [],
        }, indent=2))
        return 2

    # Normalize since to ISO format
    since_iso = None
    if args.since:
        try:
            since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            since_iso = since_dt.isoformat()
        except ValueError as exc:
            print(json.dumps({
                "errors": [f"Bad --since value: {exc}"],
                "results": [],
            }, indent=2))
            return 2

    session = make_session()
    all_results: List[FetchResult] = []
    all_errors: List[str] = []

    # Fetch curated feeds
    for idx, feed_url in enumerate(args.feed_url):
        feed_name = (
            args.feed_name[idx]
            if idx < len(args.feed_name) and args.feed_name[idx]
            else feed_url
        )
        result = fetch_one_feed(
            feed_url=feed_url,
            feed_name=feed_name,
            since_iso=since_iso,
            session=session,
            is_google_news=False,
            resolve_redirects=False,
            timeout=args.timeout,
            apply_spam_filter=not args.no_spam_filter,
        )
        all_results.append(result)
        all_errors.extend(result.errors)

    # Fetch Google News query (if any)
    if args.google_news_query:
        google_news_url = build_google_news_url(args.google_news_query, args.google_news_market)
        result = fetch_one_feed(
            feed_url=google_news_url,
            feed_name=f"google_news::{args.google_news_market}",
            since_iso=since_iso,
            session=session,
            is_google_news=True,
            resolve_redirects=args.resolve_redirects,
            timeout=args.timeout,
            apply_spam_filter=not args.no_spam_filter,
        )
        all_results.append(result)
        all_errors.extend(result.errors)

    # Merge across all sources, dedup by url_hash globally (not just per-feed)
    seen_global = set()
    merged_items: List[Dict[str, Any]] = []
    for r in all_results:
        for item in r.items:
            if item.url_hash in seen_global:
                continue
            seen_global.add(item.url_hash)
            merged_items.append(asdict(item))

    items_after_dedup = len(merged_items)

    # Post-fetch filter: name-presence requirement.
    # Rationale: Google News query scoping is fuzzy; the ticker/company name should
    # appear in title or description for the item to be genuinely about the company.
    name_filtered_drops = 0
    if args.require_name:
        tokens = [t.strip().lower() for t in args.require_name.split(",") if t.strip()]
        if tokens:
            kept = []
            for item in merged_items:
                blob = (item.get("title", "") + " " + item.get("description_text", "")).lower()
                if any(token in blob for token in tokens):
                    kept.append(item)
                else:
                    name_filtered_drops += 1
            merged_items = kept

    items_after_name_filter = len(merged_items)

    # Post-fetch filter: semantic dedup (cluster same-event items across publishers).
    # Rationale: news-rich tickers (NTPC, MSFT) get the same event reported by 8
    # different publishers. Per-publisher cap doesn't help (it caps within a
    # publisher; this is cross-publisher duplication). Jaccard clustering on
    # filtered title tokens identifies same-event clusters; we keep the highest-
    # tier most-recent rep and surface cluster_size + dropped publishers on the
    # kept item.
    semantic_drops = 0
    cluster_log: List[Dict[str, Any]] = []
    if args.semantic_dedup_threshold > 0 and merged_items:
        merged_items, semantic_drops, cluster_log = _semantic_cluster(
            merged_items,
            threshold=args.semantic_dedup_threshold,
            date_window_days=args.semantic_dedup_date_window_days,
        )

    items_after_semantic_dedup = len(merged_items)

    # Post-fetch filter: per-publisher cap.
    # Rationale: Yahoo Finance and similar sites flood per-ticker queries with
    # 30+ stock-watching articles. Cap at N per publisher (sorted by date desc)
    # to ensure publisher diversity. StockClarity's daily-batch model relied on
    # cohort-level grading to handle this; our per-ticker on-demand model needs
    # an upstream cap.
    publisher_capped_drops = 0
    if args.max_per_publisher > 0 and merged_items:
        # Sort by date descending so the most recent items survive the cap.
        # Items with no date sort last (treat as oldest).
        merged_items.sort(
            key=lambda i: (i.get("published_iso") or ""),
            reverse=True,
        )
        per_pub_kept: Dict[str, int] = {}
        kept = []
        for item in merged_items:
            pub = item.get("publisher", "")
            count = per_pub_kept.get(pub, 0)
            if count < args.max_per_publisher:
                per_pub_kept[pub] = count + 1
                kept.append(item)
            else:
                publisher_capped_drops += 1
        merged_items = kept

    output = {
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "since": since_iso,
        "errors": all_errors,
        "per_feed_summary": [
            {
                "feed_name": r.feed_name,
                "raw_count": r.raw_count,
                "kept_count": r.kept_count,
                "spam_filtered_domain": r.spam_filtered_domain,
                "spam_filtered_title": r.spam_filtered_title,
                "errors": r.errors,
            }
            for r in all_results
        ],
        "post_fetch_filters": {
            "items_after_per_feed_filters": items_after_dedup,
            "name_filter_token": args.require_name,
            "name_filtered_drops": name_filtered_drops,
            "items_after_name_filter": items_after_name_filter,
            "semantic_dedup_threshold": args.semantic_dedup_threshold,
            "semantic_dedup_date_window_days": args.semantic_dedup_date_window_days,
            "semantic_dedup_drops": semantic_drops,
            "items_after_semantic_dedup": items_after_semantic_dedup,
            "semantic_clusters": cluster_log,
            "max_per_publisher": args.max_per_publisher,
            "publisher_capped_drops": publisher_capped_drops,
            "items_after_publisher_cap": len(merged_items),
        },
        "items_total_after_global_dedup": len(merged_items),
        "items": merged_items,
    }

    print(json.dumps(output, indent=2, ensure_ascii=True))

    # Exit code: 1 if every feed produced zero items AND there were errors;
    # 0 otherwise (partial success is success).
    any_items = any(r.kept_count > 0 for r in all_results)
    if not any_items and all_errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
