"""
Orange News — Market Data Fetcher v1
=====================================
Өдрийн зах зээлийн бодит мэдээллийг татах

Эх сурвалжууд:
1. Монголбанк (mongolbank.mn) — албан валютын ханш
2. Yahoo Finance (yfinance) — дэлхийн индекс, Bitcoin, алт, нефть
3. Fallback: ханш татагдахгүй бол "мэдээлэл байхгүй" гэх эсвэл өмнөх утга

Author: Azurise AI Master Architect
Date: April 18, 2026
"""

import json
import os
from datetime import datetime

# yfinance шаардлагатай — pipeline-д аль хэдийн суулгасан байдаг
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    print("⚠️ yfinance ороогүй")

import requests


# =============================================================================
# МОНГОЛБАНК ВАЛЮТЫН ХАНШ
# =============================================================================

def fetch_mongolbank_rates():
    """
    Монголбанкны албан валютын ханшийг татах.
    API: https://www.mongolbank.mn/json/daily-rates.json

    Буцаадаг:
        {
            "USD": 3573.29,
            "EUR": 4211.76,
            "CNY": 493.50,
            "JPY": 22.43,
            "KRW": 2.48,  # Солонгос вон
            "RUB": 37.85,  # Орос рубль
        }
    """
    try:
        # Монголбанкны албан API
        url = "https://www.mongolbank.mn/json/daily-rates.json"
        r = requests.get(url, timeout=10, verify=False, headers={
            "User-Agent": "Mozilla/5.0 (compatible; OrangeNewsBot/1.0)"
        })
        data = r.json()

        rates = {}
        for item in data.get("data", []):
            code = item.get("Cur", "")
            rate = item.get("Rate", 0)
            if code and rate:
                rates[code.upper()] = float(rate)

        return rates
    except Exception as e:
        print(f"  ⚠️ Монголбанк API алдаа: {e}")
        return {}


# =============================================================================
# YAHOO FINANCE — ДЭЛХИЙН ИНДЕКС, КРИПТО, ТҮҮХИЙ ЭД
# =============================================================================

# Yahoo Finance ticker-ууд
TICKERS = {
    # Индекс
    "S&P 500":     "^GSPC",
    "Nasdaq":      "^IXIC",
    "Dow Jones":   "^DJI",
    "Nikkei":      "^N225",
    "Shanghai":    "000001.SS",
    "FTSE":        "^FTSE",

    # Крипто
    "Bitcoin":     "BTC-USD",
    "Ethereum":    "ETH-USD",
    "Solana":      "SOL-USD",

    # Түүхий эд
    "Gold":        "GC=F",       # Алт
    "Oil":         "CL=F",       # Brent нефть
    "Copper":      "HG=F",       # Зэс
    "Silver":      "SI=F",       # Мөнгө
}


def fetch_yfinance_data():
    """
    Yahoo Finance-ээс индекс, крипто, түүхий эдийн үнэ татах.

    Буцаадаг:
        {
            "S&P 500": {"price": 7041.28, "change_pct": 0.26},
            "Bitcoin": {"price": 74669.31, "change_pct": -0.32},
            ...
        }
    """
    if not YFINANCE_AVAILABLE:
        return {}

    results = {}
    for name, ticker_symbol in TICKERS.items():
        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.history(period="2d")

            if len(info) >= 2:
                current = float(info["Close"].iloc[-1])
                previous = float(info["Close"].iloc[-2])
                change_pct = ((current - previous) / previous) * 100

                results[name] = {
                    "price": round(current, 2),
                    "change_pct": round(change_pct, 2)
                }
        except Exception as e:
            print(f"  ⚠️ {name} ({ticker_symbol}): {e}")
            continue

    return results


# =============================================================================
# МАРКЕТ ДАТА FORMATTER (Facebook пост-д зориулсан)
# =============================================================================

def format_arrow(change_pct):
    """Өөрчлөлтийн хувиар сум сонгох"""
    if change_pct > 0:
        return "⬆"
    elif change_pct < 0:
        return "⬇"
    else:
        return "➡"


def format_price(price, is_crypto=False, is_index=False):
    """Үнэ format хийх"""
    if price >= 10000:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:,.2f}"
    else:
        return f"${price:.4f}"


def format_currency_mnt(rate):
    """Төгрөгийн ханш format"""
    return f"{rate:,.2f}₮"


