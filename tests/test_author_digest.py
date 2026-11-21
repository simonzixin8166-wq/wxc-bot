"""Per-author digest ("文学城博主整理", Owner 2026-11-21): parsed into one entry per utterance, deduped against the
daily topic export by (author, minute, title), routed from Telegram/Gmail, fed into the research feed without the
shared topic link collapsing replies. Invented text only; no network."""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATA_DIR"] = tempfile.mkdtemp()
import owner_forum_export as forum  # noqa: E402

DIGEST = """# zmtest 的发言整理

- 范围：2026-10-22 起
- 共 4 条发言，涉及 2 个话题

---

## 还能撑住吗？

楼主 zmtest · 2026-11-20 08:14 · [原帖](https://bbs.wenxuecity.com/cfzh/900001.html)

### 2026-11-20 08:14 · 还能撑住吗？

[图片](https://example.com/chart.png)

### 2026-11-20 08:39 · 如果不是大跌则调整基本到位，我看好 NVDA

> 回复 路人甲「是不是还没调整够？」

（标题即全文）

### 2026-11-20 09:08 · 恐慌指数很低了

> 回复 路人乙「机会来了」：后面还有一句

我觉得可以分批买 QQQ。

## 别人开的帖

楼主 someoneelse · 2026-11-19 14:36 · [原帖](https://bbs.wenxuecity.com/cfzh/900002.html)

### 2026-11-19 14:53 · 次级信号管几个月周期

> 回复 someoneelse「什么是次级信号？」

（正文未抓到，可点链接查看）
"""

assert forum.is_author_digest(DIGEST) and not forum.is_topic(DIGEST)
t = forum.parse_author_digest(DIGEST)
e = t["entries"]
assert t["digest_author"] == "zmtest" and len(e) == 4, [x["title"] for x in e]
root, r1, r2, r3 = e
assert root["kind"] == "post" and root["post_id"] == "900001" and root["parent"] is None and root["body_status"] == "title_only"
assert root["url"] == "https://bbs.wenxuecity.com/cfzh/900001.html" and not root["url_is_topic"]
assert r1["kind"] == "reply" and r1["post_id"].startswith("900001r202611200839") and len(r1["post_id"]) == len("900001r202611200839") + 4 and r1["url_is_topic"]
assert r1["parent"] == {"post_id": None, "author": "路人甲", "title": "是不是还没调整够？", "published_at": None}
assert r1["body_status"] == "title_only" and r1["text"] == "如果不是大跌则调整基本到位，我看好 NVDA"
assert r2["body_status"] == "body_exported" and r2["text"].endswith("我觉得可以分批买 QQQ。") and "后面还有一句" not in r2["text"]
assert r3["root_post_id"] == "900002" and r3["kind"] == "reply" and r3["body_status"] == "body_missing" and r3["text"] == "次级信号管几个月周期"
assert r3["published_at"] == "2026-11-19 14:53:00" and r3["author"] == "zmtest"
assert forum.parse_any(DIGEST)["digest_author"] == "zmtest"
assert forum.textpack_path(t).startswith("s2_v5_textpack/F_owner_forum/digest_zmtest_")
# same author, topic and minute twice -> distinct ids (11/21 real digest had 2 such pairs in 197)
twin = DIGEST.replace("### 2026-11-20 09:08 · 恐慌指数很低了", "### 2026-11-20 08:39 · 恐慌指数很低了")
tw = forum.parse_author_digest(twin)["entries"]
assert len({x["post_id"] for x in tw}) == 4 and tw[1]["post_id"] != tw[2]["post_id"] and tw[1]["post_id"].startswith("900001r202611200839")
print("PASS digest parse: one entry per utterance, root vs reply, parent from 回复, title-only / body / missing")


class R:
    def __init__(self, code=201):
        self.status_code = code


class Http:
    def __init__(self):
        self.puts = []

    def put(self, url, **k):
        self.puts.append(url)
        return R(201)


