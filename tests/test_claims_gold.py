"""Gold corpus integrity + evaluator (quant-dashboard#133 6106703460 phase 1)."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import eval_claims_gold as ev
items = [json.loads(x) for x in (ROOT / "research/gold/claims_gold_v0.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
assert len({i["item_id"] for i in items}) == len(items)
assert {i["split"] for i in items} == {"dev", "test"}
for i in items:
    assert len(i["text_sha256"]) == 64 and "text" not in i  # gold stores hashes + labels, never source text
    for l in i["labels"]:
        assert l["stance"] in ev.COARSE and l["holder"] == "author"
r = ev.evaluate([{"item_id": "x", "split": "dev", "labels": [{"symbol": "VGT", "stance": "hold"}]}], {"x": "没有减仓，VGT 继续持有。"})
assert r["dev"]["tp"] == 1
print("PASS claims gold")
