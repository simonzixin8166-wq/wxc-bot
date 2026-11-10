"""Owner forum export intake: synthetic topic files, mocked Telegram/GitHub, no network."""
import base64
import io
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

td = tempfile.mkdtemp()
os.environ["DATA_DIR"] = td
os.environ["TEXTPACK_TOKEN"] = "t"
os.environ["TEXTPACK_REPO"] = "o/textpack"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research_feed as rf  # noqa: E402
import owner_forum_export as fe  # noqa: E402
import owner_forward as fw  # noqa: E402
import owner_forum_feed as off  # noqa: E402

rf.FEED_PATH = Path(td) / "research_feed.json"
TOPIC = """# 今天大盘怎么看

- **楼主**：路人甲　**时间**：2026-11-05 07:21
- **参与的目标用户**：作者A, 作者B
- **链接**：https://bbs.wenxuecity.com/cfzh/1000.html
- **跟帖数**：5

## 主帖

（无正文，标题即内容）

## 跟帖

- [我今天加仓了 NVDA](https://bbs.wenxuecity.com/cfzh/1001.html) — **作者A** ⭐ 11-05 07:30
  - [为什么加？](https://bbs.wenxuecity.com/cfzh/1002.html) — 路人乙 11-05 07:35
    - [估值合理，数据中心订单没变](https://bbs.wenxuecity.com/cfzh/1003.html) — **作者A** ⭐ 11-05 07:40 (120 bytes)
      > 本帖于 2026-11-05 07:45:00 时间, 由普通用户 作者A 编辑
      > 回答:
      > 为什么加？
      > 由
      > 路人乙
      > 于
      > 2026-11-05 07:35:00
      > 第一档 180 已经成交，第二档 150
- [SPY 先看 714](https://bbs.wenxuecity.com/cfzh/1004.html) — **作者B** ⭐ 11-05 08:00 (50 bytes)
- [谢谢](https://bbs.wenxuecity.com/cfzh/1005.html) — 路人丙 11-05 08:10
"""
OTHER_POST = """# 我的 SOXL 计划

- **楼主**：作者B　**时间**：2026-10-20 09:00
- **参与的目标用户**：作者B
- **链接**：https://bbs.wenxuecity.com/cfzh/2000.html
- **跟帖数**：0

## 主帖

跌到 40 我会买 SOXL。

## 跟帖

"""

# ---- parser
t = fe.parse_topic(TOPIC)
E = {e["post_id"]: e for e in t["entries"]}
assert set(E) == {"1001", "1003", "1004"}, E.keys()       # only target authors; the non-target root is not an entry
assert E["1001"]["body_status"] == "title_only" and E["1001"]["parent"]["post_id"] == "1000"
assert E["1001"]["replies"][0]["post_id"] == "1002"       # what others replied to the author
assert E["1003"]["parent"]["author"] == "路人乙" and E["1003"]["published_at"] == "2026-11-05 07:40:00"
assert E["1003"]["text"] == "估值合理，数据中心订单没变\n第一档 180 已经成交，第二档 150", E["1003"]["text"]
assert E["1004"]["body_status"] == "body_missing" and E["1004"]["text"] == "SPY 先看 714"   # nothing guessed
p2 = fe.parse_topic(OTHER_POST)
assert [e["kind"] for e in p2["entries"]] == ["post"] and p2["entries"][0]["text"].endswith("跌到 40 我会买 SOXL。")
assert fe.parse_topic("# 普通文章\n正文") is None
print("PASS parser: target utterances, nesting, own words only, title-only and missing bodies")


# ---- Telegram zip -> private textpack + public index
class R:
    def __init__(self, code=200, payload=None, content=b""):
        self.status_code, self._p, self.content = code, payload, content

    def json(self):
        return self._p


buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("cfzh_topics/20261105_1000_a.md", TOPIC)
    z.writestr("cfzh_topics/20261020_2000_b.md", OTHER_POST)
ZIP = buf.getvalue()
store = {}


class Http:
    def get(self, url, params=None, headers=None, timeout=None):
        if url.endswith("/getFile"):
            return R(payload={"result": {"file_path": "docs/x.zip"}})
        if url.endswith("docs/x.zip"):
            return R(content=ZIP)
        path = url.split("/contents/", 1)[1]
        return R(200, {"content": base64.b64encode(store[path].encode()).decode()}) if path in store else R(404)

    def put(self, url, headers=None, timeout=None, json=None):
        assert url.startswith("https://api.github.com/repos/o/textpack/contents/s2_v5_textpack/F_owner_forum/cfzh_")
        path = url.split("/contents/", 1)[1]
        if path in store:
            return R(422)
        store[path] = base64.b64decode(json["content"]).decode()
        return R(201)


said = []
msg = {"date": int(datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc).timestamp()),
       "document": {"file_id": "f", "file_name": "cfzh_topics.zip", "file_size": len(ZIP)}}
out = fw.handle(msg, said.append, "https://tg", "https://tgf", http=Http())
assert out["forum_zip"]["new"] == 4 and out["topics"] == 2, out
assert "新收录 4 条" in said[-1] and "正文未导出 1 条" in said[-1], said
rows = [json.loads(x) for x in fe.index_path().read_text(encoding="utf-8").splitlines()]
assert len(rows) == 4 and all(r["textpack"] == "stored" and len(r["excerpt"]) <= 360 for r in rows)
assert all("text" not in r for r in rows) and len(store) == 2
said.clear()
out = fw.handle(msg, said.append, "https://tg", "https://tgf", http=Http())
assert out["forum_zip"]["new"] == 0 and out["forum_zip"]["duplicate"] == 4, out
print("PASS bot: zip of topics stored privately, index without full text, re-send is a duplicate")

