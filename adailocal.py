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
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
    except FileNotFoundError:
        pass  # .env file doesn't exist, use system environment variables

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
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2-flash").strip()
MIMO_AVAILABLE = bool(MIMO_API_KEY)
if MIMO_AVAILABLE:
    print("✅ Xiaomi MiMo LLM API configured successfully")
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

RSS_FEEDS = [
    # Google News feeds - Xiaomi and competitors focus
    # "https://news.google.com/rss/search?q=xiaomi+malaysia&hl=en&gl=MY&ceid=MY:en", # Xiaomi Malaysia (disabled)
    # "https://news.google.com/rss/search?q=redmi+malaysia&hl=en&gl=MY&ceid=MY:en", # Redmi Malaysia (disabled)
    # "https://news.google.com/rss/search?q=samsung+malaysia&hl=en&gl=MY&ceid=MY:en", # Samsung Malaysia (disabled)
    # "https://news.google.com/rss/search?q=apple+iphone+malaysia&hl=en&gl=MY&ceid=MY:en", # Apple iPhone Malaysia (disabled)
    # "https://news.google.com/rss/search?q=oneplus+malaysia&hl=en&gl=MY&ceid=MY:en", # OnePlus Malaysia (disabled)
    # "https://news.google.com/rss/search?q=huawei+malaysia&hl=en&gl=MY&ceid=MY:en", # Huawei Malaysia (disabled)
    # "https://news.google.com/rss/search?q=oppo+malaysia&hl=en&gl=MY&ceid=MY:en", # OPPO Malaysia (disabled)
    # "https://news.google.com/rss/search?q=vivo+malaysia&hl=en&gl=MY&ceid=MY:en", # Vivo Malaysia (disabled)
    # "https://news.google.com/rss/search?q=realme+malaysia&hl=en&gl=MY&ceid=MY:en", # Realme Malaysia (disabled)
    # "https://news.google.com/rss/search?q=smartphone+launch+malaysia&hl=en&gl=MY&ceid=MY:en", # Smartphone launches Malaysia (disabled)
    
    # Primary tech-focused feeds (most reliable)
    # rss.app feeds disabled due to subscription pause
    # "https://rss.app/feeds/7kWc8DwjcHvi1nOK.xml", #Xiaomi MY Fb
    # "https://rss.app/feeds/r5wzRVVTbqYIyfSE.xml", #ZingGadget MY Fb
    # "https://rss.app/feeds/DQPaHn61uiC3hfmk.xml", #TechnaveCN MY Fb
    "https://rss.app/feeds/M50McNEZ5iyyJ4LI.xml", #Soyacincau MY Fb
    "https://www.soyacincau.com/feed/",
    "https://cn.soyacincau.com/feed/",             # SoyaCincau 中文版
    "https://amanz.my/feed/",
    "https://www.lowyat.net/feed/",
    # Xiaomi official sources
    "https://news.mi.com/global/rss",          # Xiaomi Newsroom (global)
    "https://blog.mi.com/en/feed",             # Xiaomi Official Blog (EN)
    # Chinese-language sources
    "https://www.orientaldaily.com.my/feed/",   # 东方日报马来西亚
    "https://cn.technave.com/feed/",            # TechNave 中文版
    "https://zinggadget.com/zh/feed/",          # Zing Gadget 中文
    
    # Fallback feeds that are more likely to work on PythonAnywhere
    "https://feeds.feedburner.com/soyacincau",
    # "https://www.nst.com.my/rss.xml",
    "https://www.malaysiakini.com/rss/en/news.rss",
    
    # Additional feeds (may have network restrictions)
    # "https://www.freemalaysiatoday.com/category/nation/feed/",
    "https://www.astroawani.com/rss/english",
    "https://www.astroawani.com/rss/terkini",
    "https://www.sinarharian.com.my/rss/terkini",
    # "https://www.hmetro.com.my/terkini.rss",
    # "https://www.bernama.com/en/rss.php",
    # "https://www.theedgemalaysia.com/rss.xml",
    
    # Commented out feeds that may not work on PythonAnywhere
    # "https://www.thestar.com.my/rss/News/Nation",
    #"https://www.sinchew.com.my/feed/",
    #"https://www.chinapress.com.my/feed/",
]

