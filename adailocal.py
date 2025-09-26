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

# DeepSeek API Configuration
DEEPSEEK_API_KEY = "sk-07fefd77e80043979374fc5e10be9f3d"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

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
    "https://rss.app/feeds/7kWc8DwjcHvi1nOK.xml", #Xiaomi MY Fb
    "https://rss.app/feeds/r5wzRVVTbqYIyfSE.xml", #ZingGadget MY Fb
    "https://rss.app/feeds/DQPaHn61uiC3hfmk.xml", #TechnaveCN MY Fb
    "https://rss.app/feeds/M50McNEZ5iyyJ4LI.xml", #Soyacincau MY Fb
    "https://www.soyacincau.com/feed/",
    "https://amanz.my/feed/",
    "https://www.lowyat.net/feed/",
    
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
    #"https://www.orientaldaily.com.my/feed/",
]

# Feeds with highest priority (processed first when present)
PRIORITY_FEEDS = {
    "https://rss.app/feeds/7kWc8DwjcHvi1nOK.xml",
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

def _norm(u): return (u or "").split("?")[0]
def _key(link, title): return hashlib.sha1(((_norm(link) or title) or "").encode("utf-8","ignore")).hexdigest()
def _clean(html): return " ".join(BeautifulSoup(html or "", "lxml").get_text(" ").split())

def _format_source_name(source):
    """Format source name to be more user-friendly"""
    if not source:
        return "未知来源"
    
    # Clean up common RSS feed names
    source = source.replace(" - All", "").replace(" - Latest News", "").replace(" RSS", "")
    source = source.replace("Online", "").replace("Latest", "").replace("News", "")
    source = source.replace("  ", " ").strip()

    # Do not append any suffix; show the original media name only
    return source

def read_article_content(url):
    """Read and extract the main content from an article URL"""
    try:
        print(f"  📖 Reading article: {url}")
        
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
        
        response = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        print(f"  📡 Response status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"  ❌ HTTP error: {response.status_code}")
            return ""
        
        # Check if we got HTML content
        content_type = response.headers.get('content-type', '').lower()
        if 'html' not in content_type:
            print(f"  ❌ Not HTML content: {content_type}")
            return ""
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove unwanted elements
        for element in soup(["script", "style", "nav", "header", "footer", "aside", "noscript", "iframe"]):
            element.decompose()
        
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

def deepseek_summarize_from_url(title, article_url):
    """Use DeepSeek AI to read and summarize the article directly from URL"""
    try:
        print(f"  🤖 DeepSeek reading and summarizing: {title[:50]}...")
        
        # Prepare the prompt for DeepSeek to read the article directly
        # Include extracted numeric/spec facts to ground the model
        source_text_for_facts = read_article_content(article_url)
        facts = _extract_numeric_facts(source_text_for_facts)
        facts_list = sorted(list(facts.get('raw_tokens', set())))
        facts_block = "\n".join(facts_list[:40])  # cap to reasonable length
        prompt = f"""Please read the following news article URL and provide:

1. **A Mandarin Chinese title with category tag** (简洁明了的中文标题，前面加上【分类】标签)
2. **A comprehensive summary in Chinese** (no more than 50 words; if Chinese, ≤120 characters)

Requirements:
- **Title MUST be in Mandarin Chinese** (not English)
- Title should be concise and capture the main point
- Add appropriate category tag in front of title using format 【分类】
- Category options: 科技、娱乐、经济、体育、灾难、综合
- **IMPORTANT: Keep company/brand names in English** (e.g., Honda, Toyota, Samsung, Apple, Google, Microsoft, etc.)
- **IMPORTANT: Keep product names in English** (e.g., iPhone, Galaxy, Windows, etc.)
- **IMPORTANT: Keep location names in English** (e.g., Malaysia, Kuala Lumpur, Singapore, etc.)
- **IMPORTANT: Keep person names in English** (e.g., Kiandee, Najib, Anwar, etc.)
- Summary should be informative with key facts and details
- Include important numbers, dates, and names
- Do NOT invent or infer numeric values. Only use numbers explicitly present in the article.
- If multiple prices are mentioned, pick the main product's price as stated.
- Keep currency symbols/codes exactly as in the article (e.g., RM, MYR, USD, US$).
- Maintain original meaning and context
- Use clear, professional language

Article Title: {title}
Article URL: {article_url}

Please provide the response in this exact format:
标题: 【分类】中文标题
摘要: 中文摘要

Use ONLY numeric values present in the article or in this extracted facts list, and keep the exact units/currency/casing. If a number is not in the facts list and you are unsure, omit it.

Facts (from article text, may be partial):
{facts_block}

Please read the full article from the URL and provide only the title and summary without any additional commentary."""

        headers = {
            'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        data = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 500,
            "temperature": 0.1,
            "stream": False
        }
        
        print(f"  📤 Sending request to DeepSeek API...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        print(f"  📡 DeepSeek API response status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"  ❌ DeepSeek API error: {response.status_code}")
            print(f"  📄 Response text: {response.text[:500]}...")
            raise Exception(f"API returned {response.status_code}")
        
        try:
            result = response.json()
            print(f"  📋 DeepSeek API response keys: {list(result.keys())}")
        except Exception as e:
            print(f"  ❌ Failed to parse JSON response: {e}")
            print(f"  📄 Raw response: {response.text[:500]}...")
            raise Exception("Invalid JSON response")
        
        if 'choices' not in result or not result['choices']:
            print(f"  ❌ No choices in DeepSeek response")
            print(f"  📋 Full response: {result}")
            raise Exception("No choices in API response")
        
        if 'message' not in result['choices'][0] or 'content' not in result['choices'][0]['message']:
            print(f"  ❌ Invalid response structure")
            print(f"  📋 Choice structure: {result['choices'][0]}")
            raise Exception("Invalid response structure")
        
        content = result['choices'][0]['message']['content'].strip()
        
        if not content:
            print(f"  ❌ Empty content received")
            raise Exception("Empty content received")
        
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
            
            print(f"  ✅ DeepSeek Chinese title: {chinese_title}")
            print(f"  ✅ DeepSeek summary generated: {len(summary)} characters")

            # Numeric consistency check by reading article content locally
            try:
                source_text = read_article_content(article_url)
                facts = _extract_numeric_facts(source_text)
                if not _numbers_consistent(summary, facts):
                    print("  ⚠️  Numeric inconsistency detected. Regenerating with extracted facts context.")
                    facts_text = "\n".join(sorted(facts.get("prices", set())))
                    regen_prompt = f"""You summarized this article, but the numeric facts must be exact. Here are numeric facts extracted from the article; ONLY use numbers from this list. If none are relevant, omit numbers.

Facts:
{facts_text}

Now output again in the same format:
标题: 【分类】中文标题
摘要: 中文摘要
"""
                    headers = {
                        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
                        'Content-Type': 'application/json'
                    }
                    data2 = {
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": "You must not invent numbers. Use only given facts."},
                            {"role": "user", "content": regen_prompt}
                        ],
                        "max_tokens": 400,
                        "temperature": 0.0,
                        "stream": False
                    }
                    r2 = requests.post(DEEPSEEK_API_URL, headers=headers, json=data2, timeout=20)
                    if r2.status_code == 200:
                        j2 = r2.json()
                        new_content = (j2.get('choices', [{}])[0].get('message', {}).get('content') or '').strip()
                        if new_content:
                            # reparse
                            lines2 = new_content.split('\n')
                            ct2, sm2 = chinese_title, summary
                            for line in lines2:
                                s = line.strip()
                                if s.startswith('标题:'):
                                    ct2 = s.replace('标题:', '').strip()
                                elif s.startswith('摘要:'):
                                    sm2 = s.replace('摘要:', '').strip()
                            if ct2 and sm2:
                                chinese_title, summary = ct2, sm2
                                print("  🔁 Replaced with fact-consistent summary.")
            except Exception as _e:
                print(f"  ⚠️  Consistency check failed: {_e}")
            
            # Enforce short summary length (<=50 words or <=120 CJK chars)
            def _limit_summary(text: str) -> str:
                try:
                    words = text.split()
                    if len(words) > 0 and len(words) <= 70:
                        # If it's likely Chinese (few spaces), cap by characters
                        compact = text.replace("\n", " ").strip()
                        if compact and compact.count(' ') < 5:
                            return compact[:120]
                    # Otherwise cap by 50 words
                    return " ".join(words[:50])
                except Exception:
                    return text[:120]
            summary = _limit_summary(summary)
            # Return both title and shortened summary as a tuple
            return chinese_title, summary
            
        except Exception as e:
            print(f"  ⚠️  Error parsing response: {e}")
            print(f"  📄 Raw content: {content[:200]}...")
            # Fallback: use original title and full content as summary
            return title, content
        
    except Exception as e:
        print(f"  ❌ DeepSeek API error: {e}")
        # Fallback to simple truncation
        return title, (article_content[:500] + "..." if len(article_content) > 500 else article_content)

def deepseek_summarize_content(title, article_content):
    """Use DeepSeek AI to summarize pre-extracted article content"""
    try:
        print(f"  🤖 DeepSeek summarizing content: {title[:50]}...")
        
        # Prepare the prompt for DeepSeek
        facts = _extract_numeric_facts(article_content)
        facts_list = sorted(list(facts.get('raw_tokens', set())))
        facts_block = "\n".join(facts_list[:40])
        prompt = f"""Please analyze this news article and provide:

1. **A Mandarin Chinese title with category tag** (简洁明了的中文标题，前面加上【分类】标签)
2. **A comprehensive summary in Chinese** (no more than 50 words; if Chinese, ≤120 characters)

Requirements:
- **Title MUST be in Mandarin Chinese** (not English)
- Title should be concise and capture the main point
- Add appropriate category tag in front of title using format 【分类】
- Category options: 科技、娱乐、经济、体育、灾难、综合
- **IMPORTANT: Keep company/brand names in English** (e.g., Honda, Toyota, Samsung, Apple, Google, Microsoft, etc.)
- **IMPORTANT: Keep product names in English** (e.g., iPhone, Galaxy, Windows, etc.)
- **IMPORTANT: Keep location names in English** (e.g., Malaysia, Kuala Lumpur, Singapore, etc.)
- **IMPORTANT: Keep person names in English** (e.g., Kiandee, Najib, Anwar, etc.)
- Summary should be informative with key facts and details
- Include important numbers, dates, and names
- Do NOT invent or infer numeric values. Only use numbers explicitly present in the article.
- If multiple prices are mentioned, pick the main product's price as stated.
- Keep currency symbols/codes exactly as in the article (e.g., RM, MYR, USD, US$).
- Maintain original meaning and context
- Use clear, professional language

Article Title: {title}

Article Content:
{article_content}

Please provide the response in this exact format:
标题: 【分类】中文标题
摘要: 中文摘要

Use ONLY numeric values present in the article or in this extracted facts list, and keep the exact units/currency/casing. If a number is not in the facts list and you are unsure, omit it.

Facts (from article text, may be partial):
{facts_block}

Please provide only the title and summary without any additional commentary."""

        headers = {
            'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        data = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 500,
            "temperature": 0.1,
            "stream": False
        }
        
        print(f"  📤 Sending request to DeepSeek API...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        print(f"  📡 DeepSeek API response status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"  ❌ DeepSeek API error: {response.status_code}")
            print(f"  📄 Response text: {response.text[:500]}...")
            raise Exception(f"API returned {response.status_code}")
        
        try:
            result = response.json()
            print(f"  📋 DeepSeek API response keys: {list(result.keys())}")
        except Exception as e:
            print(f"  ❌ Failed to parse JSON response: {e}")
            print(f"  📄 Raw response: {response.text[:500]}...")
            raise Exception("Invalid JSON response")
        
        if 'choices' not in result or not result['choices']:
            print(f"  ❌ No choices in DeepSeek response")
            print(f"  📋 Full response: {result}")
            raise Exception("No choices in API response")
        
        if 'message' not in result['choices'][0] or 'content' not in result['choices'][0]['message']:
            print(f"  ❌ Invalid response structure")
            print(f"  📋 Choice structure: {result['choices'][0]}")
            raise Exception("Invalid response structure")
        
        content = result['choices'][0]['message']['content'].strip()
        
        if not content:
            print(f"  ❌ Empty content received")
            raise Exception("Empty content received")
        
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
            
            print(f"  ✅ DeepSeek Chinese title: {chinese_title}")
            print(f"  ✅ DeepSeek summary generated: {len(summary)} characters")

            # Numeric consistency check using provided article_content
            try:
                facts = _extract_numeric_facts(article_content)
                if not _numbers_consistent(summary, facts):
                    print("  ⚠️  Numeric inconsistency detected (content). Regenerating with facts.")
                    facts_text = "\n".join(sorted(facts.get("prices", set())))
                    regen_prompt = f"""You summarized this article, but numeric facts must be exact. ONLY use numbers from the facts list; if not present, omit numbers.

Facts:
{facts_text}

Now output again in the same format:
标题: 【分类】中文标题
摘要: 中文摘要
"""
                    headers = {
                        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
                        'Content-Type': 'application/json'
                    }
                    data2 = {
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": "You must not invent numbers. Use only given facts."},
                            {"role": "user", "content": regen_prompt}
                        ],
                        "max_tokens": 400,
                        "temperature": 0.0,
                        "stream": False
                    }
                    r2 = requests.post(DEEPSEEK_API_URL, headers=headers, json=data2, timeout=20)
                    if r2.status_code == 200:
                        j2 = r2.json()
                        new_content = (j2.get('choices', [{}])[0].get('message', {}).get('content') or '').strip()
                        if new_content:
                            lines2 = new_content.split('\n')
                            ct2, sm2 = chinese_title, summary
                            for line in lines2:
                                s = line.strip()
                                if s.startswith('标题:'):
                                    ct2 = s.replace('标题:', '').strip()
                                elif s.startswith('摘要:'):
                                    sm2 = s.replace('摘要:', '').strip()
                            if ct2 and sm2:
                                chinese_title, summary = ct2, sm2
                                print("  🔁 Replaced with fact-consistent summary (content path).")
            except Exception as _e:
                print(f"  ⚠️  Consistency check failed (content): {_e}")
            
            # Enforce short summary length (<=50 words or <=120 CJK chars)
            def _limit_summary(text: str) -> str:
                try:
                    words = text.split()
                    if len(words) > 0 and len(words) <= 70:
                        # If it's likely Chinese (few spaces), cap by characters
                        compact = text.replace("\n", " ").strip()
                        if compact and compact.count(' ') < 5:
                            return compact[:120]
                    # Otherwise cap by 50 words
                    return " ".join(words[:50])
                except Exception:
                    return text[:120]
            summary = _limit_summary(summary)
            # Return both title and shortened summary as a tuple
            return chinese_title, summary
            
        except Exception as e:
            print(f"  ⚠️  Error parsing response: {e}")
            print(f"  📄 Raw content: {content[:200]}...")
            # Fallback: return original title and full content as summary
            return title, content
        
    except Exception as e:
        print(f"  ❌ DeepSeek API error: {e}")
        # Fallback to simple truncation
        return article_content[:500] + "..." if len(article_content) > 500 else article_content

