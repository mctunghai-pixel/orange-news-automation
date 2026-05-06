# Montsame Mongolian-language scraper — Phase 6.1.5

**Status:** ✅ Implemented in `montsame_scraper.py` + `orange_rss_collector.py` integration hook.
**Shipped:** 2026-05-06.

Adds montsame.mn (Mongolia's official state news agency) as a second native-Mongolian source for the orange-news pipeline. Joins ikon.mn (RSS, already in `RSS_FEEDS`). Originally scoped as Day 6 Phase 8.1 Track B "Mongolian RSS expansion"; fell back to HTML scraping after Day 6 recon proved the Mongolian web doesn't expose RSS broadly (montsame / news.mn / gogo / eagle / shuud / unen / baabar all 404 / TCP-unreachable / serve HTML). See the dedicated memory entry `project_orange_news_mongolian_rss_dead.md` for the full probe matrix.

## Why this doc exists

Three things aren't obvious from reading `montsame_scraper.py` cold:

1. **Why HTML scraping rather than RSS or an API.** Montsame has no public RSS endpoint and no public JSON API. Day 6 recon ruled out the obvious paths (`/mn/rss.xml`, `/feed`, `/rss`, `/mn/rss/{economy,finance}.xml` all 404). HTML scraping is the only ingest option for this source.
2. **Why category URLs are numeric IDs, not name slugs.** Architect's original spec assumed `/mn/economy` and `/mn/finance` — those return 404. Day 9 recon mapped Montsame's actual category routing: `/mn/more/<numeric-id>`. Economy = `/mn/more/10`, Mining = `/mn/more/16`. The scraper hard-codes both as `CATEGORY_URLS` in the module — change requires editing the constant + redeploying. The mapping was extracted from the homepage nav (`grep -oE 'href="/mn/more/[0-9]+"[^>]*>[^<]+' /tmp/montsame_home.html`) and may shift if Montsame redesigns their nav.
3. **Why the translator integration is automatic.** Articles emitted with `category="mongolia"` route through the existing `process_mongolian_article` passthrough at `orange_translator.py:1473`. Translation is skipped (article is already Mongolian); only Bloomberg-grade editorial polish is applied (Rule 0/7 enforcement, headline 60-80 char range, footer + hashtags). The scraper just needs to set the right category — Phase 8.1 already wired the translator side end-to-end.

## Schema

**Output dicts** (matches `orange_rss_collector.fetch_feed()` shape exactly):

```python
{
  "title":     str,        # raw Montsame headline (translator polishes)
  "summary":   str,        # full article body, capped at 1500 chars
  "url":       str,        # https://www.montsame.mn/mn/read/<id>
  "published": str,        # ISO 8601 +08:00, fetch time (Montsame doesn't expose canonical pub time in HTML)
  "source":    "Montsame",
  "category":  "mongolia", # triggers process_mongolian_article passthrough
  "weight":    1.5,        # matches ikon.mn weight in RSS_FEEDS
}
```

## HTML structure (depended on)

The scraper depends on these CSS selectors. **If Montsame redesigns the page, these break:**

**Category page (`/mn/more/<id>`):**
```html
<div class="news-box">
  <a href="/mn/read/<id>">
    <div class="news-image-bg" style="background-image: url('/files/medium/<hash>.jpeg')">
    <div class="news-content">
      <div class="title content-mn">{headline}</div>
      <div class="body content-mn">{excerpt}</div>
    </div>
  </a>
</div>
```

Selectors:
- `div.news-box` — article card container
- `a[href]` matching `/mn/read/<digits>$` — article link
- `.title.content-mn` — headline
- `.body.content-mn` — excerpt
- `.news-image-bg` with `style` attr containing `background-image: url(...)` — featured image

**Article page (`/mn/read/<id>`):**

Body extraction is heuristic — pick the longest `.content-mn` block on the page. Header chrome and sidebar widgets share the class but carry only short snippets, so the longest block is reliably the article body. Falls back to `og:description` (clean ~200-char excerpt) if the heuristic finds nothing > 100 chars.

## CLI

```
python3 montsame_scraper.py
```

Standalone test: prints the top 3 articles with title / URL / body length / 160-char sample. No env vars required (no API keys; only HTTP).

## Workflow integration

The scraper is invoked from `orange_rss_collector.py` after the `RSS_FEEDS` loop:

```python
try:
    from montsame_scraper import fetch_articles as _fetch_montsame
    montsame_entries = _fetch_montsame(limit=3)
    all_entries.extend(montsame_entries)
    print(f"  ✓ MONGOLIA | {len(montsame_entries):2d} | montsame.mn (scraper)")
except Exception as e:
    print(f"[WARN] Montsame scraper failed: {type(e).__name__}: {e}")
```

Soft-fail at every layer:
- Per-article HTTP fetch: 3 attempts with exponential backoff (2s, 4s, 6s).
- Per-article parse: try/except, skip and continue on error.
- Total scraper failure: logged warning, the collector swallows and continues with the 13 RSS sources alone.

No new pip dependencies — `requests` and `bs4` are already used elsewhere in the codebase (`orange_translator.py`, `market_data_writer.py`).

## Maintenance — when Montsame changes their HTML

If the scraper starts producing 0 articles silently or the wrong text, the most likely cause is a Montsame template change. Diagnostic steps:

1. **Run the standalone CLI** (`python3 montsame_scraper.py`). Should print 3 articles. If it prints 0, parsing is broken.
2. **Check category-page structure**: `curl -s -A "Mozilla/5.0" "https://www.montsame.mn/mn/more/10" | grep -oE 'class="news-box[^"]*"' | head -3`. If no matches, the `.news-box` container class name changed — update `_parse_category_page()`.
3. **Check article-link pattern**: same curl + `grep -oE 'href="/mn/read/[0-9]+"' | head -3`. If no matches, article URL pattern changed — update `ARTICLE_HREF_RE`.
4. **Check title/body inner divs**: `curl ... | grep -oE 'class="title content-mn"\|class="body content-mn"' | head -5`. If gone, update the `.title.content-mn` / `.body.content-mn` selectors.
5. **Check article-page body extraction**: pick a real article URL, run the standalone CLI on a single URL via `python3 -c "from montsame_scraper import _http_get, _extract_full_body; print(_extract_full_body(_http_get('<URL>')))"`. If output is short / empty, the heuristic broke — likely needs a more specific selector instead of "longest .content-mn".

The `og:description` meta-tag fallback in `_extract_full_body()` provides graceful degradation: if the body heuristic fails but the article page is still reachable, the scraper emits the ~200-char excerpt instead of nothing.

## Capacity

- **Per cycle:** up to 3 articles (configurable via `limit` argument).
- **Per-category stub cap:** 6 (in case dedup across Economy + Mining trims aggressively).
- **Pipeline impact:** typically 1-2 Montsame articles in the final 10-post output — depends on the existing topic-quota selection in `_select_top_news_quota()`. Day 9 validation run produced 2 Montsame posts in the final mix (Energy policy + Oyu Tolgoi mining), doubling Mongolian content depth vs the previous ikon-only baseline.

## Migration policy

Fresh start from 2026-05-06. No historical Montsame archive — only Day 9+ content is captured.
