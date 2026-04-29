"""Spam filter for the news-researcher subagent's helper script.

This module bundles two filter layers ported verbatim from StockClarity's
``src/workflow/spam_filter.py`` (the same logic that runs in StockClarity's
production daily pipeline):

  1. ``BLOCKED_DOMAINS`` — 70 unique publisher domains known to produce
     low-signal content (trading platforms, PR wires, content-mill
     aggregators, brokerage stock tips). Each entry in the source file
     carries a comment with the rejection-rate evidence that justified
     it (e.g., *"94% rejected, 34/36 over 11 days"*).

  2. ``BLOCKED_TITLE_PATTERNS`` — 402 regex patterns covering technical
     analysis, broker recommendations, "stocks to buy" listicles,
     market-wrap headlines, share-price-movement articles, IPO
     aggregators, block-trade announcements, etc.

The ``is_spam(url, title)`` function applies both layers and returns a
single boolean plus a reason tag for logging.

Source repo: c:/Users/ankug/Downloads/StockClarity
Source file: src/workflow/spam_filter.py
Ported on: 2026-04-29

**Sync process.** When StockClarity adds or removes entries, re-extract via
``scripts/__extract_stockclarity_filters.py`` (one-shot helper, not committed)
or copy-paste the changed entries into the literals below. Veda does NOT
maintain its own list — StockClarity is the source of truth.

Why we don't import from StockClarity directly: the two repos are independent
deployments. Cross-repo imports break installation, packaging, and the
"single-folder install" promise of Veda.
"""

from __future__ import annotations

import re
from typing import FrozenSet, List, Tuple
from urllib.parse import urlparse

BLOCKED_DOMAINS: FrozenSet[str] = frozenset([
    "bollywoodhelpline.com",  # Technical breakouts, Fibonacci, MACD, unusual volume patterns
    "ts2.tech",
    "marketsmojo.com",  # Value turnover, option activity (Call/Put), technical momentum, stock ratings
    "earlytimes.in",  # ML forecasting, dip buying momentum, RSI reversals, trendlines
    "investing.com",  # Market closing prices, technical slides, end-of-session price action
    "equitymaster.com",  # Price reversals, top gainer/loser lists based on daily price action
    "tradingview.com",  # Global market sentiment, technical credit ratings
    "shiksha.com",
    "ulpravda.ru",  # Russian site with garbage/irrelevant article titles
    "tipranks.com",  # Stock rating/analyst tracking site
    "whalesbook.com",  # Stock analysis/trading site
    "富途牛牛",  # Chinese trading platform
    "futu.com",  # Chinese trading platform (Futu)
    "aastocks.com",  # Stock rating/analyst recommendation site (e.g., "CMS Recommends Overweighting")
    "barchart.com",  # Stock charting/advice site (e.g., "Should You Buy the Dip Now?")
    "aol.com",  # Aggregates low-quality investment advice and irrelevant lifestyle content
    "bitget.com",  # Multi-stock roundup articles (e.g., "Apple, Nvidia And Other X Stocks...")
    "finviz.com",  # Multi-stock roundup articles (e.g., "Why These X Stocks Are On Investors' Radars")
    "marketbeat.com",  # Extremely high noise ratio: mostly stock-position/trading churn articles
    "defenseworld.net",  # Mostly stock-position ticker churn and low-signal investment snippets
    "indianretailer.com",  # Frequently off-target retail roundup coverage for tracked companies
    "local3news.com",  # Local consumer-tech snippets (e.g., "WHAT THE TECH?") with no thesis value
    "local 3 news",  # Source-field variant token (non-domain) to catch inconsistent source metadata
    # --- Added Mar 2026: high-rejection sources (>=95% LLM rejection over 7 days) ---
    "stocktitan.net",  # PR distribution wire — corporate press releases (98.5% rejected)
    "investywise.com",  # Reformatted BSE/NSE disclosure summaries (100% rejected)
    "fool.com",  # Investment advice / "should you buy" opinions (100% rejected)
    "insidermonkey.com",  # Hedge fund holdings lists / opinion (96.3% rejected)
    "stocktradersdaily.com",  # Daily trading wrap / trading advice (100% rejected)
    "nationaltoday.com",  # Holiday / awareness day content, not business news (100% rejected)
    "247wallst.com",  # Clickbait financial listicles (95.0% rejected)
    "ipowatch.in",  # IPO listing announcements (100% rejected)
    "streetinsider.com",  # Institutional trading data / signals (100% rejected)
    "tradersunion.com",  # Forex broker reviews / trading education (100% rejected)
    "thehansindia.com",  # Regional newspaper with low company-specific signal (100% rejected)
    # --- Added Mar 2026: Google News high-reject domains (verified over 20 days of logs) ---
    "businessupturn.com",  # Shallow rewrite aggregator — press releases (87% rejected, 45/52 over 15 days)
    "fathom.video",  # YouTube video titles repackaged as articles (100% rejected)
    "sundayworld.co.za",  # South African regional news — off-target (100% rejected)
    "constructionworld.in",  # Infrastructure sector roundups, not company-specific (95% rejected, 39/41 over 10 days)
    "upstox.com",  # Brokerage platform — stock price commentary (94% rejected, 34/36 over 11 days)
    "openpr.com",  # Press release wire — generic corporate PRs (93% rejected, 119/128 over 18 days)
    "kalkinemedia.com",  # Stock analysis / ranking site (100% rejected, 14/14 over 9 days)
    "cardekho.com",  # Auto consumer reviews — not business/investor news (87% rejected, 27/31 over 14 days)
    "moomoo.com",  # Trading platform content — stock price churn (100% rejected, 4/4 over 3 days)
    "mercomindia.com",  # Solar/energy industry press releases — tangential (100% rejected, 16/16 over 9 days)
    "studycafe.in",  # Tax/compliance explainers — not business news (92% rejected, 11/12 over 9 days)
    "vocal.media",  # User-generated content platform — low quality (100% rejected, 13/13 over 9 days)
    "indiasnews.net",  # Aggregator site — recycled content (100% rejected)
    "techgraph.co",  # Shallow tech press releases (100% rejected)
    "marketwatch.com",  # Market-level commentary, stock price moves, analyst picks (99% rejected, 91/92 over 13 days)
    "sportskeeda.com",  # Sports/entertainment site — off-target (100% rejected, 10/10 over 10 days)
    "interactivecrypto.com",  # Crypto-only content — off-target (100% rejected, 16/16 over 8 days)
    "chartmill.com",  # Stock charting / technical screening tool (100% rejected, 11/11 over 8 days)
    "medianews4u.com",  # Media industry trade news — off-target (100% rejected, 11/11 over 9 days)
    "hdfcsky.com",  # Brokerage platform — stock price commentary (97% rejected, 30/31 over 9 days)
    "zacks.com",  # Stock ranking / earnings estimate site (100% rejected, 21/21 over 10 days)
    "smartkarma.com",  # Institutional research platform — opinion (100% rejected, 9/9 over 5 days)
    "samco.in",  # Brokerage platform — stock tips (100% rejected, 9/9 over 6 days)
    # --- Added Mar 2026 (late): high-rejection sources from daily run audits ---
    "gurufocus.com",  # Generic stock list aggregator (100% rejected, 16+ instances per run)
    "lokmattimes.com",  # Regional website with off-target matching and non-business content (100% rejected)
    "fathomjournal.com",  # YouTube video titles repackaged as articles (100% rejected)
    "tradebrains.in",  # Stock analysis / valuation opinion site (100% rejected)
    "durhamccc.co.uk",  # Cricket/sports site — off-target (100% rejected)
    # --- Added Mar 31 2026: AI-generated analysis rehashing old earnings/events ---
    "intellectia.ai",  # AI-generated stock analysis — rehashes old earnings data as new articles
    # --- Added Apr 25 2026: News aggregators that republish/recycle stale content ---
    "msn.com",  # Major news aggregator that republishes old articles with rewritten titles, evading historical dedup.
               # MSN appears in 100+ HISTORICAL DUP entries across daily logs. High noise, low signal.
    # --- Added Apr 25 2026: Stock-picking / opinion sites with 100% rejection rate ---
    "247wallst.com",  # "24/7 Wall St." — ETF picks, dividend stocks, price predictions (100% rejected, 18+ instances)
    "investorplace.com",  # Stock rankings, "blue-chip updated rankings", trading ideas (100% rejected, 5+ instances)
    "seekingalpha.com",  # Investor opinion articles, stock analysis pieces (100% rejected, 15+ instances)
    "zacks.com",  # Stock screeners, "featured highlights", broker-style picks (100% rejected)
    "thestreet.com",  # "Walmart customers angered" clickbait, stock price commentary (100% rejected, 20+ instances)
    "fool.com",  # Motley Fool — "Best ETFs", "Better stock: X vs Y" comparisons (100% rejected, 26+ instances)
    # --- Added Apr 25 2026: 100% rejected in Apr 15-25 analysis ---
    "exchange4media.com",  # Media/marketing industry — HR appointments, awards, campaigns (15 rejected, 0 accepted in Apr)
    "analyticsinsight.net",  # "Top stocks to invest", "Richest CEOs" listicles (9 rejected, 0 accepted in Apr)
    "globenewswire.com",  # Generic market research reports, press release wire (8 rejected, 0 accepted in Apr)
])

