"""Claims gold v4.1 (spec v0.3): reproducible with the unchanged v4 sampler; no prior use; threads disjoint."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_gold_v4 as bg  # noqa: E402
import s2_v41_sample as s  # noqa: E402

G = ROOT / "research" / "gold"
summ = json.loads((G / "claims_gold_v4.1_sample.json").read_text(encoding="utf-8"))
test = [json.loads(x) for x in (G / "claims_gold_test_v4.1.unlabeled.jsonl").read_text(encoding="utf-8").splitlines() if x]
dev = [json.loads(x) for x in (G / "claims_gold_dev_v4.1.unlabeled.jsonl").read_text(encoding="utf-8").splitlines() if x]
pack = json.loads((G / "blind_test_v4.1_textpack.json").read_text(encoding="utf-8"))
key = json.loads((G / "blind_test_v4.1_key.json").read_text(encoding="utf-8"))

# the v4 sampler is unchanged and only SEED / WINDOW differ
assert summ["v4_sampler_sha256"] == s.V4_SAMPLER_SHA256 and bg.SEED == "20261030" and bg.WINDOW == ("2026-10-12", "2026-10-31")
assert summ["seed"] == s.SEED == "20261105" and tuple(summ["window"]) == s.WINDOW
# the committed files are exactly what the procedure produces from the committed feed
assert s.main(["--check"]) == 0
# no post and no thread on both sides; labels empty; guideline v1.3
assert not ({i["record_id"] for i in test} & {i["record_id"] for i in dev})
assert not ({i["thread_id"] for i in test} & {i["thread_id"] for i in dev}) and summ["thread_overlap_after_rule"] == 0
assert all(i["labels"] is None and i["guideline"] == "v1.3" and i["origin"] == "v4.1" for i in test + dev)
# no prior use: every sampled URL is absent from every earlier gold / eval / pilot file
for f in s.PRIOR:
    t = Path(f).read_text(encoding="utf-8", errors="replace") if Path(f).exists() else ""
    hit = [i["url"] for i in test + dev if i["url"] in t or i["record_id"] in t]
    assert not hit, (Path(f).name, hit[:2])
# textpack: 120 GPT items from test, 20 Owner items among them, blind ids only, no labels or extractor output
assert len(pack["items"]) == s.GPT_N == key["gpt_items"] and key["owner_items"] == s.OWNER_N
test_ids = {i["item_id"] for i in test}
assert all(k["item_id"] in test_ids for k in key["key"])
assert all(set(it) == {"blind_id", "kind", "source_kind", "author", "url", "published_at", "is_reply", "title", "target_text",
                       "thread_context"} for it in pack["items"])
assert all(len(it["target_text"]) <= 360 or it["kind"] == "title" for it in pack["items"])
print(f"PASS v4.1 sample: test {summ['test']['items']} items / {summ['test_threads']} threads, dev {summ['dev']['items']} / "
      f"{summ['dev_threads']}; unchanged v4 sampler; no prior use; textpack 120 (Owner 20)")
