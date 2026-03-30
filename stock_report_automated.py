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
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY")
FINNHUB_API_KEY    = os.environ.get("FINNHUB_API_KEY")
EMAIL_SENDER       = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD     = os.environ.get("EMAIL_PASSWORD")
GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_ID     = os.environ.get("SPREADSHEET_ID")

COL_NAME    = 1
COL_EMAIL   = 2
COL_TICKERS = 3
COL_STYLE   = 4
COL_FOCUS   = 5

TEST_MODE = True  # Set to False for production

TEST_SUBSCRIBERS = [
    {
        "name":    "test-acika",
        "email":   "alexdzam4@gmail.com",
        "tickers": ["NVDA", "TSLA", "PLTR", "HIMS"],
    }
]

# ─────────────────────────────────────────
# GOOGLE SHEETS
# ─────────────────────────────────────────
def get_subscribers():
    try:
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
        result  = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range="Form_Responses!A2:F1000"
        ).execute()

        rows = result.get("values", [])
        subscribers = []
        for row in rows:
            while len(row) < 6:
                row.append("")
            email   = row[COL_EMAIL].strip()
            tickers = row[COL_TICKERS].strip()
            if not email or not tickers:
                continue
            ticker_list = [t.strip().upper() for t in tickers.replace(",", " ").split() if t.strip()]
            subscribers.append({
                "name":    row[COL_NAME].strip() or "Trader",
                "email":   email,
                "tickers": ticker_list,
                "style":   row[COL_STYLE].strip() or "Swing Trader",
                "focus":   row[COL_FOCUS].strip() or "",
            })

        print(f"✅ Loaded {len(subscribers)} subscribers")
        return subscribers
    except Exception as e:
        print(f"❌ Failed to read Google Sheet: {e}")
        return []


# ─────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────
def fetch_yahoo_news(ticker):
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        import xml.etree.ElementTree as ET
        root  = ET.fromstring(resp.text)
        news  = []
        for item in root.findall(".//item")[:4]:
            title = item.findtext("title", "").strip()
            desc  = item.findtext("description", "").strip()
            pub   = item.findtext("pubDate", "").strip()
            news.append(f"[Yahoo] {title} | {desc[:150]} ({pub})")
        return news
    except Exception as e:
        print(f"    Yahoo failed for {ticker}: {e}")
        return []


def fetch_finnhub_news(ticker):
    if not FINNHUB_API_KEY:
        return []
    try:
        today    = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        url      = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={week_ago}&to={today}&token={FINNHUB_API_KEY}"
        resp     = requests.get(url, timeout=10)
        resp.raise_for_status()
        news = []
        for a in resp.json()[:4]:
            news.append(f"[Finnhub] {a.get('headline','')} | {a.get('summary','')[:150]}")
        return news
    except Exception as e:
        print(f"    Finnhub news failed for {ticker}: {e}")
        return []


def fetch_finnhub_insider(ticker):
    if not FINNHUB_API_KEY:
        return []
    try:
        url  = f"https://finnhub.io/api/v1/stock/insider-transactions?symbol={ticker}&token={FINNHUB_API_KEY}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        trades = []
        for t in resp.json().get("data", [])[:3]:
            name   = t.get("name", "Unknown")
            change = t.get("change", 0)
            price  = t.get("transactionPrice", 0)
            action = "BOUGHT" if change > 0 else "SOLD"
            trades.append(f"[Insider] {name} {action} {abs(change):,} shares @ ${price:.2f}")
        return trades
    except Exception as e:
        print(f"    Finnhub insider failed for {ticker}: {e}")
        return []


def fetch_finnhub_earnings(ticker):
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
            e = earnings[0]
            return f"[Earnings] Date: {e.get('date','')} | EPS Est: {e.get('epsEstimate','N/A')} | Actual: {e.get('epsActual','TBD')}"
        return ""
    except Exception as e:
        print(f"    Finnhub earnings failed for {ticker}: {e}")
        return ""


def fetch_all_data(ticker):
    print(f"    -> {ticker}")
    lines  = []
    lines += fetch_yahoo_news(ticker)
    lines += fetch_finnhub_news(ticker)
    lines += fetch_finnhub_insider(ticker)
    earn   = fetch_finnhub_earnings(ticker)
    if earn:
        lines.append(earn)
    time.sleep(0.4)
    if not lines:
        return f"## {ticker}\nNo data available.\n"
    block = f"## {ticker}\n"
    for l in lines:
        block += f"- {l}\n"
    return block


