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
WATCHLIST = ["TQQQ"]

GROQ_API_KEY       = os.environ.get("GROQ_API_KEY")
FINNHUB_API_KEY    = os.environ.get("FINNHUB_API_KEY")
EMAIL_SENDER       = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD     = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER     = ["arotondi@airamcapital.com", "aistockreports@gmail.com"]


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
    insider   = fetch_finnhub_insider(ticker)
    earnings  = fetch_finnhub_earnings(ticker)

    lines += yahoo
    lines += finnhub
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

My trading style for this report:
- Trader uses TQQQ only
- Sells Cash Secured Puts (CSP) and Covered Calls (CC)
- Needs to know: is the trend bullish or bearish this week?
- Key support levels where selling puts would be safe
- Key resistance levels where selling covered calls makes sense
- Any macro events or volatility spikes that could blow through option positions
- VIX direction — higher VIX = better premiums but more risk
- Overall: is this a good week to be selling options or should he sit out?
---
MARKET DATA:
{all_data}
FORMAT RULES — follow these strictly:
- Do NOT use ** for bold, do NOT use ## for headers
- Use ALL CAPS for section headers instead
- Use ► for bullet points
- Use === as dividers between sections
- Use PART 1 and PART 2 as clear separators
- Use emoji as visual anchors at the start of each section
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
