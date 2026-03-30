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

    prompt = f"""You are a professional trading analyst AI covering two different trading styles.
Today is {today}.

Analyze the news below and write a report in TWO clearly separated parts:

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
For each: what's driving the move and what price area to watch.

3. 📊 SWING BREAKDOWN — STOCK BY STOCK
For each ticker with news:
- Sentiment: 🟢 Bullish / 🔴 Bearish / 🟡 Neutral
- One line news summary
- SWING SETUP: Is trend intact? Approaching demand zone?
- THESIS CHECK: Does news support or threaten a long position?

4. ⚠️ DEMAND ZONE THREATS
Stocks at risk of breaking below demand zones violently.
Remove buy limit orders on these immediately.

5. 📰 CATALYST CALENDAR — NEXT 7 DAYS
Upcoming earnings, Fed events, product launches, economic data.
Know these before entering any swing position.

6. 🧠 WEEKEND WATCHLIST PREP
Top 3 stocks worth deep chart analysis this weekend.
For each: why interesting, what price area to watch, what setup could form.

════════════════════════════════════════
PART 2 — SCALPER / DAY TRADER REPORT
════════════════════════════════════════
Trading style: enters and exits same day, wants volatility,
wants to know which stocks are moving TODAY and why,
looks for momentum, news catalysts, and volume spikes.

1. ⚡ TODAY'S TOP 5 VOLATILE STOCKS
The 5 stocks most likely to make big intraday moves TODAY.
For each: expected move size, what's driving it, direction bias.

2. 🎯 SCALP SETUPS
For each high volatility stock:
- Direction bias: Long or Short
- What to watch for as entry trigger
- Key intraday levels to be aware of
- Risk: what would invalidate this setup

3. 📰 NEWS CATALYSTS TODAY
Any specific news breaking TODAY that could cause sudden spikes —
earnings releases, economic data drops, Fed speakers, geopolitical events.
Include exact times if known.

4. 🔴 STOCKS TO AVOID TODAY
Stocks that look dangerous for scalping — low volume, unpredictable news,
wide spreads, earnings tonight (gap risk). Stay away from these.

5. ⏰ KEY TIMES TODAY
Important scheduled events with exact times EST that could move markets —
economic data releases, Fed speakers, earnings calls, option expiries.

Be direct and actionable. Part 1 is for multi-day thinking. 
Part 2 is for today only — intraday, fast, ruthless.
No fluff. No disclaimers.

---
NEWS DATA:
{news_text}

FORMAT RULES — follow these strictly:
- Do NOT use ** for bold, do NOT use ## for headers
- Use ALL CAPS for section headers instead
- Use ► for bullet points
- Use === as dividers between sections
- Use PART 1 and PART 2 as clear separators
- Keep lines under 65 characters so they wrap cleanly in email
- Use emoji as visual anchors at the start of each section

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