# ─────────────────────────────────────────
# PROMPT BUILDER — conditional by style
# ─────────────────────────────────────────
def build_prompt(all_data, subscriber):
    today   = datetime.now().strftime("%A, %B %d %Y")
    name    = subscriber["name"]
    style   = subscriber["style"].lower()
    focus   = subscriber["focus"]
    tickers = ", ".join(subscriber["tickers"])

    focus_note = f"\nAdditional focus for this trader: {focus}" if focus else ""

    is_swing = "swing" in style
    is_day   = "day" in style or "scalp" in style
    is_both  = is_swing and is_day

    if is_both:
        style_desc = "swing trader and day trader"
    elif is_day:
        style_desc = "day trader / scalper"
    else:
        style_desc = "swing trader"

    swing_section = """
PART1
SECTION: WEEKLY BIAS
BULLET: [overall market direction - bullish, bearish or ranging, and whether conditions are good for swing entries]
SECTION: TOP 5 SWING SETUPS THIS WEEK
BULLET: [ticker] - [what is driving the move and what price area to watch]
BULLET: [repeat for each of top 5]
SECTION: SWING BREAKDOWN - STOCK BY STOCK
STOCK: [ticker] | [BULLISH/BEARISH/NEUTRAL] | [news summary] | [swing setup, trend intact, demand zone] | [insider signal] | [thesis check]
[one STOCK: row per ticker with meaningful data]
SECTION: DEMAND ZONE THREATS
BULLET: [ticker] - [why it could break down and what action to take]
SECTION: CATALYST CALENDAR - NEXT 7 DAYS
EVENT: [date] | [event description] | [tickers affected]
[one EVENT: row per catalyst]
SECTION: WEEKEND WATCHLIST PREP
BULLET: [ticker] - [why interesting and what price area to analyze this weekend]"""

    scalp_section = """
PART2
SECTION: TODAY TOP 5 VOLATILE STOCKS
BULLET: [ticker] - [expected move size, what is driving it, direction bias]
SECTION: SCALP SETUPS
STOCK: [ticker] | [LONG/SHORT] | [entry trigger] | [stop loss level] | [invalidation condition]
[one STOCK: row per volatile stock]
SECTION: NEWS CATALYSTS TODAY
BULLET: [time EST] - [catalyst and which stocks it affects]
SECTION: STOCKS TO AVOID TODAY
BULLET: [ticker] - [reason to avoid scalping today]
SECTION: KEY TIMES TODAY
BULLET: [time EST] - [event and expected market impact]"""

    if is_both:
        report_sections = swing_section + "\n" + scalp_section
    elif is_day:
        report_sections = scalp_section.replace("PART2", "PART2")
    else:
        report_sections = swing_section

    return f"""You are a professional trading analyst AI writing a personalized morning report.
Today is {today}.
This report is for {name}, a {style_desc} watching: {tickers}.{focus_note}

CRITICAL FORMAT RULES - follow exactly, no exceptions:
- Every section header must start with SECTION:
- Every bullet point must start with BULLET:
- Every stock row must start with STOCK:
- Every calendar event must start with EVENT:
- Part separators must be exactly PART1 or PART2 on their own line
- Do NOT use **, ##, or any markdown
- Sentiment must be exactly one word: BULLISH, BEARISH, or NEUTRAL
- Be specific and actionable - no generic statements

STOCK row format: STOCK: TICKER | SENTIMENT | news summary | setup | insider | thesis
EVENT row format: EVENT: date | event description | tickers affected

{report_sections}

Now write the full personalized report using only the marker format above.

---
MARKET DATA:
{all_data}
"""


# ─────────────────────────────────────────
# HTML BUILDER
# ─────────────────────────────────────────
def sentiment_badge(s):
    s = s.strip().upper()
    if s == "BULLISH":
        return "<span style='background:#dcfce7;color:#16a34a;font-size:10px;font-family:monospace;padding:2px 8px;border-radius:10px;font-weight:bold;'>🟢 BULLISH</span>"
    elif s == "BEARISH":
        return "<span style='background:#fee2e2;color:#dc2626;font-size:10px;font-family:monospace;padding:2px 8px;border-radius:10px;font-weight:bold;'>🔴 BEARISH</span>"
    else:
        return "<span style='background:#fef9c3;color:#ca8a04;font-size:10px;font-family:monospace;padding:2px 8px;border-radius:10px;font-weight:bold;'>🟡 NEUTRAL</span>"