os.environ["TEXTPACK_TOKEN"], os.environ["TEXTPACK_REPO"] = "t", "o/r"
NOW = datetime(2026, 11, 21, 10, 30, tzinfo=timezone.utc)
http = Http()
seen = forum.existing()
c = forum.ingest_topic(DIGEST, NOW.isoformat(), NOW, http, seen, "author_digest_md")
assert c["new"] == 4 and c["duplicate"] == 0 and c["title_only"] == 2 and c["body_missing"] == 1 and c["failed"] == 0, c
rows = [json.loads(x) for x in forum.index_path().read_text(encoding="utf-8").splitlines()]
assert [r["url_is_topic"] for r in rows] == [False, True, True, True] and all(len(r["excerpt"]) <= 360 for r in rows)
# same digest again -> all duplicates, nothing stored
c2 = forum.ingest_topic(DIGEST, NOW.isoformat(), NOW, http, forum.existing(), "author_digest_md")
assert c2["new"] == 0 and c2["duplicate"] == 4 and len(http.puts) == 1, (c2, http.puts)

# the daily topic export later carries the same reply with its real post id -> recognised as a duplicate
TOPIC = """# 还能撑住吗？
- **楼主**：zmtest　**时间**：2026-11-20 08:14
- **参与的目标用户**：zmtest
- **链接**：https://bbs.wenxuecity.com/cfzh/900001.html
## 主帖
（无正文，标题即内容）
## 跟帖
- [如果不是大跌则调整基本到位，我看好 NVDA](https://bbs.wenxuecity.com/cfzh/900010.html) — **zmtest** ⭐ 11-20 08:39 (0 bytes)
- [全新的一条](https://bbs.wenxuecity.com/cfzh/900011.html) — **zmtest** ⭐ 11-20 10:00 (0 bytes)
"""
c3 = forum.ingest_topic(TOPIC, NOW.isoformat(), NOW, http, forum.existing(), "zip:forum_topic_md")
assert c3["new"] == 1 and c3["duplicate"] == 2, c3     # root (900001) by id, 08:39 reply by author+minute+title
print("PASS digest ingest: stored once, re-send = duplicates, cross-dedupe with the daily topic export")

# routing: a digest .md sent to the bot (or arriving by Gmail) goes to the digest path
import owner_forward  # noqa: E402
said = []
D2 = DIGEST.replace("zmtest", "zmother").replace("9000", "8000")
out = owner_forward.handle({"date": int(NOW.timestamp()), "caption": "", "document": {"file_name": "zmother_2026.md", "file_size": len(D2)},
                            "_bytes": D2.encode("utf-8")}, said.append, http=http, now=NOW)
assert out["forum"]["new"] == 4 and said and said[-1].startswith("博主整理（zmother）"), (out, said)
gs = (ROOT / "tools" / "gmail" / "myalpha_gmail_inbox.gs").read_text(encoding="utf-8")
assert "(zip|md)" in gs
print("PASS digest routing: Telegram/Gmail .md -> digest intake; Gmail script accepts .md")

# feed: replies sharing the topic link are each appended (keyed by entry id), not collapsed into one
import owner_forum_feed as off  # noqa: E402
import research_feed as rf  # noqa: E402
rf.FEED_PATH = Path(os.environ["DATA_DIR"]) / "research_feed.json"
rf.FEED_PATH.write_text(json.dumps({"records": []}), encoding="utf-8")
off.fetch_topic = lambda path, http=None: DIGEST if "zmtest" in path else (D2 if "zmother" in path else TOPIC)
rep = off.run(http=http, now=NOW)
recs = json.loads(rf.FEED_PATH.read_text(encoding="utf-8"))["records"]
zm = [r for r in recs if r.get("author") == "zmtest"]
assert len(zm) == 5 and len({r["source_entry_key"] for r in zm}) == 5, (rep, [r.get("source_entry_key") for r in zm])
assert off.run(http=http, now=NOW)["appended"] == 0
print("PASS digest feed: each utterance appended once; topic-link replies keyed by entry id")
