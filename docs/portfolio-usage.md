# Your portfolio: quick guide

[Open your portfolio](https://docs.google.com/spreadsheets/d/1vyQj_XqcAgfgwNxgBVTxP8Yps0jxYJic8dA_ltTb_2E/edit?gid=941942549#gid=941942549)

## 1. Update it each day

Run StockClarity as usual first. Then open PowerShell and run:

```powershell
cd C:\Users\ankur\Downloads\Veda-advisor
.\.venv\Scripts\python.exe scripts\portfolio.py update
```

If the Kite session has expired, log in, complete the browser step, then run the update again:

```powershell
.\.venv\Scripts\python.exe scripts\portfolio.py login
```

The command asks: `Update US portfolio market values too? ... [y/N]`.
Enter `y` or `yes` to include the US refresh. Enter `n` or press Enter to update
India only. Without an answer, US is skipped. US refreshes use the quantities,
purchase costs and cash you maintain in the sheet; Zerodha supplies India only.

This routine updates the sheet. It does not run a portfolio review or place trades.

## 2. Know what to maintain

| Where | What you do |
| --- | --- |
| **Portfolio Summary** | Nothing required. Use **B2** to choose INR or USD. Totals, allocations and exchange rate update automatically. |
| **India Portfolio** | Zerodha/Coin is authoritative for holdings, Status, purchase costs and broker cash. Held positions become Invested; absent or zero-quantity positions become Exited with zero quantity. Maintain Sector, My Thesis Conviction, My Sell Condition and My Action. |
| **US Portfolio** | When holdings change, update quantities and USD average purchase prices. Update combined Vested + Fidelity cash in **D5**, and the date you confirmed holdings/cash in **P8**. Maintain the same personal fields as India. |

Prices/NAVs, market cap and P/E update where applicable. Funds and ETFs do not receive company P/E figures. US broker exports are not needed for daily updates.

Your manual fields and thesis notes are preserved. Hover over a conviction cell to read any saved thesis and assumptions. Enter Microsoft's USD average purchase price when its USD cost basis is available; its return remains blank until then.

## 3. Ask for a portfolio review

Open the **Veda-advisor** repo in Codex and ask:

> Use $portfolio-review to review my portfolio. Start with the overall portfolio, then review India and US stocks. Give a Buy, Hold or Sell for every stock, with brief reasons and sources. Keep suggestions in chat.

The skill starts with Portfolio Summary, independently researches the companies, and checks exits, buying opportunities and portfolio balance. You can ask for **India only** or **US only** instead.

It uses your conviction, thesis notes and sell conditions. StockClarity's thesis status and signal remain informational and are excluded from its decisions. Recommendations stay in chat; **you decide whether to change My Action or trade**.

## 4. Your agreed review rules

- Check integrity concerns, a thesis broken or played out, valuation, concentration and better opportunities.
- P/E above **150** has a strong sell presumption; above **100 through 150** is a preferred sell. Growth can justify an exception, with evidence.
- Review/trim stocks above **25%** or sectors above **35%**, measured within each market. Also assess combined portfolio concentrations.
- Buy candidates need **High or Medium conviction**, with High preferred, plus supporting business and valuation evidence.
- Fund buys from that market's existing broker cash only. Keep India and US cash budgets separate.

## 5. Avoid accidental problems

- India Status follows Zerodha/Coin automatically. Maintain US Status after buying or exiting.
- Keep existing column headers and formulas intact. Ask before sorting portfolio rows: the ideas-tab conviction links use cell addresses.
- If you see **Unavailable** or an update error, check the message or ask for help. Do not fill gaps with guessed values.
- Check refresh/source dates. Prices and NAVs may predate the update; the FX calculation date is not the quote's timestamp.
- Ask for classification support when adding a different ETF or a new asset class.

Detailed rules: [portfolio-review skill](../.agents/skills/portfolio-review/SKILL.md). Technical reference: [portfolio tracker](portfolio-tracker.md).
