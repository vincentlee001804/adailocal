"""Local verification for the token-containment story dedup layer.

Run from the repo root:  python tests/test_story_dedup.py

Uses the real sent_stories.jsonl snapshot in tests/fixtures/ so the checks
exercise production data (including pre-token-format records).
"""
import os
import sys

# The module configures a RotatingFileHandler at import time.
os.makedirs("logs", exist_ok=True)
_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sent_stories.jsonl")
os.environ["SENT_STORIES_PATH"] = _FIXTURE
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import types
from unittest import mock

# The module pulls in optional prod deps (sumy, etc.) at import time; the
# dedup functions under test don't use them, so stub whatever is missing.
for _attempt in range(30):
    try:
        import adailocal as ad
        break
    except ModuleNotFoundError as e:
        sys.modules[e.name] = mock.MagicMock()
else:  # pragma: no cover
    raise RuntimeError("could not import adailocal even with stubs")

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sent_stories.jsonl")

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((name, cond))
    print(f"[{PASS if cond else FAIL}] {name}" + (f"  ({detail})" if detail else ""))


def _rec(title, url="https://example.com/x", source="Test"):
    return {
        "ts": 1791439234,
        "url": url,
        "title": title,
        "title_key": ad._norm_title_key(title),
        "source": source,
        "_sig": ad._story_signature(title),
        "_toks": ad._significant_tokens(title),
    }


# --- 1. Historical duplicate pairs must now match ---------------------------

sent = ad.load_sent_stories()
check("fixture loads with _toks precomputed (48h window applied)", len(sent) > 40 and all("_toks" in r for r in sent),
      f"{len(sent)} records in window")

fuzz_asus = next(r for r in sent if "fuzz.my/202610081225" in (r.get("url") or ""))
check("Fuzz ASUS ProArt record found in fixture", bool(fuzz_asus))

amanz_asus_title = "【科技】ASUS ProArt P14和P16笔记本开启预购，搭载NVIDIA RTX Spark N1X售价RM29,999"
m = ad.is_similar_to_sent(amanz_asus_title, [fuzz_asus])
check("ASUS ProArt rewrite caught (today's Feishu dup)", m is not None,
      f"matched: {(m or {}).get('title', '')[:40]}")

amanz_bm_title = "Pra-Tempahan ASUS ProArt P14 Dan P16 Dikuasakan NVIDIA RTX Spark N1X Dibuka Pada Harga RM29,999"
m = ad.is_similar_to_sent(amanz_bm_title, [fuzz_asus])
check("ASUS ProArt caught from BM original title too (cross-language)", m is not None)

# Older real pairs (outside the 48h fixture window) — rebuild records from the
# actual titles logged in /data/sent_stories.jsonl on the server.
adam_lobo = _rec("【科技】ASUS ROG 推出限量30套的 ROG XBOX Ally X20 Bundle，售价 RM10,999")
fuzz_xbox_title = "【科技】ASUS ROG Xbox Ally X20 售价 RM10,999 登陆马来西亚"
m = ad.is_similar_to_sent(fuzz_xbox_title, [adam_lobo])
check("ROG Xbox Ally X20 cross-source pair caught", m is not None,
      f"matched: {(m or {}).get('title', '')[:40]}")

tech = _rec("【科技】ASUS ROG Xbox Ally X20限量套组大马开启预购：售RM10,999全马仅限30套")
m = ad.is_similar_to_sent(fuzz_xbox_title, [tech])
check("ROG Xbox pair caught vs Chinese TechNave record (cross-language)", m is not None)

# Full-window simulation: later Amanz title against everything sent before it
before = [r for r in sent if r.get("ts", 0) <= 1791433828]
m = ad.is_similar_to_sent(amanz_asus_title, before)
check("ASUS ProArt caught against full 48h window", m is not None)

# --- 2. Distinct stories must NOT match --------------------------------------

amd_title = "【科技】未发布AMD Ryzen 9 5900X3D曝光，配备128MB L3缓存"
m = ad.is_similar_to_sent(amd_title, [fuzz_asus])
check("AMD story NOT flagged vs ASUS record (no false positive)", m is None)

surface_laptop = next(r for r in sent if "surface-laptop-ultra" in (r.get("url") or ""))
surface_devbox_title = "【科技】Microsoft 发布 Surface RTX Spark Dev Box 售价近 RM25,000"
m = ad.is_similar_to_sent(surface_devbox_title, [surface_laptop])
check("Surface Laptop vs Dev Box NOT merged (different products, by design)", m is None)

ugreen_title = "【科技】UGREEN在马来西亚推出MagFlow和Nexode Pro系列苹果设备配件，起价RM18"
m = ad.is_similar_to_sent(ugreen_title, before[-50:])
check("UGREEN story NOT flagged against recent window", m is None)

# Short/coincidence guard: tiny token sets must never trigger containment
t1 = _rec("【科技】小米15发布")
t2 = _rec("【科技】Redmi 15曝光")
m = ad.is_similar_to_sent(t2["title"], [t1])
check("Short token sets do not trigger containment", m is None)

# --- 3. In-batch dedup --------------------------------------------------------

batch = [
    {"title": "【科技】ASUS ProArt P14和P16在马来西亚开启预售", "url": "u1"},
    {"title": "【科技】ASUS ProArt P14和P16笔记本开启预购，搭载NVIDIA RTX Spark N1X售价RM29,999", "url": "u2"},
    {"title": "【科技】未发布AMD Ryzen 9 5900X3D曝光，配备128MB L3缓存", "url": "u3"},
]
kept = ad.dedup_batch(batch)
check("dedup_batch collapses rewritten pair, keeps distinct story",
      len(kept) == 2 and any("AMD" in k["title"] for k in kept))

# --- Summary ------------------------------------------------------------------
failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
