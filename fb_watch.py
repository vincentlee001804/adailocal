# fb_watch.py — Watch the Xiaomi Malaysia Facebook public page for new posts
# and push them to Feishu/Lark via the existing Incoming Webhook.
#
# No Facebook login / Graph API required: uses headless Chromium (Playwright)
# with light stealth to render the public page, then extracts post permalinks
# from the timestamp anchors (aria-label like "14小時" / "2 hrs").
#
# Usage:
#   python fb_watch.py            # standalone one-shot scan
#   import fb_watch; fb_watch.scan_and_push()   # from adailocal.py loop
#
# Config (env / .env):
#   FB_PAGE_URL             default https://www.facebook.com/XiaomiMalaysia
#   FB_MAX_PUSH_PER_SCAN    default 3   (max cards pushed per scan)
#   FB_WATCH_INTERVAL_SEC   default 7200 (used by adailocal.py gate)
#   FB_WATCH_ENABLED        default 1   (set 0 to disable the gate)
#   SENT_FB_POSTS_PATH      default logs/sent_fb_posts.txt
#   FB_LAST_SCAN_PATH       default logs/fb_watch_last.txt
#
# Deps: pip install playwright && python -m playwright install chromium

import os
import re
import sys
import time
import hashlib

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def _load_env_file():
    """Load .env the same way adailocal.py does (manual fallback)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        return
    except ImportError:
        pass
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())
    except FileNotFoundError:
        pass


FB_PAGE_URL = os.environ.get("FB_PAGE_URL", "https://www.facebook.com/XiaomiMalaysia").strip()
FB_MAX_PUSH = int(os.environ.get("FB_MAX_PUSH_PER_SCAN", "3"))
SENT_FB_POSTS_PATH = os.environ.get("SENT_FB_POSTS_PATH", "logs/sent_fb_posts.txt")
FB_LAST_SCAN_PATH = os.environ.get("FB_LAST_SCAN_PATH", "logs/fb_watch_last.txt")

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

MAX_TRACKED_KEYS = 500  # how many sent-post keys we keep around

# --------------------------------------------------------------------------
# State persistence
# --------------------------------------------------------------------------

def load_sent_keys():
    try:
        with open(SENT_FB_POSTS_PATH, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except FileNotFoundError:
        return []


def save_sent_keys(keys):
    os.makedirs(os.path.dirname(SENT_FB_POSTS_PATH) or ".", exist_ok=True)
    with open(SENT_FB_POSTS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(keys[-MAX_TRACKED_KEYS:]) + "\n")


def get_last_scan_ts():
    try:
        with open(FB_LAST_SCAN_PATH, "r") as f:
            return int(f.read().strip() or "0")
    except Exception:
        return 0


def set_last_scan_ts(ts=None):
    os.makedirs(os.path.dirname(FB_LAST_SCAN_PATH) or ".", exist_ok=True)
    with open(FB_LAST_SCAN_PATH, "w") as f:
        f.write(str(int(ts or time.time())))


def _post_key(url):
    return hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()

# --------------------------------------------------------------------------
# Scraping
# --------------------------------------------------------------------------

# Runs inside the page. Finds timestamp anchors that link to post permalinks,
# walks up to the post container, and returns {url, time_label, text}.
_EXTRACT_JS = r"""
() => {
  const timeRe = /(分鐘|小時|日前|天|星期|週|剛剛|秒|hours?|hrs?|minutes?|mins?|days?|yesterday|just now|secs?)/i;
  const linkRe = /facebook\.com\/(reel\/\d+|watch\b|[A-Za-z0-9.\-]+\/posts\/|[A-Za-z0-9.\-]+\/videos\/|[A-Za-z0-9.\-]+\/permalink\/)/;
  const junk = /^(讚好|回應|分享|留言|查看更多回應|查看更多|所有心情|Like|Comment|Share|View more comments|Most relevant)/;

  const out = [];
  const seen = new Set();

  for (const a of document.querySelectorAll('a[role="link"][aria-label], a[aria-label]')) {
    const label = (a.getAttribute('aria-label') || '').trim();
    const href = a.href || '';
    if (!label || !timeRe.test(label)) continue;
    if (!linkRe.test(href)) continue;
    if (href.includes('comment_id')) continue;

    // Canonical permalink: strip tracking query params
    const url = href.split('?')[0].replace(/\/+$/, '');
    if (seen.has(url)) continue;
    seen.add(url);

    // Walk up to a container that looks like a full post
    let el = a, text = '';
    for (let i = 0; i < 15 && el; i++) {
      el = el.parentElement;
      if (!el) break;
      const t = (el.innerText || '').trim();
      if (t.length > 120) { text = t; break; }
    }

    // Trim trailing UI junk (reactions, comments section)
    let lines = text.split('\n').map(s => s.trim()).filter(Boolean);
    const cut = lines.findIndex(l => junk.test(l) || /^\d+$/.test(l));
    if (cut > 0) lines = lines.slice(0, cut);
    let snippet = lines.slice(1).join(' ');          // skip author-name line
    snippet = snippet.replace(label, ' ').replace(/\s+/g, ' ').trim();
    if (snippet.length > 400) snippet = snippet.slice(0, 400) + '…';

    out.push({ url, time_label: label, text: snippet });
  }
  return out;
}
"""


def scrape_posts(page_url=FB_PAGE_URL, wait_ms=10000, scrolls=3):
    """Render the public FB page headlessly and return a list of posts."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright not installed. Run: pip install playwright && "
            "python -m playwright install chromium"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        ctx = browser.new_context(
            user_agent=DESKTOP_UA,
            # Facebook serves the full anonymous page to zh-HK clients;
            # en-US gets a stripped login wall with no post anchors.
            locale="zh-HK",
            extra_http_headers={
                "Accept-Language": "zh-HK,zh-TW;q=0.9,zh;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            },
            viewport={"width": 1366, "height": 900},
        )
        # Hide automation markers — Facebook checks these
        ctx.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => false});
            window.chrome = { runtime: {} };
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
            """
        )
        page = ctx.new_page()
        resp = page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        status = resp.status if resp else "?"
        page.wait_for_timeout(wait_ms)
        for _ in range(scrolls):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(2500)
        posts = page.evaluate(_EXTRACT_JS)
        browser.close()

    print(f"📘 FB page HTTP {status}; extracted {len(posts)} post(s) from page")
    return posts

# --------------------------------------------------------------------------
# Push
# --------------------------------------------------------------------------

def _get_webhooks():
    urls, secret = [], os.environ.get("FEISHU_WEBHOOK_SECRET", "").strip()
    for k in ("FEISHU_WEBHOOK_URL", "FEISHU_WEBHOOK_URL_2", "FEISHU_WEBHOOK_URL_3"):
        u = os.environ.get(k, "").strip()
        if u:
            urls.append(u)
    return urls, secret


def _build_content(post):
    link = f"[查看 Facebook 帖子]({post['url']})"
    body = post.get("text") or "(無文字內容 / 媒體帖子)"
    return f"{body}\n\n⏰ 發佈於 {post.get('time_label', '未知時間')}前\n🔗 {link}"


def scan_and_push(webhook_urls=None, secret=None, page_url=FB_PAGE_URL):
    """One scan cycle: scrape → dedup → push new posts. Returns count pushed."""
    if webhook_urls is None:
        webhook_urls, secret = _get_webhooks()
    if not webhook_urls:
        print("❌ FB watch: no Feishu webhook configured, skipping push")
        return 0

    from adailocal import send_card_via_webhook  # reuse existing sender

    sent_keys = load_sent_keys()
    sent_set = set(sent_keys)

    posts = scrape_posts(page_url=page_url)
    if not posts:
        print("📘 FB watch: no posts found on page (layout change or block?)")
        return 0

    new_posts = [p for p in posts if _post_key(p["url"]) not in sent_set]
    if not new_posts:
        print(f"📘 FB watch: no new posts ({len(posts)} on page, all seen before)")
        return 0

    print(f"📘 FB watch: {len(new_posts)} new post(s) to push")
    pushed = 0
    for post in new_posts[:FB_MAX_PUSH]:
        title = "【Facebook】Xiaomi Malaysia 新帖子"
        content = _build_content(post)
        ok_any = False
        for wh in webhook_urls:
            try:
                # Returns None on success, raises on failure
                send_card_via_webhook(wh, title, content, secret=secret,
                                      attribution="Xiaomi Malaysia Facebook 專頁")
                ok_any = True
            except Exception as e:
                print(f"⚠️  FB watch: send failed for webhook: {e}")
        if ok_any:
            sent_keys.append(_post_key(post["url"]))
            pushed += 1
            print(f"✅ FB post pushed: {post['url']}")
        else:
            print(f"⚠️  FB post NOT marked sent (push failed): {post['url']}")
            break  # don't burn through the backlog on failures

    save_sent_keys(sent_keys)
    return pushed


# --------------------------------------------------------------------------

if __name__ == "__main__":
    _load_env_file()
    print(f"📘 FB watch standalone scan: {FB_PAGE_URL}")
    n = scan_and_push()
    set_last_scan_ts()
    print(f"📘 Done. {n} new post(s) pushed.")
    sys.exit(0)
