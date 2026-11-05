"""S2 v4.1 manifest invariants (design v0.2 §9.2/§9.3/§9.5): the frozen selection stays clean as the feed grows."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import s2_v41_manifest as m  # noqa: E402

G = ROOT / "research" / "gold" / "v4.1"
man = json.loads((G / "candidate_manifest.json").read_text(encoding="utf-8"))
plan = json.loads((G / "sampling_plan.json").read_text(encoding="utf-8"))
sel = json.loads((G / "selection.json").read_text(encoding="utf-8"))
assert plan == m.PLAN and plan["frozen_before_draw"] and sel["seed"] == plan["seed"]

# the October records the manifest was built from are unchanged (the feed is append-only; October is closed)
recs = json.loads(m.FEED.read_text(encoding="utf-8"))["records"]
wx = [r for r in recs if r.get("source") == "wenxuecity"]
assert m.october_hash(wx) == man["october_records_sha256"], "October records changed after the freeze"

cand = {c["id"]: c for c in man["candidates"]}
test, nat, dev = set(sel["test_ids"]), set(sel["test_natural_traffic_ids"]), set(sel["dev_ids"])
assert len(test) == plan["sizes"]["test_stratified"] and len(nat) == plan["sizes"]["test_natural_traffic"] and len(dev) == plan["sizes"]["dev"]
assert not (test & nat) and not (test & dev) and not (nat & dev) and (test | nat | dev) <= set(cand)
th = lambda ids: {cand[i]["thread_id"] for i in ids}
assert not (th(test | nat) & th(dev)), "a thread spans dev and test"
assert all(v == "OK" for v in sel["test_category_status"].values()), sel["test_category_status"]
assert max(sel["test_authors"].values()) <= plan["author_cap_share_of_test"] * plan["sizes"]["test_stratified"]

# none of the selected posts appears in any gold / evaluation / pilot file that existed at the freeze
byid = {r["id"]: r for r in wx}
for name in man["prior_use_files_checked"]:
    p = next((f for f in m.PRIOR_FILES if Path(f).name == name), None)
    if not p or not Path(p).exists():
        continue
    t = Path(p).read_text(encoding="utf-8", errors="replace")
    hit = [i for i in test | nat | dev if i in t or (byid[i].get("url") and byid[i]["url"] in t)]
    assert not hit, (name, hit[:3])

# no third-party text is stored in the manifest or selection: hashes and observable flags only
blob = json.dumps(man, ensure_ascii=False) + json.dumps(sel, ensure_ascii=False)
for i in list(test)[:50]:
    r = byid[i]
    if r.get("title") and len(r["title"]) >= 6:
        assert r["title"] not in blob, "title text copied into the manifest"
assert all(set(c) >= {"content_sha256", "context_sha256", "thread_id"} for c in man["candidates"])
print(f"PASS s2 v4.1 manifest: {man['eligible']} eligible (excluded {man['excluded']}); test {len(test)} + natural {len(nat)}, "
      f"dev {len(dev)}; {sel['test_threads']} test / {sel['dev_threads']} dev threads disjoint; categories OK; no prior use; no text stored")
