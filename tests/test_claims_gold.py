"""Gold corpus v0/v1 integrity, frozen test split, blind export hygiene, evaluator + kappa."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import eval_claims_gold as ev
import gold_blind as gb

for name in ("claims_gold_v0.jsonl", "claims_gold_v1.jsonl"):
    items = [json.loads(x) for x in (ROOT / "research/gold" / name).read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len({i["item_id"] for i in items}) == len(items)
    assert {i["split"] for i in items} == {"dev", "test"}
    for i in items:
        assert len(i["text_sha256"]) == 64 and "text" not in i and len(i.get("locator", "")) <= 40
        for l in i["labels"]:
            assert l["stance"] in ev.COARSE and l["holder"] == "author"
v1 = [json.loads(x) for x in (ROOT / "research/gold/claims_gold_v1.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
fz = json.loads((ROOT / "research/gold/claims_gold_v1.freeze.json").read_text(encoding="utf-8"))
assert ev.freeze(v1)["test_sha256"] == fz["test_sha256"], "frozen test split changed"
# sentences of one article never straddle dev/test
by = {}
for i in v1:
    if i["kind"] == "sentence":
        by.setdefault(i["url"], set()).add(i["split"])
assert all(len(s) == 1 for s in by.values())
# blind request never leaks labels or predictions
req = json.loads((ROOT / "research/gold/blind_v1_request.json").read_text(encoding="utf-8"))
for r in req["requests"]:
    assert not ({"labels", "stance", "claims", "item_id", "split"} & set(r))
r = ev.evaluate([{"item_id": "x", "split": "dev", "labels": [{"symbol": "VGT", "stance": "hold"}]}], {"x": "没有减仓，VGT 继续持有。"})
assert r["dev"]["tp"] == 1
k = gb.kappa(v1, [{"blind_id": gb.blind_id(i["item_id"]), "status": "ok", "labels": i["labels"]} for i in v1[:30] if not i["ambiguous"]])
assert k["kappa"] == 1.0
print("PASS claims gold")

# frozen test v2: fresh, unseen, >= 50 genuine article claims, no overlap with gold v1
t2 = [json.loads(x) for x in (ROOT / "research/gold/claims_gold_test_v2.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
fz2 = json.loads((ROOT / "research/gold/claims_gold_test_v2.freeze.json").read_text(encoding="utf-8"))
assert ev.freeze(t2)["test_sha256"] == fz2["test_sha256"], "frozen test v2 changed"
assert all(i["split"] == "test" and i["kind"] == "sentence" for i in t2)
assert not ({i["text_sha256"] for i in t2} & {i["text_sha256"] for i in v1}), "test v2 overlaps gold v1"
assert not ({i["url"] for i in t2} & {i["url"] for i in v1 if i["kind"] == "sentence"}), "test v2 shares articles with gold v1"
assert sum(len(i["labels"]) for i in t2 if not i["ambiguous"]) >= 50
req2 = json.loads((ROOT / "research/gold/blind_test_v2_request.json").read_text(encoding="utf-8"))
assert all(not ({"labels", "item_id", "split"} & set(r)) for r in req2["requests"])
print("PASS test v2 frozen")