BLOCKED_TITLE_PATTERNS: List[str] = [
    # =========================================================================
    # TECHNICAL ANALYSIS TERMS
    # =========================================================================
    r"technical\s+analysis",
    r"technical\s+bounce",
    r"technical\s+pattern",
    r"technical\s+heatmap",
    r"price\s+action",
    r"price\s+channel",
    r"candlestick\s+trading",
    r"swing\s+trading",
    r"day\s+trading",
    
    # =========================================================================
    # CHART PATTERNS
    # =========================================================================
    r"bullish\s+pattern",
    r"bearish\s+pattern",
    r"bullish\s+engulfing",  # Candlestick pattern
    r"bearish\s+engulfing",  # Candlestick pattern
    r"elliott\s+wave",  # Technical analysis method
    r"breakout\s+(confirmed|alert|signal)",
    r"(positive|negative)\s+breakout",  # "Positive Breakout"
    r"support\s*(and|&)?\s*resistance",
    r"moving\s+average",
    r"gap\s+fill",
    r"bullish\s+signal",
    r"bearish\s+signal",
    r"flash\s+bullish",
    r"flash\s+bearish",
    r"\b(DMA|EMA|SMA)\b",  # Daily/Exponential/Simple Moving Average
    r"cross\s+(above|below)",  # "cross above their 200 DMA"
    r"sector\s+rotation",  # Trading strategy term
    r"hedging\s+(tactics?|strateg)",  # Trading tactics
    
    # =========================================================================
    # TECHNICAL INDICATORS
    # =========================================================================
    r"\bRSI\b",
    r"\bMACD\b",
    r"relative\s+strength\s+index",
    r"bollinger\s+bands?",
    
    # =========================================================================
    # TRADING SIGNALS
    # =========================================================================
    r"trading\s+signal",
    r"buy\s+signal",
    r"sell\s+signal",
    r"quant\s+signal",
    r"quant\s+screener",
    
    # =========================================================================
    # BROKER/ANALYST STOCK RECOMMENDATIONS (NEW)
    # Catches: "stocks to buy", "stocks to sell", broker picks, etc.
    # =========================================================================
    r"stocks?\s+to\s+(buy|sell|add|avoid|watch|accumulate)",
    r"(top|best)\s+\d+\s+stocks?",  # "top 10 stocks", "best 5 stocks"
    r"\d+\s+stocks?\s+to\s+(buy|sell|add|avoid|watch)",  # "15 stocks to buy"
    r"\d+\s+stocks?\s+(trading|that|which)",  # "3 Stocks trading...", "4 Stocks that could..."
    r"stocks?\s+(picks?|recommendations?)",
    r"(buy|sell|add)\s+list",
    r"securities\s+lists?",  # "Axis Securities lists"
    r"(broker|brokerage|securities)\s+(picks?|recommendations?|calls?)",
    r"(top|best)\s+picks?",
    r"stock\s+ideas?",
    r"investment\s+ideas?",
    r"portfolio\s+picks?",
    r"(buy|sell)\s+recommendations?",
    r"could\s+(skyrocket|surge|soar|rally|plunge|crash|tank)",  # Speculative price language
    r"(stocks?|shares?)\s+to\s+watch",
    
    # =========================================================================
    # INDEX-LEVEL FORECASTS (NEW)
    # Catches: Nifty target, Sensex prediction, market outlook
    # =========================================================================
    r"nifty\s*\d*\s*(target|forecast|prediction|outlook)",
    r"sensex\s*(target|forecast|prediction|outlook)",
    r"(nifty|sensex)\s+at\s+\d+",  # "Nifty at 28,100"
    r"(pegs?|sets?)\s+(nifty|sensex)",  # "pegs Nifty 50 target"
    r"index\s+target",
    r"market\s+target",
    r"(nifty|sensex)\s+could\s+(hit|reach|touch)",
    r"where\s+(nifty|sensex)\s+is\s+headed",
    
    # =========================================================================
    # MARKET SENTIMENT / INDEX MOVEMENT HEADLINES (NEW)
    # Catches: "Sensex tumbles", "Nifty falls", "Stock markets drop"
    # These mention companies only as contributors to index movement
    # =========================================================================
    r"(sensex|nifty|nifty\s*50|bank\s*nifty|dalal\s+street|benchmarks?|markets?|indices)\b.*?(tumbles?|falls?|fell|drops?|dropped|crashes?|rises?|rose|surges?|surged|gains?|jumps?|climbs?|slides?|slumps?|plunges?|soars?|rallies?|rally|resumes?\s+fall|extends?\s+losses|down|up|tanks?|in\s+the\s+red|in\s+the\s+green|ends?\s+.*?lower|ends?\s+.*?higher|closing\s+bell)",
    r"nifty\s*(below|above)\s+\d+",  # "Nifty below 26200"
    r"sensex\s*(below|above)\s+\d+",
    r"(sensex|nifty|nifty\s*50|bank\s*nifty|dalal\s+street|benchmarks?|indices).+?(down|up|fall|rise|drop|gain|tumble|soar|slide|plunge|sheds?|tanks?)\s+(nearly|over|more\s+than|almost|about)?\s*\d+(\.\d+)?%",
    r"stock\s+markets?\s+(fall|fell|drop|dropped|tumble|tumbled|crash|rise|rose|surge|surged)",
    r"markets?\s+(fall|fell|drop|dropped|tumble|tumbled|crash|close|closed)\s+(for|on|after)",
    r"what'?s?\s+behind\s+(falling|rising)\s+(stock\s+)?market",
    r"market\s+watch\s*:\s*(sensex|nifty)",  # "ET Market Watch: Sensex"
    r"selling\s+in\s+.+\s+dents?\s+sentiment",  # "selling in X, Y dents sentiment"
    r"(led|dragged)\s+by\s+.+\s+(stocks?|shares?)",  # "led by TCS, Infosys"
    r"(indices|index|markets?)\s+(snap|snapped)\s+(winning|losing)\s+streak",
    
    # =========================================================================
    # MARKET WRAP / PREVIEW / TRADING GUIDE ARTICLES (NEW)
    # Catches: "Market Wrap:", "Ahead of Market:", "Market Trading Guide:"
    # These are daily roundups that mention companies only as market movers
    # =========================================================================
    r"market\s+wrap\s*:",
    r"ahead\s+of\s+market\s*:",
    r"market\s+trading\s+guide\s*:",
    r"\d+\s+things?\s+that\s+will\s+(decide|determine|drive)\s+(stock\s+)?market",  # "10 things that will decide stock market"
    r"what\s+drove\s+the\s+.+\s+market\s+(down|up)",  # "What drove the Indian stock market down?"
    r"(sensex|nifty)\s+.+\s+pts?\s*,",  # "Sensex 376 pts, Nifty below..."
    r"dalal\s+street\s+(lower|higher|down|up)",  # "drag Dalal Street lower"
    
    # =========================================================================
    # IPO LISTINGS / UPCOMING IPOS (NEW)
    # Catches: "Upcoming IPOs", "IPOs to get listed", "IPO worth ₹X Cr"
    # These are IPO aggregation articles, not specific company news
    # =========================================================================
    r"upcoming\s+ipos?\s+in\s+",  # "Upcoming IPOs in January 2026"
    r"\d+\s+(other\s+)?ipos?\s+(worth|to\s+get\s+listed|launching)",
    r"ipos?\s+worth\s+₹?\d+",  # "IPOs worth ₹17,800 Cr"
    r"ipos?\s+to\s+watch\s+in",
    
    # =========================================================================
    # BSE/NSE THIRD-PARTY MENTIONS (NEW)
    # Catches: Articles mentioning BSE/NSE but about OTHER companies
    # "Responds to BSE Inquiry", "BSE Trading Approval", "NSE clarification"
    # =========================================================================
    r"responds?\s+to\s+(bse|nse)\s+inquiry",
    r"(bse|nse)\s+trading\s+approval",
    r"(bse|nse)\s+(inquiry|clarification|notice)\s+on",
    r"receives?\s+(bse|nse)\s+(approval|nod|clearance)",
    
    # =========================================================================
    # 52-WEEK HIGHS/LOWS ARTICLES (NEW)
    # Catches: "stocks hit 52-week highs", "touched 52-week low"
    # These are price movement lists, not business news
    # =========================================================================
    r"\d+\s+(midcap|smallcap|largecap|large[-\s]?cap|mid[-\s]?cap|small[-\s]?cap)?\s*stocks?\s+hit\s+52[-\s]?week\s+(highs?|lows?)",
    r"52[-\s]?week\s+(highs?|lows?)\s*:",
    r"touched?\s+52[-\s]?week\s+(high|low)",
    r"(stocks?|shares?)\s+at\s+(all[-\s]?time|52[-\s]?week)\s+(highs?|lows?)",
    
    # =========================================================================
    # SHARE PRICE HIGHLIGHTS / STOCK PRICE HISTORY (NEW)
    # Catches: "X Share Price Highlights: X Stock Price History"
    # These are pure price tracking pages, not news
    # =========================================================================
    r"share\s+price\s+highlights\s*:",
    r"share\s+price\s+live\s+updates\s*:",  # "HDFC Bank Share Price Live Updates:"
    r"stock\s+price\s+history",
    r"share\s+price\s+today",
    r"trading\s+activity\s+overview",  # "Grasim Industries Trading Activity Overview"
    r"(previous\s+day|closing)\s+(market\s+)?(close|price)",  # "Previous Day Market Close"
    r"current\s+price\s+and\s+daily\s+change",  # "Current Price and Daily Change"
    r"(spikes?|slides?|jumps?|falls?|rises?)\s+\d+(\.\d+)?%",  # "Titan Company Ltd Spikes 2.55%"
    r"volumes?\s+jump\s+at\s+.+\s+counter",  # "Volumes jump at SBI Life Insurance counter"
    r"leads?\s+(losers?|gainers?)",  # "Cipla Ltd leads losers"
    r"(turns?|turned)\s+(bullish|bearish)\s+on",  # "Brokerage turns bullish on Adani Ports"
    r"sheds?\s+\d+(\.\d+)?%",  # "sheds 6.6%" - stock price drop
    r"\d+(\.\d+)?%\s+this\s+(week|month|year)",  # "6.6% this week" - price movement
    r"(stock|share)\s+(is\s+)?favored",  # "stock is favored by institutions"
    r"favored\s+by\s+(top\s+)?institutions?",  # Institutional ownership focus
    r"trading\s+at\s+a\s+discount",  # Stock valuation focus
    r"officer\s+sells?\s+",  # Insider selling headlines
    r"(director|ceo|cfo|officer)\s+(buys?|sells?|acquires?)\s+(shares?|\$|₹|us\$)",  # Insider transactions
    
    # =========================================================================
    # BLOCK TRADE / LARGE TRADE / BLOCK DEAL ARTICLES (NEW)
    # Catches: "Records ₹X Crore Block Trade on NSE/BSE", "Block deal"
    # These are transaction announcements, not business operations
    # =========================================================================
    r"records?\s+₹?\d+.*\s+block\s+trade",
    r"block\s+trade\s+on\s+(nse|bse)",
    r"sees?\s+₹?\d+.*\s+block\s+trade",
    r"block\s+deal\s*:",  # "Eternal block deal:"
    r"offload\s+stake\s+worth",  # "offload stake worth Rs 1,500 crore"
    r"equity\s+stake\s+changes\s+hands",  # "Rs 1,756 crore equity stake changes hands"
    r"large\s+trade\s*:",  # "HDFC Bank large trade:"
    r"executes?\s+₹?\d+.*\s+(crore\s+)?(nse|bse)\s+block\s+trade",  # "Executes ₹37.67 Crore NSE Block Trade"

    
    # =========================================================================
    # STOCK BUY/SELL/HOLD RECOMMENDATIONS (NEW)
    # Catches: "Is X Stock a Buy, Sell, or Hold", "Should you buy X stock"
    # These are stock recommendation articles
    # =========================================================================
    r"is\s+.+\s+stock\s+a\s+buy",
    r"should\s+you\s+buy\s+.+\s+stock",
    r"should\s+you\s+buy.*dip",  # "Should You Buy the Dip Now?"
    r"buy,?\s+sell,?\s+(or\s+)?hold\s*:",
    r"(buy|sell)\s+or\s+hold\s+for",
    r"how\s+should\s+you\s+play\s+.+\s+for",  # "How Should You Play MSTR for January"
    r"etf\s+to\s+(buy|avoid)",  # "1 Dividend ETF to Buy Hand Over Fist and 1 to Avoid"
    r"recommends?\s+(overweight|underweight|buy|sell)",  # "CMS Recommends Overweighting Meta"
    
    # =========================================================================
    # SHARES RISE/FALL/SLIDE/JUMP ARTICLES (NEW)
    # Catches: "X shares slide X%", "shares rise after", "shares fall on"
    # These are pure price movement articles
    # =========================================================================
    r"shares?\s+(slide|slides|slid|slump|slumps|slumped|plunge|plunges|plunged)\s+\d+",
    r"shares?\s+(rise|rises|rose|jump|jumps|jumped|surge|surges|surged)\s+(after|on|as|following)",
    r"shares?\s+(fall|falls|fell|drop|drops|dropped|decline|declines|declined)\s+\d+",
    r"(stock|share)\s+(is\s+)?(slumping|sliding|plunging|surging|rallying)",
    r"shares?\s+(down|up)\s+\d+%",
    r"shares?\s+(fall|fell|rise|rose|extend)\s+for\s+(the\s+)?(second|third|fourth|fifth|\d+)\s+(straight\s+)?(day|session|week)",  # "shares fall for third straight session"
    r"share\s+price\s+(falls?|rises?|drops?|surges?)\s+(over\s+)?\d+",  # "share price falls over 2%"
    r"(extends?|extend)\s+(losing|winning|decline|rally)\s+streak",  # "extends losing streak"
    r"(lifts?|cuts?|raises?|lowers?)\s+.+\s+target",  # "Jefferies lifts RIL target"
    r"tests?\s+investor\s+conviction",  # "tests investor conviction as rally cools"
    r"(rally|slide)\s+cools?",  # "rally cools"
    r"how\s+to\s+trade\s+",  # "How to trade Mukesh Ambani stock"
    r"pinning\s+down\s+.+\s+p\/e",  # "Pinning Down X's P/E"
    r"attempts?\s+reversal\s+from\s+(key\s+)?support",  # "Attempts Reversal From Key Support"
    r"(high|low)\s+volatility\s+zone",  # "Chart Enters High Volatility Zone"
    r"portfolio\s+risk\s+assessment",  # Trading guide content
    r"see\s+risk\s+factors?\s+bef",  # "See Risk Factors Before"
    r"where\s+could\s+.+\s+be\s+headed",  # "Where Could X Be Headed"
    r"sector\s+etf\s+performance",  # ETF tracking content
    r"free\s+trading\s+psychology",  # Trading guide spam
    r"budget\s+investment\s+su",  # "Budget Investment Suggestions"
    r"time\s+to\s+buy\??",  # "Time to buy?" speculative headlines

    
    # =========================================================================
    # ANALYST UPGRADE/DOWNGRADE/INITIATION ARTICLES (NEW)
    # Catches: "Analyst explains upgrade", "initiated at hold", "DA Davidson Upgrades X to Neutral"
    # These are analyst opinion pieces
    # =========================================================================
    r"analyst\s+(explains?|upgrades?|downgrades?)",
    r"initiated\s+at\s+(buy|sell|hold|neutral)",
    r"(upgraded?|downgraded?)\s+(to|from)\s+(buy|sell|hold|neutral|outperform|underperform)",
    r"wall\s+street'?s?\s+(top\s+)?analyst\s+(calls?|picks?)",
    r"upgrades?\s+.{1,50}\s+to\s+(buy|sell|hold|neutral|outperform|underperform)",  # "Upgrades CoreWeave to Neutral"
    r"downgrades?\s+.{1,50}\s+to\s+(buy|sell|hold|neutral|outperform|underperform)",  # "Downgrades X to Sell"
    r"(davidson|morgan\s+stanley|goldman|jpmorgan|citi|ubs|barclays|jefferies)\s+(upgrades?|downgrades?|initiates?)",  # Broker actions
    r"assessing\s+.+\s+valuation",  # "Assessing Colgate-Palmolive Valuation"
    r"valuation\s+as\s+renewed\s+interest",  # Stock valuation focus
    
    # =========================================================================
    # CLOSING BELL / OPENING BELL ARTICLES (NEW)
    # Catches: "Closing Bell: Nifty below...", "Opening Bell:"
    # These are daily market summary articles
    # =========================================================================
    r"closing\s+bell\s*:",
    r"opening\s+bell\s*:",
    
    # =========================================================================
    # STOCKS LEAD/WEIGH/DRAG ARTICLES (NEW)
    # Catches: "X, Y Shares Lead", "X Shares Weigh", "as X drags"
    # These mention companies only as market movers
    # =========================================================================
    r"shares?\s+(lead|leads|weigh|weighs|drag|drags)\s+(gainers?|losers?|market|index)",
    r"as\s+.+\s+(drags?|weighs?)\s+(on\s+)?(market|index|dalal\s+street)",
    r"(lead|leads)\s+gainers",
    r"(nifty|sensex)\s+.*(as|after)\s+.+\s+(shares?|stocks?)\s+(weigh|drag)",
    
    # =========================================================================
    # STOCK RALLY / SLUMP LISTS (NEW)
    # Catches: "Lead Stock Market Rally", "PSU Bank Stocks Rally"
    # These are sector/thematic stock movement articles
    # =========================================================================
    r"(psu|it|banking|pharma|fmcg|auto|metal)\s+(bank\s+)?(stocks?|shares?)\s+(rally|slump|surge|plunge)",
    r"(lead|leads)\s+stock\s+market\s+(rally|decline)",
    r"stocks?\s+(on\s+)?(surge|rally|slump)\s*:",
    r"shares?\s+in\s+focus\s+as",  # "Reliance Industries, ONGC shares in focus as"
    r"techno[-\s]?funda\s+(january|february|march|april|may|june|july|august|september|october|november|december)?\s*picks?",  # "techno-funda January picks"
    r"(bp\s+wealth|motilal|icici\s+direct|hdfc\s+securities|kotak)\s+.*(picks?|recommendations?)",  # broker picks
    r"valuation\s+check\s+after",  # "Valuation Check After Mixed Returns"
    r"price[-\s]?to[-\s]?sales\s+signal",  # "Price-To-Sales Signal"
    r"mf\s+stake\s+hits\s+(all[-\s]?time|record)\s+high",  # "MF stake hits all-time high"
    r"(slides?|falls?|drops?|tumbles?)\s+\d+%\s+from\s+(peak|high|record)",  # "slides 30% from peak"
    r"(quick|sharp)\s+reversal",  # "Can X deliver quick reversal"
    r"statistical\s+arbitrage",  # "Statistical Arbitrage in Indian Banks"
    r"long\s+.+\s+vs\.?\s+short",  # "Long HDFC Bank Vs. Short Axis Bank"

    
    # =========================================================================
    # HISTORICAL RETURNS / LAGGING INDICATORS (NEW)
    # Catches: "300% return", "multibagger", past performance, "14x run"
    # =========================================================================
    r"\d+%\s*return",  # "300% return", "50% return"
    r"multibagger",
    r"multi[-\s]?bagger",
    r"(upper|lower)\s+circuit",  # "hits upper circuit"
    r"hits?\s+(upper|lower)\s+circuit",
    r"\d+%\s+(upside|downside)",  # "48% upside"
    r"(upside|downside)\s+potential",
    r"return\s+in\s+(one|two|three|\d+)\s+(year|month|week)",
    r"(doubled|tripled|quadrupled)\s+in",
    r"gave\s+\d+%\s+return",
    r"delivered\s+\d+%",
    r"(year|month)\s+in\s+review",  # Retrospective content
    r"(stock|share)\s+performance\s+review",
    r"(top|best)\s+(gainer|loser|performer)",
    r"biggest\s+(gainer|loser)",
    r"this.*stock.*soared.*\d+%",  # "This TSX Stock Has Already Soared 37% in 2026"
    r"already\s+soared\s+\d+%",  # "Has Already Soared 37%"
    
    # =========================================================================
    # MULTIPLIER RUN ANALYSIS (NEW - Jan 2026)
    # Catches: "14x run", "10x return", "Can run continue?", historical rallies
    # These analyze past stock price performance, not current business news
    # =========================================================================
    r"\d+x\s+(run|return|rally|gain)",  # "14x run", "10x return"
    r"(can|will|could)\s+(the\s+)?run\s+continue",  # "Can the run continue?"
    r"(commercial|passenger|auto)\s+vehicle\s+cycle\s+(turning|over|peaking)",  # "Is the CV cycle turning?"
    r"is\s+the\s+.+\s+cycle\s+(turning|over|peaking|ending|beginning)",  # "Is the X cycle turning?"
    r"(run|rally)\s+(continue|sustain|persist|extend)",  # "Can the rally continue?"
    r"(how|where)\s+.+\s+(stock|share)s?\s+(goes?|headed)\s+from\s+here",  # "Where does X stock go from here?"
    r"what('s|\s+is)\s+driving\s+the\s+(recent\s+)?(rally|run|surge)",  # "What's driving the rally?"
    
    # =========================================================================
    # EARNINGS CALENDAR / RESULTS ANNOUNCEMENTS (NEW - Jan 2026)
    # Catches: "Q3 Results Today", "Results on Jan 17", quarterly result dates
    # These are calendar announcements, not material business news
    # =========================================================================
    r"q[1-4]\s+results?\s+(today|tomorrow|on\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))",  # "Q3 Results Today"
    r"results?\s+(on|to\s+be\s+(announced|declared))\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)?\s*\d+",  # "Results on Jan 17"
    r"(earnings|results?)\s+(scheduled\s+for|to\s+be\s+announced)",  # "Earnings scheduled for..."
    r"(quarterly|q[1-4])\s+results?\s+(date|schedule|announcement)",  # "Q3 Results date"
    r"results?\s+live\s*:",  # "Q3 Results Live:"
    r"(hdfc|icici|sbi|axis|kotak)\s*,.*results?\s+(today|tomorrow)",  # "HDFC Bank, ICICI Bank Q3 Results Today"
    r"\d+\s+(companies|stocks?)\s+(to\s+)?report\s+(results?|earnings)",  # "10 companies to report results"

    # =========================================================================
    # EVERGREEN PROFILE PIECES / NET WORTH ARTICLES (NEW - Apr 2026)
    # Catches: "Who is X?", "Check net worth", "education, career, businesses"
    # These are recycled profile pieces that evade historical dedup
    # =========================================================================
    r"who\s+is\s+(the\s+)?(owner|ceo|founder|chairman)",  # "Who is the Owner of IndiGo?"
    r"who\s+is\s+[a-z]+\s+[a-z]+\?\s*[-–—]\s*(check|know)",  # "Who is Rahul Bhatia? Check..."
    r"check\s+(his|her|their)?\s*(education|career|net\s*worth)",  # "Check education, career, net worth"
    r"(education|career).*(businesses?|net\s*worth)",  # "education, career, businesses and net worth"
    r"net\s*worth\s*(details?|in\s+\d+)",  # "net worth details", "net worth in 2026"
    r"(richest|wealthiest)\s+(person|man|woman|indian|american)",  # "richest person" lists

    
    # =========================================================================
    # STOCK PRICE / VALUATION FOCUS
    # =========================================================================
    r"stock\s+price\s+target",
    r"price\s+target",
    r"share\s+price\s+today",
    r"stock\s+outlook",
    r"\d{4}\s+outlook",  # e.g., "2026 Outlook"
    r"analyst\s+target",
    r"target\s+price",
    r"fair\s+value",
    r"intrinsic\s+value",
    r"valuation\s+target",
    
    # =========================================================================
    # STOCK ALERTS / STOCKS IN NEWS / MARKET UPDATES (NEW)
    # Catches: "Stock Alert:", "Stocks in news:", "Stock market update:"
    # These are daily roundups mentioning multiple stocks
    # =========================================================================
    r"stock\s+alert\s*:",
    r"stocks?\s+in\s+news\s*:",
    r"stock\s+market\s+update\s*:",
    r"and\s+other\s+\d+\s+.+\s+stocks?",  # "Apple, Nvidia and other 8 tech stocks..."
    r"why\s+these\s+\d+\s+stocks?\s+are\s+on\s+investors?'?\s+radars?(\s+today)?",  # "Why these 5 stocks are on investors' radars today"
    r"stocks?\s+on\s+investors?'?\s+radars?(\s+today)?",  # Generic investor-radar roundup wording
    r"(nifty|sensex|bank\s+nifty)\s+(index\s+)?(falls?|rises?|drops?)\s+\d+",
    r"market\s+update\s*:\s*.+('s)?\s+(closing|opening)\s+price",  # "Market update: X's closing price"
    r"daily\s+performance\s+review",
    r"(nifty|sensex)\s+.+\s+index\s+(price\s+)?today",  # "Nifty 50 Index Price Today"
    r"(live\s+)?charts?\s*[-–]?\s*(business\s+today|economic\s+times)",
    
    # =========================================================================
    # STOCK COMPARISON / X VS Y ARTICLES (NEW)
    # Catches: "TCS vs Infosys: Which stock", "X vs Y: Which is better"
    # These are comparison articles focused on stock picking
    # =========================================================================
    r".+\s+vs\.?\s+.+:\s+which\s+(stock|share|company)",
    r"which\s+(tech|banking|it|pharma)\s+stock\s+is\s+(set|better|poised)",
    r"(top|best)\s+\d+\s+(stocks?|shares?)\s+to\s+(buy|watch|invest)",
    
    # =========================================================================
    # BULL RUN / OVERBOUGHT / CHART PATTERNS (NEW)
    # Catches: "shares in a bull run", "overbought on charts"
    # These are technical trading commentary
    # =========================================================================
    r"(bull|bear)\s+run",
    r"overbought\s+on\s+charts?",
    r"oversold\s+on\s+charts?",
    r"(more\s+)?upside\s+ahead",
    r"(lacks?|have)\s+mettle",  # "Most metal stocks lack mettle"
    r"kept\s+.+\s+losses?\s+in\s+check",  # "kept Nifty losses in check"
    
    # =========================================================================
    # ANALYST RESEARCH CALLS / SECTOR PREDICTIONS (NEW)
    # Catches: "Top Wall Street Analyst Research Calls", "sector outlook for 2026"
    # These are analyst opinion roundups
    # =========================================================================
    r"(top\s+)?wall\s+street\s+analyst\s+(research\s+)?calls?",
    r"sector\s+outlook\s+for\s+\d{4}",
    r"(overweight|underweight|neutral)\s+on\s+\d+\s+sectors?",
    r"\d+\s+(more\s+)?(stocks?|companies)\s+in\s+\d{4}\s+focus\s+list",  # "8 more in 2026 focus list"
    r"(right|best)\s+time\s+to\s+buy\s+.+\s+shares?",
    r"(sun|light)\s+behind\s+the\s+(dark\s+)?clouds?",  # "There's Sun Behind The Dark Clouds"
    
    # =========================================================================
    # IEPF / UNCLAIMED SHARES / LOCK-IN PERIOD (NEW)
    # Catches: "Transfer to IEPF", "Lock-in Periods End"
    # These are administrative/regulatory notices, not material business news
    # =========================================================================
    r"transfer\s+(of\s+)?(unclaimed\s+)?shares?\s+to\s+iepf",
    r"investor\s+protection\s+fund\s+updates?",
    r"(eligible|due)\s+for\s+trading\s+as\s+lock[-\s]?in\s+(periods?\s+)?end",
    r"lock[-\s]?in\s+(periods?\s+)?end",
    r"unclaimed\s+(shares?|dividend)",
    
    # =========================================================================
    # NO MATERIAL INFORMATION / PRICE CLARIFICATION (NEW)
    # Catches: "Clarifies No Material Information Behind Recent Price Movement"
    # These are routine compliance filings with no actual news
    # =========================================================================
    r"(clarifies?|confirms?)\s+no\s+material\s+information",
    r"no\s+(pending\s+)?material\s+(information|news|development)",
    r"behind\s+recent\s+price\s+movement",
    r"no\s+undisclosed\s+price\s+sensitive\s+information",
    
    # =========================================================================
    # CONSUMER PRODUCT REVIEWS / CREDIT CARD BEST (NEW)
    # Catches: "Is X Credit Card Best for Beginners"
    # These are consumer advice, not business news
    # =========================================================================
    r"is\s+.+\s+credit\s+card\s+(best|good|worth)",
    r"(best|top)\s+credit\s+cards?\s+for\s+(beginners?|students?|travel)",
    r"detailed\s+overview\s*[-–]?\s*(trade\s+brains|upstox|groww)",
    
    # =========================================================================
    # MCAP EROSION / INVESTORS LOSE (NEW)
    # Catches: "investors lose Rs X crore", "mcap erodes by Rs X"
    # These are about stock price, not operations
    # =========================================================================
    r"investors?\s+lose\s+₹?rs?\s*\d+",
    r"mcap\s+(erodes?|shrinks?|falls?|drops?)\s+by\s+₹?rs?",
    r"(market\s+)?cap\s+(erodes?|shrinks?|falls?)\s+by",
    r"(lose|lost|erodes?)\s+₹?\d+\s*(lakh\s+)?crore",
    
    # =========================================================================
    # STOCK NEWS & ANALYSIS / STAY INFORMED (NEW)
    # Catches: "Stock News & Market Analysis: Stay Informed"
    # These are generic stock tracking pages
    # =========================================================================
    r"stock\s+news\s*[&]\s*market\s+analysis",
    r"stay\s+informed\s+in\s+\d{4}",
    r"(top\s+)?(laggards?|gainers?)\s*[-–]?\s*(check|here)",
    
    # =========================================================================
    # WORST DAY / HEADS FOR / DENIES REPORT (NEW)
    # Catches: "Heads for Worst Day Since", "denies report on"
    # These are stock price reaction headlines
    # =========================================================================
    r"heads?\s+for\s+(worst|best)\s+day\s+since",
    r"(worst|best)\s+day\s+in\s+\d+\s+(months?|years?|sessions?)",
    r"shares?\s+take\s+a\s+big\s+knock",
    r"denies?\s+(link\s+between|report\s+on)\s+share\s+price",
    
    # =========================================================================
    # BUYBACK / DIVIDEND REMINDER ARTICLES (NEW)
    # Catches: "buyback opens: Five key things to know"
    # Note: Buyback announcement is news, but "things to know" explainers are not
    # =========================================================================
    r"buyback\s+opens?\s*:\s*(five|5|\d+)\s+(key\s+)?things?\s+to\s+know",
    r"(is\s+)?due\s+to\s+pay\s+a\s+dividend\s+of",
    
    # =========================================================================
    # INVESTIGATION / SECURITIES LAW (NEW)
    # Catches: "Investigation of Potential Securities Law Violations"
    # These are typically class action lawyer advertisements
    # =========================================================================
    r"(reminds?\s+)?investors?\s+of\s+.+\s+(to\s+)?an?\s+investigation",
    r"investigation\s+of\s+potential\s+securities\s+law",
    r"(kaplan\s+fox|pomerantz|rosen\s+law|glancy|kessler\s+topaz)\s+.*(reminds?|announces?|encourages?|investigat)",
    r"investigation\s+alert\s*:",  # "Investigation Alert:"
    r"investor\s+alert\s*:",  # "INVESTOR ALERT:"
    
    # =========================================================================
    # OPTIONS/DERIVATIVES TRADING
    # =========================================================================
    r"options?\s+data",
    r"put\s+option\s+activity",
    r"call\s+option\s+activity",
    r"derivatives?\s+open\s+interest",
    
    # =========================================================================
    # SPAM/CLICKBAIT PATTERNS
    # =========================================================================
    r"free\s+(discover|superior|tremendous|outstanding)",
    r"amplify\s+gains",
    r"fast\s+profit",
    r"rapid\s+capital",
    r"triple[-\s]digit\s+(stock|return)",
    r"low\s+(cost|entry|risk)\s+portfolio",
    r"small\s+(entry|investment)\s+(cost|portfolio)",
    r"machine\s+learning\s+stock",
    r"ai[-\s]driven\s+stock",
    
    # =========================================================================
    # GENERIC LOW-VALUE PATTERNS
    # =========================================================================
    r"demand\s+trends\s+crucial",
    r"volatility\s+ahead",
    r"watch\s*list",
    r"high\s+probability\s+setup",
    r"institutional\s+tools",
    r"unusual\s+flow",
    r"order\s+book\s+volume",
    r"value\s+turnover",

    r"penny\s+stock",
    r"small[-\s]?cap\s+gem",
    
    # =========================================================================
    # SPECULATIVE / PRICE PROJECTION ARTICLES (NEW)
    # Catches: "Where Will X Be in 3 Years?", "fell X% in December"
    # =========================================================================
    r"where\s+will\s+.+\s+be\s+in\s+\d+\s+(years?|months?)",  # "Where Will X Be in 3 Years?"
    r"(stock|share)\s+(fell|rose|dropped|gained)\s+\d+%\s+in\s+(january|february|march|april|may|june|july|august|september|october|november|december)",  # "stock fell 11% in December"
    r"good\s+news\s+keeps?\s+coming.+but\s+not\s+the\s+stock",  # "Good news keeps coming but not the stock"
    r"(stock|share)\s+isn't\s+keeping\s+(up|pace)",  # Stock not keeping pace with news
    r"(shake|shakes?|shook)\s+investor\s+confidence",  # "Shake Investor Confidence"
    r"leverage\s+concerns?\s+(shake|worry|concern)",  # Financial concern headlines
    r"stocks?\s+in\s+focus\s+(today|this\s+week)",  # "Stocks in focus today"
    r"why\s+.+\s+stock\s+(fell|rose|dropped|gained|tumbled)",  # "Why X stock fell 11%"
    
    # =========================================================================
    # MUTUAL FUND / PORTFOLIO HOLDINGS (NEW)
    # Catches: fund portfolio articles, top holdings, allocation mentions
    # =========================================================================
    r"(fund|portfolio)\s*'?s?\s+(top\s+)?(holdings?|allocation|stocks?)",
    r"(rules?|dominates?|leads?)\s+.*\s+(fund|portfolio)\s*'?s?\s+",
    r"top\s+\d+\s+holdings?",
    r"portfolio\s+(composition|breakdown|allocation)",
    r"(fund|amc|scheme)\s+(bought|sold|added|exited)",
    r"flexi[-\s]?cap\s+fund.*portfolio",
    r"(large|mid|small)[-\s]?cap\s+fund.*holdings?",
    r"(mutual|hedge)\s+fund.*buys",
    r"(mutual|hedge)\s+fund.*sells",
    r"(fund|scheme)\s+(outperforms?|underperforms?|beats?|lags?)",  # Fund performance
    r"(cap|debt|equity|hybrid)\s+fund\s+(outperforms?|returns?)",  # "Large Cap Fund outperforms"
    
    # =========================================================================
    # INVESTOR / FUND MANAGER INTERVIEWS (NEW)
    # Catches: investor philosophy, portfolio profiles, guru picks
    # =========================================================================
    r"(ace|star|legendary)\s+(investor|fund\s+manager)",
    r"investor'?s?\s+(motto|philosophy|strategy|lessons?)",
    r"(jhunjhunwala|rakesh|dolly|radhakishan|damani|bhaiya|siddhartha)'?s?\s+(portfolio|picks?|stocks?)",
    r"billionaire\s+investor",
    r"big\s+bull'?s?\s+(portfolio|picks?|stocks?)",
    r"(fund\s+manager|investor)\s+(interview|profile|lessons)",
    r"investment\s+(guru|legend|icon)",
    r"(would\s+have\s+been|could\s+have\s+been).*investor",
    
    # =========================================================================
    # SPORTS / IPL / ENTERTAINMENT SPONSORSHIP (NEW)
    # Catches: IPL team news, cricket mentions with sponsors
    # Note: Chess, marathons, etc. are handled by LLM in Step 10: LLM Layer 1
    # =========================================================================
    r"ipl\s+(team|squad|auction|mega|retention|player)",
    r"(full\s+)?squad\s+.*\s+(ipl|cricket|t20)",
    r"(csk|rcb|mi|kkr|srh|dc|pbks|gt|lsg|rr)\s+(team|squad|player|auction)",
    r"chennai\s+super\s+kings",
    r"mumbai\s+indians?",
    r"royal\s+challengers",
    r"kolkata\s+knight\s+riders?",
    r"(cricket|cricketer).*\s+(opens?\s+up|reveals?|speaks?)",
    r"(kuldeep|virat|rohit|dhoni).*\s+(buzz|future|contract)",
    r"ipl\s+\d{4}\s*:?\s*(full\s+)?squad",
    
    # =========================================================================
    # INSTITUTIONAL OWNERSHIP / SHAREHOLDING (NEW)
    # Catches: FII/DII buying, institutional stake changes, shareholder articles
    # =========================================================================
    r"(institutions?|fii|dii)\s+(profited|gained|lost)",
    r"market\s+cap\s+(rose|fell|increased|decreased).*\s+(last|this)\s+week",
    r"(purchases?|buys?|sells?)\s+\d+[,\d]*\s+shares?\s+of",
    r"(raises?|increases?|cuts?|reduces?)\s+(position|stake)\s+in",
    r"shareholding\s+pattern",
    r"(promoter|institutional|fii|dii)\s+stake",
    r"insider\s+(selling|buying)\s*:",
    r"(insiders?|promoters?)\s+(sold|bought|acquired|divested)",
    
    # =========================================================================
    # PERSONAL ADVICE / CONSUMER FORUM POSTS (NEW - Jan 2026)
    # Catches: "Hi, I am confused between...", "I'm planning to buy..."
    # These are personal advice seekers, not news articles
    # =========================================================================
    r"^(Hi[,.]?\s*)?I\s*(am|'m)\s*(confused|planning|looking).*between",
    r"^Hi[,.]?\s*I'?m?\s+a\s+first[-\s]?time\s+(car\s+)?buyer",
    
    # =========================================================================
    # ROUTINE NSE/BSE CERTIFICATE FILINGS (NEW - Jan 2026)
    # Catches: "[NSE] - Certificate under SEBI..."
    # These are administrative compliance filings
    # =========================================================================
    r"\[NSE\]\s*-\s*Certificate\s+under\s+SEBI",
    r"\[BSE\]\s*-\s*Certificate\s+under\s+SEBI",
    
    # =========================================================================
    # BROKER CALL HEADLINES (NEW - Jan 2026)
    # Catches: "Broker's call: Tata Motors (CV): (Add)"
    # Brief recommendations without substance
    # =========================================================================
    r"Broker'?s?\s+call\s*:",
    
    # =========================================================================
    # SESSION STREAK PRICE ARTICLES (NEW - Jan 2026)
    # Catches: "rises for fifth straight session", "up for third session", "gains for fifth session"
    # Pure price movement articles
    # =========================================================================
    r"\b(up|rises?|soars?|falls?|drops?|gains?)\s+for\s+(fifth|fourth|third|second|sixth|seventh|\d+)(st|nd|rd|th)?\s+(straight\s+)?sessions?",
    
    # =========================================================================
    # BOARD MEETING SCHEDULING ANNOUNCEMENTS (NEW - Jan 2026)
    # Catches: "Board to Consider Q3 Results", "Schedules Board Meeting for"
    # Routine scheduling announcements, not material business news
    # =========================================================================
    r"Board\s+(to\s+)?Consider\s+(Unaudited\s+)?Financial\s+Results",
    r"Board\s+(to\s+)?Consider\s+(Q[1-4]|Quarterly).*Results",
    r"Board\s+Meeting\s+(Scheduled|to\s+be\s+held)\s+(for|on)",
    r"Schedules\s+Board\s+Meeting\s+(for|on)\s+",
    r"Board\s+(to\s+)?Consider\s+Interim\s+Dividend",
    r"to\s+hold\s+board\s+meeting",

    # =========================================================================
    # SPAM PROMOTIONAL PHRASES (NEW - Jan 2026)
    # Catches: "Free Triple", "Build Wealth With", "Next-Level"
    # Promotional/spam content indicators
    # =========================================================================
    r"Free\s+Triple",
    r"Your\s+Free\s+Entry",
    r"Build\s+Wealth\s+With",
    r"Next[-\s]?Level\s+(Gains?|Returns?|Portfolio)",
    
    # =========================================================================
    # CHESS TOURNAMENT SPONSORSHIP (NEW - Jan 2026)
    # Catches: "Tata Steel Chess 2026", chess rapid/blitz mentions
    # Sports sponsorship, not about company operations
    # =========================================================================
    r"Tata\s+Steel\s+(Chess|Rapid|Blitz)",
    r"\bchess.*(rapid|blitz|tournament|championship)",
    r"(Anand|Carlsen|Caruana|Gukesh|Pragg|Vidit)\s+.*(chess|tournament|rapid|blitz)",
    
    # =========================================================================
    # SPAM PLACEHOLDER TITLES (NEW - Jan 2026)
    # Catches: "UnlistedZone - UnlistedZone"
    # Garbage/placeholder titles from scraper issues
    # =========================================================================
    r"^UnlistedZone\s*-\s*UnlistedZone",
    
    # =========================================================================
    # ADDITIONAL SPORTS SPONSORSHIP (NEW - Jan 2026)
    # Catches: kabaddi, football league sponsorship mentions
    # =========================================================================
    r"\b(pkl|pro\s+kabaddi|kabaddi\s+league)\b",
    r"\b(isl|indian\s+super\s+league|football\s+league)\s+(team|squad|match)",
    r"\b(marathon|half[-\s]?marathon|run|race)\s+(sponsor|title\s+sponsor|powered\s+by)",
    r"(title|principal|lead)\s+sponsor\s+(for|of)\s+(ipl|pkl|isl|marathon)",
    
    # =========================================================================
    # PRODUCT REVIEWS / LIFESTYLE / CONSUMER GUIDES (NEW - Jan 2026)
    # Catches: "Best Running Spikes", "How to Play Pickleball", "7 Best X"
    # These are product marketing/consumer guides, not material business news
    # =========================================================================
    r"safest\s+(travel\s+)?destinations?",  # "This European country tops 2026 list of world's safest travel destinations"
    r"(best|top)\s+(travel\s+)?destinations?\s+(for|in)\s+\d{4}",  # "Best Travel Destinations for 2026"
    r"\d+\s+best\s+(running|basketball|tennis|golf|training|hiking|walking|soccer|football)\s+(shoes?|spikes?|cleats?|sneakers?|boots?)",  # "7 Best Running Spikes"
    r"best\s+(running|basketball|tennis|golf)\s+(shoes?|spikes?|gear)",  # "Best Running Shoes"
    r"(how\s+to|tips?\s+for|guide\s+to)\s+(play|start|learn|improve)\s+(pickleball|tennis|golf|basketball|yoga)",  # "How to Play Pickleball"
    r"(pickleball|tennis|golf|yoga|fitness)\s+(strategy|drills?|tips?|lessons?|guide)",  # "Pickleball Strategy"
    r"\d+\s+ways?\s+to\s+(style|wear|use|improve|boost)",  # "5 Ways to Style"
    r"\d+\s+things?\s+to\s+(know|do|try|avoid)\s+(before|when|if)",  # "10 Things to Know Before"
    r"(workout|exercise|fitness|training)\s+(routine|plan|program|tips)",  # Fitness content
    r"(product|gear|equipment)\s+review\s*:",  # "Product Review: X"
    r"(unboxing|first\s+look|hands[-\s]?on)\s+(review|impression)",  # Unboxing/review content
    r"(best|top)\s+\d+\s+(products?|items?|things?|gadgets?)\s+(for|to|in)",  # "Top 10 Products for..."
    r"(must[-\s]?have|essential)\s+(running|training|workout|gym)\s+gear",  # "Must-Have Running Gear"
    r"(style|fashion|outfit)\s+(guide|tips?|ideas?)",  # Fashion/style content
    r"(celebrity|athlete|influencer)\s+(wears?|spotted|seen)\s+(wearing|in)",  # Celebrity wearing X
    r"new\s+(colorway|design|edition)\s+(drops?|launches?|releases?)",  # Product launch marketing
    r"limited[-\s]?edition\s+(sneakers?|shoes?|collection)",  # Limited edition products
    r"(sneaker|shoe)\s+(drop|release|launch)\s+(date|calendar)",  # Sneaker release calendar

    # =========================================================================
    # LOW-SIGNAL SOURCES (title suffix matching)
    # Added Mar 2026 — sources with >=95% LLM rejection rate over 7-day window.
    # These are structurally opinion, advice, PR wires, or non-news content.
    # NOT included: major news outlets (MarketWatch, NDTV Profit) that may
    # occasionally carry material company-specific news.
    # =========================================================================
    r" - Stock Titan$",  # PR distribution wire — corporate press releases (98.5% rejected)
    r" - InvestyWise$",  # Reformatted BSE/NSE disclosure summaries (100% rejected)
    r" - (?:The )?Motley Fool$",  # Investment advice / "should you buy" opinions (100% rejected)
    r" - Insider Monkey$",  # Hedge fund holdings lists / opinion (96.3% rejected)
    r" - Stock Traders Daily$",  # Daily trading wrap / trading advice (100% rejected)
    r" - National Today$",  # Holiday / awareness day content, not business news (100% rejected)
    r" - 24/7 Wall St",  # Clickbait financial listicles (95.0% rejected)
    r" - IPO Watch$",  # IPO listing announcements (100% rejected)
    r" - StreetInsider$",  # Institutional trading data / signals (100% rejected)
    r" - Traders Union$",  # Forex broker reviews / trading education (100% rejected)
    r" - The Hans India$",  # Regional newspaper with low company-specific signal (100% rejected)

    # =========================================================================
    # ISIN / POSTAL BALLOT ARTICLES
    # Added Mar 2026 — 100% LLM rejection rate over 7-day window.
    # ISIN codes in titles indicate stock ticker data articles, not business news.
    # Postal ballot articles are routine corporate governance filings.
    # =========================================================================
    r"\bISIN:\s*[A-Z]{2}[A-Z0-9]{9}\d",  # "Stock (ISIN: US0378331005) Faces..." — ticker data, not news
    r"\bpostal\s+ballot\b",  # "Company Completes Postal Ballot Process" — routine governance filing
]


