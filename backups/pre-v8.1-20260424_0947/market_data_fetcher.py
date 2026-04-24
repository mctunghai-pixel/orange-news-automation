"""
Orange News — Market Data Fetcher v2
=====================================
3 түвшинтэй fallback chain:

ВАЛЮТЫН ХАНШ (MNT):
  1. Монголбанк JSON API (хэрвээ ажиллавал)
  2. ExchangeRate-API (free, MNT дэмжинэ)
  3. Frankfurter + Yahoo Finance USDMNT ticker

ИНДЕКС/КРИПТО/ТҮҮХИЙ ЭД:
  1. Yahoo Finance

Author: Azurise AI Master Architect
Date: April 18, 2026
"""

import json
import os
import warnings
from datetime import datetime

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    print("⚠️ yfinance ороогүй")

import requests

# =============================================================================
# МОНГОЛБАНК ВАЛЮТЫН ХАНШ — 3 түвшинтэй fallback
# =============================================================================

def try_mongolbank_json():
    """Түвшин 1: Монголбанкны JSON API"""
    urls = [
        "https://www.mongolbank.mn/json/daily-rates.json",
        "https://www.mongolbank.mn/api/daily-rates",
        "http://www.mongolbank.mn/json/daily-rates.json",
    ]

    for url in urls:
        try:
            r = requests.get(url, timeout=10, verify=False, headers={
                "User-Agent": "Mozilla/5.0 (compatible; OrangeNewsBot/1.0)",
                "Accept": "application/json, text/plain, */*",
            })
            if r.status_code == 200 and r.text.strip():
                data = r.json()
                rates = {}

                if isinstance(data, dict) and "data" in data:
                    for item in data["data"]:
                        code = item.get("Cur", "").upper()
                        rate = item.get("Rate", 0)
                        if code and rate:
                            rates[code] = float(rate)
                elif isinstance(data, list):
                    for item in data:
                        code = item.get("code", item.get("Cur", "")).upper()
                        rate = item.get("rate", item.get("Rate", 0))
                        if code and rate:
                            rates[code] = float(rate)

                if rates:
                    print(f"  ✅ Монголбанк JSON: {len(rates)} валют")
                    return rates
        except Exception:
            continue

    return {}


def try_exchangerate_api():
    """Түвшин 2: ExchangeRate-API (free, no API key)"""
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("result") == "success":
                rates_per_usd = data.get("rates", {})
                mnt_rate = rates_per_usd.get("MNT", 0)

                if mnt_rate > 0:
                    result = {}
                    result["USD"] = round(mnt_rate, 2)

                    for code in ["EUR", "CNY", "JPY", "KRW", "RUB", "GBP"]:
                        code_rate = rates_per_usd.get(code, 0)
                        if code_rate > 0:
                            result[code] = round(mnt_rate / code_rate, 2)

                    print(f"  ✅ ExchangeRate-API: {len(result)} валют")
                    return result
    except Exception as e:
        print(f"  ⚠️ ExchangeRate-API: {e}")

    return {}


def try_yfinance_usdmnt():
    """Түвшин 3: Yahoo Finance USDMNT ticker-аас авах"""
    if not YFINANCE_AVAILABLE:
        return {}

    try:
        # USDMNT ticker-аас USD ханш
        usdmnt = yf.Ticker("USDMNT=X")
        hist = usdmnt.history(period="2d")
        if len(hist) < 1:
            return {}

        usd_rate = float(hist["Close"].iloc[-1])

        # Frankfurter-ээс бусад валют
        r = requests.get("https://api.frankfurter.dev/v1/latest?base=USD", timeout=10)
        rates_per_usd = {}
        if r.status_code == 200:
            rates_per_usd = r.json().get("rates", {})

        result = {"USD": round(usd_rate, 2)}
        for code in ["EUR", "CNY", "JPY", "GBP"]:
            code_rate = rates_per_usd.get(code, 0)
            if code_rate > 0:
                result[code] = round(usd_rate / code_rate, 2)

        if result:
            print(f"  ✅ Frankfurter + yfinance USDMNT: {len(result)} валют")
            return result
    except Exception as e:
        print(f"  ⚠️ yfinance USDMNT: {e}")

    return {}


def fetch_mongolbank_rates():
    """3 түвшинтэй fallback chain"""
    print("💱 Валютын ханш татаж байна...")

    rates = try_mongolbank_json()
    if rates:
        return rates

    rates = try_exchangerate_api()
    if rates:
        return rates

    rates = try_yfinance_usdmnt()
    if rates:
        return rates

    print("  ⚠️ Бүх валют API амжилтгүй")
    return {}


# =============================================================================
# YAHOO FINANCE
# =============================================================================

TICKERS = {
    "S&P 500":     "^GSPC",
    "Nasdaq":      "^IXIC",
    "Dow Jones":   "^DJI",
    "Nikkei":      "^N225",
    "Shanghai":    "000001.SS",
    "Bitcoin":     "BTC-USD",
    "Ethereum":    "ETH-USD",
    "Solana":      "SOL-USD",
    "Gold":        "GC=F",
    "Oil":         "CL=F",
    "Copper":      "HG=F",
    "Silver":      "SI=F",
}


