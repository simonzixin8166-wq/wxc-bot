"""Owner forwards -> research feed: local mocks only, no network."""
import base64
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

td = tempfile.mkdtemp()
os.environ["DATA_DIR"] = td
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research_feed as rf  # noqa: E402
import owner_forward_feed as off  # noqa: E402

rf.FEED_PATH = Path(td) / "research_feed.json"
BODY = "今天收盘前加仓 NVDA 一笔，理由是数据中心订单没有变化。" * 30
NOW = datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc)


def idx_row(i, url, pub, got, status="stored"):
    return {"item_id": f"C-{i:012d}", "source_url": url, "title": f"标题{i}", "chars": len(BODY), "sha256": f"{i:064d}",
            "published_at": pub, "retrieved_at": got, "textpack": status, "excerpt": BODY[:360]}


rows = [
    idx_row(1, "https://blog.wenxuecity.com/myblog/82458/202611/1.html", "2026-11-05 17:20:37", "2026-11-06T03:39:43+00:00"),
    idx_row(2, "https://blog.wenxuecity.com/myblog/82458/202608/2.html", "2026-08-18 09:00:00", "2026-11-09T05:00:00+00:00"),
    idx_row(3, "https://blog.wenxuecity.com/myblog/82458/202611/3.html", "2026-11-01 08:00:00", "2026-11-07T20:00:00+00:00"),
    idx_row(4, "https://blog.wenxuecity.com/myblog/82458/202610/4.html", "2026-10-20 08:00:00", "2026-11-09T05:00:00+00:00"),
    idx_row(5, "https://example.com/a", None, "2026-11-09T05:00:00+00:00"),
    idx_row(6, "https://blog.wenxuecity.com/myblog/82458/202611/6.html", "2026-11-08 08:00:00", "2026-11-09T05:00:00+00:00",
            status="unavailable (TEXTPACK_TOKEN / TEXTPACK_REPO not set; full text not stored)"),
    idx_row(7, "https://blog.wenxuecity.com/myblog/82458/202611/7.html", "2026-11-08 08:00:00", "2026-11-09T05:00:00+00:00"),
]
(Path(td) / "owner_forward_index.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

# item 4's link is already in the feed (blog collector) with its own first-capture time: must not be rewritten
existing = rf.normalize("blog", "BrightLine", {"title": "旧", "text": "旧正文", "url": rows[3]["source_url"], "date": "2026-10-20"})
existing["captured_at"] = "2026-10-20T20:00:00Z"
rf.FEED_PATH.write_text(json.dumps({"version": 1, "records": [existing]}, ensure_ascii=False), encoding="utf-8")


class Resp:
    def __init__(self, status, content=None):
        self.status_code, self._c = status, content

    def json(self):
        return {"content": base64.b64encode(self._c.encode("utf-8")).decode()}


class Http:
    def __init__(self):
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        assert url.startswith("https://api.github.com/repos/o/textpack/contents/s2_v5_textpack/C_owner_forward/")
        if url.endswith("C-000000000007.txt"):
            return Resp(404)
        return Resp(200, BODY)


os.environ.update(TEXTPACK_TOKEN="tok", TEXTPACK_REPO="o/textpack")
h = Http()
rep = off.run(http=h, now=NOW)
assert rep == {"pending": 6, "appended": 4, "timely": 2, "backfill": 2, "already_in_feed": 1, "text_unavailable": 1}, rep
feed = json.loads(rf.FEED_PATH.read_text(encoding="utf-8"))
recs = {r.get("owner_forward_item_id"): r for r in feed["records"]}

# 1: forwarded ~10 h after publication -> live candidate; 3: 6.5 days -> still timely (Owner: one week)
for i in ("C-000000000001", "C-000000000003"):
    assert recs[i]["intake_class_hint"] == "live_candidate" and recs[i]["capture_mode"] == "owner_forward_timely"
    assert recs[i].get("forward_evidence_eligible") is not False and recs[i]["publication_lag_hours"] <= 168
# 2: published in August, forwarded in November -> backfill, never forward evidence; 5: no publication date -> backfill
for i in ("C-000000000002", "C-000000000005"):
    assert recs[i]["intake_class_hint"] == "backfill" and recs[i]["forward_evidence_eligible"] is False
assert recs["C-000000000001"]["author"] == "BrightLine" and recs["C-000000000001"]["source_kind"] == "blog"
assert recs["C-000000000005"]["source_kind"] == "owner_forward" and recs["C-000000000005"]["author"] == "owner_forward_unattributed"
print("PASS timeliness: <=7 days live candidate, later or unknown = backfill")

# full text never in the feed: only the bounded excerpt plus structured fields
raw = rf.FEED_PATH.read_text(encoding="utf-8")
assert BODY not in raw and all(len(r.get("excerpt") or "") <= 360 for r in feed["records"])
assert recs["C-000000000001"]["content_chars"] == len(BODY)
print("PASS full text read at runtime only, feed keeps the excerpt")

# existing record for the same link untouched (first capture kept, not duplicated)
same = [r for r in feed["records"] if r.get("url") == rf._canonical(rows[3]["source_url"])]
assert len(same) == 1 and same[0]["captured_at"] == "2026-10-20T20:00:00Z" and same[0]["title"] == "旧"
print("PASS existing feed record not rewritten")

# not-stored item never fetched; unreadable item retried next run (not marked done)
assert not any("C-000000000006" in u for u in h.urls)
st = json.loads((Path(td) / off.STATE).read_text(encoding="utf-8"))
assert "C-000000000007" not in st["done"] and "C-000000000006" not in st["done"]
h2 = Http()
rep2 = off.run(http=h2, now=NOW)
assert rep2["appended"] == 0 and rep2["pending"] == 1 and [u.rsplit("/", 1)[1] for u in h2.urls] == ["C-000000000007.txt"]
print("PASS idempotent; unreadable text retried, not-stored never fetched")

# no token -> nothing appended, nothing marked done
os.environ.pop("TEXTPACK_TOKEN")
rep3 = off.run(http=Http(), now=NOW)
assert rep3["appended"] == 0 and rep3["text_unavailable"] == 1
print("PASS no token: nothing appended")
print("PASS owner forward feed")
