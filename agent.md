# agent.md — adailocal Project Guide

> Context file for AI agents (and humans) working in this repo. Read this first.

## 1. What this project is

**adailocal** is a Python bot that aggregates **Malaysia-focused news** from RSS feeds,
summarizes and classifies each story (in Chinese), and pushes interactive cards to
**Feishu/Lark group chats** via Incoming Webhooks (or the Feishu App API).

Primary audience/sources: Malaysian tech & general news sites (SoyaCincau, Amanz,
Lowyat, Oriental Daily, Astro Awani, Sinar Harian, Malaysiakini, Xiaomi/Mi blogs, etc.).

## 2. Repo layout

| Path | Purpose |
|------|---------|
| `adailocal.py` | **Core bot — single ~3,540-line module.** Feeds, dedup, classify, AI summarization, Feishu push, Flask webhook server, main loop. |
| `settings_ui.py` | Standalone local Flask UI (`http://127.0.0.1:5000`) to edit `.env` settings and `feeds.txt` without hand-editing files. |
| `feeds.txt` | RSS feed list. Format: `<feed_url> [# priority]`; `#` starts comments. |
| `.env` | Runtime secrets/config (gitignored). Loaded manually at startup if `python-dotenv` is absent. |
| `docs/README.md` | Human-facing documentation (quick start, deployment). |
| `deploy/Dockerfile`, `deploy/fly.toml`, `fly.toml` | Fly.io deployment (region `sin`, Docker, `/data` volume mount). |
| `.github/workflows/news.yml` | GitHub Actions scheduler — **currently disabled** (`if: ${{ false }}`, workflow_dispatch only). |
| `scripts/fb_probe.py` | Helper/probe script (dead RSSHub Facebook experiment, superseded by `fb_watch.py`). |
| `fb_watch.py` | **Facebook page watcher.** Scrapes the Xiaomi Malaysia public FB page with headless Chromium (no login), dedups, pushes new posts to Feishu. Runs standalone (`python fb_watch.py`) or gated inside the collector loop. |
| `archive/adaiori.py` | Old/experimental version. Do not modify. |
| `logs/` | Runtime artifacts: `adailocal.log` (rotating, 5 MB × 5), `sent_news.txt`, `sent_fb_posts.txt`, `fb_watch_last.txt`, `leader.lock`, etc. Gitignored. |
| `requirements.txt` | `requests, feedparser, beautifulsoup4, python-dateutil, lxml, sumy, google-generativeai, flask, playwright` |

## 3. Runtime architecture

Two run modes, selected by `ONE_SHOT` (`main()` at end of `adailocal.py`):

- **`ONE_SHOT=1`** — run one collection cycle synchronously and exit. Used by
  schedulers (GitHub Actions, cron, `fly ssh console`).
- **`ONE_SHOT=0` (default)** — start `run_collector_loop()` in a background daemon
  thread **and** run a Flask server on `PORT` (default 8080) exposing
  `POST /feishu/webhook` (Feishu event callback, can reply to messages) and health checks.

Per cycle (`collect_once()` + loop body):

1. **Load feeds** from `feeds.txt` (path overridable via `FEEDS_TXT_PATH`; on Fly.io uses `/data/feeds.txt`).
   On startup, `sync_image_feeds_to_data()` merges any **new feeds from the deployed image** (`/app/feeds.txt`) into the persistent volume copy, so adding feeds to the repo and redeploying automatically propagates them. Feeds tagged `# priority` are handled first; `DISABLE_RSS_APP=1` skips rss.app feeds.
2. **Fetch & parse** each feed with `feedparser`; skip items older than `RECENT_NEWS_HOURS` (default 24 h); resolve Google News redirect URLs.
3. **Deduplicate**, three layers:
   - URL-level: `sent_news.txt` (persisted, path via `SENT_NEWS_PATH`).
   - Story-level: Jaccard title similarity against stories pushed within
     `DEDUP_WINDOW_HOURS` (default 48 h), threshold `SIM_TITLE_THRESHOLD` (default 0.60).
   - Batch-level: `dedup_batch()` within the cycle.
4. **Enrich**: fetch article HTML (`read_article_content`), extract cover image,
   detect brand (`detect_brand` → `brand_category`), extract numeric facts for
   consistency checking.
5. **Classify** (`classify()`) into Chinese categories — 政治/科技/文娱/经济/体育/灾害/综合 —
   via keyword lists (conservative; falls back to 综合).
