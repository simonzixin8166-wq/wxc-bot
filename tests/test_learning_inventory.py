import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import learning_inventory as li
rep = li.build()
assert rep["records"] == len(rep["rows"]) > 0
assert all("excerpt" not in r and "title" not in r for r in rep["rows"])  # counts + ids only
assert rep["article_overlap"]["overlap_v1_v2"] == 0
t2 = {json.loads(x)["url"] for x in (ROOT / "research/gold/claims_gold_test_v2.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()}
assert not any(r["available_for_new_test"] and "test_v2" in r["used_in"] for r in rep["rows"])
print("PASS learning inventory")