# Feeds with highest priority (processed first when present)
PRIORITY_FEEDS = {
    # "https://news.google.com/rss/search?q=xiaomi+malaysia&hl=en&gl=MY&ceid=MY:en", # Xiaomi Malaysia (disabled)
    # "https://news.google.com/rss/search?q=redmi+malaysia&hl=en&gl=MY&ceid=MY:en", # Redmi Malaysia (disabled)
    "https://rss.app/feeds/7kWc8DwjcHvi1nOK.xml", #Xiaomi MY Fb
}

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

def send_card_message(token, chat_id, title, content):
    url = f"{BASE}/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    card = {
        "header": { "title": { "content": title, "tag": "plain_text" }, "template": "wathet" },
        "config": { "wide_screen_mode": True },
        "elements": [
            { "tag": "div", "text": { "tag": "lark_md", "content": content } },
            { "tag": "hr" },
            { "tag": "div", "text": { "tag": "lark_md", "content": "\n\n注：摘要、正文均不代表个人观点" } }
        ]
    }
    payload = { "receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False) }
    r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        print(f"send_fail: {data}")

def send_card_message_with_image(token, chat_id, title, content, image_key):
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
        { "tag": "hr" },
        { "tag": "div", "text": { "tag": "lark_md", "content": "\n\n注:摘要，正文均不代表个人观点。摘要经过AI总结,可能存在误差,请以原文为准。" } }
    ])
    card = {
        "header": { "title": { "content": title, "tag": "plain_text" }, "template": "wathet" },
        "config": { "wide_screen_mode": True },
        "elements": elements
    }
    payload = { "receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False) }
    r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        print(f"send_fail: {data}")

def _build_card(title, content):
	return {
		"header": { "title": { "content": title, "tag": "plain_text" }, "template": "wathet" },
		"config": { "wide_screen_mode": True },
		"elements": [
			{ "tag": "div", "text": { "tag": "lark_md", "content": content } },
			{ "tag": "hr" },
			{ "tag": "div", "text": { "tag": "lark_md", "content": "\n\n注:摘要、正文均不代表个人观点" } }
		]
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

def send_to_multiple_webhooks(webhook_urls, title, content, secret=None):
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
            
            send_card_via_webhook(webhook_url, title, content, secret)
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

def send_card_via_webhook(webhook_url, title, content, secret=None):
	# Always send interactive card so markdown links are clickable
	card = _build_card(title, content)
	payload = { "msg_type": "interactive", "card": card }
	if secret:
		ts = str(int(time.time()))
		sign = _gen_webhook_sign(secret, ts)
		payload.update({ "timestamp": ts, "sign": sign })
	r = requests.post(webhook_url, json=payload, timeout=TIMEOUT)
	print(f"  📡 Webhook response status: {r.status_code}")
	try:
		data = r.json()
		print(f"  📋 Webhook response: {data}")
		if isinstance(data, dict):
			code = data.get("code")
			if code == 0:
				print(f"  ✅ Webhook success with card: {data}")
			else:
				print(f"  ❌ Webhook error (code {code}): {data.get('msg', 'Unknown error')}")
				raise Exception(f"Feishu webhook error: {data}")
		else:
			print(f"  ✅ Webhook success with card: {data}")
	except Exception as e:
		print(f"  ❌ Webhook error: {r.status_code} - {r.text[:200]}...")
		print(f"  📄 Raw response: {r.text}")
		raise e

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
    payload = {"fields": record_fields}
    r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
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
            'amanz.my': 'Amanz',
            'technave.com': 'TechNave 中文',
            'zinggadget.com': 'Zing Gadget 中文',
            'orientaldaily.com.my': '东方日报',
            'news.mi.com': 'Xiaomi Newsroom',
            'mi.com': 'Xiaomi',
            'malaysiakini.com': 'Malaysiakini',
            'astroawani.com': 'Astro Awani',
            'thestar.com.my': 'The Star',
            'nst.com.my': 'New Straits Times',
            'bernama.com': 'Bernama',
            'freemalaysiatoday.com': 'Free Malaysia Today',
            'sinarharian.com.my': 'Sinar Harian',
            'hmetro.com.my': 'Harian Metro',
            'chinapress.com.my': 'China Press',
            'orientaldaily.com.my': 'Oriental Daily',
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
        
        # Debug: Check if page has anti-bot protection
        page_text = response.text.lower()
        if any(phrase in page_text for phrase in ['cloudflare', 'access denied', 'blocked', 'captcha', 'robot', 'bot detection']):
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
            # Common article selectors
            'article', '.article-content', '.post-content', '.entry-content', '.story-content',
            '.content', '.main-content', '.article-body', '.post-body', '.entry-body',
            'main', '.main', '#content', '#main', '.post', '.entry', '.story',
            
            # Malaysian news site specific selectors
            '.article-text', '.article-body-text', '.story-text', '.news-content',
            '.post-text', '.entry-text', '.content-text', '.article-main',
            
            # Generic content areas
            '.text', '.body', '.article', '.post', '.entry', '.story',
            'p', '.paragraph', '.content-paragraph'
        ]
        
        content = ""
        for selector in content_selectors:
            elements = soup.select(selector)
            if elements:
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
            print(f"  🔍 Page title: {soup.find('title').get_text() if soup.find('title') else 'No title'}")
            print(f"  🔍 Page has {len(soup.find_all('p'))} paragraphs")
            print(f"  🔍 Page has {len(soup.find_all('article'))} article elements")
        
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
        
        # Create Gemini prompt
        prompt = f"""请阅读以下新闻文章并提供：

1. **中文标题（带分类标签）** - 格式：【分类】中文标题
2. **中文摘要** - 不超过50字，简洁明了

要求：
- 标题和摘要必须用中文
- 分类选项：科技、娱乐、经济、体育、灾难、综合
- 对中国人名优先使用中文写法（如张庆信、雷军），品牌名、产品名、地名可保留英文
- 只使用文章中明确提到的数字和事实
- 不要添加文章中未提及的产品或信息
- 保持专业、清晰的表达

文章标题: {title}
文章内容: {article_content[:2000]}...

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
        
        # Create Gemini prompt
        prompt = f"""请分析以下新闻文章并提供：

1. **中文标题（带分类标签）** - 格式：【分类】中文标题
2. **中文摘要** - 不超过50字，简洁明了

要求：
- 标题和摘要必须用中文
- 分类选项：科技、娱乐、经济、体育、灾难、综合
- 对中国人名优先使用中文写法（如张庆信、雷军），品牌名、产品名、地名可保留英文
- 只使用文章中明确提到的数字和事实
- 不要添加文章中未提及的产品或信息
- 保持专业、清晰的表达

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
        
        # Create MiMo prompt (same format as Gemini)
        prompt = f"""请阅读以下新闻文章并提供：

1. **中文标题（带分类标签）** - 格式：【分类】中文标题
2. **中文摘要** - 不超过50字，简洁明了

要求：
- 标题和摘要必须用中文
- 分类选项：科技、娱乐、经济、体育、灾难、综合
- 人名、品牌名、产品名、地名保持原文（英文/马来文），不要翻译成中文（如Nabil Halimi、PKR、Malaysiakini等应保持原样）
- 只使用文章中明确提到的数字和事实
- 不要添加文章中未提及的产品或信息
- 保持专业、清晰的表达

文章标题: {title}
文章内容: {article_content[:2000]}...

来源信息:
{products_context}
{brands_context}

提取的事实: {facts_block}

请按以下格式回复：
标题: 【分类】中文标题
摘要: 中文摘要"""

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
            "max_tokens": 500
        }
        
        print(f"  📤 Sending request to MiMo API...")
        r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        
        if "choices" not in data or not data["choices"]:
            raise Exception("Empty or invalid response from MiMo API")
        
        content = data["choices"][0]["message"]["content"].strip()
        print(f"  📡 MiMo API response received: {len(content)} characters")
        
        # Parse the response (same as Gemini)
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
        
        # Extract facts for grounding
        facts = _extract_numeric_facts(article_content)
        facts_list = sorted(list(facts.get('raw_tokens', set())))
        facts_block = "\n".join(facts_list[:40])
        
        # Create MiMo prompt
        prompt = f"""请分析以下新闻文章并提供：

1. **中文标题（带分类标签）** - 格式：【分类】中文标题
2. **中文摘要** - 不超过50字，简洁明了

要求：
- 标题和摘要必须用中文
- 分类选项：科技、娱乐、经济、体育、灾难、综合
- 人名、品牌名、产品名、地名保持原文（英文/马来文），不要翻译成中文（如Nabil Halimi、PKR、Malaysiakini等应保持原样）
- 只使用文章中明确提到的数字和事实
- 不要添加文章中未提及的产品或信息
- 保持专业、清晰的表达

文章标题: {title}

文章内容:
{article_content}

提取的事实: {facts_block}

请按以下格式回复：
标题: 【分类】中文标题
摘要: 中文摘要"""

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
            "max_tokens": 500
        }
        
        print(f"  📤 Sending request to MiMo API...")
        r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        
        if "choices" not in data or not data["choices"]:
            raise Exception("Empty or invalid response from MiMo API")
        
        content = data["choices"][0]["message"]["content"].strip()
        print(f"  📡 MiMo API response received: {len(content)} characters")
        
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
            
            print(f"  ✅ MiMo Chinese title: {chinese_title}")
            print(f"  ✅ MiMo summary generated: {len(summary)} characters")

            return chinese_title, summary
            
        except Exception as e:
            print(f"  ⚠️  Error parsing response: {e}")
            print(f"  📄 Raw content: {content[:200]}...")
            # Re-raise exception so fallback to Gemini can work
            raise
        
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
            pattern = r"\\b" + re.escape(k) + r"\\b"
            if re.search(pattern, text_lc):
                return True
        else:
            if k in text_lc:
                return True
    return False