6. **Prioritize & sort** — before sending, items are sorted by:
   - Brand keywords (Xiaomi/REDMI/POCO/mijia) — absolute highest priority.
   - Priority feed flag (`# priority` in `feeds.txt`).
   - **Category weight** — 科技/灾难/文娱 (tier 1, weight 4), 经济/体育 (tier 2, weight 3), 政治 (tier 3, weight 2), 综合 (tier 4, weight 1).
   - Publication date (newest first).
7. **Summarize in Chinese**, LLM-first with fallback chain:
   - **Xiaomi MiMo** (`mimo_summarize_*`, retry with backoff, optional "deep thinking")
   - **Google Gemini** (`gemini_summarize_*`)
   - Local **TextRank** via `sumy` when `USE_AI_SUMMARY=1`, else safe truncation.
   - English-titled stories get a Chinese title regenerated
     (`ai_regenerate_chinese_title_only`).
   - Numeric-fact consistency check (`_numbers_consistent`) guards against hallucinated figures.
   - AI is instructed to `SKIP` low-content/empty articles.
7. **Push** to all configured webhooks (`FEISHU_WEBHOOK_URL`, `_2`, `_3`; optional
   HMAC sign with `FEISHU_WEBHOOK_SECRET`) as interactive cards, with cover image when
   available. Alternatively use the App API (`USE_APP_API=1` + `FEISHU_APP_ID/SECRET/CHAT_ID`).
   Optional logging to **Feishu Bitable** (`BITABLE_APP_TOKEN`, `BITABLE_TABLE_ID`).
   Sends at most `MAX_PUSH_PER_CYCLE` messages, spaced `SEND_INTERVAL_SEC` apart;
   the cycle breaks on send failure to avoid wasting AI tokens.
8. **Sleep** until the next `COLLECT_INTERVAL_SEC` boundary (default 600 s), aligned to
   clock boundaries (e.g. XX:00, XX:10).
9. **Facebook watch gate** (end of each cycle): if `FB_WATCH_ENABLED=1` (default) and the
   last FB scan is older than `FB_WATCH_INTERVAL_SEC` (default 7200 s / 2 h, persisted in
   `logs/fb_watch_last.txt`), `fb_watch.scan_and_push()` scrapes the Xiaomi Malaysia
   Facebook page and pushes new posts. Failures never affect the news loop, and the
   timestamp is stamped on attempt to avoid hammering Facebook.

**Leader election**: in loop mode, machines coordinate through `leader.lock`
(`/data/leader.lock` on Fly.io, `logs/leader.lock` locally; 5-minute TTL) so only one
machine pushes. Set `DISABLE_LEADER_ELECTION=1` for local testing.

**Logging**: built-in `print` is overridden (`print_log`) and routed to a `logging`
logger — console honors `LOG_LEVEL` (default INFO), file handler always records DEBUG
to `logs/adailocal.log`.

## 4. Configuration (environment variables / `.env`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `FEISHU_WEBHOOK_URL` (+ `_2`, `_3`) | — | Feishu group incoming webhook(s). Required unless App API used. |
| `FEISHU_WEBHOOK_SECRET` | — | Optional webhook HMAC signing secret. |
| `USE_APP_API` | `0` | `1` = send via Feishu App API instead of webhooks. |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_CHAT_ID` | — | App API credentials + target chat. |
| `GEMINI_API_KEY` | — | Google Gemini key (no hardcoded fallback). |
| `MIMO_API_KEY` / `MIMO_API_BASE` / `MIMO_MODEL` / `MIMO_DEEP_THINKING` | — / `https://api.xiaomimimo.com/v1` / `mimo-v2.5` / `true` | Xiaomi MiMo LLM settings (tried before Gemini). |
| `ONE_SHOT` | `0` | `1` = single cycle then exit. |
| `USE_AI_SUMMARY` | `0` | Enable AI/TextRank summaries (default truncation otherwise). |
| `MAX_PUSH_PER_CYCLE` | `1` | Max messages per cycle. |
| `SEND_INTERVAL_SEC` | `1.0` | Delay between sends within a cycle. |
| `COLLECT_INTERVAL_SEC` | `600` | Loop interval (clock-aligned). |
| `RECENT_NEWS_HOURS` | `24` | Ignore items older than this. |
| `DEDUP_WINDOW_HOURS` | `48` | Story-similarity dedup window. |
| `SIM_TITLE_THRESHOLD` | `0.60` | Jaccard threshold for story dedup. |
| `MIN_TITLE_LEN_FOR_SIM` | `8` | Min title-key length for similarity matching. |
| `BITABLE_APP_TOKEN` / `BITABLE_TABLE_ID` | — | Optional Feishu Bitable logging. |
| `SENT_NEWS_PATH` / `SENT_STORIES_PATH` / `FEEDS_TXT_PATH` | — | Override state/config file locations. |
| `TEST_WEBHOOKS` | `0` | `1` = run connectivity test at startup. |
| `DISABLE_LEADER_ELECTION` | `0` | `1` = skip leader lock (local testing). |
| `DISABLE_RSS_APP` | `0` | `1` = skip rss.app feeds. |
| `FB_WATCH_ENABLED` | `1` | `0` = disable the Facebook page watch gate. |
| `FB_WATCH_INTERVAL_SEC` | `7200` | Min seconds between FB scans (2 h default). |
| `FB_PAGE_URL` | `https://www.facebook.com/XiaomiMalaysia` | Facebook page to watch. |
| `FB_MAX_PUSH_PER_SCAN` | `3` | Max FB post cards pushed per scan. |
| `SENT_FB_POSTS_PATH` / `FB_LAST_SCAN_PATH` | `logs/sent_fb_posts.txt` / `logs/fb_watch_last.txt` | FB watcher state files. |
| `CHINESE_NAME_MAP` | — | Custom name-translation map. |
| `LOG_LEVEL` | `INFO` | Console log level. |
| `PORT` | `8080` | Flask listen port (loop mode). |

