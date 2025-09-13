# push_my_news.py
# deps: pip install requests feedparser beautifulsoup4 python-dateutil

import os, time, json, hashlib, requests
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

from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.text_rank import TextRankSummarizer
try:
    import nltk  # For tokenizers used by sumy
except Exception:
    nltk = None
 
# Feishu China base (keep this)
BASE = "https://open.f.mioffice.cn"

RSS_FEEDS = [
    # Primary tech-focused feeds (most reliable)
    "https://www.soyacincau.com/feed/",
    "https://amanz.my/feed/",
    "https://www.lowyat.net/feed/",
    
    # Fallback feeds that are more likely to work on PythonAnywhere
    "https://feeds.feedburner.com/soyacincau",
    "https://www.nst.com.my/rss.xml",
    "https://www.malaysiakini.com/rss/en/news.rss",
    
    # Additional feeds (may have network restrictions)
    "https://www.freemalaysiatoday.com/category/nation/feed/",
    "https://www.astroawani.com/rss/english",
    "https://www.astroawani.com/rss/terkini",
    "https://www.sinarharian.com.my/rss/terkini",
    "https://www.hmetro.com.my/terkini.rss",
    "https://www.bernama.com/en/rss.php",
    "https://www.theedgemalaysia.com/rss.xml",
    
    # Commented out feeds that may not work on PythonAnywhere
    # "https://www.thestar.com.my/rss/News/Nation",
    #"https://www.sinchew.com.my/feed/",
    #"https://www.chinapress.com.my/feed/",
    #"https://www.orientaldaily.com.my/feed/",
]

# Tech keywords to filter - only tech-related news will be pushed
TECH_KEYWORDS = [
    # Core tech terms
    "AI", "artificial intelligence", "machine learning", "ML", "technology", "digital innovation",
    "smartphone", "mobile phone", "gadget", "device", "hardware", "software", "app", "application",
    "computer", "laptop", "desktop", "tablet", "iPad", "iPhone", "Android", "iOS", "Windows", "Mac",
    
    # Tech companies and brands
    "Apple", "Samsung", "Google", "Microsoft", "Meta", "Facebook", "Tesla", "Amazon", "Netflix", "Spotify",
    "Xiaomi", "POCO", "Huawei", "OnePlus", "Sony", "LG", "Intel", "AMD", "NVIDIA", "Qualcomm",
    
    # Tech categories
    "EV", "electric vehicle", "automotive tech", "autonomous", "self-driving", "battery", "charging",
    "camera", "photography", "drone", "robot", "robotics", "IoT", "internet of things", "smart home",
    "blockchain", "cryptocurrency", "crypto", "bitcoin", "NFT", "Web3", "metaverse", "VR", "AR",
    "gaming", "console", "PlayStation", "Xbox", "Nintendo", "Steam", "esports", "streaming",
    "cloud", "data center", "server", "database", "cybersecurity", "hacking", "privacy", "encryption",
    
    # Malaysian tech terms
    "Malaysia tech", "Malaysian startup", "tech startup", "fintech", "e-commerce", "online shopping",
    "digital banking", "mobile payment", "e-wallet", "Touch 'n Go", "Grab", "Shopee", "Lazada",
    
    # Tech-specific terms
    "processor", "CPU", "GPU", "RAM", "storage", "SSD", "USB", "Bluetooth", "WiFi", "5G", "4G",
    "programming", "coding", "developer", "startup", "venture capital", "tech investment",
    "artificial", "algorithm", "data science", "analytics", "automation", "digitization"
]
TIMEOUT = (5, 15)

# Time-based dedup (only consider items from last 24 hours)
from datetime import datetime, timedelta