def fetch_yfinance_data():
    if not YFINANCE_AVAILABLE:
        return {}

    results = {}
    print("📊 Yahoo Finance татаж байна...")
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
        except Exception:
            continue

    print(f"  ✅ {len(results)}/{len(TICKERS)} ticker амжилттай")
    return results


# =============================================================================
# CRYPTO FALLBACK — CoinGecko API (no key required)
# =============================================================================

COINGECKO_IDS = {
    "Bitcoin":  "bitcoin",
    "Ethereum": "ethereum",
    "Solana":   "solana",
}

BINANCE_SYMBOLS = {
    "Bitcoin":  "BTCUSDT",
    "Ethereum": "ETHUSDT",
    "Solana":   "SOLUSDT",
}


def fetch_coingecko_crypto():
    """
    Fallback #1 for yfinance: CoinGecko API (no key required).
    Free tier: 10-30 calls/min.
    Returns same format as yfinance: {name: {price, change_pct}}
    """
    try:
        ids = ",".join(COINGECKO_IDS.values())
        url = (
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={ids}&vs_currencies=usd&include_24hr_change=true"
        )
        r = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (OrangeNewsBot/1.0)",
            "Accept": "application/json",
        })
        if r.status_code != 200:
            print(f"  ⚠️ CoinGecko HTTP {r.status_code}")
            return {}

        data = r.json()
        results = {}
        for name, gecko_id in COINGECKO_IDS.items():
            coin = data.get(gecko_id, {})
            price = coin.get("usd")
            change = coin.get("usd_24h_change")
            if price is not None and change is not None:
                results[name] = {
                    "price": round(float(price), 2),
                    "change_pct": round(float(change), 2),
                }

        if results:
            print(f"  ✅ CoinGecko fallback: {len(results)} крипто")
        return results
    except Exception as e:
        print(f"  ⚠️ CoinGecko алдаа: {e}")
        return {}


def fetch_binance_crypto():
    """
    Fallback #2: Binance public API (no key, no rate limit issues).
    Uses /api/v3/ticker/24hr endpoint for price + 24h % change.
    """
    try:
        results = {}
        for name, symbol in BINANCE_SYMBOLS.items():
            try:
                r = requests.get(
                    f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}",
                    timeout=8,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if r.status_code != 200:
                    continue
                data = r.json()
                price = float(data.get("lastPrice", 0))
                change = float(data.get("priceChangePercent", 0))
                if price > 0:
                    results[name] = {
                        "price": round(price, 2),
                        "change_pct": round(change, 2),
                    }
            except Exception:
                continue

        if results:
            print(f"  ✅ Binance fallback: {len(results)} крипто")
        return results
    except Exception as e:
        print(f"  ⚠️ Binance алдаа: {e}")
        return {}


def ensure_crypto_data(yf_data):
    """
    Check if crypto data from yfinance is complete.
    Multi-tier fallback: yfinance → CoinGecko → Binance.
    Guarantees crypto section is never empty unless ALL 3 sources fail.
    """
    crypto_names = ["Bitcoin", "Ethereum", "Solana"]
    missing = [n for n in crypto_names if n not in yf_data]

    if not missing:
        return yf_data

    print(f"  ⚠️ Yahoo Finance-ээс {len(missing)} крипто дутуу: {missing}")

    # Tier 1: CoinGecko
    print(f"  🔄 CoinGecko fallback...")
    gecko_data = fetch_coingecko_crypto()
    for name in crypto_names:
        if name not in yf_data and name in gecko_data:
            yf_data[name] = gecko_data[name]

    # Tier 2: Binance (зөвхөн CoinGecko-оос татагдаагүй зүйлд)
    still_missing = [n for n in crypto_names if n not in yf_data]
    if still_missing:
        print(f"  🔄 Binance fallback ({len(still_missing)} үлдсэн)...")
        binance_data = fetch_binance_crypto()
        for name in still_missing:
            if name in binance_data:
                yf_data[name] = binance_data[name]

    # Эцсийн тайлан
    final_missing = [n for n in crypto_names if n not in yf_data]
    if final_missing:
        print(f"  ❌ БҮХ fallback амжилтгүй: {final_missing}")
    else:
        print(f"  ✅ Крипто мэдээлэл бүрэн нөхөгдсөн")

    return yf_data


# =============================================================================
# FORMATTER
# =============================================================================

def format_arrow(change_pct):
    if change_pct > 0.1:
        return "⬆"
    elif change_pct < -0.1:
        return "⬇"
    else:
        return "➡"


def format_price(price):
    return f"${price:,.2f}" if price >= 1 else f"${price:.4f}"


def format_currency_mnt(rate):
    return f"{rate:,.2f}₮"