def build_market_watch_body():
    """
    Facebook пост-д зориулсан Market Watch body бэлдэх.
    Бодит тоог татаж, formatted текст буцаана.
    """
    today = datetime.now().strftime("%Y.%m.%d")

    print("📊 Market Data татаж байна...")
    mb_rates = fetch_mongolbank_rates()
    yf_data = fetch_yfinance_data()

    # Валютын хэсэг
    currency_section = "💵 ВАЛЮТЫН ХАНШ (Монголбанк албан ханш)\n"
    currency_lines = []

    if mb_rates:
        # USD
        if "USD" in mb_rates:
            currency_lines.append(f"🇺🇸 USD: {format_currency_mnt(mb_rates['USD'])}")
        # EUR
        if "EUR" in mb_rates:
            currency_lines.append(f"🇪🇺 EUR: {format_currency_mnt(mb_rates['EUR'])}")
        # CNY
        if "CNY" in mb_rates:
            currency_lines.append(f"🇨🇳 Юань: {format_currency_mnt(mb_rates['CNY'])}")
        # JPY
        if "JPY" in mb_rates:
            currency_lines.append(f"🇯🇵 JPY: {format_currency_mnt(mb_rates['JPY'])}")
        # KRW
        if "KRW" in mb_rates:
            currency_lines.append(f"🇰🇷 Вон: {format_currency_mnt(mb_rates['KRW'])}")
    else:
        currency_lines.append("🇺🇸 USD: [мэдээлэл байхгүй]")
        currency_lines.append("🇪🇺 EUR: [мэдээлэл байхгүй]")

    currency_section += " | ".join(currency_lines)

    # Хөрөнгийн зах зээл (индекс)
    stock_section = "\n\n🌐 ДЭЛХИЙН ХӨРӨНГИЙН ЗАХ ЗЭЭЛ\n"
    stock_lines = []
    for name in ["S&P 500", "Nasdaq", "Nikkei"]:
        if name in yf_data:
            d = yf_data[name]
            arrow = format_arrow(d["change_pct"])
            flag = {"S&P 500": "🇺🇸", "Nasdaq": "🇺🇸", "Nikkei": "🇯🇵"}[name]
            stock_lines.append(f"{flag} {name}: {d['price']:,.2f} {arrow} {d['change_pct']:+.2f}%")

    if stock_lines:
        stock_section += " | ".join(stock_lines)
    else:
        stock_section += "[зах зээлийн мэдээлэл одоохондоо байхгүй]"

    # Крипто
    crypto_section = "\n\n💎 КРИПТО ЗАХ ЗЭЭЛ\n"
    crypto_lines = []
    for name in ["Bitcoin", "Ethereum", "Solana"]:
        if name in yf_data:
            d = yf_data[name]
            arrow = format_arrow(d["change_pct"])
            emoji = {"Bitcoin": "₿", "Ethereum": "Ξ", "Solana": "◎"}[name]
            crypto_lines.append(f"{emoji} {name}: {format_price(d['price'])} {arrow} {d['change_pct']:+.2f}%")

    if crypto_lines:
        crypto_section += " | ".join(crypto_lines)
    else:
        crypto_section += "[крипто мэдээлэл байхгүй]"

    # Түүхий эд
    commodity_section = "\n\n🏗️ ТҮҮХИЙ ЭД\n"
    commodity_lines = []
    commodity_emojis = {"Gold": "🥇 Алт", "Oil": "🛢️ Нефть", "Copper": "🔶 Зэс"}
    for name in ["Gold", "Oil", "Copper"]:
        if name in yf_data:
            d = yf_data[name]
            arrow = format_arrow(d["change_pct"])
            label = commodity_emojis[name]
            commodity_lines.append(f"{label}: ${d['price']:,.2f}/унц {arrow} {d['change_pct']:+.2f}%")

    if commodity_lines:
        commodity_section += " | ".join(commodity_lines)
    else:
        commodity_section += "[түүхий эдийн мэдээлэл байхгүй]"

    # Ерөнхий дүгнэлт
    summary_section = f"""\n\n📰 ӨНӨӨДРИЙН ТОЙМ

Америкийн хувьцааны зах зээл сүүлийн 24 цагийн хугацаанд"""

    if "S&P 500" in yf_data:
        sp500_change = yf_data["S&P 500"]["change_pct"]
        if sp500_change > 0.3:
            summary_section += f" өсөлттэй ({sp500_change:+.2f}%)"
        elif sp500_change < -0.3:
            summary_section += f" бууралттай ({sp500_change:+.2f}%)"
        else:
            summary_section += " тогтвортой"

    summary_section += " байна. Ази болон түүхий эдийн зах зээлийн гол үзүүлэлтийг дэлгэрэнгүй мэдээнд уншина уу."

    # Бүгдийг нэгтгэх
    header = f"""📊 Дэлхийн хөрөнгийн зах зээл — {today}

Өнөөдрийн Orange Market Watch таны өдрийн эхний санхүүгийн зурваст тавтай морилно уу. Дэлхийн томоохон биржүүд, валют, түүхий эдийн зах зээлийн гол үзүүлэлтүүдийг товчлон танилцуулж байна."""

    body = header + "\n\n" + currency_section + stock_section + crypto_section + commodity_section + summary_section + "\n\nДэлгэрэнгүй мэдээллийг www.orangenews.mn сайтаас уншина уу."

    return body


# =============================================================================
# MAIN (тест)
# =============================================================================

if __name__ == "__main__":
    print("🔍 Market Data Fetcher тест")
    print("=" * 60)

    body = build_market_watch_body()

    print("\n📰 ORANGE MARKET WATCH BODY:")
    print("=" * 60)
    print(body)
    print("=" * 60)

    # JSON-д хадгалах (debugging)
    mb = fetch_mongolbank_rates()
    yf_raw = fetch_yfinance_data()

    output = {
        "date": datetime.now().isoformat(),
        "mongolbank": mb,
        "markets": yf_raw,
        "facebook_body": body
    }

    with open("market_data_today.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n✅ market_data_today.json хадгалав")
