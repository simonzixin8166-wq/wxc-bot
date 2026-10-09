import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_fulltext_claims as p
recs = [{"author": "yifan99", "url": f"https://bbs.wenxuecity.com/cfzh/{i}.html", "content_chars": 900, "source_kind": "forum"} for i in range(20)]
recs += [{"author": "yifan99", "url": "short", "content_chars": 100, "source_kind": "forum"}]
picked = p.pick(recs, {"yifan99": 8})
assert len(picked) == 8 and all(r["url"] != "short" for r in picked)
assert [r["url"] for r in picked] == [r["url"] for r in p.pick(recs, {"yifan99": 8})]
s = p.summarize([{"symbol": "VGT", "stance": "hold", "question": False}], [])
assert s["checkable_full"] == 1 and s["claims_excerpt"] == 0 and s["symbols_full"] == ["VGT"]
src = Path(p.__file__).read_text(encoding="utf-8")
assert '"text":' not in src  # report never carries body text
print("PASS pilot_fulltext_claims")
