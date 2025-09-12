import feedparser, json
feeds = [
  """https://rsshub.app/facebook/page/XiaomiMalaysia""",
  """https://rsshub.rssforever.com/facebook/page/XiaomiMalaysia""",
]
items = []
for u in feeds:
    f = feedparser.parse(u)
    source = (getattr(f, 'feed', {}).get('title', '') or '').strip()
    for e in getattr(f, 'entries', [])[:5]:
        items.append({
            'source': source or 'RSSHub Facebook',
            'title': (e.get('title') or '').strip(),
            'url': (e.get('link') or '').strip(),
        })
print(json.dumps(items, ensure_ascii=False, indent=2))
