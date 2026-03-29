import os
import time
import smtplib
import requests
from datetime import datetime
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

GROQ_API_KEY   = os.environ.get("GROQ_API_KEY")
EMAIL_SENDER   = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")


# ─────────────────────────────────────────
# STEP 1 — Fetch news from Yahoo Finance RSS
# ─────────────────────────────────────────
def fetch_news(ticker: str) -> list:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.text)
        items = root.findall(".//item")
        news = []
        for item in items[:5]:
            title = item.findtext("title", "").strip()
            desc  = item.findtext("description", "").strip()
            pub   = item.findtext("pubDate", "").strip()
            news.append({"title": title, "description": desc, "published": pub})
        return news
    except Exception as e:
        print(f"  [!] Failed to fetch news for {ticker}: {e}")
        return []


# ─────────────────────────────────────────
# STEP 2 — Analyze with Groq (free & fast)
# ─────────────────────────────────────────
def analyze_with_groq(watchlist_news: dict) -> str:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY environment variable not set.")

    # Build news text
    news_text = ""
    for ticker, articles in watchlist_news.items():
        news_text += f"\n\n## {ticker}\n"
        if not articles:
            news_text += "No news found.\n"
        for a in articles:
            news_text += f"- {a['title']} ({a['published']})\n"
            if a['description']:
                news_text += f"  {a['description'][:200]}\n"

    today = datetime.now().strftime("%A, %B %d %Y")

    prompt = f"""You are a professional swing and position trading analyst AI.
Today is {today}.

My trading style:
- I am a swing/position trader, holding trades for days to weeks
- I identify demand zones on charts and set buy limit orders there
- I do NOT day trade or scalp
- I want to know if my longer term thesis on a stock is still valid
- I want to know which stocks are setting up for a big move this week

Analyze the news below and write a MORNING REPORT with these exact sections:

1. 📅 WEEKLY BIAS
Overall market direction bias for the coming days — bullish, bearish, or ranging.
Are conditions good for swing entries or should I wait?

2. 🔥 VOLATILITY WATCHLIST
List the top 5 stocks from my watchlist most likely to make a significant 
move in the next 2-5 days and WHY. Include what's driving the expected move.

3. 📊 STOCK-BY-STOCK BREAKDOWN
For each ticker with news:
- Sentiment: 🟢 Bullish / 🔴 Bearish / 🟡 Neutral
- One line summary of what's happening
- SWING SETUP: Is this stock approaching a potential demand zone? 
  Is the trend intact? Any reason to avoid or watch closely?
- THESIS CHECK: Does today's news support or threaten a long position?

4. ⚠️ DEMAND ZONE THREATS
Any news that could cause a stock to BREAK BELOW a demand zone violently —
earnings surprises, macro shocks, sector bad news, geopolitical escalation.
These are stocks to remove buy limit orders from immediately.

5. 📰 CATALYST CALENDAR
Any upcoming events in the next 7 days that could cause big moves —
earnings dates, Fed meetings, product launches, economic data releases.
These are dates to be aware of before entering a swing position.

6. 🧠 WEEKEND WATCHLIST PREP
Top 3 stocks worth doing deep chart analysis on this weekend.
For each: why it's interesting, what price area to watch, what the setup could be.

Be direct and actionable. Write for a swing trader, not a day trader.
No intraday noise. Focus on multi-day and multi-week moves only.

---
NEWS DATA:
{news_text}
"""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.4,
        "max_tokens": 2048
    }

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=60
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ─────────────────────────────────────────
# STEP 3 — Send email
# ─────────────────────────────────────────
def send_email(report: str):
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        print("⚠️  Email credentials not set — printing report to console instead.\n")
        print(report)
        return

    today = datetime.now().strftime("%b %d, %Y")
    subject = f"📈 Morning Stock Report — {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECEIVER

    html_body = f"""
    <html><body style="font-family:monospace;background:#0f0f0f;color:#e0e0e0;padding:24px;max-width:700px;margin:auto;">
    <h2 style="color:#00e5a0;border-bottom:1px solid #333;padding-bottom:8px;">
        📈 Morning Stock Report — {today}
    </h2>
    <pre style="white-space:pre-wrap;font-size:14px;line-height:1.7;">{report}</pre>
    <p style="color:#555;font-size:12px;margin-top:32px;">
        Generated automatically · Not financial advice.
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
    print(f"🔍 Fetching news for {len(WATCHLIST)} stocks...")
    watchlist_news = {}
    for ticker in WATCHLIST:
        print(f"  → {ticker}")
        watchlist_news[ticker] = fetch_news(ticker)
        time.sleep(0.3)

    print("\n🤖 Analyzing with Groq AI...")
    report = analyze_with_groq(watchlist_news)

    print("\n📧 Sending email report...")
    send_email(report)


if __name__ == "__main__":
    main()