def build_html_email(report, subscriber):
    today   = datetime.now().strftime("%b %d, %Y")
    name    = subscriber["name"]
    tickers = " · ".join(subscriber["tickers"])
    lines   = report.strip().split("\n")

    in_part2       = False
    in_stock_table = False
    in_event_table = False
    body_html      = ""

    def close_tables():
        nonlocal in_stock_table, in_event_table
        out = ""
        if in_stock_table:
            out += "</div>"
            in_stock_table = False
        if in_event_table:
            out += "</table>"
            in_event_table = False
        return out

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line == "PART1":
            body_html += close_tables()
            body_html += """
            <div style="background:#00c87a;border-radius:4px;padding:10px 14px;margin:20px 0 4px;">
              <div style="font-size:13px;font-weight:bold;color:#0d1117;font-family:monospace;letter-spacing:1px;">
                ▌ PART 1 — SWING TRADER REPORT
              </div>
            </div>"""
            in_part2 = False
            continue

        if line == "PART2":
            body_html += close_tables()
            body_html += """
            <div style="border-top:2px dashed #e2e8f0;margin:24px 0 0;"></div>
            <div style="background:#e63946;border-radius:4px;padding:10px 14px;margin:16px 0 4px;">
              <div style="font-size:13px;font-weight:bold;color:#ffffff;font-family:monospace;letter-spacing:1px;">
                ▌ PART 2 — SCALPER / DAY TRADER REPORT
              </div>
            </div>"""
            in_part2 = True
            continue

        if line.startswith("SECTION:"):
            body_html += close_tables()
            title = line[8:].strip()
            if any(x in title.upper() for x in ["BIAS", "BREAKDOWN", "WEEKLY"]):
                accent = "#2a9fd6"
            elif any(x in title.upper() for x in ["THREAT", "AVOID"]):
                accent = "#e63946"
            elif any(x in title.upper() for x in ["CATALYST", "TIMES", "KEY", "CALENDAR"]):
                accent = "#f59e0b"
            elif in_part2:
                accent = "#e63946"
            else:
                accent = "#00c87a"
            body_html += f"""
            <div style="border-left:3px solid {accent};padding-left:12px;margin:18px 0 8px;">
              <div style="font-size:12px;font-weight:bold;color:{accent};font-family:monospace;letter-spacing:1.5px;">
                {title}
              </div>
            </div>"""
            continue

        if line.startswith("BULLET:"):
            body_html += close_tables()
            text = line[7:].strip()
            body_html += f"""
            <div style="font-size:13.5px;color:#374151;line-height:1.75;padding:3px 0 3px 12px;">
              ► {text}
            </div>"""
            continue

        if line.startswith("STOCK:"):
            parts   = [p.strip() for p in line[6:].split("|")]
            ticker  = parts[0] if len(parts) > 0 else ""
            senti   = parts[1] if len(parts) > 1 else ""
            col3    = parts[2] if len(parts) > 2 else ""
            col4    = parts[3] if len(parts) > 3 else ""
            col5    = parts[4] if len(parts) > 4 else ""
            col6    = parts[5] if len(parts) > 5 else ""

            if not in_stock_table:
                body_html += """<div style="display:flex;flex-direction:column;gap:6px;margin:6px 0;">"""
                in_stock_table = True

            s      = senti.strip().upper()
            row_bg = "#fff5f5" if s == "BEARISH" else "#f8fafc"
            border = "#fecaca" if s == "BEARISH" else "#e2e8f0"

            if in_part2:
                label3, label4, label5 = "Direction", "Entry", "Stop / Invalidation"
            else:
                label3, label4, label5 = "News", "Setup", "Insider"

            body_html += f"""
            <div style="border:1px solid {border};border-radius:5px;padding:10px 14px;background:{row_bg};">
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
                <span style="font-size:14px;font-weight:bold;color:#2a9fd6;font-family:monospace;">{ticker}</span>
                {sentiment_badge(senti)}
              </div>
              <div style="font-size:12.5px;color:#374151;line-height:1.8;">"""
            if col3: body_html += f"<b>{label3}:</b> {col3}<br/>"
            if col4: body_html += f"<b>{label4}:</b> {col4}<br/>"
            if col5: body_html += f"<b>{label5}:</b> {col5}<br/>"
            if col6: body_html += f"<b>Thesis:</b> {col6}"
            body_html += "</div></div>"
            continue

        if line.startswith("EVENT:"):
            parts   = [p.strip() for p in line[6:].split("|")]
            date    = parts[0] if len(parts) > 0 else ""
            event   = parts[1] if len(parts) > 1 else ""
            affects = parts[2] if len(parts) > 2 else ""

            if not in_event_table:
                body_html += """
                <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:12.5px;margin:6px 0;">
                <tr style="background:#0d1117;color:#ffffff;">
                  <td style="padding:6px 10px;font-family:monospace;font-size:10px;width:110px;">DATE</td>
                  <td style="padding:6px 10px;font-family:monospace;font-size:10px;">EVENT</td>
                  <td style="padding:6px 10px;font-family:monospace;font-size:10px;width:120px;">AFFECTS</td>
                </tr>"""
                in_event_table = True

            body_html += f"""
            <tr>
              <td style="padding:6px 10px;color:#374151;border-bottom:1px solid #e2e8f0;font-family:monospace;font-size:11px;">{date}</td>
              <td style="padding:6px 10px;color:#374151;border-bottom:1px solid #e2e8f0;">{event}</td>
              <td style="padding:6px 10px;color:#2a9fd6;border-bottom:1px solid #e2e8f0;font-size:11px;">{affects}</td>
            </tr>"""
            continue

    body_html += close_tables()

    return f"""
<html>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Georgia,serif;">
<div style="max-width:680px;margin:24px auto;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.1);">
  <div style="background:#0d1117;padding:22px 28px 18px;">
    <div style="font-size:11px;letter-spacing:3px;color:#00c87a;font-family:monospace;margin-bottom:6px;text-transform:uppercase;">● LIVE · {today}</div>
    <div style="font-size:24px;font-weight:bold;color:#ffffff;line-height:1.2;">📈 Morning Stock Report</div>
    <div style="font-size:11px;color:#6b7280;margin-top:5px;font-family:monospace;">Hey {name} — your personalized report for: {tickers}</div>
  </div>
  <div style="padding:0 24px 28px;">
    {body_html}
  </div>
  <div style="background:#0d1117;padding:14px 28px;text-align:center;">
    <div style="font-size:11px;color:#4b5563;font-family:monospace;">Sources: Yahoo Finance · Finnhub · AI: Groq / Llama 3.3 70B</div>
    <div style="font-size:11px;color:#374151;margin-top:4px;font-family:monospace;">Not financial advice · Generated automatically · {today}</div>
  </div>
</div>
</body>
</html>"""


