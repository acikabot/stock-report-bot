import os
import time
import json
import smtplib
import requests
import tempfile
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
GROQ_API_KEY          = os.environ.get("GROQ_API_KEY")
FINNHUB_API_KEY       = os.environ.get("FINNHUB_API_KEY")
EMAIL_SENDER          = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD        = os.environ.get("EMAIL_PASSWORD")
GOOGLE_CREDENTIALS    = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_ID        = os.environ.get("SPREADSHEET_ID")

# Column indexes (0-based)
COL_TIMESTAMP   = 0
COL_NAME        = 1
COL_EMAIL       = 2
COL_TICKERS     = 3
COL_STYLE       = 4
COL_FOCUS       = 5


# ─────────────────────────────────────────
# GOOGLE SHEETS — Read subscribers
# ─────────────────────────────────────────
def get_subscribers() -> list:
    try:
        import google.auth
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds_dict = json.loads(GOOGLE_CREDENTIALS)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(creds_dict, f)
            creds_path = f.name

        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )

        service = build("sheets", "v4", credentials=creds)
        sheet   = service.spreadsheets()
        result  = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range="Form_Responses!A2:F1000"
        ).execute()

        rows = result.get("values", [])
        subscribers = []

        for row in rows:
            while len(row) < 6:
                row.append("")

            email   = row[COL_EMAIL].strip()
            name    = row[COL_NAME].strip()
            tickers = row[COL_TICKERS].strip()
            style   = row[COL_STYLE].strip()
            focus   = row[COL_FOCUS].strip()

            if not email or not tickers:
                continue

            ticker_list = [t.strip().upper() for t in tickers.replace(",", " ").split() if t.strip()]

            subscribers.append({
                "name":    name if name else "Trader",
                "email":   email,
                "tickers": ticker_list,
                "style":   style if style else "Swing Trader",
                "focus":   focus if focus else "",
            })

        print(f"✅ Loaded {len(subscribers)} subscribers from Google Sheet")
        return subscribers

    except Exception as e:
        print(f"❌ Failed to read Google Sheet: {e}")
        return []


# ─────────────────────────────────────────
# SOURCE 1 — Yahoo Finance RSS
# ─────────────────────────────────────────
def fetch_yahoo_news(ticker: str) -> list:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        import xml.etree.ElementTree as ET
        root  = ET.fromstring(resp.text)
        items = root.findall(".//item")
        news  = []
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
# SOURCE 2 — Finnhub
# ─────────────────────────────────────────
def fetch_finnhub_news(ticker: str) -> list:
    if not FINNHUB_API_KEY:
        return []
    try:
        today    = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        url      = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={week_ago}&to={today}&token={FINNHUB_API_KEY}"
        resp     = requests.get(url, timeout=10)
        resp.raise_for_status()
        articles = resp.json()[:4]
        news     = []
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
        url  = f"https://finnhub.io/api/v1/stock/insider-transactions?symbol={ticker}&token={FINNHUB_API_KEY}"
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
        today     = datetime.now().strftime("%Y-%m-%d")
        two_weeks = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        url       = f"https://finnhub.io/api/v1/calendar/earnings?from={today}&to={two_weeks}&symbol={ticker}&token={FINNHUB_API_KEY}"
        resp      = requests.get(url, timeout=10)
        resp.raise_for_status()
        earnings  = resp.json().get("earningsCalendar", [])
        if earnings:
            e      = earnings[0]
            date   = e.get("date", "")
            est    = e.get("epsEstimate", "N/A")
            actual = e.get("epsActual", "TBD")
            return f"[Earnings] Date: {date} | EPS Estimate: {est} | Actual: {actual}"
        return ""
    except Exception as e:
        print(f"    Finnhub earnings failed for {ticker}: {e}")
        return ""


# ─────────────────────────────────────────
# COMPILE DATA PER TICKER
# ─────────────────────────────────────────
def fetch_all_data(ticker: str) -> str:
    lines = []
    lines += fetch_yahoo_news(ticker)
    lines += fetch_finnhub_news(ticker)
    lines += fetch_finnhub_insider(ticker)
    earnings = fetch_finnhub_earnings(ticker)
    if earnings:
        lines.append(earnings)

    if not lines:
        return f"## {ticker}\nNo data available.\n"

    block = f"## {ticker}\n"
    for l in lines:
        block += f"- {l}\n"
    return block


