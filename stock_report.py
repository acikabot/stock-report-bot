import os
import json
import smtplib
import requests
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─────────────────────────────────────────
# CONFIG — edit these values
# ─────────────────────────────────────────
WATCHLIST = [
    # AI & Tech
    "NVDA", "MSFT", "GOOGL", "META", "AMZN", "AMD", "TSM", "PLTR", "TSLA", "INTC", "ANET",
    # Geopolitical / Iran-war sensitive
    "XOM", "CVX", "LMT", "RTX", "NOC", "GD", "USO",
]

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_SENDER   = os.environ.get("EMAIL_SENDER")    # your Gmail address
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")  # Gmail app password
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")  # where to send the report


# ─────────────────────────────────────────
# STEP 1 — Fetch news from Yahoo Finance RSS
# ─────────────────────────────────────────
def fetch_news(ticker: str) -> list[dict]:
    """Fetch latest news headlines for a ticker via Yahoo Finance RSS."""
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.text)
        items = root.findall(".//item")
        news = []
        for item in items[:5]:  # top 5 headlines per stock
            title = item.findtext("title", "").strip()
            desc  = item.findtext("description", "").strip()
            pub   = item.findtext("pubDate", "").strip()
            news.append({"title": title, "description": desc, "published": pub})
        return news
    except Exception as e:
        print(f"  [!] Failed to fetch news for {ticker}: {e}")
        return []


# ─────────────────────────────────────────
# STEP 2 — Analyze with Gemini (free API)
# ─────────────────────────────────────────
def analyze_with_gemini(watchlist_news: dict) -> str:
    """Send all news to Gemini and get a structured morning report."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY environment variable not set.")

    # Build prompt
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
    prompt = f"""You are a professional stock market analyst AI. 
Today is {today}.

Below is the latest news for a watchlist of stocks. The watchlist contains:
- AI & Tech stocks: NVDA, MSFT, GOOGL, META, AMZN, AMD, TSM, PLTR, TSLA, INTC, ANET
- Geopolitical/Iran-war sensitive stocks: XOM, CVX, LMT, RTX, NOC, GD, USO

Your job is to write a clean, insightful MORNING REPORT with these sections:

1. 🌍 MACRO OVERVIEW — Any big geopolitical or macro themes today (Iran, oil, Fed, etc.)
2. 🤖 AI & TECH SUMMARY — Key moves/news in the tech/AI space
3. ⚔️ GEOPOLITICAL WATCH — Iran war impact on oil/defense stocks
4. 📊 STOCK-BY-STOCK BREAKDOWN — For each ticker with news: sentiment (🟢 Bullish / 🔴 Bearish / 🟡 Neutral), one-line summary, and any action to watch
5. ⚡ TOP 3 THINGS TO WATCH TODAY — The most important catalysts for the day
6. ⚠️ RISK FLAGS — Anything that could hurt positions today

Be concise, direct, and actionable. Use bullet points. No fluff.

---
NEWS DATA:
{news_text}
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2048}
    }

    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


# ─────────────────────────────────────────
# STEP 3 — Send email
# ─────────────────────────────────────────
def send_email(report: str):
    """Send the morning report via Gmail."""
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        print("⚠️  Email credentials not set — printing report to console instead.\n")
        print(report)
        return

    today = datetime.now().strftime("%b %d, %Y")
    subject = f"📈 Morning Stock Report — {today}"

    # Plain text version
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECEIVER

    # HTML version for nicer formatting
    html_body = f"""
    <html><body style="font-family: monospace; background:#0f0f0f; color:#e0e0e0; padding:24px; max-width:700px; margin:auto;">
    <h2 style="color:#00e5a0; border-bottom:1px solid #333; padding-bottom:8px;">
        📈 Morning Stock Report — {today}
    </h2>
    <pre style="white-space:pre-wrap; font-size:14px; line-height:1.7;">{report}</pre>
    <p style="color:#555; font-size:12px; margin-top:32px;">
        Generated automatically by your AI Stock Reporter · Not financial advice.
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

    print("\n🤖 Analyzing with Gemini AI...")
    report = analyze_with_gemini(watchlist_news)

    print("\n📧 Sending email report...")
    send_email(report)


if __name__ == "__main__":
    main()