def build_market_watch_body():
    today = datetime.now().strftime("%Y.%m.%d")

    print("\n📊 Market Data цуглуулж байна...\n")
    mb_rates = fetch_mongolbank_rates()
    yf_data = fetch_yfinance_data()

    # Крипто мэдээллийг заавал нөхөх (CoinGecko fallback)
    yf_data = ensure_crypto_data(yf_data)

    # Валют
    currency_lines = []
    currency_map = [
        ("🇺🇸", "USD", "USD"),
        ("🇪🇺", "EUR", "EUR"),
        ("🇨🇳", "CNY", "Юань"),
        ("🇯🇵", "JPY", "JPY"),
        ("🇰🇷", "KRW", "Вон"),
        ("🇷🇺", "RUB", "Рубль"),
    ]
    for flag, code, name in currency_map:
        if code in mb_rates:
            currency_lines.append(f"{flag} {name}: {format_currency_mnt(mb_rates[code])}")

    if currency_lines:
        currency_section = "💵 ВАЛЮТЫН ХАНШ (төгрөгтэй харьцуулсан)\n" + " | ".join(currency_lines)
    else:
        currency_section = "💵 ВАЛЮТЫН ХАНШ\nӨгөгдөл түр хүртээмжгүй"

    # Индекс
    stock_lines = []
    for name in ["S&P 500", "Nasdaq", "Nikkei"]:
        if name in yf_data:
            d = yf_data[name]
            flag = {"S&P 500": "🇺🇸", "Nasdaq": "🇺🇸", "Nikkei": "🇯🇵"}[name]
            stock_lines.append(f"{flag} {name}: {d['price']:,.2f} {format_arrow(d['change_pct'])} {d['change_pct']:+.2f}%")

    stock_section = "🌐 ДЭЛХИЙН ХӨРӨНГИЙН ЗАХ ЗЭЭЛ\n"
    stock_section += " | ".join(stock_lines) if stock_lines else "Өгөгдөл түр хүртээмжгүй"

    # Крипто
    crypto_lines = []
    emojis = {"Bitcoin": "₿", "Ethereum": "Ξ", "Solana": "◎"}
    for name in ["Bitcoin", "Ethereum", "Solana"]:
        if name in yf_data:
            d = yf_data[name]
            crypto_lines.append(f"{emojis[name]} {name}: {format_price(d['price'])} {format_arrow(d['change_pct'])} {d['change_pct']:+.2f}%")

    crypto_section = "💎 КРИПТО ЗАХ ЗЭЭЛ\n"
    crypto_section += " | ".join(crypto_lines) if crypto_lines else "Өгөгдөл түр хүртээмжгүй"

    # Түүхий эд
    commodity_lines = []
    labels = {"Gold": "🥇 Алт", "Oil": "🛢️ Нефть", "Copper": "🔶 Зэс"}
    for name in ["Gold", "Oil", "Copper"]:
        if name in yf_data:
            d = yf_data[name]
            unit = {"Gold": "унц", "Oil": "баррель", "Copper": "фунт"}[name]
            commodity_lines.append(f"{labels[name]}: ${d['price']:,.2f}/{unit} {format_arrow(d['change_pct'])} {d['change_pct']:+.2f}%")

    commodity_section = "🏗️ ТҮҮХИЙ ЭД\n"
    commodity_section += " | ".join(commodity_lines) if commodity_lines else "Өгөгдөл түр хүртээмжгүй"

    # Дүгнэлт
    summary = "\n\n📰 ӨНӨӨДРИЙН ТОЙМ\n\n"
    if "S&P 500" in yf_data:
        sp500_change = yf_data["S&P 500"]["change_pct"]
        if sp500_change > 0.3:
            summary += f"Америкийн хувьцааны зах зээл өсөлттэй ({sp500_change:+.2f}%) байна."
        elif sp500_change < -0.3:
            summary += f"Америкийн хувьцааны зах зээл бууралттай ({sp500_change:+.2f}%) байна."
        else:
            summary += "Америкийн хувьцааны зах зээл тогтвортой байна."
    else:
        summary += "Дэлхийн зах зээлийн чиглэлийг дэлгэрэнгүй мэдээнээс уншина уу."

    summary += " Ази болон түүхий эдийн зах зээлийн гол үзүүлэлтийг доорх мэдээнээс уншина уу."

    header = f"📊 Дэлхийн хөрөнгийн зах зээл — {today}\n\n"
    header += "Өнөөдрийн Orange Market Watch таны өдрийн эхний санхүүгийн зурваст тавтай морилно уу. "
    header += "Дэлхийн томоохон биржүүд, валют, түүхий эдийн зах зээлийн гол үзүүлэлтүүдийг товчлон танилцуулж байна."

    body = f"{header}\n\n{currency_section}\n\n{stock_section}\n\n{crypto_section}\n\n{commodity_section}{summary}\n\nДэлгэрэнгүй мэдээллийг www.orangenews.mn сайтаас уншина уу."

    return body


if __name__ == "__main__":
    print("🔍 Market Data Fetcher v2 тест")
    print("=" * 60)

    body = build_market_watch_body()

    print("\n📰 ORANGE MARKET WATCH BODY:")
    print("=" * 60)
    print(body)
    print("=" * 60)

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
