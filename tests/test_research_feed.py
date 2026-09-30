from pathlib import Path
import tempfile
import research_feed as rf

assert "INTC" in rf.detect_themes("Intel INTC thesis")
assert "Sell Put" in rf.detect_themes("sell put on QQQ")
assert "失败复盘" in rf.detect_themes("这次看错了，割肉复盘")

row = rf.normalize("forum", "yifan99", {
    "title": "INTC sell put 复盘",
    "text": "作者讨论风险和失败复盘",
    "url": "https://bbs.wenxuecity.com/cfzh/123.html#comment_1",
    "date": "2026-09-30 12:00:00",
    "images": [],
})
assert row["author"] == "yifan99"
assert row["url"].endswith("/123.html")
assert "INTC" in row["themes_hint"]
assert row["source_notice"].startswith("作者原始观点")

with tempfile.TemporaryDirectory() as td:
    old = rf.FEED_PATH
    rf.FEED_PATH = Path(td) / "research_feed.json"
    try:
        assert rf.append_records([row]) == 1
        assert rf.append_records([row]) == 0
    finally:
        rf.FEED_PATH = old

print("PASS source intelligence research feed")