# =============================================================================
# Veda extensions — added 2026-04-29
# =============================================================================
# Stock-price-commentary patterns that StockClarity's daily-batch model didn't
# need to filter (cohort-level grading caught them) but which dominate the
# noise floor for Veda's per-ticker on-demand fetch. Diagnosed empirically on
# MSFT (33 of 51 surviving items from finance.yahoo.com after the original
# blocklist; mostly Cramer commentary, "Is X a buy?" listicles, and analyst-
# stance churn). Each pattern is conservative — title must look unambiguously
# like commentary, not company news.
#
# These are appended to BLOCKED_TITLE_PATTERNS above before the regex compiles.
_VEDA_EXTENSIONS = [
    # Cramer / personality-driven commentary
    r"\b(jim\s+cramer|cramer)\b",  # "Jim Cramer Reveals...", "Cramer Says..."

    # "Is X a buy?" / "Should you buy X?" rating listicles
    r"\bis\s+\w+\s+(stock|shares?)\s+a\s+(smart|smarter|better|good|great|safe|risky)\s+(buy|sell|hold)\b",
    r"\bshould\s+you\s+(buy|sell|hold)\b.*\b(stock|shares?)\b",
    r"\bsmart(er)?\s+buy\s+than\b",

    # Earnings-preview / "what to expect" commentary (not the actual results)
    r"\bearnings\s+preview\b",
    r"\bearnings?\s+(expected|projected|forecast)\s+to\s+(grow|rise|fall|drop|move)\b",
    r"\b(here'?s\s+)?(how\s+much|why)\s+\w+\s+(stock|shares?)\s+(is|are|could|might|may)\s+(expected|likely)\s+to\s+(move|jump|gain|fall|drop)\b",
    r"\bafter\s+earnings\b.*\b(expect|move|preview)\b",

    # "Stock is up/down today" — generic intraday commentary
    r"\b(why|here'?s why)\s+\w+\s+(stock|shares?)\s+(is|are)\s+(up|down|rising|falling)\s+(today|now|this\s+(week|month))\b",
    r"\b(stock|shares?)\s+(is|are)\s+up\s+today\b",

    # Analyst-stance churn (price target maintenance, "bullish stance maintained")
    r"\b(maintains?|reiterates?|keeps?|sustains?)\s+(bullish|bearish|buy|sell|hold|outperform|underperform|overweight)\s+(stance|rating|view|on)\b",
    r"\b(price\s+target|pt)\s+(raised|cut|lowered|maintained|reiterated)\b",
    r"\bgoldman\s+sachs\b.*\b(bullish|bearish|maintains?)\b",  # "Goldman Sachs Maintains Bullish Stance on..."

    # Multi-ticker listicles (MAG 7, FAANG, "top 5 stocks", etc.)
    r"\bmag(nificent)?\s*(7|seven)\b",  # MAG 7 / Magnificent 7
    r"\bfaang\b",
    r"\b(top|best|hot|hottest|smart|smartest)\s+\d+\s+(stocks?|picks?|names?|ai\s+stocks?)\s+(to\s+(buy|watch|consider|own)|for)\b",
    r"\bstocks?\s+to\s+(buy|watch|consider)\s+(this|next)\s+(week|month|quarter|year)\b",

    # Hedge-fund / billionaire / Insider Monkey style "X favorite" listicles
    r"\b(hedge\s+fund|billionaire)\s+(favorites?|picks?|holdings?|portfolio)\b",
    r"\baccording\s+to\s+billionaire\b",
    r"\binsider\s+monkey\b",

    # Stock-movement speculation (chart-watching, breakout, rally commentary)
    r"\b(verge|brink)\s+of\s+(a\s+)?(big\s+)?(breakout|breakdown|rally|reversal|rebound)\b",
    r"\b(quietly|secretly)\s+turning\b",  # "Is X Quietly Turning... Into Its Next..."
    r"\b\d+\s*%\s+(rally|rebound|gain|drop|fall|surge|crash)\b",  # "250% Rally", "30% Rebound"
    r"\bpricing\s+attractive\s+after\b",  # "Pricing Attractive After Recent X% Rebound"

    # Generic "stock is up / what you need to know" filler
    r"\bstock\s+is\s+up,?\s+what\s+you\s+need\s+to\s+know\b",
    r"\bwhat\s+you\s+need\s+to\s+know\s+about\s+\w+\s+(stock|shares?)\b",

    # AI-stock listicles (sector-level commentary, not company news)
    r"\bbest\s+ai\s+stock\b",
    r"\b(buy|sell|hold)\s+\w+\s+on\s+ai\s+(disruption|fears?|hype)\b",
]

