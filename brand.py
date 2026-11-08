"""
brand.py — single source of truth for the public brand.

Rebrand 2026-11 (Orange News → Aravt News) after the Orange Group trademark notice.
Every user-visible name, link, hashtag and colour comes from here, so a future
rename is one edit. Internal file/repo names (orange_translator.py, repo
orange-news-automation) are NOT public and stay as they are.
"""

NAME = "Aravt News"
NAME_UPPER = "ARAVT NEWS"
DOMAIN = "aravtnews.com"
SITE_URL = "https://www.aravtnews.com"
FACEBOOK = "facebook.com/AravtNews"
INSTAGRAM = "instagram.com/aravtnews"
TELEGRAM = "t.me/AravtNews"            # renamed from t.me/OrangeNewsMN 2026-11-08
HANDLE = "@AravtNews"
HASHTAG = "#AravtNews"
MW_TITLE = "Aravt Market Watch"
MW_BADGE = "📊 ARAVT MARKET WATCH"
MW_HASHTAG = "#AravtMarket"
BOT_UA = f"Mozilla/5.0 (compatible; AravtNews/1.0; +{SITE_URL})"

# Markers used to recognise our own already-formatted posts / Market Watch,
# including posts published before the rebrand (same day de-dupe).
DOMAIN_MARKERS = (DOMAIN, "orangenews.mn")
HASHTAG_MARKERS = (HASHTAG, "#OrangeNews")
MW_MARKERS = ("ARAVT MARKET WATCH", "ORANGE MARKET WATCH")

# Visual Standard v2 — palette A "Navy + Gold" (approved 2026-11-08)
NAVY = (8, 20, 43)        # #08142B
GOLD = (212, 175, 55)     # #D4AF37
GREY = (160, 172, 196)    # #A0ACC4

FOOTER_LINKS = f"""

━━━━━━━━━━━━━━━━━━━━━━

🌐 www.{DOMAIN}

📘 {FACEBOOK}

📷 {INSTAGRAM}

📨 Telegram: {TELEGRAM}"""


def is_formatted_post(text: str) -> bool:
    """True if text already carries our footer + brand hashtag."""
    return bool(text) and any(m in text for m in DOMAIN_MARKERS) and any(h in text for h in HASHTAG_MARKERS)


def is_market_watch(text: str) -> bool:
    return bool(text) and any(m in text for m in MW_MARKERS)
