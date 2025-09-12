# push_my_news.py
# deps: pip install requests feedparser beautifulsoup4 python-dateutil

import os, time, json, hashlib, requests
import hmac, base64, hashlib as _hashlib
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.text_rank import TextRankSummarizer

# Feishu China base (keep this)
BASE = "https://open.f.mioffice.cn"

RSS_FEEDS = [
    "https://www.soyacincau.com/feed/",
    "https://amanz.my/feed/",
    "https://www.lowyat.net/feed/"
    "https://www.thestar.com.my/rss/News/Nation",
    "https://www.freemalaysiatoday.com/category/nation/feed/",
    "https://www.astroawani.com/rss/english",
    "https://www.astroawani.com/rss/terkini",
    "https://www.sinarharian.com.my/rss/terkini",
    "https://www.hmetro.com.my/terkini.rss",
    #"https://www.sinchew.com.my/feed/",
    #"https://www.chinapress.com.my/feed/",
    #"https://www.orientaldaily.com.my/feed/",
]

# Keywords to filter
# keywords = ["Xiaomi", "POCO", "AI", "EV", "smartphone", "gadget", "tech"]
SEEN_FILE = "seen_items.txt"
# TIMEOUT = (5, 15)

def load_seen():
    try:
        with open(SEEN_FILE, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()

def save_seen(seen_set):
    with open(SEEN_FILE, 'w', encoding='utf-8') as f:
        for item in seen_set:
            f.write(item + '\n')

SEEN = load_seen()

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
    parser = PlaintextParser.from_string(text, Tokenizer("english"))
    summarizer = TextRankSummarizer()
    sents = [str(s) for s in summarizer(parser.document, sentences)]
    if not sents:
        return (body or title)[:320]
    res = " ".join(sents)
    return res[:800]  # keep card compact

def collect_once():
    items = []
    for feed_url in RSS_FEEDS:
        try:
            print(f"Fetching: {feed_url}")
            feed = feedparser.parse(feed_url)
            if hasattr(feed, 'bozo') and feed.bozo:
                print(f"Feed parse warning: {feed_url}")
            source_name = (feed.feed.get("title", "") or "").strip()
            if not source_name:
                source_name = feed_url.split('/')[-1] or "Unknown"
            
            feed_items = 0
            for e in feed.entries:
                link = (e.get("link") or "").strip()
                title = (e.get("title") or "").strip()
                if not title: continue
                k = _key(link, title)
                if k in SEEN: continue
                SEEN.add(k)
                desc = e.get("summary") or e.get("description") or ""
                body = _clean(desc)
                pub = e.get("published") or e.get("updated") or ""
                try:
                    published_at = dateparser.parse(pub).isoformat()
                except Exception:
                    published_at = ""
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
    
    # Save seen items after each collection
    save_seen(SEEN)
    return items

def main():
    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    webhook_secret = os.environ.get("FEISHU_WEBHOOK_SECRET", "").strip()

    if not webhook_url:
        app_id = os.environ["FEISHU_APP_ID"]
        app_secret = os.environ["FEISHU_APP_SECRET"]
        chat_id = os.environ["FEISHU_CHAT_ID"]

    MAX_PER_CYCLE = int(os.environ.get("MAX_PUSH_PER_CYCLE", "1"))
    SEND_INTERVAL_SEC = float(os.environ.get("SEND_INTERVAL_SEC", "1.0"))

    while True:
        try:
            sent = 0
            items = collect_once()
            # Prefer newest first
            def _k(it):
                return it.get("published_at") or ""
            items.sort(key=_k, reverse=True)
            for it in items:
                use_ai = os.environ.get("USE_AI_SUMMARY", "0") == "1"
                summary = ai_summarize(it["title"], it["body"]) if use_ai else summarize(it["title"], it["body"])
                category = classify(it["title"], summary)
                title = f"【{category}】{it['title']}"
                content = f"{summary}\n\n来源：{it['source']}  {it['url']}"
                if webhook_url:
                    send_card_via_webhook(webhook_url, title, content, secret=webhook_secret)
                else:
                    token = get_tenant_access_token(app_id, app_secret)
                    send_card_message(token, chat_id, title, content)
                sent += 1
                if sent >= MAX_PER_CYCLE:
                    print(f"Reached MAX_PER_CYCLE={MAX_PER_CYCLE}, stop sending this round.")
                    break
                time.sleep(SEND_INTERVAL_SEC)
        except Exception as e:
            print(f"loop_error: {e}")
        time.sleep(120)  # every 10 minutes

if __name__ == "__main__":
    main()