# Append Veda extensions to the main pattern list before regex compilation.
BLOCKED_TITLE_PATTERNS.extend(_VEDA_EXTENSIONS)


# =============================================================================
# Compiled regex + filter function
# =============================================================================

_BLOCKED_TITLE_REGEX = re.compile(
    "|".join(f"({p})" for p in BLOCKED_TITLE_PATTERNS),
    re.IGNORECASE,
)


def _normalize_publisher(url: str) -> str:
    """Return the registrable domain (no www, lowercased) for blocklist match."""
    if not url:
        return ""
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def is_spam(url: str, title: str, publisher_override: str = "") -> Tuple[bool, str]:
    """Return ``(is_spam, reason)`` for a candidate article.

    ``reason`` is one of:
      - ``"blocked_domain"`` — publisher is in BLOCKED_DOMAINS (or a subdomain of one)
      - ``"blocked_title_pattern"`` — title matches the BLOCKED_TITLE_REGEX
      - ``""`` — passed both layers

    ``publisher_override`` lets callers pass a publisher domain directly when
    they've already resolved it (e.g., from feedparser's ``entry.source`` for
    Google News items, where the article URL is a tracking redirect that does
    NOT reveal the actual publisher). When provided, it takes precedence over
    URL-derived publisher.
    """
    publisher = (publisher_override or "").lower().strip()
    if not publisher:
        publisher = _normalize_publisher(url)
    if publisher:
        if publisher in BLOCKED_DOMAINS:
            return True, "blocked_domain"
        # Match subdomain of a blocked publisher (e.g., "in.marketwatch.com")
        for blocked in BLOCKED_DOMAINS:
            if publisher.endswith("." + blocked):
                return True, "blocked_domain"

    if title and _BLOCKED_TITLE_REGEX.search(title):
        return True, "blocked_title_pattern"

    return False, ""