def is_tech_news(title, body):
    """Check if news is tech-related based on keywords"""
    import re
    text = f"{title} {body}".lower()
    
    # More specific tech keywords that are less likely to have false positives
    specific_tech_keywords = [
        # Tech companies and brands (exact matches)
        "apple", "samsung", "google", "microsoft", "meta", "facebook", "tesla", "amazon", "netflix", "spotify",
        "xiaomi", "poco", "huawei", "oneplus", "sony", "lg", "intel", "amd", "nvidia", "qualcomm",
        
        # Tech products and devices
        "iphone", "android", "ios", "windows", "ipad", "smartphone", "laptop", "desktop", "tablet",
        "playstation", "xbox", "nintendo", "steam", "gaming", "console",
        
        # Tech terms with word boundaries
        "\\bai\\b", "\\bml\\b", "\\bev\\b", "\\biot\\b", "\\bvr\\b", "\\bar\\b", "\\b5g\\b", "\\b4g\\b",
        "\\bcpu\\b", "\\bgpu\\b", "\\bram\\b", "\\bssd\\b", "\\busb\\b", "\\bbluetooth\\b", "\\bwifi\\b",
        
        # Tech categories
        "electric vehicle", "autonomous", "self-driving", "battery", "charging", "camera", "photography",
        "drone", "robot", "robotics", "smart home", "blockchain", "cryptocurrency", "crypto", "bitcoin",
        "nft", "web3", "metaverse", "streaming", "cloud", "data center", "server", "database",
        "cybersecurity", "hacking", "privacy", "encryption", "programming", "coding", "developer",
        "startup", "venture capital", "tech investment", "algorithm", "data science", "analytics",
        "automation", "digitization",
        
        # Malaysian tech terms
        "fintech", "e-commerce", "online shopping", "digital banking", "mobile payment", "e-wallet",
        "touch 'n go", "grab", "shopee", "lazada"
    ]
    
    # Check for specific tech matches
    tech_matches = []
    for keyword in specific_tech_keywords:
        if keyword.startswith("\\b") and keyword.endswith("\\b"):
            # Word boundary search
            if re.search(keyword, text):
                tech_matches.append(keyword.replace("\\b", ""))
        else:
            # Regular substring search
            if keyword in text:
                tech_matches.append(keyword)
    
    is_tech = len(tech_matches) > 0
    if is_tech:
        print(f"    🔍 Tech match: {tech_matches[:3]}")
    else:
        print(f"    ❌ Not tech: no matches")
    
    return is_tech

def is_recent_news(published_at_str, hours=2):
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

# Persistent deduplication file
SENT_NEWS_FILE = "sent_news.txt"

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

def _build_card(title, content):
	return {
		"header": { "title": { "content": title, "tag": "plain_text" }, "template": "wathet" },
		"config": { "wide_screen_mode": True },
		"elements": [
			{ "tag": "div", "text": { "tag": "lark_md", "content": content } },
			{ "tag": "hr" },
			{ "tag": "div", "text": { "tag": "lark_md", "content": "\n\n注：摘要、正文均不代表个人观点" } }
		]
	}

def _gen_webhook_sign(secret, timestamp):
	if not secret:
		return None
	string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
	digest = hmac.new(secret.encode("utf-8"), string_to_sign, digestmod=_hashlib.sha256).digest()
	return base64.b64encode(digest).decode("utf-8")

def send_card_via_webhook(webhook_url, title, content, secret=None):
	card = _build_card(title, content)
	payload = { "msg_type": "interactive", "card": card }
	# Optional signing
	if secret:
		ts = str(int(time.time()))
		sign = _gen_webhook_sign(secret, ts)
		payload.update({ "timestamp": ts, "sign": sign })
	r = requests.post(webhook_url, json=payload, timeout=TIMEOUT)
	try:
		data = r.json()
		if isinstance(data, dict) and data.get("StatusCode") not in (0, None) and data.get("code") not in (0, None):
			print(f"webhook_send_warn: {data}")
	except Exception:
		# If not JSON, surface status for debugging
		print(f"webhook_send_status: {r.status_code}")

def _norm(u): return (u or "").split("?")[0]
def _key(link, title): return hashlib.sha1(((_norm(link) or title) or "").encode("utf-8","ignore")).hexdigest()
def _clean(html): return " ".join(BeautifulSoup(html or "", "lxml").get_text(" ").split())

