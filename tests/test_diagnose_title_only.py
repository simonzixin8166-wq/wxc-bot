import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnose_title_only as d

assert d.classify(404, None, "a") == "http_error"
assert d.classify(200, None, "a") == "selector_miss"
assert d.classify(200, {"author": "B", "text_chars": 0, "images": 0}, "a") == "author_mismatch"
assert d.classify(200, {"author": "A", "text_chars": 120, "images": 0}, "a") == "body_now_present"
assert d.classify(200, {"author": "A", "text_chars": 0, "images": 2}, "a") == "image_only"
assert d.classify(200, {"author": "A", "text_chars": 0, "images": 0}, "a") == "genuinely_empty"
recs = [{"author": "x", "url": f"u{i}", "excerpt": "", "content_chars": 0, "published_at": str(i)} for i in range(30)]
recs += [{"author": "x", "url": "full", "excerpt": "body", "content_chars": 4}]
picks, totals = d.sample(recs, 10)
assert totals == {"x": 30} and len(picks["x"]) == 10 and all(r["url"] != "full" for r in picks["x"])
assert [r["url"] for r in d.sample(recs, 10)[0]["x"]] == [r["url"] for r in picks["x"]]  # deterministic
# report never stores body text
src = Path(d.__file__).read_text(encoding="utf-8")
assert '"text":' not in src.split("def main")[1]
print("PASS diagnose_title_only")