# ─────────────────────────────────────────
# GROQ
# ─────────────────────────────────────────
def analyze_with_groq(all_data, subscriber):
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set.")
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json"
    }
    payload = {
        "model":       "llama-3.3-70b-versatile",
        "messages":    [{"role": "user", "content": build_prompt(all_data, subscriber)}],
        "temperature": 0.4,
        "max_tokens":  4096
    }
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers, json=payload, timeout=60
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ─────────────────────────────────────────
# SEND EMAIL
# ─────────────────────────────────────────
def send_email(report, subscriber):
    today   = datetime.now().strftime("%b %d, %Y")
    name    = subscriber["name"]
    email   = subscriber["email"]
    subject = f"📈 Your Morning Stock Report — {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = email

    plain = report.replace("SECTION:", "\n").replace("BULLET:", "► ").replace("STOCK:", "► ").replace("EVENT:", "► ").replace("PART1", "\n=== PART 1 - SWING TRADER ===\n").replace("PART2", "\n=== PART 2 - SCALPER ===\n")
    html  = build_html_email(report, subscriber)

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, email, msg.as_string())

    print(f"  ✅ Sent to {name} ({email})")


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
   if TEST_MODE:
    print("🧪 TEST MODE — using hardcoded subscribers")
    subscribers = TEST_SUBSCRIBERS
else:
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
            all_data += fetch_all_data(ticker)

        print(f"  🤖 Analyzing with Groq...")
        report = analyze_with_groq(all_data, subscriber)

        print(f"  📧 Sending styled email...")
        send_email(report, subscriber)
        time.sleep(2)

    print(f"\n✅ All {len(subscribers)} reports sent!")


if __name__ == "__main__":
    main()
