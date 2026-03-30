import os
import time
import smtplib
import requests
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
WATCHLIST = [
    # AI & Tech
    "NVDA", "MSFT", "GOOGL", "META", "AMZN", "AMD", "TSM", "PLTR", "TSLA", "INTC", "ANET",
    # Geopolitical / Iran-war sensitive
    "XOM", "CVX", "LMT", "RTX", "NOC", "GD", "USO",
]

GROQ_API_KEY       = os.environ.get("GROQ_API_KEY")
FINNHUB_API_KEY    = os.environ.get("FINNHUB_API_KEY")
EMAIL_SENDER       = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD     = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER     = os.environ.get("EMAIL_RECEIVER")


# ─────────────────────────────────────────
# SOURCE 1 — Yahoo Finance RSS (headlines)
# ─────────────────────────────────────────
def fetch_yahoo_news(ticker: str) -> list:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.text)
        items = root.findall(".//item")
        news = []
        for item in items[:4]:
            title = item.findtext("title", "").strip()
            desc  = item.findtext("description", "").strip()
            pub   = item.findtext("pubDate", "").strip()
            news.append(f"[Yahoo] {title} | {desc[:150]} ({pub})")
        return news
    except Exception as e:
        print(f"    Yahoo failed for {ticker}: {e}")
        return []


# ─────────────────────────────────────────
# SOURCE 2 — Finnhub (news + insider + earnings + sentiment)
# ─────────────────────────────────────────
def fetch_finnhub_news(ticker: str) -> list:
    if not FINNHUB_API_KEY:
        return []
    try:
        today     = datetime.now().strftime("%Y-%m-%d")
        week_ago  = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={week_ago}&to={today}&token={FINNHUB_API_KEY}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        articles = resp.json()[:4]
        news = []
        for a in articles:
            headline = a.get("headline", "")
            summary  = a.get("summary", "")[:150]
            news.append(f"[Finnhub] {headline} | {summary}")
        return news
    except Exception as e:
        print(f"    Finnhub news failed for {ticker}: {e}")
        return []


def fetch_finnhub_sentiment(ticker: str) -> str:
    if not FINNHUB_API_KEY:
        return ""
    try:
        url = f"https://finnhub.io/api/v1/news-sentiment?symbol={ticker}&token={FINNHUB_API_KEY}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        score = data.get("companyNewsScore", None)
        buzz  = data.get("buzz", {}).get("buzz", None)
        if score is not None:
            sentiment = "Positive" if score > 0.6 else "Negative" if score < 0.4 else "Neutral"
            return f"[Sentiment] Score: {score:.2f} ({sentiment}) | Buzz level: {buzz:.2f}" if buzz else f"[Sentiment] Score: {score:.2f} ({sentiment})"
        return ""
    except Exception as e:
        print(f"    Finnhub sentiment failed for {ticker}: {e}")
        return ""


def fetch_finnhub_insider(ticker: str) -> list:
    if not FINNHUB_API_KEY:
        return []
    try:
        url = f"https://finnhub.io/api/v1/stock/insider-transactions?symbol={ticker}&token={FINNHUB_API_KEY}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])[:3]
        trades = []
        for t in data:
            name   = t.get("name", "Unknown")
            change = t.get("change", 0)
            price  = t.get("transactionPrice", 0)
            action = "BOUGHT" if change > 0 else "SOLD"
            shares = abs(change)
            trades.append(f"[Insider] {name} {action} {shares:,} shares @ ${price:.2f}")
        return trades
    except Exception as e:
        print(f"    Finnhub insider failed for {ticker}: {e}")
        return []


def fetch_finnhub_earnings(ticker: str) -> str:
    if not FINNHUB_API_KEY:
        return ""
    try:
        today    = datetime.now().strftime("%Y-%m-%d")
        two_weeks = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/calendar/earnings?from={today}&to={two_weeks}&symbol={ticker}&token={FINNHUB_API_KEY}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        earnings = resp.json().get("earningsCalendar", [])
        if earnings:
            e = earnings[0]
            date   = e.get("date", "")
            est    = e.get("epsEstimate", "N/A")
            actual = e.get("epsActual", "TBD")
            return f"[Earnings] Date: {date} | EPS Estimate: {est} | Actual: {actual}"
        return ""
    except Exception as e:
        print(f"    Finnhub earnings failed for {ticker}: {e}")
        return ""

# ─────────────────────────────────────────
# COMPILE ALL DATA PER TICKER
# ─────────────────────────────────────────
def fetch_all_data(ticker: str) -> str:
    print(f"  → {ticker}")
    lines = []

    yahoo     = fetch_yahoo_news(ticker)
    finnhub   = fetch_finnhub_news(ticker)
    sentiment = fetch_finnhub_sentiment(ticker)
    insider   = fetch_finnhub_insider(ticker)
    earnings  = fetch_finnhub_earnings(ticker)

    lines += yahoo
    lines += finnhub
    if sentiment: lines.append(sentiment)
    if premarket: lines.append(premarket)
    if earnings:  lines.append(earnings)
    lines += insider

    if not lines:
        return f"## {ticker}\nNo data available.\n"

    block = f"## {ticker}\n"
    for l in lines:
        block += f"- {l}\n"
    return block


