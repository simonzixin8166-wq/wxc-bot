import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gold_context as g
text = "开场白没有内容。我在 29、30、31 加了 IREN。今天天气不错。准备止盈一部分。"
locs, total = g.locators(text)
assert total == 2 and locs[0]["symbols"] == ["IREN"] and len(locs[0]["locator"]) <= 40
assert locs[1]["symbols"] == [] and locs[1]["stance_cue"]
assert all(len(x["sha256"]) == 64 for x in locs)
recs = [{"source_kind": "forum", "url": f"u{i}", "content_chars": 500, "author": "bogbog"} for i in range(20)]
assert len(g.pick(recs, {"u0"}, {"bogbog": 5})) == 5 and all(r["url"] != "u0" for r in g.pick(recs, {"u0"}, {"bogbog": 5}))
print("PASS gold context")
