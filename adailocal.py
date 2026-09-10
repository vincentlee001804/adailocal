# push_my_news.py
# deps: pip install requests feedparser beautifulsoup4 python-dateutil

import os, time, json, hashlib, requests
import re
import hmac, base64, hashlib as _hashlib
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # If python-dotenv is not installed, try to load .env manually
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
    except FileNotFoundError:
        pass  # .env file doesn't exist, use system environment variables

# --- LOGGING CONFIGURATION & INTERCEPTION ---
import logging
from logging.handlers import RotatingFileHandler

os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("adailocal")

# Read log level from environment variables (default to INFO)
log_level_env = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_env, logging.INFO)
logger.setLevel(logging.DEBUG)  # Capture everything, filter at handlers

# Unified log formatter
formatter = logging.Formatter(
    '[%(asctime)s] [%(levelname)s] %(message)s', 
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Console Handler (respects user configured level)
console_handler = logging.StreamHandler()
console_handler.setLevel(log_level)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# File Handler (always records everything at DEBUG level for auditing, rotates at 5MB)
file_handler = RotatingFileHandler(
    "logs/adailocal.log", 
    maxBytes=5 * 1024 * 1024, 
    backupCount=5, 
    encoding="utf-8"
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Intercept print
def print_log(*args, sep=" ", end="\n", file=None, flush=False):
    msg = sep.join(str(arg) for arg in args)
    lower_msg = msg.lower()
    
    # Classify messages into DEBUG, WARNING, or INFO
    if (
        "raw date:" in lower_msg 
        or "parsed date:" in lower_msg 
        or "checking:" in lower_msg
        or "skipping old news:" in lower_msg
        or "date parsing failed" in lower_msg
        or "no date found" in lower_msg
        or "date parsing error" in lower_msg
        or "cutoff:" in lower_msg
        or "resolving google news" in lower_msg
        or "resolved google news url" in lower_msg
        or "checking for local feed lock" in lower_msg
        or "google news redirect bypass" in lower_msg
        or "timeout for " in lower_msg
        or "request failed for " in lower_msg
        or "feed parse warning" in lower_msg
        or "bozo exception" in lower_msg
        or "found 0 new items" in lower_msg
        or "http 404 for" in lower_msg
        or "loading sent news" in lower_msg
        or "previously sent news urls" in lower_msg
    ):
        logger.debug(msg)
    elif "failed" in lower_msg or "error" in lower_msg or "❌" in msg or "⚠️" in msg:
        logger.warning(msg)
    else:
        logger.info(msg)

# Override built-in print
print = print_log

# Google Gemini API Configuration (no default hardcoded key)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Import Gemini
try:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    GEMINI_AVAILABLE = True
    print("✅ Google Gemini API configured successfully")
except ImportError:
    print("❌ Google Generative AI library not installed. Run: pip install google-generativeai")
    GEMINI_AVAILABLE = False
except Exception as e:
    print(f"❌ Failed to configure Gemini API: {e}")
    GEMINI_AVAILABLE = False

# Xiaomi MiMo LLM API Configuration
MIMO_API_KEY = os.getenv("MIMO_API_KEY", "").strip()
MIMO_API_BASE = os.getenv("MIMO_API_BASE", "https://api.xiaomimimo.com/v1").strip()
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5").strip()
mimo_deep_thinking_env = os.getenv("MIMO_DEEP_THINKING", "true").strip().lower()
MIMO_DEEP_THINKING = mimo_deep_thinking_env in ("1", "true")
MIMO_AVAILABLE = bool(MIMO_API_KEY)
if MIMO_AVAILABLE:
    thinking_status = "enabled" if MIMO_DEEP_THINKING else "disabled"
    print(f"✅ Xiaomi MiMo LLM API configured successfully (Deep Thinking: {thinking_status})")
else:
    print("ℹ️  Xiaomi MiMo LLM API not configured (MIMO_API_KEY not set)")

from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.text_rank import TextRankSummarizer
try:
    import nltk  # For tokenizers used by sumy
except Exception:
    nltk = None
 
# Feishu Open Platform base (international)
BASE = "https://open.feishu.cn"

def get_feeds_file_path():
    # Check if we are running on Fly.io / have access to persistent /data volume
    if os.path.exists("/data"):
        return "/data/feeds.txt"
    return os.environ.get("FEEDS_TXT_PATH", "feeds.txt")

DEFAULT_FEEDS = [
    "https://rss.app/feeds/M50McNEZ5iyyJ4LI.xml",
    "https://www.soyacincau.com/feed/",
    "https://cn.soyacincau.com/feed/",
    "https://amanz.my/feed/",
    "https://www.lowyat.net/feed/",
    "https://news.mi.com/global/rss",
    "https://blog.mi.com/en/feed",
    "https://www.orientaldaily.com.my/feed/",
    "https://cn.technave.com/feed/",
    "https://zinggadget.com/zh/feed/",
    "https://feeds.feedburner.com/soyacincau",
    "https://www.malaysiakini.com/rss/en/news.rss",
    "https://www.astroawani.com/rss/latest/en/public",
    "https://www.astroawani.com/rss/latest/public",
    "https://www.sinarharian.com.my/rss/terkini",
]

DEFAULT_PRIORITY_FEEDS = [
    "https://rss.app/feeds/7kWc8DwjcHvi1nOK.xml",
]

def load_feeds_from_file():
    """Load feeds from feeds.txt. If file does not exist, create it with defaults."""
    path = get_feeds_file_path()
    if not os.path.exists(path):
        try:
            parent = os.path.dirname(path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write("# Adailocal RSS feeds configuration\n")
                f.write("# Format: <feed_url> [# priority]\n\n")
                f.write("# Priority feeds\n")
                for pf in DEFAULT_PRIORITY_FEEDS:
                    f.write(f"{pf} # priority\n")
                f.write("\n# Regular feeds\n")
                for rf in DEFAULT_FEEDS:
                    f.write(f"{rf}\n")
            print(f"Created new feeds file with defaults at {path}")
        except Exception as e:
            print(f"⚠️ Failed to create feeds file: {e}")
            return list(DEFAULT_PRIORITY_FEEDS) + list(DEFAULT_FEEDS), set(DEFAULT_PRIORITY_FEEDS)

    feeds = []
    priority_feeds = set()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                
                # Check for priority suffix
                url = stripped
                is_priority = False
                if '#' in stripped:
                    url_part, comment_part = stripped.split('#', 1)
                    url = url_part.strip()
                    if 'priority' in comment_part.lower():
                        is_priority = True
                
                if url:
                    feeds.append(url)
                    if is_priority:
                        priority_feeds.add(url)
        print(f"Loaded {len(feeds)} feeds ({len(priority_feeds)} priority) from {path}")
    except Exception as e:
        print(f"⚠️ Failed to read feeds file: {e}")
        return list(DEFAULT_PRIORITY_FEEDS) + list(DEFAULT_FEEDS), set(DEFAULT_PRIORITY_FEEDS)
        
    return feeds, priority_feeds

def add_feed_to_file(feed_url, is_priority=False):
    """Appends a new feed URL to feeds.txt if it doesn't already exist."""
    path = get_feeds_file_path()
    # Check if already exists in file
    feeds, _ = load_feeds_from_file()
    if feed_url in feeds:
        return False, "already_exists"
        
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
            
        # Append to file
        with open(path, 'a', encoding='utf-8') as f:
            suffix = " # priority" if is_priority else ""
            # Ensure it starts on a new line
            f.write(f"\n{feed_url}{suffix}\n")
        print(f"Added new feed to {path}: {feed_url} (priority={is_priority})")
        return True, "success"
    except Exception as e:
        print(f"⚠️ Failed to write to feeds file: {e}")
        return False, str(e)

def sync_image_feeds_to_data():
    """Merge any new feeds from the deployed image's /app/feeds.txt into /data/feeds.txt
    so that adding feeds to the repo and redeploying actually propagates to Fly machines
    that use a persistent /data volume."""
    image_path = "/app/feeds.txt"
    data_path = "/data/feeds.txt"
    if not os.path.exists(image_path) or not os.path.exists(data_path):
        return
    try:
        def parse_feeds(path):
            feeds = {}
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith('#'):
                        continue
                    url = stripped
                    is_priority = False
                    if '#' in stripped:
                        url_part, comment_part = stripped.split('#', 1)
                        url = url_part.strip()
                        if 'priority' in comment_part.lower():
                            is_priority = True
                    if url:
                        feeds[url] = is_priority
            return feeds

        image_feeds = parse_feeds(image_path)
        data_feeds = parse_feeds(data_path)
        
        # Add feeds from image that are missing in /data
        added = []
        for url, is_priority in image_feeds.items():
            if url not in data_feeds:
                suffix = " # priority" if is_priority else ""
                data_feeds[url] = is_priority
                added.append(url)
        
        # Remove feeds from /data that are no longer in the image
        removed = []
        for url in list(data_feeds.keys()):
            if url not in image_feeds:
                del data_feeds[url]
                removed.append(url)
        
        # Rewrite /data/feeds.txt with the synced set, preserving priority flags
        priority_feeds = [u for u, p in data_feeds.items() if p]
        regular_feeds = [u for u, p in data_feeds.items() if not p]
        with open(data_path, 'w', encoding='utf-8') as f:
            f.write("# Adailocal RSS feeds configuration\n")
            f.write("# Format: <feed_url> [# priority]\n")
            if priority_feeds:
                f.write("\n# Priority feeds\n")
                for u in priority_feeds:
                    f.write(f"{u} # priority\n")
            f.write("\n# Regular feeds\n")
            for u in regular_feeds:
                f.write(f"{u}\n")
        
        if added:
            print(f"[sync] Added {len(added)} new feed(s): {added}")
        if removed:
            print(f"[sync] Removed {len(removed)} stale feed(s): {removed}")
        if not added and not removed:
            print(f"[sync] /data/feeds.txt already in sync with image ({len(data_feeds)} feeds)")
    except Exception as e:
        print(f"[sync] Warning: could not sync image feeds to /data: {e}")

# Initial load of RSS_FEEDS and PRIORITY_FEEDS
sync_image_feeds_to_data()
RSS_FEEDS, PRIORITY_FEEDS = load_feeds_from_file()

# All news categories are now supported (经济, 体育, 文娱, 灾害, 科技, 综合)
TIMEOUT = (5, 15)

# Time-based dedup (only consider items from last 24 hours)
from datetime import datetime, timedelta

# Tech filtering removed - now supports all news categories

def is_recent_news(published_at_str, hours=24):
    """Check if news is recent enough to be considered for deduplication"""
    if not published_at_str:
        print(f"  No date found, considering recent")
        return True  # If no date, consider it recent
    
    try:
        published_at = dateparser.parse(published_at_str)
        if published_at is None:
            print(f"  Date parsing failed, considering recent")
            return True
        
        # Check if date is in the future (reject future dates)
        now = datetime.now(published_at.tzinfo) if published_at.tzinfo else datetime.now()
        if published_at > now:
            print(f"  Future date detected: {published_at}, rejecting")
            return False
        
        # Also reject dates that are clearly wrong (like 2026+ when we're in 2025)
        current_year = datetime.now().year
        if published_at.year > current_year:
            print(f"  Suspicious future year detected: {published_at.year}, rejecting")
            return False
        
        # Check if published within last N hours
        cutoff = now - timedelta(hours=hours)
        is_recent = published_at >= cutoff
        
        print(f"  Date: {published_at}, Cutoff: {cutoff}, Recent: {is_recent}")
        return is_recent
    except Exception as e:
        print(f"  Date parsing error: {e}, considering recent")
        return True  # If parsing fails, consider it recent

# In-memory dedup for current run only (time-based filtering handles cross-run)
SEEN = set()
SENT_URLS = set()  # Track URLs that have been sent to prevent repeats

# Persistent deduplication file (can be overridden to a mounted volume path)
SENT_NEWS_FILE = os.environ.get("SENT_NEWS_PATH", "logs/sent_news.txt").strip() or "logs/sent_news.txt"

def load_sent_news():
    """Load previously sent news URLs from file"""
    sent_urls = set()
    try:
        if os.path.exists(SENT_NEWS_FILE):
            with open(SENT_NEWS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    url = line.strip()
                    if url:
                        sent_urls.add(url)
        print(f"Loaded {len(sent_urls)} previously sent news URLs")
    except Exception as e:
        print(f"Error loading sent news: {e}")
    return sent_urls

def save_sent_news(sent_urls):
    """Save sent news URLs to file"""
    try:
        # Ensure parent directory exists when using volume paths like /data/sent_news.txt
        try:
            parent = os.path.dirname(SENT_NEWS_FILE)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
        except Exception:
            pass
        with open(SENT_NEWS_FILE, 'w', encoding='utf-8') as f:
            for url in sorted(sent_urls):
                f.write(f"{url}\n")
        print(f"Saved {len(sent_urls)} sent news URLs to file")
    except Exception as e:
        print(f"Error saving sent news: {e}")

def is_news_already_sent(url, sent_urls):
    """Check if news URL has already been sent"""
    return url in sent_urls

def get_tenant_access_token(app_id, app_secret):
    url = f"{BASE}/open-apis/auth/v3/tenant_access_token/internal"
    headers = {'Content-Type': 'application/json; charset=utf-8'}
    payload = {'app_id': app_id, 'app_secret': app_secret}
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("code") == 0:
        return data["tenant_access_token"]
    raise RuntimeError(f"token_error: {data}")

def send_card_message(token, chat_id, title, content, attribution=None):
    url = f"{BASE}/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    elements = [
        { "tag": "div", "text": { "tag": "lark_md", "content": content } },
        { "tag": "hr" }
    ]
    # Add attribution if provided (on separate line above disclaimer)
    if attribution:
        elements.append({ "tag": "div", "text": { "tag": "lark_md", "content": attribution } })
    elements.append({ "tag": "div", "text": { "tag": "lark_md", "content": "\n\n注：摘要、正文均不代表个人观点" } })
    card = {
        "header": { "title": { "content": title, "tag": "plain_text" }, "template": "wathet" },
        "config": { "wide_screen_mode": True },
        "elements": elements
    }
    payload = { "receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False) }
    r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    if r.status_code != 200:
        print(f"❌ Feishu send message API error response: {r.status_code} - {r.text}")
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        print(f"send_fail: {data}")

def send_card_message_with_image(token, chat_id, title, content, image_key, attribution=None):
    url = f"{BASE}/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    elements = []
    if image_key:
        elements.append({
            "tag": "img",
            "img_key": image_key,
            "alt": {"tag": "plain_text", "content": title}
        })
    elements.extend([
        { "tag": "div", "text": { "tag": "lark_md", "content": content } },
        { "tag": "hr" }
    ])
    # Add attribution if provided (on separate line above disclaimer)
    if attribution:
        elements.append({ "tag": "div", "text": { "tag": "lark_md", "content": attribution } })
    elements.append({ "tag": "div", "text": { "tag": "lark_md", "content": "\n\n注:摘要，正文均不代表个人观点。摘要经过AI总结,可能存在误差,请以原文为准。" } })
    card = {
        "header": { "title": { "content": title, "tag": "plain_text" }, "template": "wathet" },
        "config": { "wide_screen_mode": True },
        "elements": elements
    }
    payload = { "receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False) }
    r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    if r.status_code != 200:
        print(f"❌ Feishu send message (image) API error response: {r.status_code} - {r.text}")
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        print(f"send_fail: {data}")

def _build_card(title, content, attribution=None):
	elements = [
		{ "tag": "div", "text": { "tag": "lark_md", "content": content } },
		{ "tag": "hr" }
	]
	# Add attribution if provided (on separate line above disclaimer)
	if attribution:
		elements.append({ "tag": "div", "text": { "tag": "lark_md", "content": attribution } })
	elements.append({ "tag": "div", "text": { "tag": "lark_md", "content": "\n\n注:摘要、正文均不代表个人观点" } })
	return {
		"header": { "title": { "content": title, "tag": "plain_text" }, "template": "wathet" },
		"config": { "wide_screen_mode": True },
		"elements": elements
	}

def _gen_webhook_sign(secret, timestamp):
	if not secret:
		return None
	string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
	digest = hmac.new(secret.encode("utf-8"), string_to_sign, digestmod=_hashlib.sha256).digest()
	return base64.b64encode(digest).decode("utf-8")

def test_webhook_connectivity(webhook_urls, secret=None):
    """Test webhook connectivity with a simple test message"""
    print("🧪 Testing webhook connectivity...")
    
    test_title = "🔧 Webhook Test"
    test_content = "This is a test message to verify webhook connectivity. If you see this, your webhook is working correctly!"
    
    return send_to_multiple_webhooks(webhook_urls, test_title, test_content, secret)

def send_to_multiple_webhooks(webhook_urls, title, content, secret=None, attribution=None):
    """Send the same message to multiple webhook URLs"""
    success_count = 0
    total_count = len(webhook_urls)
    
    print(f"🚀 Starting to send to {total_count} webhook(s)...")
    
    for i, webhook_url in enumerate(webhook_urls, 1):
        try:
            print(f"📤 Sending to webhook {i}/{total_count}: {webhook_url[:50]}...")
            print(f"  🔗 Full URL: {webhook_url}")
            print(f"  📝 Title: {title[:50]}...")
            print(f"  🔐 Secret: {'Set' if secret else 'Not set'}")
            
            send_card_via_webhook(webhook_url, title, content, secret, attribution)
            success_count += 1
            print(f"✅ Webhook {i} sent successfully")
        except Exception as webhook_error:
            print(f"❌ Webhook {i} failed: {webhook_error}")
            print(f"  🔍 Error details: {type(webhook_error).__name__}: {str(webhook_error)}")
            continue
    
    print(f"📊 Summary: {success_count}/{total_count} webhooks sent successfully")
    if success_count == 0:
        print("❌ All webhooks failed! Check your URLs and secrets.")
    elif success_count < total_count:
        print(f"⚠️  Some webhooks failed ({total_count - success_count} failed)")
    return success_count > 0

def send_card_via_webhook(webhook_url, title, content, secret=None, attribution=None):
	# Always send interactive card so markdown links are clickable
	card = _build_card(title, content, attribution)
	payload = { "msg_type": "interactive", "card": card }
	
	max_retries = 3
	initial_delay = 2.0
	
	for attempt in range(max_retries):
		if secret:
			ts = str(int(time.time()))
			sign = _gen_webhook_sign(secret, ts)
			payload.update({ "timestamp": ts, "sign": sign })
		try:
			r = requests.post(webhook_url, json=payload, timeout=TIMEOUT)
			print(f"  📡 Webhook response status: {r.status_code}")
			
			data = r.json()
			print(f"  📋 Webhook response: {data}")
			if isinstance(data, dict):
				code = data.get("code")
				if code == 0:
					print(f"  ✅ Webhook success with card: {data}")
					return
				elif code == 11232:
					# Frequency limited / rate limit
					delay = initial_delay * (2 ** attempt)
					print(f"  ⏳ Feishu rate limit (code 11232) hit. Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
					time.sleep(delay)
					continue
				else:
					print(f"  ❌ Webhook error (code {code}): {data.get('msg', 'Unknown error')}")
					raise Exception(f"Feishu webhook error: {data}")
			else:
				print(f"  ✅ Webhook success with card: {data}")
				return
		except Exception as e:
			if attempt == max_retries - 1:
				print(f"  ❌ Webhook send failed after {max_retries} attempts.")
				raise e
			else:
				delay = initial_delay * (2 ** attempt)
				print(f"  ⚠️ Request error: {e}. Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
				time.sleep(delay)

# --- Feishu Bitable helpers ---
# Env vars required:
#   BITABLE_APP_TOKEN, BITABLE_TABLE_ID, FEISHU_APP_ID, FEISHU_APP_SECRET
def add_bitable_record(token, app_token, table_id, record_fields):
    """Append a row to Feishu Bitable."""
    url = f"{BASE}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    # Filter out None values and empty strings to avoid errors
    filtered_fields = {k: v for k, v in record_fields.items() if v is not None and v != ""}
    payload = {"fields": filtered_fields}
    r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        # Check if it's a field name error - provide helpful message
        error_code = data.get("code")
        error_msg = data.get("msg", "")
        if error_code == 1254045 or "FieldNameNotFound" in error_msg:
            error_detail = data.get("error", {})
            field_name = ""
            if isinstance(error_detail, dict):
                error_message = error_detail.get("message", "")
                # Try to extract field name from error message
                if "fields." in error_message:
                    parts = error_message.split("fields.")
                    if len(parts) > 1:
                        field_name = parts[1].split(".")[0]
            raise RuntimeError(f"Bitable field '{field_name}' not found in table. Please create this field in your Bitable or update the code. Error: {data}")
        raise RuntimeError(f"Bitable write failed: {data}")
    return data

def maybe_log_to_bitable(fields):
    """Safely log a news item to Bitable if env vars are configured."""
    app_token = os.environ.get("BITABLE_APP_TOKEN", "").strip()
    table_id = os.environ.get("BITABLE_TABLE_ID", "").strip()
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if not app_token or not table_id:
        return  # Not configured, skip silently
    if not app_id or not app_secret:
        print("⚠️  BITABLE_* is set but FEISHU_APP_ID/SECRET missing; skip logging.")
        return
    try:
        token = get_tenant_access_token(app_id, app_secret)
    except Exception as e:
        print(f"⚠️  Failed to get tenant token for Bitable logging: {e}")
        return
    try:
        add_bitable_record(token, app_token, table_id, fields)
        print("📝 Logged to Bitable")
    except Exception as e:
        print(f"⚠️  Failed to log to Bitable: {e}")

def _norm(u): return (u or "").split("?")[0]
def _key(link, title): return hashlib.sha1(((_norm(link) or title) or "").encode("utf-8","ignore")).hexdigest()
def _clean(html): return " ".join(BeautifulSoup(html or "", "lxml").get_text(" ").split())

# ---------------------------------------------------------------------------
# Story-level (cross-source) deduplication
# ---------------------------------------------------------------------------
# Catches the case where multiple media outlets publish the same story under
# different URLs (e.g. The Star + Lowyat + Malaysiakini all covering the same
# Xiaomi launch). We compare normalized titles using character-bigram Jaccard,
# which works for both Chinese and English without external NLP deps.

# Persistent log of stories that have been pushed (for cross-run dedup).
SENT_STORIES_FILE = os.environ.get("SENT_STORIES_PATH", "logs/sent_stories.jsonl").strip() or "logs/sent_stories.jsonl"

# How long a sent story keeps blocking similar stories (hours).
try:
    DEDUP_WINDOW_HOURS = int(os.environ.get("DEDUP_WINDOW_HOURS", "48"))
except Exception:
    DEDUP_WINDOW_HOURS = 48

# Title-bigram Jaccard threshold above which two titles are treated as the same story.
try:
    SIM_TITLE_THRESHOLD = float(os.environ.get("SIM_TITLE_THRESHOLD", "0.60"))
except Exception:
    SIM_TITLE_THRESHOLD = 0.60

# Below this normalized-title length we only do exact-key match (similarity is
# unreliable on very short titles because a single overlapping bigram can spike Jaccard).
try:
    MIN_TITLE_LEN_FOR_SIM = int(os.environ.get("MIN_TITLE_LEN_FOR_SIM", "8"))
except Exception:
    MIN_TITLE_LEN_FOR_SIM = 8


def _norm_title_key(title: str) -> str:
    """Strict normalized title for exact-match fast path. Lowercase, strip
    whitespace + punctuation, keep CJK + alnum."""
    if not title:
        return ""
    return re.sub(r'[\s\W_]+', '', title.lower(), flags=re.UNICODE)


def _story_signature(title: str):
    """Language-agnostic story signature: char bigrams of the normalized title.
    Returns a frozenset for cheap Jaccard math."""
    t = _norm_title_key(title)
    if len(t) < 2:
        return frozenset({t}) if t else frozenset()
    return frozenset(t[i:i+2] for i in range(len(t) - 1))


def _jaccard(a, b) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def load_sent_stories():
    """Load stories sent within the dedup window. Returns a list of dicts with
    a precomputed _sig field for fast similarity checks."""
    cutoff = time.time() - DEDUP_WINDOW_HOURS * 3600
    out = []
    if not os.path.exists(SENT_STORIES_FILE):
        print(f"No sent-stories file yet at {SENT_STORIES_FILE}")
        return out
    try:
        with open(SENT_STORIES_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("ts", 0) < cutoff:
                    continue
                rec["_sig"] = _story_signature(rec.get("title", ""))
                out.append(rec)
        print(f"Loaded {len(out)} sent stories within last {DEDUP_WINDOW_HOURS}h (window dedup)")
    except Exception as e:
        print(f"Error loading sent stories: {e}")
    return out


def append_sent_story(url: str, title: str, source: str):
    """Append a single sent story to the JSONL log."""
    try:
        parent = os.path.dirname(SENT_STORIES_FILE)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        rec = {
            "ts": int(time.time()),
            "url": url or "",
            "title": title or "",
            "title_key": _norm_title_key(title or ""),
            "source": source or "",
        }
        with open(SENT_STORIES_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"Error appending sent story: {e}")


def is_similar_to_sent(title: str, sent_stories):
    """Return the matching sent record if a similar story was already pushed,
    else None. Uses exact title_key fast path then bigram Jaccard."""
    if not title or not sent_stories:
        return None
    key = _norm_title_key(title)
    if not key:
        return None
    sig = _story_signature(title)
    short_title = len(key) < MIN_TITLE_LEN_FOR_SIM
    for rec in sent_stories:
        if key and rec.get("title_key") == key:
            return rec
        if short_title:
            continue
        rec_sig = rec.get("_sig")
        if not rec_sig:
            continue
        if len(rec.get("title_key") or "") < MIN_TITLE_LEN_FOR_SIM:
            continue
        if _jaccard(sig, rec_sig) >= SIM_TITLE_THRESHOLD:
            return rec
    return None


def dedup_batch(items):
    """Collapse near-duplicate items within a single fetch round so we don't
    queue 5 versions of the same story for the next 5 cycles. Keeps the first
    occurrence (which is already sorted to be the highest-priority one)."""
    if not items:
        return items
    kept = []
    sigs = []  # list of (title_key, _sig) tuples for items we kept
    dropped = 0
    for it in items:
        title = it.get("title", "") or ""
        key = _norm_title_key(title)
        if not key:
            kept.append(it)
            continue
        sig = _story_signature(title)
        is_dup = False
        for k_seen, sig_seen in sigs:
            if key == k_seen:
                is_dup = True
                break
            if len(key) >= MIN_TITLE_LEN_FOR_SIM and len(k_seen) >= MIN_TITLE_LEN_FOR_SIM:
                if _jaccard(sig, sig_seen) >= SIM_TITLE_THRESHOLD:
                    is_dup = True
                    break
        if is_dup:
            dropped += 1
            continue
        sigs.append((key, sig))
        kept.append(it)
    if dropped:
        print(f"🧹 In-batch similarity dedup removed {dropped} item(s); {len(kept)} remain")
    return kept

def has_brand_keywords(title):
    """Check if title contains Xiaomi, REDMI, POCO, or mijia brand keywords (case-insensitive)."""
    if not title:
        return False
    title_lower = title.lower()
    brand_keywords = ['xiaomi', 'redmi', 'poco', 'mijia']
    return any(keyword in title_lower for keyword in brand_keywords)

def _extract_source_from_url(url):
    """Extract source name from article URL"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Remove www. prefix
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Handle CMS subdomains (cms.domain.com -> domain.com)
        if domain.startswith('cms.'):
            print(f"  🔧 Removing CMS subdomain: {domain} -> {domain[4:]}")
            domain = domain[4:]  # Remove 'cms.' prefix
        
        # Handle Google News URLs - extract from resolved URL if available
        if 'news.google.com' in domain:
            # Try to extract actual source from the resolved URL
            resolved_url = _resolve_actual_url(url)
            if resolved_url != url:
                return _extract_source_from_url(resolved_url)
            return "Google News"
        
        # Map domains to friendly names
        domain_mapping = {
            'lowyat.net': 'Lowyat.NET',
            'soyacincau.com': 'SoyaCincau',
            'cn.soyacincau.com': 'SoyaCincau 中文',
            'bm.soyacincau.com': 'SoyaCincau BM',
            'amanz.my': 'Amanz',
            'technave.com': 'TechNave',
            'cn.technave.com': 'TechNave 中文',
            'zinggadget.com': 'Zing Gadget 中文',
            'vtechgraphy.com': 'VTecH Graphy',
            'fuzz.my': 'Fuzz.my',
            'izamigadget.com': 'Izami Gadget',
            'klgadgetguy.com': 'KL Gadget Guy',
            'nasilemaktech.com': 'Nasi Lemak Tech',
            'nextrift.com': 'Nextrift',
            'thevocket.com': 'The Vocket',
            'leetechnews.wordpress.com': 'Lee Tech News',
            'sea.ign.com': 'IGN SEA',
            'gamerbraves.com': 'GamerBraves',
            'gamersantai.com': 'Gamer Santai',
            'wanuxi.com': 'Wanuxi',
            'adamlobo.tv': 'Adam Lobo TV',
            'malaysiakini.com': 'Malaysiakini',
            'thestar.com.my': 'The Star',
            'nst.com.my': 'New Straits Times',
            'bernama.com': 'Bernama',
            'freemalaysiatoday.com': 'Free Malaysia Today',
            'hmetro.com.my': 'Harian Metro',
            'chinapress.com.my': 'China Press',
            'sinchew.com.my': 'Sin Chew Daily',
            'samsung.com': 'Samsung Malaysia',
            'samsung.com.my': 'Samsung Malaysia',
            'msn.com': 'MSN',
            'cnn.com': 'CNN',
            'bbc.com': 'BBC',
            'reuters.com': 'Reuters'
        }
        
        return domain_mapping.get(domain, domain.title())
    except Exception:
        return "未知来源"

def _format_source_name(source):
    """Format source name to be more user-friendly"""
    if not source:
        return "未知来源"
    
    # Clean up common RSS feed names
    source = source.replace(" - All", "").replace(" - Latest News", "").replace(" RSS", "")
    source = source.replace("Online", "").replace("Latest", "").replace("News", "")
    source = source.replace("  ", " ").strip()
    
    # Handle Google News specific formatting
    if "Google News" in source:
        return "Google News"
    if "news.google.com" in source:
        return "Google News"
    
    # Handle Google search result feeds that show "search term - Google"
    if " - Google" in source:
        # Extract the search term and use it as source
        search_term = source.replace(" - Google", "").strip()
        return search_term
    
    # Handle Google News feeds - try to extract actual source from URL patterns
    if "news.google.com" in source or "Google News" in source:
        return "Google News"
    
    # Handle specific known sources
    if "lowyat" in source.lower():
        return "Lowyat.NET"
    if "soyacincau" in source.lower():
        return "SoyaCincau"
    if "amanz" in source.lower():
        return "Amanz"
    if "malaysiakini" in source.lower():
        return "Malaysiakini"
    if "astroawani" in source.lower():
        return "Astro Awani"

    # Do not append any suffix; show the original media name only
    return source

# Known Chinese name mapping (extendable via env CHINESE_NAME_MAP as JSON)
_DEFAULT_CHINESE_NAME_MAP = {
    "Tiong King Sing": "张庆信",
    "Xi Jinping": "习近平",
    "Jack Ma": "马云",
    "Lei Jun": "雷军",
    "Pony Ma": "马化腾",
    "Robin Li": "李彦宏",
    "William Ding": "丁磊",
}

def _load_chinese_name_map():
    try:
        env_json = os.getenv("CHINESE_NAME_MAP", "").strip()
        if env_json:
            import json as _json
            user_map = _json.loads(env_json)
            if isinstance(user_map, dict):
                return {**_DEFAULT_CHINESE_NAME_MAP, **user_map}
    except Exception:
        pass
    return dict(_DEFAULT_CHINESE_NAME_MAP)

CHINESE_NAME_MAP = _load_chinese_name_map()

def _apply_chinese_name_map(text: str) -> str:
    try:
        if not text:
            return text
        out = text
        for en, zh in CHINESE_NAME_MAP.items():
            out = re.sub(rf"\b{re.escape(en)}\b", zh, out)
        return out
    except Exception:
        return text
def _resolve_actual_url(url: str) -> str:
    """Resolve real article URL from Google News or Google redirect links.
    - For news.google.com/rss/articles?...&url=ACTUAL, extract the 'url'/'u' param
    - For generic google.com/url?url=..., extract and unquote
    - Otherwise, follow redirects with a lightweight HEAD/GET
    """
    try:
        if not url:
            return url
        from urllib.parse import urlparse, parse_qs, unquote
        parsed = urlparse(url)
        host = (parsed.netloc or '').lower()
        
        # Direct extraction from query param (most reliable for Google News)
        if 'news.google.com' in host or 'google.com' in host:
            qs = parse_qs(parsed.query)
            for key in ('url', 'u'):
                if key in qs and qs[key]:
                    candidate = unquote(qs[key][0])
                    if candidate.startswith('http'):
                        print(f"  🔗 Resolved Google News URL: {candidate}")
                        return candidate
        
        # Fallback: follow redirects with better error handling
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            r = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            final_url = r.url or url
            if final_url != url:
                print(f"  🔗 Resolved redirect URL: {final_url}")
            return final_url
        except Exception as e:
            print(f"  ⚠️  Redirect resolution failed: {e}")
            return url
    except Exception as e:
        print(f"  ⚠️  URL resolution failed: {e}")
        return url


def read_article_content(url):
    """Read and extract the main content from an article URL"""
    try:
        resolved_url = _resolve_actual_url(url)
        if resolved_url != url:
            print(f"  🔗 Resolved URL: {resolved_url}")
        print(f"  📖 Reading article: {resolved_url}")
        
        # More comprehensive headers to avoid blocking
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        }
        
        response = requests.get(resolved_url, headers=headers, timeout=20, allow_redirects=True)
        print(f"  📡 Response status: {response.status_code}, Content length: {len(response.content)}")
        
        if response.status_code != 200:
            print(f"  ❌ HTTP error: {response.status_code}")
            return ""
        
        # Check if we got HTML content
        content_type = response.headers.get('content-type', '').lower()
        if 'html' not in content_type:
            print(f"  ❌ Not HTML content: {content_type}")
            return ""
        
        # Debug: Check if page has anti-bot protection or paywall
        page_text = response.text.lower()
        anti_bot_phrases = ['cloudflare', 'access denied', 'blocked', 'captcha', 'robot', 'bot detection']
        paywall_phrases = ['subscribe', 'paywall', 'unlock', 'premium', 'members only', 'sign in to continue']
        
        has_anti_bot = any(phrase in page_text for phrase in anti_bot_phrases)
        has_paywall = any(phrase in page_text for phrase in paywall_phrases)
        
        if has_anti_bot:
            print(f"  ⚠️  Possible anti-bot protection detected")
            # Try with different headers
            headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            print(f"  🔄 Retrying with different User-Agent...")
            try:
                response = requests.get(resolved_url, headers=headers, timeout=20, allow_redirects=True)
                print(f"  📡 Retry response: {response.status_code}, Content length: {len(response.content)}")
            except Exception as e:
                print(f"  ❌ Retry failed: {e}")
                return ""
        
        if has_paywall:
            print(f"  🔒 Paywall detected - article content may be limited")
        
        soup = BeautifulSoup(response.content, 'html.parser')

        # Generic improvements for aggregator → source bridging
        # 1) Follow canonical and AMP versions when available (many sites expose cleaner AMP HTML)
        try:
            amp = soup.find('link', rel=lambda v: v and 'amphtml' in v.lower())
            if amp and amp.get('href') and 'amp' in amp['href']:
                amp_url = amp['href']
                if not amp_url.startswith('http'):
                    from urllib.parse import urljoin
                    amp_url = urljoin(resolved_url, amp_url)
                print(f"  🔁 Following AMP page for cleaner content: {amp_url}")
                amp_resp = requests.get(amp_url, headers=headers, timeout=15, allow_redirects=True)
                if amp_resp.status_code == 200 and 'html' in amp_resp.headers.get('content-type','').lower():
                    amp_soup = BeautifulSoup(amp_resp.content, 'html.parser')
                    amp_paras = amp_soup.find_all('p')
                    if amp_paras:
                        amp_text = " ".join([p.get_text(strip=True) for p in amp_paras if len(p.get_text(strip=True)) > 20])
                        if len(amp_text) > 100:
                            print("  🎯 Using AMP paragraphs as main content")
                            return amp_text[:8000]
        except Exception:
            pass

        # 2) Try to extract JSON-LD Article/NewsArticle on ANY domain
        try:
            import json as _json
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = _json.loads(script.string or '{}')
                except Exception:
                    continue
                def _extract_from(obj):
                    if not isinstance(obj, dict):
                        return None
                    t = obj.get('@type')
                    if isinstance(t, list):
                        t = next((x for x in t if isinstance(x, str)), None)
                    if t in ('Article', 'NewsArticle', 'Report', 'BlogPosting'):
                        body = (obj.get('articleBody') or obj.get('description') or '').strip()
                        if body and len(body) > 80:
                            return body
                    # Some sites nest under "mainEntityOfPage"
                    if isinstance(obj.get('mainEntityOfPage'), dict):
                        return _extract_from(obj['mainEntityOfPage'])
                    return None
                if isinstance(data, list):
                    for obj in data:
                        body = _extract_from(obj)
                        if body:
                            print('  🎯 JSON-LD: extracted article body')
                            return " ".join(body.split())[:8000]
                else:
                    body = _extract_from(data)
                    if body:
                        print('  🎯 JSON-LD: extracted article body')
                        return " ".join(body.split())[:8000]
        except Exception:
            pass

        # Domain-specific extraction: MSN articles are often JS-heavy; prefer JSON-LD/OG data
        if 'msn.com' in resolved_url:
            try:
                # Try JSON-LD Article/NewsArticle payload
                for script in soup.find_all('script', type='application/ld+json'):
                    try:
                        import json as _json
                        data = _json.loads(script.string or '{}')
                        if isinstance(data, list):
                            for obj in data:
                                if isinstance(obj, dict) and obj.get('@type') in ('Article', 'NewsArticle'):
                                    body = (obj.get('articleBody') or '').strip()
                                    if body and len(body) > 80:
                                        print('  🎯 MSN: extracted articleBody from JSON-LD')
                                        return " ".join(body.split())[:8000]
                        elif isinstance(data, dict) and data.get('@type') in ('Article', 'NewsArticle'):
                            body = (data.get('articleBody') or '').strip()
                            if body and len(body) > 80:
                                print('  🎯 MSN: extracted articleBody from JSON-LD')
                                return " ".join(body.split())[:8000]
                    except Exception:
                        continue
                # Fallback to OpenGraph/Twitter description
                og_desc = soup.find('meta', attrs={'property': 'og:description'}) or soup.find('meta', attrs={'name': 'description'})
                if og_desc and og_desc.get('content'):
                    text = og_desc['content'].strip()
                    if len(text) > 50:
                        print('  🎯 MSN: using OG/description as content fallback')
                        return text[:8000]
            except Exception:
                pass
        
        # Remove unwanted elements
        for element in soup(["script", "style", "nav", "header", "footer", "aside", "noscript", "iframe"]):
            element.decompose()
        
        # Lowyat.NET: ensure we only read the first article block
        if 'lowyat.net' in resolved_url:
            try:
                # Prefer the first explicit article container
                main_article = (
                    soup.find('article') or
                    soup.select_one('.entry-content') or
                    soup.select_one('.post-content') or
                    soup.select_one('.article-content')
                )
                if main_article:
                    # Collect only meaningful paragraphs inside the first article
                    text_parts = []
                    for p in main_article.find_all('p'):
                        t = p.get_text(strip=True)
                        if len(t) > 20:
                            text_parts.append(t)
                    if text_parts:
                        content = ' '.join(text_parts)
                        print("  🎯 Lowyat: extracted from first <article> container")
                        # continue to common cleanup and return later
                        # Clean up the content
                        content = " ".join(content.split())
                        if len(content) > 8000:
                            content = content[:8000]
                            print("  ✂️  Truncated to 8000 characters")
                        print(f"  ✅ Article content extracted: {len(content)} characters")
                        if content:
                            print(f"  📄 Content preview: {content[:200]}...")
                        return content
                # Fallback: accumulate <p> tags from the whole page until stop markers
                stop_markers = [
                    'ALSO READ', 'Filed Under', 'TRENDING THIS WEEK', 'No Result',
                    'View All Result', 'Follow us on', 'Share on Facebook', 'Share on Twitter'
                ]
                collected = []
                for p in soup.find_all('p'):
                    text = p.get_text(strip=True)
                    if not text:
                        continue
                    if any(text.upper().startswith(m.upper()) for m in stop_markers):
                        break
                    if len(text) > 20:
                        collected.append(text)
                if collected:
                    content = ' '.join(collected)
                    print("  🎯 Lowyat: extracted first-news paragraphs with stop markers")
                    content = " ".join(content.split())
                    if len(content) > 8000:
                        content = content[:8000]
                        print("  ✂️  Truncated to 8000 characters")
                    print(f"  ✅ Article content extracted: {len(content)} characters")
                    if content:
                        print(f"  📄 Content preview: {content[:200]}...")
                    return content
            except Exception as _e:
                print(f"  ⚠️ Lowyat-specific extraction failed: {_e}")

        # More comprehensive content selectors for Malaysian news sites
        content_selectors = [
            # Specific content containers FIRST (generic 'article' often matches
            # sidebar widget cards, e.g. JNews-theme sites like SoyaCincau)
            '.entry-content', '.post-content', '.article-content', '.story-content',
            '.article-body', '.post-body', '.entry-body', '.content-body',

            # Malaysian news site specific selectors
            '.article-text', '.article-body-text', '.story-text', '.news-content',
            '.post-text', '.entry-text', '.content-text', '.article-main',

            # Generic containers
            '.content', '.main-content', 'main', '.main', '#content', '#main',
            '.post', '.entry', '.story',

            # Bare <article> last among containers — handled specially below
            'article',

            # Generic content areas
            '.text', '.body', '.article',
            'p', '.paragraph', '.content-paragraph'
        ]

        content = ""
        for selector in content_selectors:
            elements = soup.select(selector)
            if elements:
                if selector == 'article':
                    # Many themes (e.g. JNews) wrap sidebar/related-post cards in
                    # <article> tags too. Take the single LARGEST article element
                    # (the real story body) instead of joining all of them.
                    candidates = [e for e in elements if len(e.get_text(strip=True)) > 50]
                    if candidates:
                        best = max(candidates, key=lambda e: len(e.get_text(strip=True)))
                        content = best.get_text(strip=True)
                        print(f"  🎯 Found content with selector: article (largest of {len(elements)} matches)")
                        break
                    continue
                # Get text from all matching elements
                text_parts = []
                for elem in elements:
                    text = elem.get_text(strip=True)
                    if len(text) > 50:  # Only include substantial text blocks
                        text_parts.append(text)

                if text_parts:
                    content = " ".join(text_parts)
                    print(f"  🎯 Found content with selector: {selector}")
                    break
        
        # If no specific content found, try to get all paragraph text
        if not content or len(content) < 100:
            paragraphs = soup.find_all('p')
            if paragraphs:
                content = " ".join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20])
                print(f"  📝 Using paragraph text: {len(paragraphs)} paragraphs")
        
        # Final fallback - get all text
        if not content or len(content) < 100:
            content = soup.get_text()
            print(f"  🔄 Using all text as fallback")
        
        # Clean up the content
        content = " ".join(content.split())  # Remove extra whitespace
        
        # Limit content length for API
        if len(content) > 8000:
            content = content[:8000]
            print(f"  ✂️  Truncated to 8000 characters")
        
        print(f"  ✅ Article content extracted: {len(content)} characters")
        
        # Debug: show first 200 characters
        if content:
            print(f"  📄 Content preview: {content[:200]}...")
            # Additional debug: check for key terms to verify we got the right article
            content_lower = content.lower()
            if 'xiaomi' in content_lower or 'redmi' in content_lower:
                print(f"  📱 Xiaomi/Redmi content detected - this appears to be mobile tech content")
            elif 'samsung' in content_lower or 'galaxy' in content_lower:
                print(f"  📱 Samsung content detected - competitor news")
            elif 'apple' in content_lower or 'iphone' in content_lower:
                print(f"  📱 Apple/iPhone content detected - competitor news")
            elif 'oneplus' in content_lower or 'oppo' in content_lower or 'vivo' in content_lower:
                print(f"  📱 Chinese brand content detected - competitor news")
            elif 'forza' in content_lower:
                print(f"  🎮 Forza content detected - this appears to be gaming content (may be off-topic)")
            else:
                print(f"  📝 Content type unclear from preview")
        
        # Final debugging - show what we extracted
        if content:
            print(f"  ✅ Final content extracted: {len(content)} characters")
            print(f"  📄 Content preview: {content[:200]}...")
        else:
            print(f"  ❌ No content extracted from {resolved_url}")
            page_title = soup.find('title').get_text() if soup.find('title') else 'No title'
            print(f"  🔍 Page title: {page_title}")
            print(f"  🔍 Page has {len(soup.find_all('p'))} paragraphs")
            print(f"  🔍 Page has {len(soup.find_all('article'))} article elements")
            
            # Check for common reasons why extraction failed
            if has_paywall:
                print(f"  💡 Reason: Paywall detected - article requires subscription")
            elif 'subscribe' in page_text or 'unlock' in page_text:
                print(f"  💡 Reason: Likely paywall - subscription required")
            elif len(soup.find_all('p')) < 3:
                print(f"  💡 Reason: Page has very few paragraphs - may be paywall or redirect page")
            else:
                print(f"  💡 Reason: Content extraction failed - page structure may not match expected format")
        
        return content
        
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Request error: {e}")
        return ""
    except Exception as e:
        print(f"  ❌ Error reading article: {e}")
        return ""

def extract_cover_image_from_html(html, base_url):
    try:
        soup = BeautifulSoup(html, 'html.parser')
        # Prefer OpenGraph/Twitter cards
        og = soup.find('meta', property='og:image')
        if og and og.get('content'):
            return og['content']
        tw = soup.find('meta', attrs={'name': 'twitter:image'})
        if tw and tw.get('content'):
            return tw['content']
        # Fallback: first meaningful <img>
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src')
            if src and len(src) > 10 and not src.startswith('data:'):
                return src
    except Exception:
        pass
    return None

BRAND_PATTERNS = {
    'xiaomi': ['xiaomi', 'mi ', 'redmi', 'poco'],
    'samsung': ['samsung', 'galaxy'],
    'apple': ['apple', 'iphone', 'ipad', 'mac'],
    'vivo': ['vivo', 'iqoo'],
    'oppo': ['oppo', 'oneplus'],
    'huawei': ['huawei', 'honor'],
    'realme': ['realme'],
    'google': ['google', 'pixel'],
    'sony': ['sony', 'xperia'],
    'lg': ['lg'],
    'motorola': ['motorola', 'moto']
}

def detect_brand(text: str) -> str:
    """Detect primary brand from text."""
    if not text:
        return "other"
    lower = text.lower()
    for brand, patterns in BRAND_PATTERNS.items():
        if any(p in lower for p in patterns):
            return brand
    return "other"

def brand_category(brand: str) -> str:
    """Map brand to Xiaomi vs Competitor."""
    if not brand:
        return "Other"
    if brand.lower() in ("xiaomi", "poco", "redmi", "mi"):
        return "Xiaomi"
    if brand.lower() == "other":
        return "Other"
    return "Competitor"

def map_category_to_bitable(chinese_category: str) -> str:
    """Map Chinese category from classify() or LLM to English Bitable category options.
    
    Bitable options: Politics, Economy, Technology, Entertainment, Sports, 
                     Health, Environment, Science, Education, Culture
    """
    if not chinese_category:
        return "Politics"
    
    # Normalize the category (handle variations)
    category_lower = chinese_category.strip()
    
    mapping = {
        "政治": "Politics",
        "经济": "Economy",
        "科技": "Technology", 
        "文娱": "Entertainment",
        "娱乐": "Entertainment",  # LLM might return "娱乐" instead of "文娱"
        "体育": "Sports",
        "灾害": "Environment",  # Disaster/Environment related
        "灾难": "Environment",  # LLM might return "灾难" instead of "灾害"
        "综合": "Politics"  # General/Comprehensive -> Politics as default / fallback
    }
    return mapping.get(category_lower, "Politics")  # Default to Politics if not found

def _extract_numeric_facts(text: str):
    """Extract numeric facts (prices, currencies, dates-like numbers) from text.
    Returns a dict with sets: prices, currencies, numbers, raw_tokens.
    """
    try:
        if not text:
            return {"prices": set(), "currencies": set(), "numbers": set(), "raw_tokens": set()}
        tokens = set()
        prices = set()
        currencies = set()
        numbers = set()
        specs = set()
        # Common currency symbols and codes
        currency_patterns = [r"RM\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?", r"MYR\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?", r"USD\s?\$?\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?", r"US\$\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?", r"\$\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?", r"SGD\s?\$?\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?", r"EUR\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?", r"£\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?"]
        for pat in currency_patterns:
            for m in re.findall(pat, text, flags=re.IGNORECASE):
                prices.add(m.strip())
                tokens.add(m.strip())
        # Specs with units (e.g., 6.7-inch, 120Hz, 5000mAh, 12GB, 200MP, 120W)
        spec_patterns = [
            r"\b\d{1,2}(?:\.\d)?\s?(?:inch|in|英寸)\b",
            r"\b\d{2,4}\s?mAh\b",
            r"\b\d{2,4}\s?Hz\b",
            r"\b\d{1,3}\s?(?:GB|TB)\b",
            r"\b\d{1,3}\s?MP\b",
            r"\b\d{1,3}\s?W\b",
            r"\b\d{2,4}x\d{2,4}\b",
            r"\b\d{2,3}%\b",
            r"\b\d{2}\s?nm\b",
        ]
        for pat in spec_patterns:
            for m in re.findall(pat, text, flags=re.IGNORECASE):
                specs.add(m.strip())
                tokens.add(m.strip())
        # Standalone numbers (avoid years already captured by prices)
        for m in re.findall(r"\b\d{1,3}(?:[,\.]\d{3})*(?:\.\d+)?\b", text):
            numbers.add(m)
            tokens.add(m)
        # Currency mentions without amounts
        for m in re.findall(r"\b(RM|MYR|USD|US\$|SGD|EUR|GBP)\b", text, flags=re.IGNORECASE):
            currencies.add(m.upper())
        # Merge specs into tokens
        tokens |= specs
        return {"prices": prices, "currencies": currencies, "numbers": numbers, "specs": specs, "raw_tokens": tokens}
    except Exception:
        return {"prices": set(), "currencies": set(), "numbers": set(), "specs": set(), "raw_tokens": set()}

def _find_numeric_tokens(text: str):
    if not text:
        return set()
    found = set()
    # capture currency+amount and plain numbers
    for m in re.findall(r"(RM\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|MYR\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|USD\s?\$?\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|US\$\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|SGD\s?\$?\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|\$\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|£\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|\b\d{1,3}(?:[,\.]\d{3})*(?:\.\d+)?\b|\b\d{1,2}(?:\.\d)?\s?(?:inch|in|英寸)\b|\b\d{2,4}\s?mAh\b|\b\d{2,4}\s?Hz\b|\b\d{1,3}\s?(?:GB|TB)\b|\b\d{1,3}\s?MP\b|\b\d{1,3}\s?W\b|\b\d{2,4}x\d{2,4}\b|\b\d{2}\s?nm\b|\b\d{2,3}%\b)", text, flags=re.IGNORECASE):
        found.add(m.strip())
    return found

def _numbers_consistent(summary: str, source_facts: dict) -> bool:
    """Return True if all numeric tokens in summary are present in source facts (prices/numbers)."""
    try:
        if not summary:
            return True
        summary_nums = _find_numeric_tokens(summary)
        if not summary_nums:
            return True
        source_tokens = set(source_facts.get("raw_tokens", set())) | set(source_facts.get("prices", set())) | set(source_facts.get("numbers", set()))
        # simple normalization: remove spaces in currency like "RM 1,299" -> "RM1,299"
        def _norm_set(s):
            out = set()
            for t in s:
                out.add(t.replace(" ", ""))
            return out
        return _norm_set(summary_nums).issubset(_norm_set(source_tokens))
    except Exception:
        return True

def extract_cover_image(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        return extract_cover_image_from_html(r.text, url)
    except Exception:
        return None

def upload_image_to_feishu(token, image_url):
    try:
        r = requests.get(image_url, timeout=10)
        if r.status_code != 200:
            return None
        files = {
            'image': ('cover.jpg', r.content, 'image/jpeg')
        }
        data = { 'image_type': 'message' }
        up = requests.post(f"{BASE}/open-apis/im/v1/images", headers={'Authorization': f'Bearer {token}'}, files=files, data=data, timeout=20)
        if up.status_code != 200:
            print(f"❌ Feishu image upload API error response: {up.status_code} - {up.text}")
        up.raise_for_status()
        resp = up.json()
        if resp.get('code') == 0:
            return resp['data']['image_key']
        print(f"image_upload_fail: {resp}")
    except Exception as e:
        print(f"image_upload_error: {e}")
    return None

def gemini_summarize_from_url(title, article_url):
    """Use Google Gemini AI to read and summarize the article directly from URL"""
    if not GEMINI_AVAILABLE:
        raise Exception("Gemini API not available")
    
    try:
        print(f"  🤖 Gemini reading and summarizing: {title[:50]}...")
        
        # Read article content first
        article_content = read_article_content(article_url)
        if not article_content or len(article_content.strip()) < 50:
            raise Exception("Failed to read article content or content too short")
        
        # Extract facts for grounding
        facts = _extract_numeric_facts(article_content)
        facts_list = sorted(list(facts.get('raw_tokens', set())))
        facts_block = "\n".join(facts_list[:40])
        
        # Extract mentioned products and brands
        source_lower = article_content.lower()
        mentioned_products = []
        mentioned_brands = []
        
        # Brand detection patterns
        brand_patterns = {
            'xiaomi': ['xiaomi', 'mi ', 'redmi', 'poco'],
            'samsung': ['samsung', 'galaxy'],
            'apple': ['apple', 'iphone', 'ipad', 'mac'],
            'vivo': ['vivo', 'iqoo'],
            'oppo': ['oppo', 'oneplus'],
            'huawei': ['huawei', 'honor'],
            'realme': ['realme'],
            'google': ['google', 'pixel'],
            'sony': ['sony', 'xperia'],
            'lg': ['lg'],
            'motorola': ['motorola', 'moto']
        }
        
        # Detect mentioned brands
        for brand, patterns in brand_patterns.items():
            if any(pattern in source_lower for pattern in patterns):
                mentioned_brands.append(brand.title())
        
        # Look for model numbers
        import re
        model_patterns = [
            r'\b[a-z]+\s*\d{2,4}[a-z]*\b',  # Like "X300", "Y28", "15T"
            r'\b[a-z]+\s*[a-z]+\s*\d+[a-z]*\b',  # Like "iPhone 15", "Redmi Note 12"
        ]
        
        for pattern in model_patterns:
            matches = re.findall(pattern, source_lower)
            for match in matches:
                if len(match) > 3:
                    mentioned_products.append(match.title())
        
        products_context = f"Products mentioned in source: {', '.join(mentioned_products)}" if mentioned_products else "No specific products mentioned"
        brands_context = f"Brands mentioned in source: {', '.join(mentioned_brands)}" if mentioned_brands else "No specific brands mentioned"
        
        # Create Gemini prompt (aligned with MiMo summary length and style)
        prompt = f"""请阅读以下新闻文章并提供：

1. **中文标题（带分类标签）** - 格式：【分类】中文标题
2. **中文摘要** - 不超过100字，用2-3句完整的话总结新闻的关键信息（时间、地点、主体、关键数字和影响）

要求：
- 如果文章极其简短、或者缺乏实质性内容（例如没有明确的产品型号、品牌名称、具体参数规格或核心功能介绍，仅为视频引流或社交媒体互动等），请将“标题”和“摘要”均直接输出为 "SKIP"。
- 标题和摘要必须用简体中文（不要使用繁体中文）
- 分类选项：科技、娱乐、经济、体育、灾难、政治、综合
- 人名、品牌名、产品名、地名保持原文（英文/马来文），不要翻译成中文（如Nabil Halimi、PKR、Malaysiakini等应保持原样）
- 只使用文章中明确提到的数字和事实
- 不要添加文章中未提及的产品或信息
- 摘要不能只是简单改写标题，必须补充标题中没有的细节（如具体机型、价格、合作方、时间等）
- 保持专业、清晰的表达
- **重要：请仔细阅读文章内容，不要只基于标题生成摘要**

文章标题: {title}
文章内容: {article_content[:5000]}...

来源信息:
{products_context}
{brands_context}

提取的事实: {facts_block}

请按以下格式回复：
标题: 【分类】中文标题
摘要: 中文摘要"""

        # Initialize Gemini model
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        print(f"  📤 Sending request to Gemini API...")
        response = model.generate_content(prompt)
        
        if not response.text:
            raise Exception("Empty response from Gemini")
        
        content = response.text.strip()
        print(f"  📡 Gemini API response received: {len(content)} characters")
        
        # Parse the response
        lines = content.split('\n')
        chinese_title = ""
        summary = ""
        
        for line in lines:
            line = line.strip()
            if line.startswith('标题:'):
                chinese_title = line.replace('标题:', '').strip()
            elif line.startswith('摘要:'):
                summary = line.replace('摘要:', '').strip()
            elif not chinese_title and line and not line.startswith('摘要:'):
                chinese_title = line
            elif chinese_title and line and not line.startswith('标题:'):
                if summary:
                    summary += " " + line
                else:
                    summary = line
        
        # Fallback if parsing failed
        if not chinese_title or not summary:
            print(f"  ⚠️  Could not parse title/summary, using full content")
            chinese_title = f"【科技】{title}"
            summary = content[:200] + "..." if len(content) > 200 else content
        
        print(f"  ✅ Gemini Chinese title: {chinese_title}")
        print(f"  ✅ Gemini summary generated: {len(summary)} characters")
        
        return chinese_title, summary
        
    except Exception as e:
        print(f"  ❌ Gemini summarization failed: {e}")
        # Fallback to simple truncation
        return f"【科技】{title}", (article_content[:500] + "..." if len(article_content) > 500 else article_content)

def gemini_summarize_content(title, article_content):
    """Use Google Gemini AI to summarize pre-extracted article content"""
    if not GEMINI_AVAILABLE:
        raise Exception("Gemini API not available")
    
    try:
        print(f"  🤖 Gemini summarizing content: {title[:50]}...")
        
        # Extract facts for grounding
        facts = _extract_numeric_facts(article_content)
        facts_list = sorted(list(facts.get('raw_tokens', set())))
        facts_block = "\n".join(facts_list[:40])
        
        # Create Gemini prompt (aligned with MiMo summary length and style)
        prompt = f"""请分析以下新闻文章并提供：

1. **中文标题（带分类标签）** - 格式：【分类】中文标题
2. **中文摘要** - 不超过100字，用2-3句完整的话总结新闻的关键信息（时间、地点、主体、关键数字和影响）

要求：
- 如果文章极其简短、或者缺乏实质性内容（例如没有明确的产品型号、品牌名称、具体参数规格或核心功能介绍，仅为视频引流或社交媒体互动等），请将“标题”和“摘要”均直接输出为 "SKIP"。
- 标题和摘要必须用简体中文（不要使用繁体中文）
- 分类选项：科技、娱乐、经济、体育、灾难、政治、综合
- 人名、品牌名、产品名、地名保持原文（英文/马来文），不要翻译成中文（如Nabil Halimi、PKR、Malaysiakini等应保持原样）
- 只使用文章中明确提到的数字和事实
- 不要添加文章中未提及的产品或信息
- 摘要不能只是简单改写标题，必须补充标题中没有的细节（如具体机型、价格、合作方、时间等）
- 保持专业、清晰的表达
- **重要：请仔细阅读文章内容，不要只基于标题生成摘要**

文章标题: {title}

文章内容:
{article_content}

提取的事实: {facts_block}

请按以下格式回复：
标题: 【分类】中文标题
摘要: 中文摘要"""

        # Initialize Gemini model
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        print(f"  📤 Sending request to Gemini API...")
        response = model.generate_content(prompt)
        
        if not response.text:
            raise Exception("Empty response from Gemini")
        
        content = response.text.strip()
        print(f"  📡 Gemini API response received: {len(content)} characters")
        
        # Parse the response to extract title and summary
        try:
            lines = content.split('\n')
            chinese_title = ""
            summary = ""
            
            for line in lines:
                line = line.strip()
                if line.startswith('标题:'):
                    chinese_title = line.replace('标题:', '').strip()
                elif line.startswith('摘要:'):
                    summary = line.replace('摘要:', '').strip()
                elif not chinese_title and line and not line.startswith('摘要:'):
                    # If no title found yet, this might be the title
                    chinese_title = line
                elif chinese_title and line and not line.startswith('标题:'):
                    # If we have a title, this is part of the summary
                    if summary:
                        summary += " " + line
                    else:
                        summary = line
            
            # If we couldn't parse properly, use the whole content as summary
            if not chinese_title or not summary:
                print(f"  ⚠️  Could not parse title/summary, using full content")
                chinese_title = title  # Fallback to original title
                summary = content
            
            print(f"  ✅ Gemini Chinese title: {chinese_title}")
            print(f"  ✅ Gemini summary generated: {len(summary)} characters")

            return chinese_title, summary
            
        except Exception as e:
            print(f"  ⚠️  Error parsing response: {e}")
            print(f"  📄 Raw content: {content[:200]}...")
            # Fallback: return original title and full content as summary
            return title, content
        
    except Exception as e:
        print(f"  ❌ Gemini API error: {e}")
        # Fallback to simple truncation
        return f"【科技】{title}", (article_content[:500] + "..." if len(article_content) > 500 else article_content)

def _mimo_api_request_with_retry(url, headers, payload, max_retries=5, initial_delay=1):
    """Make MiMo API request with exponential backoff retry logic for rate limiting (429 errors)
    
    Args:
        url: API endpoint URL
        headers: Request headers
        payload: Request payload
        max_retries: Maximum number of retry attempts (default: 5)
        initial_delay: Initial delay in seconds before first retry (default: 1)
    
    Returns:
        Response object from successful request
    
    Raises:
        Exception: If all retries are exhausted or non-retryable error occurs
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            if attempt == 0:
                print(f"  📤 Sending request to MiMo API...")
            else:
                print(f"  📤 Retrying MiMo API request... (attempt {attempt + 1}/{max_retries})")
            
            r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
            
            # Check for rate limit (429) error before raising
            if r.status_code == 429:
                # Try to get Retry-After header if available
                retry_after = r.headers.get('Retry-After')
                if retry_after:
                    try:
                        wait_time = int(retry_after)
                        print(f"  ⏳ Rate limit reached (429). Server requested wait time: {wait_time} seconds")
                    except ValueError:
                        # If Retry-After is not a number, use exponential backoff
                        wait_time = initial_delay * (2 ** attempt)
                        print(f"  ⏳ Rate limit reached (429). Waiting {wait_time} seconds before retry...")
                else:
                    # Use exponential backoff: 1s, 2s, 4s, 8s, 16s
                    wait_time = initial_delay * (2 ** attempt)
                    print(f"  ⏳ Rate limit reached (429). Waiting {wait_time} seconds before retry...")
                
                # If this is not the last attempt, wait and retry
                if attempt < max_retries - 1:
                    time.sleep(wait_time)
                    continue
                else:
                    # Last attempt failed, raise the error
                    r.raise_for_status()
            
            # For non-429 errors, raise immediately if status is not OK
            r.raise_for_status()
            return r
            
        except requests.exceptions.HTTPError as e:
            # Handle HTTP errors that were raised by raise_for_status()
            if e.response and e.response.status_code == 429:
                # 429 error - retry with backoff
                last_exception = e
                if attempt < max_retries - 1:
                    # Calculate wait time
                    retry_after = e.response.headers.get('Retry-After')
                    if retry_after:
                        try:
                            wait_time = int(retry_after)
                        except ValueError:
                            wait_time = initial_delay * (2 ** attempt)
                    else:
                        wait_time = initial_delay * (2 ** attempt)
                    
                    print(f"  ⏳ Rate limit reached (429). Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                    continue
                else:
                    # Last attempt failed
                    raise
            else:
                # Non-429 HTTP errors should not be retried
                raise
        except requests.exceptions.RequestException as e:
            # Network errors, timeouts, etc. - retry with exponential backoff
            last_exception = e
            if attempt < max_retries - 1:
                wait_time = initial_delay * (2 ** attempt)
                print(f"  ⚠️  Request error: {e}. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            else:
                raise
    
    # If we exhausted all retries, raise the last exception
    if last_exception:
        raise last_exception
    else:
        raise Exception("Failed to make MiMo API request after all retries")

def mimo_summarize_from_url(title, article_url):
    """Use Xiaomi MiMo LLM to read and summarize the article directly from URL"""
    if not MIMO_AVAILABLE:
        raise Exception("MiMo API not available")
    
    try:
        print(f"  🤖 MiMo reading and summarizing: {title[:50]}...")
        
        # Read article content first
        article_content = read_article_content(article_url)
        if not article_content or len(article_content.strip()) < 50:
            raise Exception("Failed to read article content or content too short")
        
        # Clean HTML tags if any remain (extra safety)
        from bs4 import BeautifulSoup
        if '<' in article_content and '>' in article_content:
            # Re-parse to ensure clean text
            soup_clean = BeautifulSoup(article_content, 'html.parser')
            article_content = soup_clean.get_text(separator=' ', strip=True)
            article_content = " ".join(article_content.split())  # Normalize whitespace
            print(f"  🧹 Cleaned HTML tags from content")
        
        # Extract facts for grounding
        facts = _extract_numeric_facts(article_content)
        facts_list = sorted(list(facts.get('raw_tokens', set())))
        facts_block = "\n".join(facts_list[:40])
        
        # Extract mentioned products and brands
        source_lower = article_content.lower()
        mentioned_products = []
        mentioned_brands = []
        
        # Brand detection patterns (same as Gemini)
        brand_patterns = {
            'xiaomi': ['xiaomi', 'mi ', 'redmi', 'poco'],
            'samsung': ['samsung', 'galaxy'],
            'apple': ['apple', 'iphone', 'ipad', 'mac'],
            'vivo': ['vivo', 'iqoo'],
            'oppo': ['oppo', 'oneplus'],
            'huawei': ['huawei', 'honor'],
            'realme': ['realme'],
            'google': ['google', 'pixel'],
            'sony': ['sony', 'xperia'],
            'lg': ['lg'],
            'motorola': ['motorola', 'moto']
        }
        
        # Detect mentioned brands
        for brand, patterns in brand_patterns.items():
            if any(pattern in source_lower for pattern in patterns):
                mentioned_brands.append(brand.title())
        
        # Look for model numbers
        import re
        model_patterns = [
            r'\b[a-z]+\s*\d{2,4}[a-z]*\b',  # Like "X300", "Y28", "15T"
            r'\b[a-z]+\s*[a-z]+\s*\d+[a-z]*\b',  # Like "iPhone 15", "Redmi Note 12"
        ]
        
        for pattern in model_patterns:
            matches = re.findall(pattern, source_lower)
            for match in matches:
                if len(match) > 3:
                    mentioned_products.append(match.title())
        
        products_context = f"Products mentioned in source: {', '.join(mentioned_products)}" if mentioned_products else "No specific products mentioned"
        brands_context = f"Brands mentioned in source: {', '.join(mentioned_brands)}" if mentioned_brands else "No specific brands mentioned"
        
        # Limit content length for API (keep more content than before)
        original_length = len(article_content)
        if len(article_content) > 5000:
            article_content_truncated = article_content[:5000]
            print(f"  ✂️  Truncated content from {original_length} to 5000 characters for MiMo API")
        else:
            article_content_truncated = article_content
            print(f"  📄 Sending {len(article_content)} characters of content to MiMo")
        
        # Log content preview to verify it's not empty
        if len(article_content.strip()) < 100:
            print(f"  ⚠️  WARNING: Content seems too short ({len(article_content)} chars)")
        else:
            print(f"  📝 Content preview (first 300 chars): {article_content[:300]}...")
        
        # Create MiMo prompt (JSON format)
        prompt = f"""请阅读以下新闻文章并输出 JSON 格式的结果，包含以下字段：
1. "title": 中文标题（带分类标签），格式：【分类】中文标题
2. "summary": 中文摘要，不超过100字，用2-3句完整的话总结新闻的关键信息（时间、地点、主体、关键数字和影响）

要求：
- 标题和摘要必须用简体中文（不要使用繁体中文）
- 分类选项：科技、娱乐、经济、体育、灾难、政治、综合
- 人名、品牌名、产品名、地名保持原文（英文/马来文），不要翻译成中文（如Nabil Halimi、PKR、Malaysiakini等应保持原样）
- 只使用文章中明确提到的数字和事实
- 不要添加文章中未提及的产品或信息
- 摘要不能只是简单改写标题，必须补充标题中没有的细节（如具体机型、价格、合作方、时间等）
- 保持专业、清晰的表达
- **重要：请仔细阅读文章内容，不要只基于标题生成摘要**

文章标题: {title}
文章内容: {article_content_truncated}

来源信息:
{products_context}
{brands_context}

提取的事实: {facts_block}

请以 JSON 格式输出，例如：
{{
  "title": "【分类】中文标题",
  "summary": "中文摘要"
}}"""

        # Call MiMo API (OpenAI-compatible chat completions)
        url = f"{MIMO_API_BASE}/chat/completions"
        headers = {
            "Authorization": f"Bearer {MIMO_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": MIMO_MODEL,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2048,
            "response_format": {"type": "json_object"}
        }
        if not MIMO_DEEP_THINKING:
            payload["thinking"] = {"type": "disabled"}
        
        chinese_title = ""
        summary = ""
        max_attempts = 2
        
        for attempt in range(max_attempts):
            try:
                # Use retry logic with exponential backoff for rate limiting
                r = _mimo_api_request_with_retry(url, headers, payload)
                data = r.json()
                
                if "choices" not in data or not data["choices"]:
                    raise Exception("Empty or invalid response from MiMo API")
                
                content = data["choices"][0]["message"]["content"].strip()
                print(f"  📡 MiMo API response received: {len(content)} characters (attempt {attempt + 1}/{max_attempts})")
                
                # Clean markdown code blocks if present
                clean_content = content
                if clean_content.startswith("```"):
                    lines = clean_content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    clean_content = "\n".join(lines).strip()
                    
                import json
                parsed = json.loads(clean_content)
                chinese_title = parsed.get("title", "").strip()
                summary = parsed.get("summary", "").strip()
                
                if not chinese_title or not summary:
                    raise ValueError("Parsed fields 'title' or 'summary' are empty")
                
                # If we successfully parsed valid JSON, break the retry loop
                break
                
            except (json.JSONDecodeError, ValueError) as parse_err:
                print(f"  ⚠️ JSON extraction failed on attempt {attempt + 1}/{max_attempts}: {parse_err}")
                if attempt < max_attempts - 1:
                    print(f"  🔄 Retrying AI generation...")
                    time.sleep(1)
                else:
                    # On final attempt, fallback to legacy text parsing if we have the content
                    if 'content' in locals() and content:
                        print(f"  ⚠️ Attempting text fallback parsing on final attempt...")
                        lines = content.split('\n')
                        chinese_title = ""
                        summary = ""
                        for line in lines:
                            line = line.strip()
                            if line.startswith('标题:'):
                                chinese_title = line.replace('标题:', '').strip()
                            elif line.startswith('标题：'):
                                chinese_title = line.replace('标题：', '').strip()
                            elif line.startswith('摘要:'):
                                summary = line.replace('摘要:', '').strip()
                            elif line.startswith('摘要：'):
                                summary = line.replace('摘要：', '').strip()
                            elif not chinese_title and line and not line.startswith('摘要:') and not line.startswith('摘要：'):
                                chinese_title = line
                            elif chinese_title and line and not line.startswith('标题:') and not line.startswith('标题：'):
                                if summary:
                                    summary += " " + line
                                else:
                                    summary = line
                    
                    if not chinese_title or not summary:
                        # Fallback if parsing failed entirely on the final attempt
                        print(f"  ⚠️ Could not parse title/summary on final attempt, using full content fallback")
                        chinese_title = f"【科技】{title}"
                        summary = content[:200] + "..." if ('content' in locals() and len(content) > 200) else (content if 'content' in locals() else "")
        
        print(f"  ✅ MiMo Chinese title: {chinese_title}")
        print(f"  ✅ MiMo summary generated: {len(summary)} characters")
        
        return chinese_title, summary
        
    except Exception as e:
        print(f"  ❌ MiMo summarization failed: {e}")
        # Re-raise exception so fallback to Gemini can work
        raise

def mimo_summarize_content(title, article_content):
    """Use Xiaomi MiMo LLM to summarize pre-extracted article content"""
    if not MIMO_AVAILABLE:
        raise Exception("MiMo API not available")
    
    try:
        print(f"  🤖 MiMo summarizing content: {title[:50]}...")
        
        # Clean HTML tags if any remain (extra safety)
        from bs4 import BeautifulSoup
        if '<' in article_content and '>' in article_content:
            # Re-parse to ensure clean text
            soup_clean = BeautifulSoup(article_content, 'html.parser')
            article_content = soup_clean.get_text(separator=' ', strip=True)
            article_content = " ".join(article_content.split())  # Normalize whitespace
            print(f"  🧹 Cleaned HTML tags from content")
        
        # Limit content length for API (keep more content than before)
        original_length = len(article_content)
        if len(article_content) > 5000:
            article_content = article_content[:5000]
            print(f"  ✂️  Truncated content from {original_length} to 5000 characters for MiMo API")
        else:
            print(f"  📄 Sending {len(article_content)} characters of content to MiMo")
        
        # Log content preview to verify it's not empty
        if len(article_content.strip()) < 100:
            print(f"  ⚠️  WARNING: Content seems too short ({len(article_content)} chars)")
        else:
            print(f"  📝 Content preview (first 300 chars): {article_content[:300]}...")
        
        # Extract facts for grounding
        facts = _extract_numeric_facts(article_content)
        facts_list = sorted(list(facts.get('raw_tokens', set())))
        facts_block = "\n".join(facts_list[:40])
        
        # Create MiMo prompt (JSON format)
        prompt = f"""请分析以下新闻文章并输出 JSON 格式的结果，包含以下字段：
1. "title": 中文标题（带分类标签），格式：【分类】中文标题
2. "summary": 中文摘要，不超过100字，用2-3句完整的话总结新闻的关键信息（时间、地点、主体、关键数字和影响）

要求：
- 如果文章极其简短、或者缺乏实质性内容（例如没有明确的产品型号、品牌名称、具体参数规格或核心功能介绍，仅为视频导流或社交媒体互动等），请将 JSON 中的 "title" 和 "summary" 均直接设置为 "SKIP"。
- 标题和摘要必须用简体中文（不要使用繁体中文）
- 分类选项：科技、娱乐、经济、体育、灾难、政治、综合
- 人名、品牌名、产品名、地名保持原文（英文/马来文），不要翻译成中文（如Nabil Halimi、PKR、Malaysiakini等应保持原样）
- 只使用文章中明确提到的数字和事实
- 不要添加文章中未提及的产品或信息
- 摘要不能只是简单改写标题，必须补充标题中没有的细节（如具体机型、价格、合作方、时间等）
- 保持专业、清晰的表达
- **重要：请仔细阅读文章内容，不要只基于标题生成摘要**

文章标题: {title}

文章内容:
{article_content}

提取的事实: {facts_block}

请以 JSON 格式输出，例如：
{{
  "title": "【分类】中文标题",
  "summary": "中文摘要"
}}"""

        # Call MiMo API (OpenAI-compatible chat completions)
        url = f"{MIMO_API_BASE}/chat/completions"
        headers = {
            "Authorization": f"Bearer {MIMO_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": MIMO_MODEL,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2048,
            "response_format": {"type": "json_object"}
        }
        if not MIMO_DEEP_THINKING:
            payload["thinking"] = {"type": "disabled"}
        
        chinese_title = ""
        summary = ""
        max_attempts = 2
        
        for attempt in range(max_attempts):
            try:
                # Use retry logic with exponential backoff for rate limiting
                r = _mimo_api_request_with_retry(url, headers, payload)
                data = r.json()
                
                if "choices" not in data or not data["choices"]:
                    raise Exception("Empty or invalid response from MiMo API")
                
                content = data["choices"][0]["message"]["content"].strip()
                print(f"  📡 MiMo API response received: {len(content)} characters (attempt {attempt + 1}/{max_attempts})")
                
                # Clean markdown code blocks if present
                clean_content = content
                if clean_content.startswith("```"):
                    lines = clean_content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    clean_content = "\n".join(lines).strip()
                    
                import json
                parsed = json.loads(clean_content)
                chinese_title = parsed.get("title", "").strip()
                summary = parsed.get("summary", "").strip()
                
                if not chinese_title or not summary:
                    raise ValueError("Parsed fields 'title' or 'summary' are empty")
                
                # If we successfully parsed valid JSON, break the retry loop
                break
                
            except (json.JSONDecodeError, ValueError) as parse_err:
                print(f"  ⚠️ JSON extraction failed on attempt {attempt + 1}/{max_attempts}: {parse_err}")
                if attempt < max_attempts - 1:
                    print(f"  🔄 Retrying AI generation...")
                    time.sleep(1)
                else:
                    # On final attempt, fallback to legacy text parsing if we have the content
                    if 'content' in locals() and content:
                        print(f"  ⚠️ Attempting text fallback parsing on final attempt...")
                        lines = content.split('\n')
                        chinese_title = ""
                        summary = ""
                        for line in lines:
                            line = line.strip()
                            if line.startswith('标题:'):
                                chinese_title = line.replace('标题:', '').strip()
                            elif line.startswith('标题：'):
                                chinese_title = line.replace('标题：', '').strip()
                            elif line.startswith('摘要:'):
                                summary = line.replace('摘要:', '').strip()
                            elif line.startswith('摘要：'):
                                summary = line.replace('摘要：', '').strip()
                            elif not chinese_title and line and not line.startswith('摘要:') and not line.startswith('摘要：'):
                                chinese_title = line
                            elif chinese_title and line and not line.startswith('标题:') and not line.startswith('标题：'):
                                if summary:
                                    summary += " " + line
                                else:
                                    summary = line
                    
                    if not chinese_title or not summary:
                        # Fallback if parsing failed entirely on the final attempt
                        print(f"  ⚠️ Could not parse title/summary on final attempt, using full content fallback")
                        chinese_title = title  # Fallback to original title
                        summary = content if 'content' in locals() else ""
        
        print(f"  ✅ MiMo Chinese title: {chinese_title}")
        print(f"  ✅ MiMo summary generated: {len(summary)} characters")

        return chinese_title, summary
        
    except Exception as e:
        print(f"  ❌ MiMo API error: {e}")
        # Re-raise exception so fallback to Gemini can work
        raise

def ai_summarize_from_url(title, article_url):
    """Try MiMo first, fallback to Gemini, for summarizing from URL
    Returns: (chinese_title, summary, provider) where provider is 'mimo' or 'gemini'
    """
    if MIMO_AVAILABLE:
        try:
            chinese_title, summary = mimo_summarize_from_url(title, article_url)
            return chinese_title, summary, "mimo"
        except Exception as e:
            print(f"  ⚠️  MiMo failed, trying Gemini: {e}")
    
    if GEMINI_AVAILABLE:
        try:
            chinese_title, summary = gemini_summarize_from_url(title, article_url)
            return chinese_title, summary, "gemini"
        except Exception as e:
            print(f"  ⚠️  Gemini also failed: {e}")
    
    raise Exception("Neither MiMo nor Gemini available")

def ai_summarize_content(title, article_content):
    """Try MiMo first, fallback to Gemini, for summarizing content
    Returns: (chinese_title, summary, provider) where provider is 'mimo' or 'gemini'
    """
    if MIMO_AVAILABLE:
        try:
            chinese_title, summary = mimo_summarize_content(title, article_content)
            return chinese_title, summary, "mimo"
        except Exception as e:
            print(f"  ⚠️  MiMo failed, trying Gemini: {e}")
    
    if GEMINI_AVAILABLE:
        try:
            chinese_title, summary = gemini_summarize_content(title, article_content)
            return chinese_title, summary, "gemini"
        except Exception as e:
            print(f"  ⚠️  Gemini also failed: {e}")
    
    raise Exception("Neither MiMo nor Gemini available")

def _extract_title_headline_for_lang_check(title: str) -> str:
    """Part after 【分类】; used so a Chinese tag does not hide an English headline."""
    if not (title or "").strip():
        return ""
    t = title.strip()
    if "【" in t and "】" in t:
        idx = t.find("】")
        return t[idx + 1 :].strip()
    return t

def _title_headline_is_mostly_english(title: str) -> bool:
    h = _extract_title_headline_for_lang_check(title)
    if not h:
        return False
    if any("\u4e00" <= ch <= "\u9fff" for ch in h):
        return False
    return _is_mostly_english(h)

def _parse_title_only_from_llm_response(content: str) -> str:
    for line in (content or "").split("\n"):
        line = line.strip()
        if line.startswith("标题:"):
            return line.replace("标题:", "").strip()
    first = (content or "").strip().split("\n")[0].strip()
    return first

def mimo_regenerate_chinese_title_only(reference_title: str, chinese_summary: str, article_excerpt: str | None):
    if not MIMO_AVAILABLE:
        raise Exception("MiMo API not available")
    excerpt_block = ""
    if article_excerpt and len(article_excerpt.strip()) > 80:
        excerpt_block = f"\n文章摘录（供核对事实，请优先与摘要一致）：\n{article_excerpt.strip()[:4000]}\n"
    prompt = f"""先前生成的新闻标题中，【分类】后的主标题仍是英文。请根据下面已写好的中文摘要{('与文章摘录' if excerpt_block else '')}，只重新写一条中文标题。

请以 JSON 格式输出，包含以下字段：
1. "title": 中文标题，格式：【分类】简体中文标题

要求：
- 【】内分类必须是：科技、娱乐、经济、体育、灾难、政治、综合 之一
- 标题主文用简体中文；人名、品牌、地名可保留英文或马来文原文
- 请只输出 JSON 格式的结果，不要包含其它任何解释性文字。

例如：
{{
  "title": "【分类】简体中文标题"
}}

当前有问题的标题：{reference_title}

中文摘要：
{chinese_summary}
{excerpt_block}"""
    url = f"{MIMO_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {MIMO_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MIMO_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.35,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"}
    }
    if not MIMO_DEEP_THINKING:
        payload["thinking"] = {"type": "disabled"}
    title = ""
    max_attempts = 2
    
    for attempt in range(max_attempts):
        try:
            r = _mimo_api_request_with_retry(url, headers, payload)
            data = r.json()
            if "choices" not in data or not data["choices"]:
                raise Exception("Empty or invalid response from MiMo API")
            raw = data["choices"][0]["message"]["content"].strip()
            
            # Try parsing as JSON first
            import json
            clean_content = raw
            if clean_content.startswith("```"):
                lines = clean_content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_content = "\n".join(lines).strip()
                
            parsed = json.loads(clean_content)
            title = parsed.get("title", "").strip()
            if not title:
                raise ValueError("Parsed field 'title' is empty")
            
            # If we successfully parsed valid JSON, break the retry loop
            break
            
        except (json.JSONDecodeError, ValueError) as json_err:
            print(f"  ⚠️ JSON parsing failed for regenerated title on attempt {attempt + 1}/{max_attempts}: {json_err}")
            if attempt < max_attempts - 1:
                print(f"  🔄 Retrying title regeneration...")
                time.sleep(1)
            else:
                # Fallback to legacy parser if JSON parsing failed on final attempt
                if 'raw' in locals() and raw:
                    print(f"  ⚠️ Attempting text fallback parsing for title on final attempt...")
                    title = _parse_title_only_from_llm_response(raw)
                if not title:
                    raise Exception(f"Failed to regenerate title after {max_attempts} attempts: {json_err}")
                    
    return title

def gemini_regenerate_chinese_title_only(reference_title: str, chinese_summary: str, article_excerpt: str | None):
    if not GEMINI_AVAILABLE:
        raise Exception("Gemini API not available")
    excerpt_block = ""
    if article_excerpt and len(article_excerpt.strip()) > 80:
        excerpt_block = f"\n文章摘录（供核对事实，请优先与摘要一致）：\n{article_excerpt.strip()[:4000]}\n"
    prompt = f"""先前生成的新闻标题中，【分类】后的主标题仍是英文。请根据下面已写好的中文摘要{('与文章摘录' if excerpt_block else '')}，只重新写一条中文标题。

要求：
- 只输出一行，格式：标题: 【分类】简体中文标题
- 【】内分类必须是：科技、娱乐、经济、体育、灾难、政治、综合 之一
- 标题主文用简体中文；人名、品牌、地名可保留英文或马来文原文
- 不要输出摘要、不要解释、不要其它行

当前有问题的标题：{reference_title}

中文摘要：
{chinese_summary}
{excerpt_block}"""
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)
    if not response.text:
        raise Exception("Empty response from Gemini")
    return _parse_title_only_from_llm_response(response.text.strip())

def ai_regenerate_chinese_title_only(reference_title: str, chinese_summary: str, article_excerpt: str | None) -> str:
    if MIMO_AVAILABLE:
        try:
            return mimo_regenerate_chinese_title_only(reference_title, chinese_summary, article_excerpt)
        except Exception as e:
            print(f"  ⚠️  MiMo title regeneration failed, trying Gemini: {e}")
    if GEMINI_AVAILABLE:
        return gemini_regenerate_chinese_title_only(reference_title, chinese_summary, article_excerpt)
    raise Exception("Neither MiMo nor Gemini available for title regeneration")

def _article_excerpt_for_title_regen(it: dict) -> str | None:
    t = it.get("_fetched_article_text")
    if isinstance(t, str) and len(t.strip()) > 120:
        return t.strip()[:4500]
    try:
        c = read_article_content(it["url"])
        if c and len((c or "").strip()) > 120:
            return c.strip()[:4500]
    except Exception:
        pass
    return None

def _is_mostly_english(text: str) -> bool:
    try:
        if not text:
            return False
        
        # Count English letters
        english_letters = sum(1 for ch in text if ('a' <= ch.lower() <= 'z'))
        # Count Chinese characters (CJK Unified Ideographs)
        chinese_chars = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
        # Count total alphabetic characters
        total_alpha = sum(1 for ch in text if ch.isalpha())
        
        if total_alpha == 0:
            return False
        
        # If there are Chinese characters, it's not mostly English
        if chinese_chars > 0:
            return False
        
        # If more than 50% are English letters, consider it mostly English
        return (english_letters / total_alpha) > 0.5
    except Exception:
        return False

def _contains_kw(text_lc: str, keywords):
    import re
    for kw in keywords:
        k = kw.lower()
        # Use word-boundary matching for plain latin words to avoid 'goal' matching 'global'
        if all(('a' <= ch <= 'z') or ch == ' ' for ch in k) and len(k) >= 3:
            # FIX: use raw string r"\b" (single backslash) for real regex word boundary
            pattern = r"\b" + re.escape(k) + r"\b"
            if re.search(pattern, text_lc):
                return True
        else:
            if k in text_lc:
                return True
    return False

def classify(title, text):
    t = (title + " " + text).lower()
    
    # 政治 (Politics) - keywords
    # Keep this list conservative so that only clearly political / national-level stories
    # are tagged as 政治. Local policy / lifestyle-related items will fall back to 综合.
    politics_keywords = [
        # Elections and parties
        "election", "elections", "pilihan raya", "pru", "by-election", "prk",
        "manifesto", "campaign", "kempen", "undi", "voter", "pengundi",
        "umno", "pas ", "pkr", "dap", "bersatu", "amanah", "gps ",
        # High-level institutions and positions
        "parliament", "parlimen", "senate", "senator",
        "prime minister", "perdana menteri", "pm ", "president", "presiden",
        "mps", "ahli parlimen", "wakil rakyat",
        # Laws and constitution
        "law", "act", "bill", "rang undang-undang", "constitution", "perlembagaan",
        # Anti-corruption / major scandals
        "macc", "sprm", "anti-corruption", "rasuah",
        "shafee", "najib", "jho low", "1mdb"
    ]
    
    # 经济 (Economy) - Expanded keywords
    economy_keywords = [
        "ringgit", "bnm", "gdp", "market", "investment", "budget", "economy", "economic",
        "bank", "banking", "finance", "financial", "stock", "trading", "currency", "forex",
        "inflation", "deflation", "interest rate", "loan", "credit", "debt", "revenue",
        "profit", "loss", "earnings", "quarterly", "annual", "fiscal", "monetary policy",
        "central bank", "reserve bank", "treasury", "ministry of finance", "kementerian kewangan",
        "bursa malaysia", "klse", "ftse", "index", "share", "equity", "bond", "sukuk",
        "ipo", "listing", "merger", "acquisition", "takeover", "dividend", "yield",
        "retail", "wholesale", "trade", "export", "import", "balance of trade", "current account",
        "foreign direct investment", "fdi", "portfolio investment", "capital flow",
        "exchange rate", "usd", "rm", "myr", "yen", "euro", "pound", "singapore dollar",
        "oil price", "crude oil", "petroleum", "petronas", "palm oil", "commodity",
        "manufacturing", "industrial", "production", "capacity", "output", "supply chain",
        "business", "corporate", "enterprise", "sme", "msme", "entrepreneur", "startup",
        "venture capital", "private equity", "funding", "capital", "investment fund",
        "pension fund", "epf", "kwsp", "tabung haji", "asb", "unit trust", "mutual fund",
        "insurance", "takaful", "premium", "claim", "coverage", "policy", "actuarial",
        "audit", "accounting", "tax", "gst", "sst", "income tax", "corporate tax",
        "property", "real estate", "housing", "mortgage", "loan", "developer", "construction",
        "infrastructure", "development", "project", "tender", "contract", "procurement"
    ]
    
    # 灾害 (Disaster) - Expanded keywords
    disaster_keywords = [
        "flood", "banjir", "earthquake", "gempa", "landslide", "haze", "disaster", "emergency",
        "storm", "typhoon", "hurricane", "cyclone", "tornado", "thunderstorm", "heavy rain",
        "drought", "kekeringan", "fire", "kebakaran", "wildfire", "forest fire", "bush fire",
        "tsunami", "volcano", "gunung berapi", "eruption", "lava", "ash", "smoke",
        "accident", "kemalangan", "crash", "collision", "explosion", "letupan", "blast",
        "chemical spill", "oil spill", "contamination", "pollution", "toxic", "hazardous",
        "evacuation", "pemindahan", "rescue", "penyelamatan", "relief", "bantuan",
        "emergency response", "crisis", "krisis", "calamity", "catastrophe", "tragedy",
        "casualty", "fatality", "death", "kematian", "injury", "cedera", "hospital",
        "red cross", "civil defence", "bomba", "fire department", "police", "military",
        "warning", "amaran", "alert", "sirene", "siren", "emergency broadcast",
        "weather warning", "flood warning", "storm warning", "severe weather",
        "climate change", "global warming", "extreme weather", "natural disaster"
    ]
    
    # 体育 (Sports) - Expanded keywords
    sports_keywords = [
        "match", "goal", "badminton", "football", "harimau malaya", "sports", "sukan",
        "game", "permainan", "tournament", "kejohanan", "championship", "pertandingan",
        "league", "liga", "cup", "piala", "final", "separuh akhir", "semi final",
        "olympics", "olimpik", "paralympics", "world cup", "piala dunia", "asian games",
        "seagames", "southeast asian games", "commonwealth games", "sukan komanwel",
        "soccer", "tennis", "golf", "basketball", "volleyball", "hockey", "cricket",
        "swimming", "renang", "athletics", "olahraga", "track and field", "marathon",
        "cycling", "berbasikal", "motorcycle", "motorsport", "f1", "formula 1", "moto gp",
        "boxing", "tinju", "martial arts", "seni mempertahankan diri", "karate", "taekwondo",
        "judo", "wrestling", "gymnastics", "gimnastik", "weightlifting", "angkat berat",
        "archery", "memanah", "shooting", "menembak", "sailing", "perlayaran", "rowing",
        "rugby", "baseball", "softball", "squash", "table tennis", "ping pong",
        "player", "pemain", "athlete", "atlet", "coach", "jurulatih", "team", "pasukan",
        "score", "markah", "point", "mata", "win", "menang", "lose", "kalah", "draw", "seri",
        "victory", "kemenangan", "defeat", "kekalahan", "record", "rekod", "achievement",
        "medal", "pingat", "gold", "emas", "silver", "perak", "bronze", "gangsa",
        "stadium", "arena", "field", "padang", "court", "gelanggang", "track", "litar"
    ]
    
    # 科技 (Technology) - Expanded keywords
    tech_keywords = [
        "小米", "华为", "红米", "荣耀", "发布", "新品", "参数", "处理器", "相机", "镜头",
        "ai", "artificial intelligence", "tech", "technology", "startup", "software", "chip", "semiconductor",
        "digital", "innovation", "smartphone", "mobile", "gadget", "device", "hardware", "app", "application",
        "computer", "laptop", "desktop", "tablet", "ipad", "iphone", "android", "ios", "windows", "mac",
        "apple", "samsung", "google", "microsoft", "meta", "facebook", "tesla", "amazon", "netflix", "spotify",
        "xiaomi", "poco", "huawei", "oneplus", "sony", "lg", "intel", "amd", "nvidia", "qualcomm",
        "ev", "electric vehicle", "automotive tech", "autonomous", "self-driving", "battery", "charging",
        "camera", "photography", "drone", "vr", "ar", "virtual reality", "augmented reality",
        "gaming", "console", "playstation", "xbox", "nintendo", "steam", "streaming", "youtube", "twitch",
        "fintech", "cryptocurrency", "blockchain", "bitcoin", "ethereum", "nft", "web3",
        "malaysia tech", "malaysian startup", "e-commerce", "online shopping", "digital payment",
        "cloud computing", "aws", "azure", "gcp", "server", "database", "api", "developer",
        "programming", "coding", "python", "javascript", "java", "c++", "react", "node.js",
        "cybersecurity", "hacking", "privacy", "data protection", "gdpr", "encryption",
        "iot", "internet of things", "smart home", "wearable", "fitness tracker", "smartwatch",
        "5g", "6g", "wireless", "bluetooth", "wifi", "network", "internet", "broadband",
        "robotics", "automation", "ai chatbot", "machine learning", "deep learning", "neural network",
        "quantum computing", "quantum", "supercomputer", "data center", "server farm",
        "open source", "github", "git", "version control", "software development", "agile", "devops",
        "ui", "ux", "user interface", "user experience", "design", "frontend", "backend", "full stack",
        "mobile app", "app store", "google play", "mobile development",
        "web development", "website", "html", "css", "bootstrap", "responsive design",
        "data science", "analytics", "big data", "artificial intelligence", "machine learning",
        "tech news", "technology news", "tech industry", "silicon valley", "tech giant",
        "innovation", "disruptive technology", "emerging technology", "cutting edge", "breakthrough",
        "tech conference", "ces", "wwdc", "google io", "microsoft build", "aws re:invent",
        "tech review", "product review", "tech comparison", "benchmark", "performance test",
        "tech tutorial", "how to", "tech guide", "tech tips", "tech tricks", "tech hacks",
        "tech update", "software update", "firmware update", "security patch", "bug fix",
        "tech release", "product launch", "new product", "announcement", "unveiling",
        "tech acquisition", "merger", "partnership", "collaboration", "joint venture",
        "tech investment", "funding round", "series a", "series b", "ipo", "valuation",
        "tech startup", "unicorn", "scale-up", "growth", "expansion", "international",
        "tech talent", "recruitment", "hiring", "job opening", "career", "tech job",
        "tech education", "coding bootcamp", "online course", "certification", "training",
        "tech community", "meetup", "conference", "hackathon", "tech event", "networking",
        "tech blog", "tech article", "tech opinion", "tech analysis", "tech insight",
        "tech trend", "market trend", "industry trend", "future of tech", "tech prediction",
        "tech regulation", "tech policy", "tech law", "tech ethics", "tech responsibility",
        "tech sustainability", "green tech", "clean tech", "renewable energy", "carbon neutral",
        "tech accessibility", "inclusive design", "tech for good", "social impact", "tech charity",
        "tech diversity", "inclusion", "equality", "tech for all", "democratizing tech"
    ]
    
    # 文娱 / 娱乐 (Entertainment) - Expanded keywords
    entertainment_keywords = [
        "film", "movie", "concert", "celebrity", "艺人", "pelakon", "entertainment", "hiburan",
        "cinema", "wayang", "theater", "teater", "drama", "drama", "musical", "muzikal",
        "music", "muzik", "song", "lagu", "singer", "penyanyi", "band", "kumpulan", "artist",
        "actor", "pelakon", "actress", "pelakon wanita", "director", "pengarah", "producer",
        "penerbit", "script", "skrip", "screenplay", "story", "cerita", "plot", "plot",
        "character", "watak", "role", "peranan", "performance", "persembahan", "show",
        "acara", "program", "program", "series", "siri", "episode", "episod", "season",
        "musim", "season", "finale", "penamat", "premiere", "tayangan perdana", "release",
        "keluaran", "box office", "hasil kutipan", "revenue", "pendapatan", "ticket",
        "tiket", "audience", "penonton", "viewer", "pemirsa", "fan", "peminat", "fandom",
        "award", "anugerah", "oscar", "grammy", "emmy", "golden globe", "cannes",
        "festival", "festival", "competition", "pertandingan", "contest", "pertandingan",
        "reality show", "rancangan realiti", "talent show", "pertandingan bakat", "dance",
        "tarian", "singing", "nyanyian", "comedy", "komedi", "stand-up", "joke", "lawak",
        "drama", "drama", "romance", "cinta", "action", "aksi", "horror", "seram",
        "thriller", "suspense", "mystery", "misteri", "sci-fi", "science fiction",
        "fantasy", "fantasi", "animation", "animasi", "cartoon", "kartun", "anime",
        "manga", "comic", "komik", "book", "buku", "novel", "novel", "author", "penulis",
        "publisher", "penerbit", "magazine", "majalah", "newspaper", "surat khabar",
        "radio", "radio", "podcast", "podcast", "streaming", "penstriman", "netflix",
        "disney", "hbo", "amazon prime", "youtube", "tiktok", "instagram", "social media",
        "media sosial", "influencer", "influencer", "youtuber", "blogger", "vlogger",
        "fashion", "fesyen", "beauty", "kecantikan", "lifestyle", "gaya hidup", "travel",
        "pelancongan", "food", "makanan", "restaurant", "restoran", "cooking", "memasak",
        "recipe", "resipi", "culture", "budaya", "tradition", "tradisi", "festival",
        "perayaan", "celebration", "sambutan", "party", "parti", "event", "acara",
        "exhibition", "pameran", "museum", "muzium", "gallery", "galeri", "art",
        "seni", "painting", "lukisan", "sculpture", "arca", "photography", "fotografi"
    ]
    
    # Check categories in order of specificity.
    # Tech is checked FIRST because tech articles often mention generic words
    # ("law", "act", "bank", "development") that would otherwise trigger politics/economy.
    # Disaster and sports are clear-cut and checked next. Politics is last among the
    # major categories so that ambiguous words don't shadow tech/economy content.
    if _contains_kw(t, tech_keywords): return "科技"
    if _contains_kw(t, disaster_keywords): return "灾害"
    if _contains_kw(t, sports_keywords): return "体育"
    if _contains_kw(t, entertainment_keywords): return "文娱"
    if _contains_kw(t, economy_keywords): return "经济"
    if _contains_kw(t, politics_keywords): return "政治"
    return "综合"

def summarize(title, body):
    text = body or title
    text = text[:320]
    return text + ("…" if len(text) == 320 else "")

def ai_summarize(title, body, sentences=3):
    text = (body or "").strip() or title
    try:
        # Ensure NLTK punkt is available (needed by sumy Tokenizer)
        if nltk is not None:
            try:
                nltk.data.find('tokenizers/punkt')
            except LookupError:
                try:
                    nltk.download('punkt', quiet=True)
                except Exception:
                    pass
            # Newer NLTK may require 'punkt_tab' as well
            try:
                nltk.data.find('tokenizers/punkt_tab')
            except Exception:
                try:
                    nltk.download('punkt_tab', quiet=True)
                except Exception:
                    pass

        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summarizer = TextRankSummarizer()
        sents = [str(s) for s in summarizer(parser.document, sentences)]
        if not sents:
            return (body or title)[:320]
        res = " ".join(sents)
        return res[:800]  # keep card compact
    except Exception:
        # Fallback to simple heuristic summary if NLTK/sumy unavailable
        return summarize(title, body)

def is_malaysiakini_snapshot(source_name, feed_url, title, desc):
    """Return True when an item is a Malaysiakini SNAPSHOT post."""
    source_text = f"{source_name} {feed_url}".lower()
    if "malaysiakini" not in source_text:
        return False

    content_text = f"{title or ''} {desc or ''}".lower()
    snapshot_markers = [
        "kini snapshot",
        "snapshot |",
        "| snapshot",
        " snapshot "
    ]
    return any(marker in content_text for marker in snapshot_markers)

def collect_once(already_sent=None):
    """Fetch all feeds and return a list of recent news items.
    already_sent: optional set of URLs that have already been sent (persistent
    dedup). When provided, duplicate URLs are skipped during collection instead
    of wasting AI tokens later in the pipeline."""
    if already_sent is None:
        already_sent = set()
    items = []
    # Process priority feeds first, then the rest
    ordered_feeds = list(PRIORITY_FEEDS) + [u for u in RSS_FEEDS if u not in PRIORITY_FEEDS]
    for i, feed_url in enumerate(ordered_feeds):
        # Skip rss.app feeds if disabled via env
        if os.environ.get("DISABLE_RSS_APP", "1") == "1" and "rss.app" in feed_url:
            print(f"Skipping rss.app feed due to DISABLE_RSS_APP=1: {feed_url}")
            continue
        try:
            print(f"Fetching ({i+1}/{len(ordered_feeds)}): {feed_url}")
            
            # Add headers to mimic a real browser
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # Try to fetch with requests first, then parse with feedparser
            feed = None
            try:
                response = requests.get(feed_url, headers=headers, timeout=15)
                if response.status_code == 200:
                    feed = feedparser.parse(response.content)
                else:
                    print(f"HTTP {response.status_code} for {feed_url}")
                    feed = feedparser.parse(feed_url)
            except requests.exceptions.Timeout:
                print(f"⏰ Timeout for {feed_url} - skipping this feed")
                continue  # Skip this feed and move to next one
            except Exception as e:
                print(f"Request failed for {feed_url}: {e}")
                continue  # Skip this feed and move to next one
            
            # Only proceed if we successfully got a feed
            if not feed:
                print(f"⚠️ No feed data for {feed_url} - skipping")
                continue
                
            if hasattr(feed, 'bozo') and feed.bozo:
                print(f"Feed parse warning: {feed_url}")
                print(f"Bozo exception: {getattr(feed, 'bozo_exception', 'Unknown error')}")
            
            source_name = (feed.feed.get("title", "") or "").strip()
            if not source_name:
                source_name = feed_url.split('/')[-1] or "Unknown"
            
            feed_items = 0
            for e in feed.entries:
                link = (e.get("link") or "").strip()
                title = (e.get("title") or "").strip()
                if not title: continue
                desc = e.get("summary") or e.get("description") or ""

                if is_malaysiakini_snapshot(source_name, feed_url, title, desc):
                    print(f"  ⏭️  Skipping Malaysiakini SNAPSHOT: {title[:60]}...")
                    continue
                
                # Get publication date first
                pub = e.get("published") or e.get("updated") or ""
                print(f"  Raw date: {pub}")
                try:
                    published_at = dateparser.parse(pub).isoformat()
                    print(f"  Parsed date: {published_at}")
                except Exception as e:
                    published_at = ""
                    print(f"  Date parsing failed: {e}")
                
                # Only process recent news (last 6 hours for latest news)
                print(f"  Checking: {title[:50]}...")
                try:
                    recent_hours = int(os.environ.get("RECENT_NEWS_HOURS", "6"))
                except Exception:
                    recent_hours = 6
                if not is_recent_news(published_at, hours=recent_hours):
                    print(f"  Skipping old news: {title[:50]}...")
                    continue
                
                # Get description for processing
                body = _clean(desc)
                
                print(f"  ✅ News found: {title[:50]}...")

                # Resolve the actual URL early so dedup works across Google News wrappers
                resolved_link = _norm(_resolve_actual_url(link))

                k = _key(resolved_link or link, title)
                if k in SEEN:
                    print(f"  Already seen this item (resolved dedup), skipping")
                    continue
                SEEN.add(k)

                # Also check if we've already sent this resolved URL
                if resolved_link in already_sent or link in already_sent:
                    print(f"  URL already sent (persistent dedup), skipping: {resolved_link or link}")
                    continue

                items.append({
                    "title": title,
                    "url": resolved_link,
                    "body": body,
                    "source": source_name,
                    "published_at": published_at,
                    "cover_url": e.get('media_content', [{}])[0].get('url') if isinstance(e.get('media_content'), list) else (e.get('media_content', {}).get('url') if isinstance(e.get('media_content'), dict) else e.get('image') or e.get('enclosure', {}).get('url')),
                    "priority": feed_url in PRIORITY_FEEDS,
                })
                feed_items += 1
            
            print(f"  Found {feed_items} new items from {source_name}")
            
        except Exception as e:
            print(f"Error fetching {feed_url}: {e}")
            continue
    
    return items

# --- Feishu webhook callback receiver & Flask server ---
from flask import Flask, request, jsonify

flask_app = Flask("adailocal_receiver")

def reply_to_feishu_message(message_id, title, content):
    """Sends a card reply to a specific message using Feishu App API."""
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    
    if not app_id or not app_secret:
        print("⚠️ FEISHU_APP_ID or FEISHU_APP_SECRET is not set; cannot send Feishu reply.")
        return
        
    token = get_tenant_access_token(app_id, app_secret)
    url = f"{BASE}/open-apis/im/v1/messages/{message_id}/reply"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    card = _build_card(title, content)
    payload = {
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False)
    }
    
    r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        print(f"reply_fail: {data}")
        raise RuntimeError(f"Feishu reply failed: {data}")
    else:
        print(f"Reply sent successfully to message {message_id}")

@flask_app.route("/feishu/webhook", methods=["POST"])
def feishu_webhook():
    data = request.json or {}
    print(f"📩 Webhook received from Feishu: {json.dumps(data)[:300]}")
    
    # 1. Handle URL verification challenge
    if data.get("type") == "url_verification":
        challenge = data.get("challenge")
        print(f"✅ Handled URL verification challenge: {challenge}")
        return jsonify({"challenge": challenge})
        
    # 2. Handle message events
    event_header = data.get("header", {})
    event_type = event_header.get("event_type")
    
    if event_type == "im.message.receive_v1":
        event_body = data.get("event", {})
        message = event_body.get("message", {})
        
        # Verify it is a text message
        msg_type = message.get("message_type")
        if msg_type == "text":
            content_str = message.get("content", "{}")
            message_id = message.get("message_id")
            chat_id = message.get("chat_id")
            
            try:
                content = json.loads(content_str)
                text = content.get("text", "")
            except Exception as parse_err:
                print(f"⚠️ Failed to parse message content JSON: {parse_err}")
                text = ""
                
            # Clean text (remove Feishu mention tags like <at id="..."></at>)
            clean_text = re.sub(r'<at[^>]*>.*?</at>', '', text).strip()
            clean_text_lower = clean_text.lower()
            
            # Find URLs in the clean text
            urls = re.findall(r'https?://[^\s\u4e00-\u9fff]+', clean_text)
            
            if urls:
                added_feeds = []
                already_exists = []
                errors = []
                
                for url in urls:
                    # Clean trailing punctuation from URLs if any
                    url = url.rstrip('.,;()[]{}')
                    success, reason = add_feed_to_file(url, is_priority=False)
                    if success:
                        added_feeds.append(url)
                    elif reason == "already_exists":
                        already_exists.append(url)
                    else:
                        errors.append((url, reason))
                        
                # Construct response message
                reply_lines = []
                if added_feeds:
                    reply_lines.append("✅ **Successfully added feeds:**")
                    for f in added_feeds:
                        reply_lines.append(f"- {f}")
                if already_exists:
                    reply_lines.append("ℹ️ **Feeds already exist:**")
                    for f in already_exists:
                        reply_lines.append(f"- {f}")
                if errors:
                    reply_lines.append("❌ **Failed to add feeds:**")
                    for f, err in errors:
                        reply_lines.append(f"- {f} (Error: {err})")
                        
                reply_content = "\n".join(reply_lines)
                print(f"Sending reply to message {message_id}: {reply_content[:150]}...")
                
                # Send reply to Feishu group/user
                try:
                    reply_to_feishu_message(message_id, "RSS Feed Subscription Update", reply_content)
                except Exception as reply_err:
                    print(f"⚠️ Failed to send Feishu reply: {reply_err}")
            elif clean_text_lower in ["list", "show", "feeds", "列表", "订阅列表"]:
                feeds, priority_feeds = load_feeds_from_file()
                reply_lines = []
                reply_lines.append("📋 **Active RSS Subscriptions:**")
                if not feeds:
                    reply_lines.append("*(No active RSS subscriptions found)*")
                else:
                    for i, f in enumerate(feeds, 1):
                        is_priority = f in priority_feeds
                        suffix = " ⭐️ [priority]" if is_priority else ""
                        reply_lines.append(f"{i}. {f}{suffix}")
                reply_content = "\n".join(reply_lines)
                print(f"Sending feeds list reply to message {message_id}...")
                try:
                    reply_to_feishu_message(message_id, "RSS Feeds List", reply_content)
                except Exception as reply_err:
                    print(f"⚠️ Failed to send Feishu reply: {reply_err}")
            elif clean_text:
                # User sent text but it didn't contain URLs or known commands, reply with help guidelines
                reply_content = (
                    "🤖 **AdaiLocal RSS Helper**\n\n"
                    "Supported commands when tagging/mentioning the bot:\n"
                    "• **Paste any RSS feed URL** to subscribe immediately.\n"
                    "• Type **`list`** or **`列表`** to view all active subscriptions."
                )
                print(f"Sending help reply to message {message_id}...")
                try:
                    reply_to_feishu_message(message_id, "RSS Help Guide", reply_content)
                except Exception as reply_err:
                    print(f"⚠️ Failed to send Feishu reply: {reply_err}")
            else:
                print("No content found in the text message after cleaning mentions.")
                
    return jsonify({"status": "ok"})

def run_collector_loop():
    # Support multiple webhook URLs
    webhook_urls = []
    webhook_secret = os.environ.get("FEISHU_WEBHOOK_SECRET", "").strip()
    
    # Primary webhook URL
    primary_webhook = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    if primary_webhook:
        webhook_urls.append(primary_webhook)
    
    # Secondary webhook URL
    secondary_webhook = os.environ.get("FEISHU_WEBHOOK_URL_2", "").strip()
    if secondary_webhook:
        webhook_urls.append(secondary_webhook)
    
    # Tertiary webhook URL (if needed)
    tertiary_webhook = os.environ.get("FEISHU_WEBHOOK_URL_3", "").strip()
    if tertiary_webhook:
        webhook_urls.append(tertiary_webhook)
    
    # Debug environment variables
    print(f"🔧 Environment check:")
    print(f"  FEISHU_WEBHOOK_URL: {'Set' if primary_webhook else 'Not set'}")
    print(f"  FEISHU_WEBHOOK_URL_2: {'Set' if secondary_webhook else 'Not set'}")
    print(f"  FEISHU_WEBHOOK_URL_3: {'Set' if tertiary_webhook else 'Not set'}")
    print(f"  FEISHU_WEBHOOK_SECRET: {'Set' if webhook_secret else 'Not set (optional)'}")
    print(f"  Total webhook URLs configured: {len(webhook_urls)}")
    for i, url in enumerate(webhook_urls, 1):
        print(f"    Webhook {i}: {url[:50]}...")
    
    # Additional debugging for webhook URLs
    if len(webhook_urls) == 0:
        print("❌ No webhook URLs configured! Check your environment variables.")
    elif len(webhook_urls) == 1:
        print("⚠️  Only 1 webhook URL configured. Add FEISHU_WEBHOOK_URL_2 for multiple groups.")
    else:
        print(f"✅ Multiple webhook URLs configured: {len(webhook_urls)} groups will receive news")
    
    # Test webhook connectivity if requested
    if os.environ.get("TEST_WEBHOOKS", "0") == "1" and len(webhook_urls) > 0:
        print("🧪 Running webhook connectivity test...")
        test_webhook_connectivity(webhook_urls, webhook_secret)
        print("🧪 Webhook test completed.")
    
    # Test mode - don't actually send if webhook URL is placeholder
    TEST_MODE = len(webhook_urls) == 0 or any(url == "your_webhook_url_here" for url in webhook_urls)
    if TEST_MODE:
        print("=== RUNNING IN TEST MODE (no actual sending) ===")

    USE_APP_API = os.environ.get("USE_APP_API", "0") == "1"

    if len(webhook_urls) == 0 or USE_APP_API:
        app_id = os.environ.get("FEISHU_APP_ID", "")
        app_secret = os.environ.get("FEISHU_APP_SECRET", "")
        chat_id = os.environ.get("FEISHU_CHAT_ID", "")

    MAX_PER_CYCLE = int(os.environ.get("MAX_PUSH_PER_CYCLE", "1"))
    SEND_INTERVAL_SEC = float(os.environ.get("SEND_INTERVAL_SEC", "1.0"))

    ONE_SHOT = os.environ.get("ONE_SHOT", "0") == "1"
    
    # Debug environment variables
    use_ai = os.environ.get("USE_AI_SUMMARY", "0") == "1"
    print(f"🔧 Environment check:")
    print(f"  USE_AI_SUMMARY: {os.environ.get('USE_AI_SUMMARY', '0')} -> {use_ai}")
    print(f"  GEMINI_API_KEY: {'Set' if GEMINI_API_KEY else 'Not set'}")
    print(f"  GEMINI_AVAILABLE: {GEMINI_AVAILABLE}")

    # Load previously sent news for persistent deduplication
    sent_news_urls = load_sent_news()
    # Load story-level dedup index (titles of stories pushed within DEDUP_WINDOW_HOURS)
    sent_stories = load_sent_stories()
    print(f"🧠 Story-similarity dedup: threshold={SIM_TITLE_THRESHOLD}, window={DEDUP_WINDOW_HOURS}h")
    
    # Leader election mechanism to prevent duplicate news from multiple machines
    def is_leader():
        """Check if this machine should be the leader (only one runs at a time)"""
        try:
            # Skip leader election if DISABLE_LEADER_ELECTION is set (useful for local testing)
            if os.environ.get("DISABLE_LEADER_ELECTION", "0") == "1":
                return True
            
            # Use /data/leader.lock on deployment platforms, or local path for testing
            if os.path.exists("/data"):
                lock_file = "/data/leader.lock"
            else:
                # For local testing, use a local directory
                os.makedirs("logs", exist_ok=True)
                lock_file = "logs/leader.lock"
            
            # Check if lock file exists and is recent
            if os.path.exists(lock_file):
                try:
                    with open(lock_file, 'r') as f:
                        content = f.read().strip()
                        if content:
                            parts = content.split(':')
                            if len(parts) == 2:
                                timestamp = int(parts[1])
                                # If lock is less than 5 minutes old, another machine is active
                                if time.time() - timestamp < 300:
                                    return False
                except:
                    pass
            
            # Try to become leader
            machine_id = os.environ.get('FLY_MACHINE_ID', 'unknown')
            timestamp = str(int(time.time()))
            
            with open(lock_file, 'w') as f:
                f.write(f"{machine_id}:{timestamp}\n")
            
            # Double-check we're still the leader after a short delay
            time.sleep(1)
            try:
                with open(lock_file, 'r') as f:
                    content = f.read().strip()
                    if content and content.startswith(f"{machine_id}:"):
                        return True
            except:
                pass
            
            return False
        except Exception as e:
            print(f"  ⚠️  Leader election error: {e}")
            return False
    
    def check_leader_health():
        """Check if the current leader is still healthy"""
        try:
            # Skip if leader election is disabled
            if os.environ.get("DISABLE_LEADER_ELECTION", "0") == "1":
                return False
            
            # Use /data/leader.lock on deployment platforms, or local path for testing
            if os.path.exists("/data"):
                lock_file = "/data/leader.lock"
            else:
                lock_file = "logs/leader.lock"
            if not os.path.exists(lock_file):
                return False
            
            with open(lock_file, 'r') as f:
                content = f.read().strip()
                if not content:
                    return False
                
                parts = content.split(':')
                if len(parts) != 2:
                    return False
                
                timestamp = int(parts[1])
                # If leader hasn't updated in 5 minutes, consider it dead
                if time.time() - timestamp > 300:
                    print(f"  ⚠️  Leader appears dead (last seen {time.time() - timestamp}s ago)")
                    return False
                
                return True
        except Exception:
            return False
    
    # Wait for leader election
    print("🔄 Waiting for leader election...")
    while not is_leader():
        if not check_leader_health():
            print("  💀 Previous leader appears dead, attempting to take over...")
            try:
                # Try both paths
                for lock_path in ["/data/leader.lock", "logs/leader.lock"]:
                    if os.path.exists(lock_path):
                        os.remove(lock_path)
            except:
                pass
            continue
        
        print("  ⏳ Another machine is the leader, waiting...")
        time.sleep(30)  # Wait 30 seconds before trying again
    
    print("  ✅ This machine is now the leader!")
    
    while True:
        try:
            sent = 0
            print(f"=== Starting collection cycle ===")
            items = collect_once(already_sent=sent_news_urls)
            print(f"=== Found {len(items)} total items ===")
            # Category priority weights (higher = sent first)
            CATEGORY_WEIGHTS = {
                "科技": 4,
                "灾难": 4,
                "文娱": 4,
                "经济": 3,
                "体育": 3,
                "政治": 2,
                "综合": 1,
            }
            
            # Sort by: brand keywords → priority feeds → category weight → published_at (latest first)
            def _k(it):
                title = it.get("title", "") or ""
                has_brand = 1 if has_brand_keywords(title) else 0
                priority = 1 if it.get("priority") else 0
                cat = classify(title, "")
                category_weight = CATEGORY_WEIGHTS.get(cat, 1)
                published_at = it.get("published_at") or "1970-01-01T00:00:00"
                return (has_brand, priority, category_weight, published_at)
            items.sort(key=_k, reverse=True)
            # Collapse near-duplicate items within this fetch round so we don't queue
            # 5 versions of the same story for the next 5 cycles.
            items = dedup_batch(items)
            
            # Count brand-related news
            brand_news_count = sum(1 for it in items if has_brand_keywords(it.get("title", "")))
            if brand_news_count > 0:
                print(f"🏷️  Found {brand_news_count} brand-related news items (Xiaomi/REDMI/POCO/mijia) - prioritized!")
            
            # Log category breakdown for verification
            cat_counts = {}
            for it in items:
                c = classify(it.get("title", ""), "")
                cat_counts[c] = cat_counts.get(c, 0) + 1
            print(f"=== Category breakdown ({len(items)} items) ===")
            for c in ["科技", "灾难", "文娱", "经济", "体育", "政治", "综合"]:
                if c in cat_counts:
                    print(f"  {c}: {cat_counts[c]}")
            
            # Log the top 10 most recent news items for verification
            print(f"=== Top 10 most recent news items ===")
            for i, item in enumerate(items[:10]):
                brand_marker = " [BRAND]" if has_brand_keywords(item.get("title", "")) else ""
                cat = classify(item.get("title", ""), "")
                print(f"{i+1}. {item['title'][:60]}...{brand_marker} [{cat}] (Published: {item.get('published_at', 'No date')})")
            
            # Process items and skip already sent news
            for it in items:
                # Check if this news has already been sent
                if is_news_already_sent(it['url'], sent_news_urls):
                    print(f"⏭️  Skipping already sent news: {it['title'][:50]}...")
                    continue

                # Cross-source story-level dedup: skip if a similar story was
                # already pushed within the dedup window, even if the URL differs.
                sim_match = is_similar_to_sent(it.get('title', ''), sent_stories)
                if sim_match:
                    print(
                        f"⏭️  Skipping similar story (already pushed): "
                        f"{(it.get('title') or '')[:50]}  ⟵  "
                        f"{(sim_match.get('title') or '')[:50]} "
                        f"({sim_match.get('source','')})"
                    )
                    continue

                # Temporary filter: skip Astro Awani politics articles
                source_name_raw = it.get("source", "")
                is_astro_awani = "astroawani" in source_name_raw.lower() or "astro awani" in source_name_raw.lower()
                if is_astro_awani and classify(it.get("title", ""), "") == "政治":
                    print(f"⏭️  Skipping Astro Awani politics article: {it['title'][:50]}...")
                    sent_news_urls.add(it['url'])  # Mark as processed so it doesn't retry
                    continue
                if has_brand_keywords(it.get("title", "")):
                    print(f"🏷️  Processing brand-related news (priority): {it['title'][:60]}...")

                # For priority sources, also generate Chinese summary via AI (MiMo/Gemini)
                ai_provider_used = None  # Track which AI provider was used
                if it.get("priority"):
                    print(f"  🛑 Priority source: using AI for Chinese title and summary.")
                    summary = it["body"] or it["title"]
                    if use_ai:
                        try:
                            chinese_title, ai_summary, ai_provider_used = ai_summarize_from_url(it["title"], it['url'])
                            if chinese_title:
                                it["title"] = chinese_title
                                print(f"  🏷️  AI-generated Chinese title (priority): {chinese_title[:40]}...")
                            if ai_summary:
                                summary = ai_summary
                        except Exception as e:
                            print(f"  ⚠️  AI generation failed for priority source: {e}")
                # Use AI (MiMo/Gemini) for summarization if enabled
                elif use_ai:
                    ai_provider = "MiMo" if MIMO_AVAILABLE else ("Gemini" if GEMINI_AVAILABLE else "None")
                    print(f"🔍 Processing with {ai_provider} AI: {it['title'][:50]}...")
                    print(f"  📄 Original RSS body: {it['body'][:100]}...")
                    
                    # Google News approach: Use Google News to discover, then follow actual source
                    print(f"  🌐 Google News discovery approach:")
                    print(f"  🔗 Source URL: {it['url']}")
                    print(f"  📰 Original title: {it['title']}")
                    
                    # Extract content from the actual source URL (not Google News)
                    article_content = read_article_content(it['url'])
                    it["_fetched_article_text"] = article_content if (article_content and len(article_content) > 100) else None
                    
                    # Heuristic pre-filtering to skip short stub/teaser articles without brand/product keywords
                    fetched_len = len(article_content) if article_content else 0
                    rss_len = len(it.get('body', '') or '')
                    if fetched_len < 250 and rss_len < 100:
                        if not has_brand_keywords(it.get("title", "")):
                            print(f"  ⏭️ Skipping low-content article (fetched: {fetched_len} chars, RSS body: {rss_len} chars): {it['title'][:60]}")
                            sent_news_urls.add(it['url'])  # Mark as processed to prevent retrying
                            continue
                    
                    if article_content and len(article_content) > 100:
                        print(f"  📖 Article content extracted: {len(article_content)} characters")
                        print(f"  📄 Content preview: {article_content[:200]}...")
                        
                        # Use AI (MiMo/Gemini) to summarize the actual article content
                        try:
                            chinese_title, summary, ai_provider_used = ai_summarize_content(it["title"], article_content)
                            
                            # Validate that we got meaningful content
                            if not chinese_title or chinese_title.strip() in ["【分类】中文标题", "中文标题", ""]:
                                print(f"  ⚠️  AI returned empty/placeholder title, using fallback")
                                chinese_title = f"【科技】{it['title']}"
                            
                            if not summary or summary.strip() in ["中文摘要", "摘要", ""]:
                                print(f"  ⚠️  AI returned empty/placeholder summary, using fallback")
                                summary = f"根据{it['title']}的报道，这是一条重要的科技新闻。"
                            
                            print(f"  🤖 AI Chinese title: {chinese_title}")
                            print(f"  🤖 AI summary length: {len(summary)} characters")
                            print(f"  📄 Summary preview: {summary[:150]}...")
                            
                            # Use the Chinese title from AI
                            it["title"] = _apply_chinese_name_map(chinese_title)
                            summary = _apply_chinese_name_map(summary)
                            
                        except Exception as ai_error:
                            print(f"  ❌ AI summarization failed: {ai_error}")
                            print(f"  🔄 Using fallback summarization")
                            chinese_title = f"【科技】{it['title']}"
                            summary = f"根据{it['title']}的报道，这是一条重要的科技新闻。"
                            it["title"] = _apply_chinese_name_map(chinese_title)
                    else:
                        print(f"  ⚠️  Content extraction failed, using RSS content with AI")
                        print(f"  📄 RSS body length: {len(it.get('body', '') or '')} characters")
                        
                        # Check if RSS body has meaningful content
                        rss_body = (it.get('body') or '').strip()
                        if len(rss_body) > 50:
                            # RSS body has content, use it for AI summarization
                            rss_content = f"Title: {it['title']}\n\nContent: {rss_body}"
                            it["_fetched_article_text"] = rss_body
                            print(f"  ✅ Using RSS body content ({len(rss_body)} chars) for AI summarization")
                        else:
                            # RSS body is empty or too short, create a prompt from title only
                            rss_content = f"Title: {it['title']}\n\nNote: Full article content is not available (may be behind paywall or RSS feed only provides title). Please generate a Chinese title and summary based on the title alone."
                            it["_fetched_article_text"] = None
                            print(f"  ⚠️  RSS body too short/empty, generating summary from title only")
                        
                        try:
                            chinese_title, summary, ai_provider_used = ai_summarize_content(it["title"], rss_content)
                            
                            # Validate that we got meaningful content
                            if not chinese_title or chinese_title.strip() in ["【分类】中文标题", "中文标题", ""]:
                                print(f"  ⚠️  AI returned empty/placeholder title, using fallback")
                                chinese_title = f"【科技】{it['title']}"
                            
                            if not summary or summary.strip() in ["中文摘要", "摘要", ""]:
                                print(f"  ⚠️  AI returned empty/placeholder summary, using fallback")
                                summary = f"根据{it['title']}的报道，这是一条重要的科技新闻。详细内容请查看原文链接。"
                            
                            if chinese_title:
                                it["title"] = chinese_title
                                print(f"  🏷️  AI-generated Chinese title (RSS fallback): {chinese_title[:40]}...")
                            print(f"  🤖 AI RSS summary length: {len(summary)} characters")
                            
                        except Exception as ai_error:
                            print(f"  ❌ AI RSS summarization failed: {ai_error}")
                            print(f"  🔄 Using final fallback")
                            chinese_title = f"【科技】{it['title']}"
                            summary = f"根据{it['title']}的报道，这是一条重要的科技新闻。详细内容请查看原文链接。"
                            it["title"] = _apply_chinese_name_map(chinese_title)
                else:
                    print(f"  📝 Using simple summarization (AI disabled)")
                    summary = summarize(it["title"], it["body"])
                
                # If summary still looks English and AI is enabled, try to regenerate in Chinese
                if use_ai and _is_mostly_english(summary):
                    try:
                        print(f"  🔁 Summary looks English; regenerating with AI in Chinese")
                        chinese_title, cn_summary, ai_provider_used = ai_summarize_from_url(it["title"], it['url'])
                        if chinese_title:
                            it["title"] = chinese_title
                        if cn_summary:
                            summary = cn_summary
                    except Exception as _e:
                        print(f"  ⚠️ Regeneration failed: {_e}")

                # Check if LLM flagged the article to be skipped
                if use_ai and (
                    "skip" in (summary or "").lower() or 
                    "skip" in (it["title"] or "").lower()
                ):
                    print(f"  ⏭️ Skipping low-substance article (filtered by AI): {it['title']}")
                    sent_news_urls.add(it['url'])  # Mark as processed to prevent retrying
                    continue

                # Final safety check - ensure we never send empty/placeholder content
                # Apply Chinese name mapping to any remaining English-name instances
                summary = _apply_chinese_name_map(summary)
                it["title"] = _apply_chinese_name_map(it["title"])

                if (
                    use_ai
                    and summary
                    and not _is_mostly_english(summary)
                    and _title_headline_is_mostly_english(it["title"])
                ):
                    try:
                        print(f"  🔁 Title headline still English (after Chinese summary); regenerating title via LLM")
                        excerpt = _article_excerpt_for_title_regen(it)
                        regen_title = ai_regenerate_chinese_title_only(it["title"], summary, excerpt)
                        if regen_title and regen_title not in ("【分类】中文标题", "中文标题"):
                            it["title"] = _apply_chinese_name_map(regen_title)
                    except Exception as _e:
                        print(f"  ⚠️ Title regeneration failed: {_e}")

                if not summary or summary.strip() in ["中文摘要", "摘要", "", "中文标题", "【分类】中文标题"]:
                    print(f"  🚨 CRITICAL: Empty/placeholder content detected, using emergency fallback")
                    summary = f"根据{it['title']}的报道，这是一条重要的科技新闻。"
                
                if not it["title"] or it["title"].strip() in ["【分类】中文标题", "中文标题", ""]:
                    print(f"  🚨 CRITICAL: Empty/placeholder title detected, using emergency fallback")
                    it["title"] = f"【科技】{it['title']}"
                
                # Force Chinese output for any remaining English content
                if not it["title"].startswith("【") and not any(ord(c) > 127 for c in it["title"]):
                    print(f"  🔄 Forcing Chinese title for English content")
                    it["title"] = f"【综合】{it['title']}"
                
                # More aggressive English detection for summary
                if (not any(ord(c) > 127 for c in summary) and len(summary) > 20) or _is_mostly_english(summary):
                    print(f"  🔄 Forcing Chinese summary for English content")
                    # Extract key English words and create a Chinese summary
                    english_words = [word for word in summary.split() if word.isalpha() and len(word) > 3][:3]
                    if english_words:
                        summary = f"根据{it['title']}的报道，这是一条关于{', '.join(english_words)}的重要新闻。详细内容请查看原文链接。"
                    else:
                        summary = f"根据{it['title']}的报道，这是一条重要的新闻。详细内容请查看原文链接。"
                
                # Content quality check - ensure summary is meaningful
                if len(summary.strip()) < 10:
                    print(f"  ⚠️  Summary too short, enhancing with more details")
                    summary = f"根据{it['title']}的报道，这是一条重要的科技新闻。详细内容请查看原文链接。"
                
                print(f"  ✅ Final content validation:")
                print(f"    Title: {it['title']}")
                print(f"    Summary: {summary[:100]}...")
                print(f"    Summary length: {len(summary)} characters")
                # Extract category from LLM title if it contains 【】 tags.
                # Prefer the LLM's own category (based on full content). Fall back to our
                # rule-based classifier only when the LLM label is missing or invalid.
                if "【" in it["title"] and "】" in it["title"]:
                    try:
                        start = it["title"].find("【") + 1
                        end = it["title"].find("】")
                        if start > 0 and end > start:
                            raw_category = it["title"][start:end]
                            print(f"  🏷️  Category extracted from LLM title: {raw_category}")
                            # Allowable categories from LLM prompt
                            allowed_categories = {"科技", "娱乐", "经济", "体育", "灾难", "政治", "综合"}
                            if raw_category in allowed_categories:
                                category = raw_category
                                print(f"  ✅ Using LLM category: {category}")
                            else:
                                # If LLM returns something unexpected, fall back to our classifier
                                inferred = classify(it["title"], summary)
                                category = inferred or "综合"
                                print(f"  🔁 Invalid LLM category '{raw_category}', using inferred: {category}")
                            # Rebuild title so the bracket label always matches final category
                            plain_title = it["title"][end + 1 :].lstrip()
                            title = f"【{category}】{plain_title}"
                        else:
                            category = classify(it["title"], summary)
                            title = f"【{category}】{it['title']}"
                    except Exception as e:
                        print(f"  ⚠️  Failed to extract category from title, fallback to classifier: {e}")
                        category = classify(it["title"], summary)
                        title = f"【{category}】{it['title']}"
                else:
                    category = classify(it["title"], summary)
                    title = f"【{category}】{it['title']}"

                # Keep the item title in sync with the final title we actually send,
                # so logs, Feishu card and Bitable all use the same category label.
                it["title"] = title
                
                # No extra required keyword; use the generated title as-is
                
                # Add publication time to content
                source_name = _extract_source_from_url(it['url'])
                pub_time = it.get("published_at", "")
                if pub_time:
                    try:
                        from datetime import datetime
                        pub_dt = dateparser.parse(pub_time)
                        if pub_dt:
                            # Convert to Malaysia timezone (UTC+8)
                            from datetime import timezone, timedelta
                            malaysia_tz = timezone(timedelta(hours=8))
                            if pub_dt.tzinfo is None:
                                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                            malaysia_time = pub_dt.astimezone(malaysia_tz)
                            time_str = malaysia_time.strftime("%Y-%m-%d %H:%M (MYT)")
                            # If source is still Google News, try to extract from original link
                            if 'news.google.com' in source_name.lower() or 'google' in source_name.lower():
                                original_source = _extract_source_from_url(it.get('url'))  # Use available URL
                                if original_source and original_source != source_name:
                                    source_name = original_source
                                    print(f"  🔄 Using original source: {source_name}")
                            content = f"{summary}\n\n⏰ {time_str}\n\n来源：[{source_name}]({it['url']})"
                        else:
                            content = f"{summary}\n\n来源：[{source_name}]({it['url']})"
                    except:
                        content = f"{summary}\n\n来源：[{source_name}]({it['url']})"
                else:
                    content = f"{summary}\n\n来源：[{source_name}]({it['url']})"
                
                # Prepare AI attribution if MiMo or Gemini was used (separate from content)
                attribution = None
                if ai_provider_used == "mimo":
                    attribution = "摘要由 [Xiaomi MiMo](https://mimo.xiaomi.com/) LLM 生成"
                elif ai_provider_used == "gemini":
                    attribution = "摘要由 Google Gemini LLM 生成"
                
                # Brand detection for Xiaomi vs competitors
                brand = detect_brand(f"{title} {summary} {content}")
                category_brand = brand_category(brand)
                brand_label = brand.title() if brand and brand != "other" else "Other"

                send_successful = False
                if TEST_MODE:
                    print(f"WOULD SEND: {title}")
                    print(f"CONTENT: {content[:100]}...")
                    if attribution:
                        print(f"ATTRIBUTION: {attribution}")
                    send_successful = True  # In test mode, consider it successful
                else:
                    if len(webhook_urls) > 0 and not USE_APP_API:
                        # Send to all configured webhook URLs
                        print(f"📝 Title: {title}")
                        print(f"📄 Content preview: {content[:200]}...")
                        send_successful = send_to_multiple_webhooks(webhook_urls, title, content, webhook_secret, attribution)
                        if send_successful:
                            print(f"✅ At least one webhook sent successfully")
                        else:
                            print(f"❌ All webhooks failed - news NOT marked as sent")
                    else:
                        print(f"📤 Sending via API (token method)")
                        try:
                            token = get_tenant_access_token(app_id, app_secret)
                            image_key = None
                            # Try to get cover from RSS, else from article page
                            cover_url = it.get('cover_url')
                            if not cover_url:
                                cover_url = extract_cover_image(it['url'])
                            if cover_url:
                                image_key = upload_image_to_feishu(token, cover_url)
                            if image_key:
                                send_card_message_with_image(token, chat_id, title, content, image_key, attribution)
                            else:
                                send_card_message(token, chat_id, title, content, attribution)
                            print(f"✅ API sent successfully")
                            send_successful = True
                        except Exception as api_error:
                            print(f"❌ API send failed: {api_error}")
                            print(f"❌ News NOT marked as sent due to API failure")
                            send_successful = False

                # Only mark as sent and log to Bitable if send was successful
                if send_successful:
                    # Log to Bitable if configured
                    # Convert datetime to Unix timestamp (milliseconds) for Bitable
                    from datetime import datetime, timezone
                    received_at_dt = datetime.utcnow().replace(tzinfo=timezone.utc)
                    received_at_timestamp = int(received_at_dt.timestamp() * 1000)  # Convert to milliseconds
                    
                    # Convert published_at if provided (from ISO string to Unix timestamp)
                    published_at_timestamp = None
                    published_at_str = it.get("published_at", "")
                    if published_at_str:
                        try:
                            pub_dt = dateparser.parse(published_at_str)
                            if pub_dt:
                                # Ensure timezone-aware
                                if pub_dt.tzinfo is None:
                                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                                published_at_timestamp = int(pub_dt.timestamp() * 1000)  # Convert to milliseconds
                        except Exception as e:
                            print(f"  ⚠️  Failed to parse published_at for Bitable: {e}")
                    
                    # Format URL as Link object for Bitable (Link fields require object format)
                    url_value = it["url"]
                    if url_value:
                        # Bitable Link field expects: {"link": "url", "text": "text"}
                        url_link_obj = {
                            "link": url_value,
                            "text": url_value  # Use URL as text, or could use title
                        }
                    else:
                        url_link_obj = None
                    
                    bitable_fields = {
                        "title": title,
                        "url": url_link_obj,  # Link field must be object, not string
                        "media": source_name,
                        "brand": brand_label,
                        # Use the same Chinese category as in the title (科技/经济/灾难/政治/综合等)
                        # so Feishu card and Bitable stay in sync. Make sure the Bitable field
                        # allows these options (single-select) or is a text field.
                        "category": category,
                        "published_at": published_at_timestamp if published_at_timestamp else None,
                        "received_at": received_at_timestamp,
                        "source_feed": it.get("source", ""),
                        "hash": _key(it["url"], it["title"]),
                        "is_duplicate": "False",  # Text field expects string, not boolean
                        "summary": summary
                    }
                    maybe_log_to_bitable(bitable_fields)
                    
                    # Mark this URL as sent (both in-memory and persistent)
                    SENT_URLS.add(it['url'])
                    sent_news_urls.add(it['url'])
                    # Record this story for cross-source similarity dedup. We do
                    # this after a successful send so that failed pushes can be
                    # retried with a different source on the next cycle.
                    try:
                        append_sent_story(it.get('url', ''), it.get('title', ''), it.get('source', ''))
                        sent_stories.append({
                            "ts": int(time.time()),
                            "url": it.get('url', ''),
                            "title": it.get('title', ''),
                            "title_key": _norm_title_key(it.get('title', '')),
                            "source": it.get('source', ''),
                            "_sig": _story_signature(it.get('title', '')),
                        })
                    except Exception as e:
                        print(f"  ⚠️  Failed to record sent story for similarity dedup: {e}")
                    print(f"✅ Sent news: {it['title'][:50]}...")
                    sent += 1
                else:
                    print(f"⚠️  News NOT marked as sent due to send failure - will retry next cycle")
                    print(f"🛑 Breaking cycle to prevent infinite AI token usage on failed sends.")
                    break
                if sent >= MAX_PER_CYCLE:
                    print(f"Reached MAX_PER_CYCLE={MAX_PER_CYCLE}, stop sending this round.")
                    break
                time.sleep(SEND_INTERVAL_SEC)
            
            # Save sent news URLs to file after each cycle
            save_sent_news(sent_news_urls)
            
            # --- Facebook page watch (Xiaomi Malaysia), gated by interval ---
            # Runs at most once every FB_WATCH_INTERVAL_SEC (default 2h); the
            # last-scan timestamp persists in logs/fb_watch_last.txt so restarts
            # don't re-trigger it. Set FB_WATCH_ENABLED=0 to disable.
            try:
                if os.environ.get("FB_WATCH_ENABLED", "1") == "1":
                    try:
                        fb_interval = int(os.environ.get("FB_WATCH_INTERVAL_SEC", "7200"))
                    except Exception:
                        fb_interval = 7200
                    fb_state_path = os.environ.get("FB_LAST_SCAN_PATH", "logs/fb_watch_last.txt")
                    last_scan = 0
                    if os.path.exists(fb_state_path):
                        try:
                            with open(fb_state_path) as f:
                                last_scan = int(f.read().strip() or "0")
                        except Exception:
                            last_scan = 0
                    if time.time() - last_scan >= fb_interval:
                        print("📘 Running Facebook page watch (Xiaomi Malaysia)...")
                        try:
                            import fb_watch
                            pushed = fb_watch.scan_and_push(webhook_urls=webhook_urls, secret=webhook_secret)
                            print(f"📘 Facebook watch done: {pushed} new post(s) pushed")
                        except Exception as fb_err:
                            print(f"⚠️  Facebook watch failed (news loop unaffected): {fb_err}")
                        # Stamp the attempt either way so a broken scrape doesn't
                        # hammer Facebook every cycle.
                        try:
                            os.makedirs("logs", exist_ok=True)
                            with open(fb_state_path, "w") as f:
                                f.write(str(int(time.time())))
                        except Exception:
                            pass
                    else:
                        next_in = int(fb_interval - (time.time() - last_scan))
                        print(f"📘 Facebook watch: next scan in ~{next_in // 60}min")
            except Exception as fb_gate_err:
                print(f"⚠️  Facebook watch gate error: {fb_gate_err}")
            
        except Exception as e:
            print(f"loop_error: {e}")
        if ONE_SHOT:
            break
        # Update leader heartbeat
        try:
            # Skip if leader election is disabled
            if os.environ.get("DISABLE_LEADER_ELECTION", "0") == "1":
                return
            
            # Use /data/leader.lock on deployment platforms, or local path for testing
            if os.path.exists("/data"):
                lock_file = "/data/leader.lock"
            else:
                lock_file = "logs/leader.lock"
            machine_id = os.environ.get('FLY_MACHINE_ID', 'unknown')
            timestamp = str(int(time.time()))
            with open(lock_file, 'w') as f:
                f.write(f"{machine_id}:{timestamp}\n")
            print(f"  💓 Leader heartbeat updated")
        except Exception as e:
            print(f"  ⚠️  Failed to update heartbeat: {e}")
        
        try:
            loop_sleep = int(os.environ.get("COLLECT_INTERVAL_SEC", "600"))
        except Exception:
            loop_sleep = 600
        
        # Calculate time to sleep to align with the next interval boundary (e.g. 1800s aligns to XX:00 and XX:30)
        # Malaysia time (UTC+8) is offset by exactly 8 hours (0 minutes), so UTC epoch multiples align 
        # perfectly with Malaysia clock intervals.
        now = time.time()
        next_run = (int(now) // loop_sleep + 1) * loop_sleep
        sleep_duration = next_run - now
        
        # Guard against extremely short sleep due to float precision
        if sleep_duration < 1:
            sleep_duration = loop_sleep
            
        # Format next run time for logs in Malaysia timezone
        from datetime import datetime, timezone, timedelta
        malaysia_tz = timezone(timedelta(hours=8))
        next_dt = datetime.fromtimestamp(next_run, tz=malaysia_tz)
        next_run_str = next_dt.strftime("%Y-%m-%d %H:%M:%S (MYT)")
        
        print(f"⏳ Sleeping {sleep_duration:.1f}s before next cycle (Next run aligned at: {next_run_str})...")
        time.sleep(sleep_duration)

def main():
    ONE_SHOT = os.environ.get("ONE_SHOT", "0") == "1"
    if ONE_SHOT:
        # Run collection once synchronously and exit
        run_collector_loop()
    else:
        # Run background thread for collection
        import threading
        collector_thread = threading.Thread(target=run_collector_loop, daemon=True)
        collector_thread.start()
        print("🤖 Background news collector thread started")
        
        # Start Flask server for Webhooks & health checks (port 8080/configured PORT)
        port = int(os.environ.get("PORT", 8080))
        print(f"🚀 Starting Flask webhook listener on port {port}...")
        flask_app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()