# ---- research-close: index -> feed (forum records with conversation; 7-day rule)
existing = rf.normalize("forum", "作者A", {"title": "旧", "text": "", "url": "https://bbs.wenxuecity.com/cfzh/1001.html",
                                            "date": "2026-11-05 07:30:00"})
rf.FEED_PATH.write_text(json.dumps({"version": 1, "records": [existing]}, ensure_ascii=False), encoding="utf-8")
rep = off.run(http=Http(), now=datetime(2026, 11, 10, 22, 0, tzinfo=timezone.utc))
assert rep["already_in_feed"] == 1 and rep["appended"] == 3 and rep["timely"] == 2 and rep["backfill"] == 1, rep
feed = {r["url"]: r for r in json.loads(rf.FEED_PATH.read_text(encoding="utf-8"))["records"]}
r3 = feed["https://bbs.wenxuecity.com/cfzh/1003.html"]
assert r3["source_kind"] == "forum" and r3["author"] == "作者A" and r3["forum_entry_kind"] == "reply"
assert r3["thread_context"]["in_reply_to"]["author"] == "路人乙" and r3["capture_mode"] == "owner_forum_export_timely"
assert r3["intake_class_hint"] == "live_candidate" and r3["intake_provenance"] == "owner_forum_export"
r4 = feed["https://bbs.wenxuecity.com/cfzh/1004.html"]
assert r4["body_status"] == "body_missing" and r4["attribution_fallback"] == "owner_export_title_only"
old = feed["https://bbs.wenxuecity.com/cfzh/2000.html"]
assert old["capture_mode"] == "owner_forum_export_backfill" and old["forward_evidence_eligible"] is False
assert feed["https://bbs.wenxuecity.com/cfzh/1001.html"]["title"] == "旧"   # existing record never rewritten
assert off.run(http=Http())["appended"] == 0
print("PASS feed: forum records with thread context; >7 days = backfill; existing records untouched; idempotent")

# ---- without the textpack token nothing full-text is stored and the feed step waits
os.environ.pop("TEXTPACK_TOKEN")
assert fe._store("s2_v5_textpack/F_owner_forum/x.md", TOPIC, Http()).startswith("unavailable")
print("PASS no token: full text not stored anywhere")

# ---- structured export (index/posts.jsonl): same entries, same dedupe as the .md export
os.environ["TEXTPACK_TOKEN"] = "t"
P = [
    {"post_id": "1000", "topic_id": "1000", "parent_id": None, "depth": 0, "author": "路人甲", "time": "2026-11-05T07:21",
     "title": "今天大盘怎么看", "bytes": 0, "body": "", "url": "https://bbs.wenxuecity.com/cfzh/1000.html", "source": "cfzh",
     "is_target": False, "body_status": "title_only"},
    {"post_id": "1001", "topic_id": "1000", "parent_id": "1000", "depth": 1, "author": "作者A", "time": "2026-11-05T07:30",
     "title": "我今天加仓了 NVDA", "bytes": 0, "body": "", "url": "https://bbs.wenxuecity.com/cfzh/1001.html",
     "source": "cfzh", "is_target": True, "body_status": "title_only"},
    {"post_id": "1006", "topic_id": "1000", "parent_id": "1001", "depth": 2, "author": "作者A", "time": "2026-11-05T09:00",
     "title": "补充", "bytes": 60, "body": "回答:\n问\n由\n路人乙\n于\n2026-11-05 08:59:00\n第二档 150 也挂了", "source": "cfzh",
     "url": "https://bbs.wenxuecity.com/cfzh/1006.html", "is_target": True, "body_status": "ok"},
    {"post_id": "blog-1", "topic_id": None, "depth": 0, "author": "blog 1", "source": "blog_1", "title": "测试",
     "body": "太短", "url": "https://blog.wenxuecity.com/myblog/1/202611/1.html", "time": "2026-11-09T08:00:00",
     "is_target": True, "body_status": "ok"},
]
mds, other = fe.topics_from_index("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in P))
assert len(mds) == 1 and len(other) == 1
E2 = {e["post_id"]: e for e in fe.parse_topic(mds[0])["entries"]}
assert set(E2) == {"1001", "1006"} and E2["1006"]["text"] == "补充\n第二档 150 也挂了" and E2["1006"]["parent"]["post_id"] == "1001"
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("index/posts.jsonl", "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in P))
    z.writestr("index/topics.jsonl", "{}\n")
    z.writestr("index/manifest.json", "{}")
ZIP = buf.getvalue()
said.clear()
out = fw.handle(msg, said.append, "https://tg", "https://tgf", http=Http())
assert out["forum_zip"]["new"] == 1 and out["forum_zip"]["duplicate"] == 1, out   # 1001 came in with the .md export
assert "博客文章 1 篇：新收录 0" in said[-1], said
print("PASS structured export: rebuilt into topics, deduped by post_id with the .md export, short blog text refused")
