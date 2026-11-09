"""S2 v5 sample: reproducible, disjoint, owner subset inside test, no full text in the public files."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import s2_v5_sample as s  # noqa: E402

assert s.main(["--check"]) == 0
test = [json.loads(x) for x in s.OUT["test"].read_text(encoding="utf-8").splitlines()]
dev = [json.loads(x) for x in s.OUT["dev"].read_text(encoding="utf-8").splitlines()]
assert not {x["item_id"] for x in test} & {x["item_id"] for x in dev}
assert not {u for x in test for u in [x["url"]]} & {x["url"] for x in dev}
owner = [x for x in test if x["owner_subset"]]
assert len(owner) == 30 and sum(x["source"] == "C" for x in owner) == 15 and sum(x["source"] == "A" for x in owner) == 15
allowed = {"has_ticker", "source", "owner_subset", "title_sha256", "record_ids", "published_at", "author",
           "owner_forward_item_id", "url", "item_id", "text_sha256", "chars"}
assert all(set(x) <= allowed for x in test + dev), "only ids, links, hashes and counts are public"
a = [x for x in test if x["source"] == "A"]
assert max(sum(y["author"] == x["author"] for y in a) for x in a) <= int(s.A_TEST * s.AUTHOR_CAP)
print(f"PASS s2 v5 sample: test {len(test)} / dev {len(dev)}, owner 30, disjoint, ids and hashes only")