def classify(title, text):
    t = (title + " " + text).lower()
    if any(x in t for x in ["ringgit", "bnm", "gdp", "market", "investment", "budget"]): return "经济"
    if any(x in t for x in ["flood", "banjir", "earthquake", "gempa", "landslide", "haze"]): return "灾害"
    if any(x in t for x in ["match", "goal", "badminton", "football", "harimau malaya"]): return "体育"
    if any(x in t for x in ["ai", "tech", "startup", "software", "chip", "semiconductor"]): return "科技"
    if any(x in t for x in ["film", "movie", "concert", "celebrity", "艺人", "pelakon"]): return "文娱"
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
    for feed_url in RSS_FEEDS:
        try:
            print(f"Fetching: {feed_url}")
            
            # Add headers to mimic a real browser
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # Try to fetch with requests first, then parse with feedparser
            try:
                response = requests.get(feed_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    feed = feedparser.parse(response.content)
                else:
                    print(f"HTTP {response.status_code} for {feed_url}")
                    feed = feedparser.parse(feed_url)
            except Exception as e:
                print(f"Request failed for {feed_url}: {e}")
                feed = feedparser.parse(feed_url)
            
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
                if not is_recent_news(published_at, hours=6):
                    print(f"  Skipping old news: {title[:50]}...")
                    continue
                
                # Get description for tech filtering
                desc = e.get("summary") or e.get("description") or ""
                body = _clean(desc)
                
                # Only process tech-related news
                if not is_tech_news(title, body):
                    print(f"  Skipping non-tech news: {title[:50]}...")
                    continue
                
                print(f"  ✅ Tech news found: {title[:50]}...")
                
                k = _key(link, title)
                if k in SEEN: 
                    print(f"  Already seen this item, skipping")
                    continue
                SEEN.add(k)
                
                # Also check if we've already sent this URL
                if link in SENT_URLS:
                    print(f"  URL already sent, skipping: {link}")
                    continue
                
                items.append({
                    "title": title,
                    "url": _norm(link),
                    "body": body,
                    "source": source_name,
                    "published_at": published_at,
                })
                feed_items += 1
            
            print(f"  Found {feed_items} new items from {source_name}")
            
        except Exception as e:
            print(f"Error fetching {feed_url}: {e}")
            continue
    
    return items

def main():
    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    webhook_secret = os.environ.get("FEISHU_WEBHOOK_SECRET", "").strip()
    
    # Test mode - don't actually send if webhook URL is placeholder
    TEST_MODE = webhook_url == "your_webhook_url_here" or not webhook_url
    if TEST_MODE:
        print("=== RUNNING IN TEST MODE (no actual sending) ===")

    if not webhook_url:
        app_id = os.environ.get("FEISHU_APP_ID", "")
        app_secret = os.environ.get("FEISHU_APP_SECRET", "")
        chat_id = os.environ.get("FEISHU_CHAT_ID", "")

    MAX_PER_CYCLE = int(os.environ.get("MAX_PUSH_PER_CYCLE", "1"))
    SEND_INTERVAL_SEC = float(os.environ.get("SEND_INTERVAL_SEC", "1.0"))

    ONE_SHOT = os.environ.get("ONE_SHOT", "0") == "1"

    # Load previously sent news for persistent deduplication
    sent_news_urls = load_sent_news()
    
    while True:
        try:
            sent = 0
            print(f"=== Starting collection cycle ===")
            items = collect_once()
            print(f"=== Found {len(items)} total items ===")
            # Sort by published_at to get the absolute latest news first
            def _k(it):
                published_at = it.get("published_at") or ""
                # If no date, put at end (lowest priority)
                if not published_at:
                    return "1970-01-01T00:00:00"
                return published_at
            items.sort(key=_k, reverse=True)
            
            # Log the top 3 most recent items for verification
            print(f"=== Top 3 most recent news items ===")
            for i, item in enumerate(items[:3]):
                print(f"{i+1}. {item['title'][:60]}... (Published: {item.get('published_at', 'No date')})")
            
            # Process items and skip already sent news
            for it in items:
                # Check if this news has already been sent
                if is_news_already_sent(it['url'], sent_news_urls):
                    print(f"⏭️  Skipping already sent news: {it['title'][:50]}...")
                    continue
                use_ai = os.environ.get("USE_AI_SUMMARY", "0") == "1"
                summary = ai_summarize(it["title"], it["body"]) if use_ai else summarize(it["title"], it["body"])
                category = classify(it["title"], summary)
                title = f"【{category}】{it['title']}"
                
                # Add publication time to content
                pub_time = it.get("published_at", "")
                if pub_time:
                    try:
                        from datetime import datetime
                        pub_dt = dateparser.parse(pub_time)
                        if pub_dt:
                            time_str = pub_dt.strftime("%Y-%m-%d %H:%M")
                            content = f"{summary}\n\n⏰ {time_str}\n来源：{it['source']}  {it['url']}"
                        else:
                            content = f"{summary}\n\n来源：{it['source']}  {it['url']}"
                    except:
                        content = f"{summary}\n\n来源：{it['source']}  {it['url']}"
                else:
                    content = f"{summary}\n\n来源：{it['source']}  {it['url']}"
                
                if TEST_MODE:
                    print(f"WOULD SEND: {title}")
                    print(f"CONTENT: {content[:100]}...")
                else:
                    if webhook_url:
                        send_card_via_webhook(webhook_url, title, content, secret=webhook_secret)
                    else:
                        token = get_tenant_access_token(app_id, app_secret)
                        send_card_message(token, chat_id, title, content)
                
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
        time.sleep(600)  # every 10 minutes

if __name__ == "__main__":
    main()