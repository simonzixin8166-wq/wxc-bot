"""Owner blind test 2026-10-17 + guideline v1.2 adjudication: integrity, frozen gold untouched, honest κ."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gold_blind import blind_id, kappa  # noqa: E402

GD = ROOT / "research" / "gold"
gold = [json.loads(l) for f in ("claims_gold_test_v2.jsonl", "claims_gold_test_v3.jsonl")
        for l in (GD / f).read_text(encoding="utf-8").splitlines() if l.strip()]
ids = {blind_id(g["item_id"]) for g in gold}
rep = json.loads((GD / "blind_owner_2026-10-17.json").read_text(encoding="utf-8"))
adj = [json.loads(l) for l in (GD / "claims_gold_test_v2v3_owner_v1.2_adjudication.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

# every blind item belongs to the frozen tests; nothing invented
assert len(rep["labels_round2"]) == 69 and {a["blind_id"] for a in rep["labels_round2"]} <= ids
assert len(adj) == 69 and len({r["blind_id"] for r in adj}) == 69 and {r["blind_id"] for r in adj} <= ids
# κ in the report is recomputed from the stored raw labels (no hand-entered numbers)
assert rep["round2"]["kappa"] == kappa(gold, rep["labels_round2"])
assert rep["round1"]["kappa"] == kappa(gold, rep["labels_round1"]) and rep["round1"]["status"] == "INVALID"
assert rep["learning_status"] == "UNPROVEN"
# adjudication shape: claims carry holder + ticker_source; non-claims carry no labels; never used for agreement
ok = {"claim", "none", "ambiguous", "needs_article_check"}
for r in adj:
    assert r["decision"] in ok and r["guideline"] == "v1.2" and r["reason"]
    if r["decision"] == "claim":
        assert r["labels"] and all(l["holder"] in ("author", "author_system") and l["ticker_source"] in ("sentence", "context") for l in r["labels"])
    else:
        assert r["labels"] == []
assert "never used to compute agreement" in rep["adjudication"]["note"]
print("PASS owner blind 2026-10-17 + v1.2 adjudication")