## 5. How to run

```bash
pip install -r requirements.txt          # Python 3.11+ (.python-version: 3.11.9)

# Local, one cycle (safe test):
set ONE_SHOT=1 && set DISABLE_LEADER_ELECTION=1
python adailocal.py

# Local, continuous loop + Flask on :8080:
python adailocal.py

# Settings UI (edit .env + feeds.txt in browser):
python settings_ui.py                    # http://127.0.0.1:5000

# Fly.io:
fly deploy -c deploy/fly.toml            # or root fly.toml
```

## 6. Conventions & gotchas for agents

- **Single-file core.** All bot logic lives in `adailocal.py`. It is long but organized
  in sections (logging → feeds → dedup → extraction → LLM → classify → collect → Flask → main).
  Make surgical edits; do not restructure without being asked.
- **`print` is monkey-patched** into the logger near the top of `adailocal.py`. Use
  `print(...)` for logging; messages containing "failed/error/❌/⚠️" auto-become WARNING,
  known noisy patterns become DEBUG.
- **Never commit secrets.** `.env` is gitignored; API keys must come from env vars.
  Do not hardcode keys (the Gemini key has no default by design).
- **State files** (`sent_news.txt`, sent-stories index, `leader.lock`) live in `logs/`
  or `/data` on Fly.io — respect the `*_PATH` overrides and the `/data` mount checks.
- **LLM fallback order matters**: MiMo → Gemini → TextRank → truncation. Keep that chain intact.
- **Summaries and titles are in Chinese**; classification categories are Chinese labels.
  `map_category_to_bitable()` maps them for Bitable.
- **GitHub Actions workflow is disabled** (`if: ${{ false }}`); don't assume CI runs.
- **`archive/` is frozen** — reference only.
- **FB watcher scraping is fragile by nature.** Key facts: Facebook only renders the full
  anonymous page for `zh-HK` locale + `Accept-Language` clients (en-US gets a login wall);
  stealth launch args (`--disable-blink-features=AutomationControlled`) are required;
  anonymously only the **latest** post has a permalink, so 2 posts inside one scan window
  means the older is skipped. If Facebook hardens the wall, fallback = add the page to
  rss.app and drop the feed into `feeds.txt`. Playwright browsers must be installed
  (`python -m playwright install chromium`); Fly.io Docker image has no browser, so the
  watcher is currently local-run only.
- **Feed sync on Fly.io** — because the `/data` volume persists across deploys, the running bot uses `/data/feeds.txt`, not the image's `/app/feeds.txt`. The `sync_image_feeds_to_data()` function runs on startup to merge any new feeds from the image into `/data`, so simply editing `feeds.txt` and redeploying now works without manual SSH intervention.
- **Category-based send priority** — `classify()` determines the category (科技/灾难/文娱/经济/体育/政治/综合), and the sort key applies category weights in addition to brand/priority/date. This is purely about send-order priority; the category label in the title remains the same.
  filtering, send-failure cycle breaking.

## 7. Quick verification after changes

1. `python -c "import adailocal"` — syntax/import check.
2. `ONE_SHOT=1 DISABLE_LEADER_ELECTION=1 MAX_PUSH_PER_CYCLE=1 python adailocal.py`
   with no webhook set → runs in TEST MODE (no actual sending).
3. Check `logs/adailocal.log` for feed warnings, dedup counts, category breakdown (`=== Category breakdown ===`), and send results.