# ─────────────────────────────────────────
# BUILD PROMPT BASED ON TRADING STYLE
# ─────────────────────────────────────────
def build_prompt(all_data: str, subscriber: dict) -> str:
    today   = datetime.now().strftime("%A, %B %d %Y")
    name    = subscriber["name"]
    style   = subscriber["style"].lower()
    focus   = subscriber["focus"]
    tickers = ", ".join(subscriber["tickers"])

    focus_note = f"\nAdditional focus: {focus}" if focus else ""

    format_rules = """
FORMAT RULES — follow these strictly:
- Do NOT use ** for bold, do NOT use ## for headers
- Use ALL CAPS for section headers
- Use ► for bullet points
- Use === as dividers between sections
- Use emoji as visual anchors at the start of each section
- Be direct, specific, and actionable
- No generic statements, no fluff, no disclaimers
"""

    swing_part = """
===================================================
SWING TRADER REPORT
===================================================

📅 WEEKLY BIAS
Overall market direction for the coming days.
Are conditions good for swing entries or should they wait?

🔥 TOP SWING SETUPS THIS WEEK
Top 3 stocks from their watchlist most likely to make
a significant move in 2-5 days. What is driving it
and what price area to watch.

📊 SWING BREAKDOWN — STOCK BY STOCK
For each ticker:
► Sentiment: Bullish / Bearish / Neutral
► One line news summary
► SWING SETUP: Trend intact? Demand zone nearby?
► INSIDER SIGNAL: Any notable buying or selling?
► THESIS CHECK: Does data support or threaten a long?

⚠️ DEMAND ZONE THREATS
Stocks at risk of breaking down violently.
Remove buy limit orders on these immediately.

📰 CATALYST CALENDAR — NEXT 7 DAYS
Upcoming earnings with EPS estimates, Fed events,
key product launches or economic data releases.
Know these before entering any swing position.

🧠 WEEKEND WATCHLIST PREP
Top 2 stocks worth deep chart analysis this weekend.
Why interesting and what price area to watch.
"""

    scalp_part = """
===================================================
SCALPER / DAY TRADER REPORT
===================================================

⚡ TODAY'S TOP VOLATILE STOCKS
Top 3 most likely to make big intraday moves today.
Expected move size, what is driving it, direction bias.

🎯 SCALP SETUPS
For each volatile stock:
► Direction bias: Long or Short
► Entry trigger
► Stop loss level
► Invalidation condition

📰 NEWS CATALYSTS TODAY
Breaking news today that could cause sudden spikes.
Include exact times EST if known.

🔴 STOCKS TO AVOID TODAY
Dangerous for scalping today and why.

⏰ KEY TIMES TODAY EST
Scheduled events that could move markets today.
"""

    # Determine which parts to include based on trading style
    is_swing = "swing" in style
    is_day   = "day" in style or "scalp" in style
    is_both  = is_swing and is_day

    if is_both:
        report_parts = swing_part + "\n" + scalp_part
        style_desc   = "swing trader and day trader"
    elif is_day:
        report_parts = scalp_part
        style_desc   = "day trader / scalper"
    else:
        # Default to swing trader only
        report_parts = swing_part
        style_desc   = "swing trader"

    prompt = f"""You are a professional trading analyst AI writing a personalized morning report.
Today is {today}.
This report is for {name}, a {style_desc} watching: {tickers}.{focus_note}

{format_rules}

{report_parts}

---
MARKET DATA:
{all_data}
"""
    return prompt


# ─────────────────────────────────────────
# GROQ ANALYSIS
# ─────────────────────────────────────────
def analyze_with_groq(all_data: str, subscriber: dict) -> str:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set.")

    prompt = build_prompt(all_data, subscriber)

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json"
    }

    payload = {
        "model":       "llama-3.3-70b-versatile",
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens":  3000
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
def send_email(report: str, subscriber: dict):
    today   = datetime.now().strftime("%b %d, %Y")
    name    = subscriber["name"]
    email   = subscriber["email"]
    tickers = ", ".join(subscriber["tickers"])
    subject = f"📈 Your Morning Stock Report — {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = email

    html_body = f"""
    <html><body style="font-family:monospace;background:#0f0f0f;color:#e0e0e0;padding:24px;max-width:700px;margin:auto;">
    <h2 style="color:#00e5a0;border-bottom:1px solid #333;padding-bottom:8px;">
        📈 Morning Stock Report — {today}
    </h2>
    <p style="color:#888;font-size:13px;margin-bottom:20px;">
        Hey {name} — here is your personalized report for: {tickers}
    </p>
    <pre style="white-space:pre-wrap;font-size:13.5px;line-height:1.75;">{report}</pre>
    <p style="color:#555;font-size:12px;margin-top:32px;">
        Sources: Yahoo Finance · Finnhub · AI: Groq / Llama 3.3 70B · Not financial advice.
    </p>
    </body></html>
    """

    msg.attach(MIMEText(report, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, email, msg.as_string())

    print(f"  ✅ Report sent to {name} ({email})")


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    print("📋 Reading subscribers from Google Sheet...")
    subscribers = get_subscribers()

    if not subscribers:
        print("⚠️  No subscribers found. Exiting.")
        return

    print(f"\n🚀 Processing {len(subscribers)} subscriber(s)...\n")

    for subscriber in subscribers:
        name    = subscriber["name"]
        style   = subscriber["style"]
        tickers = subscriber["tickers"]
        print(f"─── {name} | {style} | {', '.join(tickers)} ───")

        all_data = ""
        for ticker in tickers:
            print(f"  → {ticker}")
            all_data += fetch_all_data(ticker)
            time.sleep(0.4)

        print(f"  🤖 Analyzing with Groq...")
        report = analyze_with_groq(all_data, subscriber)

        print(f"  📧 Sending to {subscriber['email']}...")
        send_email(report, subscriber)

        time.sleep(2)

    print(f"\n✅ All {len(subscribers)} reports sent successfully!")


if __name__ == "__main__":
    main()