def deepseek_verify_category(title: str, summary: str) -> str:
    """Ask DeepSeek to classify the news into one of fixed categories.
    Returns a label in {经济, 灾害, 体育, 科技, 文娱, 综合} or empty string on failure.
    """
    try:
        print("  🤖 DeepSeek verifying category...")
        prompt = f"""你是新闻分类助手。请根据下列标题和简要内容，判断其所属类别，并只输出以下六个标签中的一个：
经济 / 灾害 / 体育 / 科技 / 文娱 / 综合。

标题: {title}
内容: {summary}

只输出一个标签，不要输出任何解释或其他文字。"""

        headers = {
            'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json'
        }
        data = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 10,
            "temperature": 0.0,
            "stream": False
        }
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=20)
        if response.status_code != 200:
            print(f"  ❌ DeepSeek cat API error: {response.status_code}")
            return ""
        result = response.json()
        label = (result.get('choices', [{}])[0].get('message', {}).get('content') or '').strip()
        valid = {"经济", "灾害", "体育", "科技", "文娱", "综合"}
        if label in valid:
            print(f"  ✅ DeepSeek category: {label}")
            return label
        # Sometimes wrapped in extra text; try to pick the first valid token
        for v in valid:
            if v in label:
                print(f"  ✅ DeepSeek category (extracted): {v}")
                return v
        print(f"  ⚠️ DeepSeek category invalid: {label}")
        return ""
    except Exception as e:
        print(f"  ❌ DeepSeek category verify error: {e}")
        return ""

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
    for feed_url in ordered_feeds:
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
                
                # Get description for processing
                desc = e.get("summary") or e.get("description") or ""
                body = _clean(desc)
                
                print(f"  ✅ News found: {title[:50]}...")
                
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
    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    webhook_secret = os.environ.get("FEISHU_WEBHOOK_SECRET", "").strip()
    
    # Debug environment variables
    print(f"🔧 Environment check:")
    print(f"  FEISHU_WEBHOOK_URL: {'Set' if webhook_url else 'Not set'}")
    print(f"  FEISHU_WEBHOOK_SECRET: {'Set' if webhook_secret else 'Not set (optional)'}")
    if webhook_url:
        print(f"  Webhook URL: {webhook_url[:50]}...")
    
    # Test mode - don't actually send if webhook URL is placeholder
    TEST_MODE = webhook_url == "your_webhook_url_here" or not webhook_url
    if TEST_MODE:
        print("=== RUNNING IN TEST MODE (no actual sending) ===")

    USE_APP_API = os.environ.get("USE_APP_API", "0") == "1"

    if not webhook_url or USE_APP_API:
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
    print(f"  DEEPSEEK_API_KEY: {'Set' if DEEPSEEK_API_KEY else 'Not set'}")
    print(f"  DEEPSEEK_API_URL: {DEEPSEEK_API_URL}")

    # Load previously sent news for persistent deduplication
    sent_news_urls = load_sent_news()
    
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
                use_ai = os.environ.get("USE_AI_SUMMARY", "0") == "1"

                # For priority sources, keep original content; still allow AI to generate a better Chinese title
                if it.get("priority"):
                    print(f"  🛑 Priority source: keep original content. AI may generate title only.")
                    summary = it["body"] or it["title"]
                    if use_ai:
                        try:
                            chinese_title, _tmp_summary = deepseek_summarize_from_url(it["title"], it['url'])
                            if chinese_title:
                                it["title"] = chinese_title
                                print(f"  🏷️  AI-generated Chinese title (priority): {chinese_title[:40]}...")
                        except Exception as e:
                            print(f"  ⚠️  AI title gen failed for priority source: {e}")
                # Use DeepSeek for AI summarization if enabled
                elif use_ai:
                    print(f"🔍 Processing with DeepSeek AI: {it['title'][:50]}...")
                    print(f"  📄 Original RSS body: {it['body'][:100]}...")
                    
                    # Try direct URL approach first (let DeepSeek read the article)
                    try:
                        print(f"  🌐 Letting DeepSeek read article directly from URL")
                        chinese_title, summary = deepseek_summarize_from_url(it["title"], it['url'])
                        print(f"  🤖 DeepSeek Chinese title: {chinese_title}")
                        print(f"  🤖 DeepSeek direct URL summary length: {len(summary)} characters")
                        # Use the Chinese title from DeepSeek
                        it["title"] = chinese_title
                    except Exception as e:
                        print(f"  ⚠️  Direct URL approach failed: {e}")
                        print(f"  🔄 Falling back to content extraction + DeepSeek")
                        
                        # Fallback: extract content and then summarize
                        article_content = read_article_content(it['url'])
                        if article_content and len(article_content) > 100:
                            print(f"  📖 Article content length: {len(article_content)} characters")
                            chinese_title, summary = deepseek_summarize_content(it["title"], article_content)
                            if chinese_title:
                                it["title"] = chinese_title
                                print(f"  🏷️  AI-generated Chinese title (fallback): {chinese_title[:40]}...")
                            print(f"  🤖 DeepSeek content summary length: {len(summary)} characters")
                        else:
                            print(f"  ⚠️  Content extraction failed, using RSS content with DeepSeek")
                            # Use RSS content but still try DeepSeek summarization
                            rss_content = f"Title: {it['title']}\n\nContent: {it['body']}"
                            chinese_title, summary = deepseek_summarize_content(it["title"], rss_content)
                            if chinese_title:
                                it["title"] = chinese_title
                                print(f"  🏷️  AI-generated Chinese title (RSS fallback): {chinese_title[:40]}...")
                            print(f"  🤖 DeepSeek RSS summary length: {len(summary)} characters")
                else:
                    print(f"  📝 Using simple summarization (AI disabled)")
                    summary = summarize(it["title"], it["body"])
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
                            # Format source name nicely and make it a clickable link
                            source_name = _format_source_name(it['source'])
                            content = f"{summary}\n\n⏰ {time_str}\n\n来源：[{source_name}]({it['url']})"
                        else:
                            source_name = _format_source_name(it['source'])
                            content = f"{summary}\n\n来源：[{source_name}]({it['url']})"
                    except:
                        source_name = _format_source_name(it['source'])
                        content = f"{summary}\n\n来源：[{source_name}]({it['url']})"
                else:
                    source_name = _format_source_name(it['source'])
                    content = f"{summary}\n\n来源：[{source_name}]({it['url']})"
                
                if TEST_MODE:
                    print(f"WOULD SEND: {title}")
                    print(f"CONTENT: {content[:100]}...")
                else:
                    if webhook_url and not USE_APP_API:
                        print(f"📤 Sending via webhook: {webhook_url[:50]}...")
                        print(f"  📝 Title: {title}")
                        print(f"  📄 Content preview: {content[:200]}...")
                        # Only pass secret if it's actually set
                        if webhook_secret:
                            send_card_via_webhook(webhook_url, title, content, secret=webhook_secret)
                        else:
                            send_card_via_webhook(webhook_url, title, content)
                        print(f"✅ Webhook sent successfully")
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