# ─────────────────────────────────────────
# GROQ ANALYSIS
# ─────────────────────────────────────────
def analyze_with_groq(all_data: str) -> str:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY environment variable not set.")

    today = datetime.now().strftime("%A, %B %d %Y")

    prompt = f"""You are a professional trading analyst AI covering two different trading styles.
Today is {today}.

You have access to rich data per stock including:
- News headlines from Yahoo Finance and Finnhub
- Sentiment scores and buzz levels
- Pre-market price data
- Upcoming earnings dates and EPS estimates
- Insider buying and selling activity

Analyze all the data below and write a report in TWO clearly separated parts:

════════════════════════════════════════
PART 1 — SWING TRADER REPORT
════════════════════════════════════════
Trading style: holds positions days to weeks, identifies demand zones,
sets buy limit orders, does NOT day trade or scalp.

1. 📅 WEEKLY BIAS
Overall market direction for the coming days — bullish, bearish, or ranging.
Are conditions good for swing entries or should I wait?

2. 🔥 TOP 5 SWING SETUPS THIS WEEK
Top 5 stocks most likely to make a significant move in the next 2-5 days.
For each: what's driving the move, what price area to watch, insider activity if any.

3. 📊 SWING BREAKDOWN — STOCK BY STOCK
For each ticker with meaningful data:
- Sentiment: 🟢 Bullish / 🔴 Bearish / 🟡 Neutral
- One line news summary
- SWING SETUP: Is trend intact? Approaching demand zone?
- INSIDER SIGNAL: Any notable insider buying or selling?
- THESIS CHECK: Does today's data support or threaten a long position?

4. ⚠️ DEMAND ZONE THREATS
Stocks at risk of breaking below demand zones violently.
Flag earnings surprises, macro shocks, heavy insider selling.
Remove buy limit orders on these immediately.

5. 📰 CATALYST CALENDAR — NEXT 7 DAYS
Upcoming earnings with EPS estimates, Fed events, product launches.
Know these before entering any swing position.

6. 🧠 WEEKEND WATCHLIST PREP
Top 3 stocks worth deep chart analysis this weekend.
For each: why interesting, what price area to watch, insider context.

════════════════════════════════════════
PART 2 — SCALPER / DAY TRADER REPORT
════════════════════════════════════════
Trading style: enters and exits same day, wants volatility,
wants to know which stocks are moving TODAY and why,
looks for momentum, news catalysts, volume spikes, and pre-market movers.

1. ⚡ TODAY'S TOP 5 VOLATILE STOCKS
The 5 stocks most likely to make big intraday moves TODAY.
For each: expected move size, what's driving it, direction bias, pre-market price if available.

2. 🎯 SCALP SETUPS
For each high volatility stock:
- Direction bias: Long or Short
- What to watch for as entry trigger
- Key intraday levels to be aware of
- Risk: what would invalidate this setup

3. 📰 NEWS CATALYSTS TODAY
Specific breaking news TODAY that could cause sudden spikes.
Include exact times EST if known.

4. 🔴 STOCKS TO AVOID TODAY
Stocks dangerous for scalping — low volume, unpredictable news,
earnings tonight (gap risk), wide spreads. Stay away.

5. ⏰ KEY TIMES TODAY
Important scheduled events with exact times EST —
economic data, Fed speakers, earnings calls, option expiries.

Be direct and actionable. Part 1 is for multi-day thinking.
Part 2 is for today only — intraday, fast, ruthless.
No fluff. No disclaimers.

---
MARKET DATA:
{all_data}
"""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json"
    }

    payload = {
        "model":       "llama-3.3-70b-versatile",
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens":  4096
    }

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=60
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ─────────────────────────────────────────
# SEND EMAIL
# ─────────────────────────────────────────
def send_email(report: str):
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        print("⚠️  Email credentials not set — printing to console.\n")
        print(report)
        return

    today   = datetime.now().strftime("%b %d, %Y")
    subject = f"📈 Morning Stock Report — {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECEIVER

    html_body = f"""
    <html><body style="font-family:monospace;background:#0f0f0f;color:#e0e0e0;padding:24px;max-width:760px;margin:auto;">
    <h2 style="color:#00e5a0;border-bottom:1px solid #333;padding-bottom:8px;">
        📈 Morning Stock Report — {today}
    </h2>
    <pre style="white-space:pre-wrap;font-size:13.5px;line-height:1.75;">{report}</pre>
    <p style="color:#555;font-size:12px;margin-top:32px;">
        Generated automatically · Sources: Yahoo Finance, Finnhub · Not financial advice.
    </p>
    </body></html>
    """

    msg.attach(MIMEText(report, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())

    print(f"✅ Report sent to {EMAIL_RECEIVER}")


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    print(f"🔍 Fetching data for {len(WATCHLIST)} stocks from 3 sources...")
    all_data = ""
    for ticker in WATCHLIST:
        all_data += fetch_all_data(ticker)
        time.sleep(0.5)  # gentle delay between tickers

    print("\n🤖 Analyzing with Groq AI...")
    report = analyze_with_groq(all_data)

    print("\n📧 Sending email report...")
    send_email(report)
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
