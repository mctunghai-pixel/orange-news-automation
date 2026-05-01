"""
Orange News — Market Data Writer
=================================
Fetches 8 instruments via Yahoo Finance and writes market_data.json
matching the frontend MarketInstrument schema.

Instruments: spx, dji, ixic, btc, eth, mntusd, xau, cl

On partial failure (some tickers fetch, others don't), merges fresh
data into the existing market_data.json so missing instruments keep
their last-known values. On total failure, leaves the existing file
untouched and exits non-zero so CI skips the commit.

Output: ./market_data.json (repo root, alongside this script)
"""

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import requests

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

try:
    import yfinance as yf
except ImportError:
    print("yfinance шаардлагатай: pip install yfinance")
    sys.exit(1)

OUTPUT_PATH = Path(__file__).resolve().parent / "market_data.json"

# yfinance USDMNT=X / MNT=X always return 1 row regardless of period — the
# ticker is effectively unusable. mntusd is fetched via ExchangeRate-API.
INSTRUMENTS = [
    {"slug": "spx",  "ticker": "^GSPC",   "symbol": "S&P 500", "name": "S&P 500 Index",        "assetClass": "index",     "currency": "USD"},
    {"slug": "dji",  "ticker": "^DJI",    "symbol": "DJIA",    "name": "Dow Jones Industrial", "assetClass": "index",     "currency": "USD"},
    {"slug": "ixic", "ticker": "^IXIC",   "symbol": "NASDAQ",  "name": "Nasdaq Composite",     "assetClass": "index",     "currency": "USD"},
    {"slug": "btc",  "ticker": "BTC-USD", "symbol": "BTC",     "name": "Bitcoin",              "assetClass": "crypto",    "currency": "USD"},
    {"slug": "eth",  "ticker": "ETH-USD", "symbol": "ETH",     "name": "Ethereum",             "assetClass": "crypto",    "currency": "USD"},
    {"slug": "xau",  "ticker": "GC=F",    "symbol": "XAU",     "name": "Gold Futures",         "assetClass": "commodity", "currency": "USD"},
    {"slug": "cl",   "ticker": "CL=F",    "symbol": "WTI",     "name": "Crude Oil WTI",        "assetClass": "commodity", "currency": "USD"},
]

MNTUSD_META = {
    "slug": "mntusd",
    "symbol": "USD/MNT",
    "name": "Mongolian Tögrög",
    "assetClass": "forex",
    "currency": "MNT",
}


def _series(series, n):
    sliced = series.iloc[-n:]
    return [
        {"date": idx.strftime("%Y-%m-%d"), "close": round(float(val), 4)}
        for idx, val in sliced.items()
    ]


def fetch_instrument(spec):
    ticker = yf.Ticker(spec["ticker"])
    hist = ticker.history(period="1y", interval="1d", auto_adjust=False)

    if len(hist) < 2:
        raise ValueError(f"insufficient history: {len(hist)} rows")

    closes = hist["Close"]
    last_close = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])
    change = last_close - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0

    instrument = {
        "slug": spec["slug"],
        "symbol": spec["symbol"],
        "name": spec["name"],
        "assetClass": spec["assetClass"],
        "currency": spec["currency"],
        "price": round(last_close, 4),
        "change": round(change, 4),
        "changePct": round(change_pct, 4),
        "open": round(float(hist["Open"].iloc[-1]), 4),
        "prevClose": round(prev_close, 4),
        "dayHigh": round(float(hist["High"].iloc[-1]), 4),
        "dayLow": round(float(hist["Low"].iloc[-1]), 4),
        "high52w": round(float(hist["High"].max()), 4),
        "low52w": round(float(hist["Low"].min()), 4),
        "history1w": _series(closes, 7),
        "history1m": _series(closes, 30),
        "lastUpdated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if spec["assetClass"] == "crypto":
        last_volume = float(hist["Volume"].iloc[-1])
        if last_volume > 0:
            instrument["volume24h"] = round(last_volume, 2)

    return instrument


def fetch_mntusd(existing):
    """USD→MNT via ExchangeRate-API. History grows organically (one point per UTC day, capped at 30)."""
    r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("result") != "success":
        raise ValueError(f"exchangerate-api result={data.get('result')}")

    rate = float(data["rates"]["MNT"])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    prior = existing.get("mntusd", {}) if existing else {}
    history = list(prior.get("history1m") or [])

    if history and history[-1].get("date") == today:
        history[-1] = {"date": today, "close": round(rate, 4)}
    else:
        history.append({"date": today, "close": round(rate, 4)})
    history = history[-30:]

    if len(history) >= 2:
        prev_close = history[-2]["close"]
        change = rate - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0
    else:
        prev_close = rate
        change = 0.0
        change_pct = 0.0

    closes = [h["close"] for h in history]

    return {
        **MNTUSD_META,
        "price": round(rate, 4),
        "change": round(change, 4),
        "changePct": round(change_pct, 4),
        "open": round(rate, 4),
        "prevClose": round(prev_close, 4),
        "dayHigh": round(rate, 4),
        "dayLow": round(rate, 4),
        "high52w": round(max(closes), 4),
        "low52w": round(min(closes), 4),
        "history1w": history[-7:],
        "history1m": history,
        "lastUpdated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main():
    print(f"Market data writer — {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")

    existing = {}
    if OUTPUT_PATH.exists():
        try:
            with OUTPUT_PATH.open("r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}

    fresh = {}
    for spec in INSTRUMENTS:
        try:
            fresh[spec["slug"]] = fetch_instrument(spec)
            price = fresh[spec["slug"]]["price"]
            change_pct = fresh[spec["slug"]]["changePct"]
            print(f"  ok   {spec['slug']:7s}  {price:>14,.4f}  {change_pct:+.2f}%")
        except Exception as e:
            print(f"  fail {spec['slug']:7s}  {e}")

    try:
        fresh["mntusd"] = fetch_mntusd(existing)
        m = fresh["mntusd"]
        print(f"  ok   {'mntusd':7s}  {m['price']:>14,.4f}  {m['changePct']:+.2f}%  (history: {len(m['history1m'])}d)")
    except Exception as e:
        print(f"  fail {'mntusd':7s}  {e}")

    if not fresh:
        print("No instruments fetched. Leaving existing market_data.json untouched.")
        sys.exit(1)

    merged = {**existing, **fresh}

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"Wrote {OUTPUT_PATH.name} — {len(merged)} instruments total, {len(fresh)} fresh.")


if __name__ == "__main__":
    main()