def classify(title, text):
    t = (title + " " + text).lower()
    
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
    
    # 文娱 (Entertainment) - Expanded keywords
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
    
    # Check categories in order of specificity
    if _contains_kw(t, economy_keywords): return "经济"
    if _contains_kw(t, disaster_keywords): return "灾害"
    if _contains_kw(t, sports_keywords): return "体育"
    if _contains_kw(t, tech_keywords): return "科技"
    if _contains_kw(t, entertainment_keywords): return "文娱"
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

def collect_once():
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
                desc = e.get("summary") or e.get("description") or ""
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
                if resolved_link in SENT_URLS or link in SENT_URLS:
                    print(f"  URL already sent, skipping: {resolved_link or link}")
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

def main():
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
    
    # Leader election mechanism to prevent duplicate news from multiple machines
    def is_leader():
        """Check if this machine should be the leader (only one runs at a time)"""
        try:
            # Create a lock file to ensure only one machine runs
            lock_file = "/data/leader.lock"
            
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
            lock_file = "/data/leader.lock"
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
                os.remove("/data/leader.lock")
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
            items = collect_once()
            print(f"=== Found {len(items)} total items ===")
            # Sort by priority first, then by published_at (latest first)
            def _k(it):
                priority = 1 if it.get("priority") else 0
                published_at = it.get("published_at") or "1970-01-01T00:00:00"
                return (priority, published_at)
            items.sort(key=_k, reverse=True)
            
            # Log the top 10 most recent items for verification
            print(f"=== Top 10 most recent news items ===")
            for i, item in enumerate(items[:10]):
                print(f"{i+1}. {item['title'][:60]}... (Published: {item.get('published_at', 'No date')})")
            
            # Process items and skip already sent news
            for it in items:
                # Check if this news has already been sent
                if is_news_already_sent(it['url'], sent_news_urls):
                    print(f"⏭️  Skipping already sent news: {it['title'][:50]}...")
                    continue

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
                        # Fallback: Use RSS content but still try AI summarization
                        rss_content = f"Title: {it['title']}\n\nContent: {it['body']}"
                        try:
                            chinese_title, summary, ai_provider_used = ai_summarize_content(it["title"], rss_content)
                            
                            # Validate that we got meaningful content
                            if not chinese_title or chinese_title.strip() in ["【分类】中文标题", "中文标题", ""]:
                                print(f"  ⚠️  AI returned empty/placeholder title, using fallback")
                                chinese_title = f"【科技】{it['title']}"
                            
                            if not summary or summary.strip() in ["中文摘要", "摘要", ""]:
                                print(f"  ⚠️  AI returned empty/placeholder summary, using fallback")
                                summary = f"根据{it['title']}的报道，这是一条重要的科技新闻。"
                            
                            if chinese_title:
                                it["title"] = chinese_title
                                print(f"  🏷️  AI-generated Chinese title (RSS fallback): {chinese_title[:40]}...")
                            print(f"  🤖 AI RSS summary length: {len(summary)} characters")
                            
                        except Exception as ai_error:
                            print(f"  ❌ AI RSS summarization failed: {ai_error}")
                            print(f"  🔄 Using final fallback")
                            chinese_title = f"【科技】{it['title']}"
                            summary = f"根据{it['title']}的报道，这是一条重要的科技新闻。"
                            it["title"] = _apply_chinese_name_map(chinese_title)
                else:
                    print(f"  📝 Using simple summarization (AI disabled)")
                    summary = summarize(it["title"], it["body"])
                
                # If summary still looks English and AI is enabled, try to regenerate in Chinese
                if use_ai and _is_mostly_english(summary):
                    try:
                        print(f"  🔁 Summary looks English; regenerating with AI in Chinese")
                        chinese_title, cn_summary, ai_provider_used = ai_summarize_from_url(it["title"], it['url'])
                        if chinese_title and not it["title"].startswith("【"):
                            it["title"] = chinese_title
                        if cn_summary:
                            summary = cn_summary
                    except Exception as _e:
                        print(f"  ⚠️ Regeneration failed: {_e}")

                # Final safety check - ensure we never send empty/placeholder content
                # Apply Chinese name mapping to any remaining English-name instances
                summary = _apply_chinese_name_map(summary)
                it["title"] = _apply_chinese_name_map(it["title"])

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
                # Extract category from title if it contains 【】 tags, otherwise use rule-based classification
                if "【" in it["title"] and "】" in it["title"]:
                    # Extract category from title (e.g., 【科技】标题 -> 科技)
                    try:
                        start = it["title"].find("【") + 1
                        end = it["title"].find("】")
                        if start > 0 and end > start:
                            category = it["title"][start:end]
                            print(f"  🏷️  Category extracted from title: {category}")
                            title = it["title"]  # Use the title as-is since it already has the category
                        else:
                            category = classify(it["title"], summary)
                            title = f"【{category}】{it['title']}"
                    except:
                        category = classify(it["title"], summary)
                        title = f"【{category}】{it['title']}"
                else:
                    category = classify(it["title"], summary)
                    title = f"【{category}】{it['title']}"
                
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
                
                # Add MiMo attribution if MiMo was used
                if ai_provider_used == "mimo":
                    content += f"\n\n摘要由 [Xiaomi MiMo](https://mimo.xiaomi.com/) LLM 生成"
                
                # Brand detection for Xiaomi vs competitors
                brand = detect_brand(f"{title} {summary} {content}")
                category_brand = brand_category(brand)
                brand_label = brand.title() if brand and brand != "other" else "Other"

                if TEST_MODE:
                    print(f"WOULD SEND: {title}")
                    print(f"CONTENT: {content[:100]}...")
                else:
                    if len(webhook_urls) > 0 and not USE_APP_API:
                        # Send to all configured webhook URLs
                        print(f"📝 Title: {title}")
                        print(f"📄 Content preview: {content[:200]}...")
                        send_to_multiple_webhooks(webhook_urls, title, content, webhook_secret)
                    else:
                        print(f"📤 Sending via API (token method)")
                        token = get_tenant_access_token(app_id, app_secret)
                        image_key = None
                        # Try to get cover from RSS, else from article page
                        cover_url = it.get('cover_url')
                        if not cover_url:
                            cover_url = extract_cover_image(it['url'])
                        if cover_url:
                            image_key = upload_image_to_feishu(token, cover_url)
                        if image_key:
                            send_card_message_with_image(token, chat_id, title, content, image_key)
                        else:
                            send_card_message(token, chat_id, title, content)
                        print(f"✅ API sent successfully")

                # Log to Bitable if configured
                received_at = datetime.utcnow().isoformat() + "Z"
                bitable_fields = {
                    "title": title,
                    "url": it["url"],
                    "media": source_name,
                    "brand": brand_label,
                    "category": category_brand,
                    "published_at": it.get("published_at") or "",
                    "received_at": received_at,
                    "source_feed": it.get("source", ""),
                    "hash": _key(it["url"], it["title"]),
                    "is_duplicate": False,
                    "summary": summary
                }
                maybe_log_to_bitable(bitable_fields)
                
                # Mark this URL as sent (both in-memory and persistent)
                SENT_URLS.add(it['url'])
                sent_news_urls.add(it['url'])
                print(f"✅ Sent news: {it['title'][:50]}...")
                sent += 1
                if sent >= MAX_PER_CYCLE:
                    print(f"Reached MAX_PER_CYCLE={MAX_PER_CYCLE}, stop sending this round.")
                    break
                time.sleep(SEND_INTERVAL_SEC)
            
            # Save sent news URLs to file after each cycle
            save_sent_news(sent_news_urls)
            
        except Exception as e:
            print(f"loop_error: {e}")
        if ONE_SHOT:
            break
        # Update leader heartbeat
        try:
            lock_file = "/data/leader.lock"
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
        print(f"⏳ Sleeping {loop_sleep}s before next cycle...")
        time.sleep(loop_sleep)

if __name__ == "__main__":
    main()