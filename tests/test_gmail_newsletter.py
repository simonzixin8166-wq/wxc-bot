"""Gmail newsletters (Owner 2026-11-22): a newsletter the Owner subscribes to arrives as '<ts>_<id>_newsletter.md'
(mail body + 原文链接 header, built by the Apps Script) and goes through the forwarded-article path: stored privately,
indexed with title/excerpt/link/hash, input gmail_newsletter_md, attributed to the Substack publication.
Invented text only; no network."""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["TEXTPACK_TOKEN"], os.environ["TEXTPACK_REPO"] = "t", "o/r"
import owner_forward as of  # noqa: E402
import owner_forward_feed as off  # noqa: E402

MD = """# 2027 展望 测试第 1 篇
- 原文链接：https://zmletter.substack.com/p/2027-test-1
- 发布时间：2026-11-22 04:00
- 发件人：测试作者 from 测试笔记
- 来源：Owner 自己订阅的邮件（Gmail）
---
View this post on the web at https://zmletter.substack.com/p/2027-test-1

""" + "这是一篇虚构的测试文章，用来检查邮件订阅的收录流程。" * 20


class R:
    status_code = 201


class Http:
    def put(self, url, **k):
        return R()


said = []
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
msg = {"date": int(NOW.timestamp()), "caption": "", "_bytes": MD.encode("utf-8"),
       "document": {"file_name": "zmtest_newsletter.md", "file_size": len(MD.encode("utf-8"))}}
row = of.handle(msg, said.append, http=Http(), now=NOW)
assert row and row["input"] == "gmail_newsletter_md" and row["source_url"] == "https://zmletter.substack.com/p/2027-test-1", row
assert row["title"] == "2027 展望 测试第 1 篇" and row["published_at"] == "2026-11-22 04:00" and len(row["excerpt"]) <= 360
idx = [json.loads(x) for x in of.index_path().read_text(encoding="utf-8").splitlines()]
assert idx[-1]["input"] == "gmail_newsletter_md"
# the same mail again is a duplicate (no second copy)
assert of.handle(msg, said.append, http=Http(), now=NOW) is None and len(of.index_path().read_text().splitlines()) == 1
# attribution: the Substack publication becomes the author
assert off.attribute("https://zmletter.substack.com/p/2027-test-1") == ("blog", "zmletter (Substack)")
assert off.attribute("https://example.com/x") == ("owner_forward", "owner_forward_unattributed")
# the inbox strips "<ts>_<msgId>_" before handing the file over: the bare name must still be a newsletter
import gmail_inbox  # noqa: E402
bare = gmail_inbox.PREFIX_RE.sub("", "20261122T040000Z_1a2016c716f30d2f_newsletter.md")
assert bare == "newsletter.md" and of._parse_file(bare, MD, None)[4] == "gmail_newsletter_md"
# a normal .md article keeps its kind
assert of._parse_file("note.md", MD, None)[4] == "md_file"

gs = (ROOT / "tools" / "gmail" / "myalpha_gmail_inbox.gs").read_text(encoding="utf-8")
assert "MyAlpha/Newsletter" in gs and "_newsletter.md" in gs and "原文链接" in gs and "Unsubscribe" in gs
print("PASS gmail newsletter: body -> .md article with link, private store, attributed, deduped")
