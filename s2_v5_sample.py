#!/usr/bin/env python3
"""S2 test set v5 sample (spec v5 v0.2, Owner 2026-11-09). Unit: the whole post, read in full by every labeler.

Sources (spec §2):
  A  Wenxuecity forum ROOT posts whose whole text is in the feed (title, plus body <= 360 chars).
  C  Owner-forwarded long articles (state/owner_forward_index.jsonl, full text in the private textpack).
  B  YouTube transcripts: phase 2. Not in this freeze, because the transcripts still have to be packed in Actions.
Split (seed 20261109, deterministic, by post; a post never appears in both sets):
  C  test 40 / dev = the rest. Stratified: posts with a ticker first, in seeded order.
  A  test 60 / dev 60. 2/3 with a ticker; no author above 25% of the A test items.
  Owner subset: 15 C + 15 A from the test set (spec §4, changed 11/9: C is now the long-text core, B is not ready).
Prior use: posts already used in any earlier gold, eval or pilot file are excluded (same scan as v4.1).
Output: ids, links, hashes and counts only. No full text is written to this public repo.

  python s2_v5_sample.py            # writes research/gold/claims_gold_v5_*.json(l)
  python s2_v5_sample.py --check    # recomputes and compares byte for byte
"""
from __future__ import annotations

import glob
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GOLD = ROOT / "research" / "gold"
FEED = ROOT / "state" / "research_feed.json"
INDEX = ROOT / "state" / "owner_forward_index.jsonl"
SEED = "20261109"
# Frozen inputs: only feed records and forwards that existed when the sample was drawn.
CUTOFF = "2026-11-09T07:00:00Z"
C_TEST, A_TEST, A_DEV, OWNER_C, OWNER_A, AUTHOR_CAP = 40, 60, 60, 15, 15, 0.25
PRIOR_STATE = ["author_claims_hp.json", "claims_gold_eval.json", "eval_claims_gold_test_v2.json",
               "eval_claims_gold_test_v3_ce.json", "eval_claims_gold_test_v3_hp.json", "eval_claims_gold_v1_ce_dev.json",
               "eval_claims_gold_v1_hp_dev.json", "fulltext_claims_pilot.json", "fulltext_claims_pilot_round2.json",
               "fulltext_claims_review_round2.json", "gold_context_test_v2.json", "gold_context_v1.json",
               "title_only_diagnosis.json", "title_only_diagnosis_round2.json", "title_claims_scan.json"]
OUT = {"sample": GOLD / "claims_gold_v5_sample.json", "test": GOLD / "claims_gold_test_v5.unlabeled.jsonl",
       "dev": GOLD / "claims_gold_dev_v5.unlabeled.jsonl"}


def h(s: str) -> str:
    return hashlib.sha256(f"{SEED}|{s}".encode("utf-8")).hexdigest()


def canon(u: str) -> str:
    return re.sub(r"[#?].*$", "", (u or "").strip())


FROZEN_PRIOR = GOLD / "claims_gold_v5_prior_use.json"


def prior_use(byid: set) -> tuple[set, set]:
    """Frozen at draw time (rolling state files such as author_claims_hp.json are rewritten daily)."""
    if FROZEN_PRIOR.exists():
        fz = json.loads(FROZEN_PRIOR.read_text(encoding="utf-8"))
        return set(fz["used_ids"]) & byid, set(fz["used_urls"])
    return scan_prior_use(byid)


def scan_prior_use(byid: set) -> tuple[set, set]:
    files = [f for f in sorted(glob.glob(str(GOLD / "*"))) if Path(f).is_file() and "v5" not in Path(f).name]
    files += [str(ROOT / "state" / f) for f in PRIOR_STATE]
    ids, urls = set(), set()
    for f in files:
        try:
            t = Path(f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        urls |= {canon(u.rstrip(",")) for u in re.findall(r"https?://[^\s\"'\\]*wenxuecity[^\s\"'\\]*", t)}
        ids |= {i for i in re.findall(r"\b[0-9a-f]{20}\b", t) if i in byid}
    return ids, urls


def has_ticker(r: dict | None) -> bool:
    return bool(r and (r.get("symbols") or r.get("claims")))


def run() -> dict:
    feed = [r for r in json.loads(FEED.read_text(encoding="utf-8"))["records"] if str(r.get("captured_at") or "") <= CUTOFF]
    byid = {r["id"] for r in feed}
    used_ids, used_urls = prior_use(byid)
    by_url = {}
    for r in feed:
        by_url.setdefault(canon(r.get("url") or ""), []).append(r)

    # C: owner forwards, stored, indexed before the cutoff
    cpool, why = [], Counter()
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        x = json.loads(line)
        if x.get("textpack") != "stored" or str(x.get("indexed_at") or "") > CUTOFF.replace("Z", "+00:00"):
            why["c_not_stored_or_late"] += 1
            continue
        recs = by_url.get(canon(x["source_url"]), [])
        cpool.append({"source": "C", "item_id": "v5-" + x["item_id"].lower(), "owner_forward_item_id": x["item_id"],
                      "url": canon(x["source_url"]), "title_sha256": hashlib.sha256((x.get("title") or "").encode()).hexdigest(),
                      "text_sha256": x["sha256"], "chars": x["chars"], "published_at": x.get("published_at"),
                      "record_ids": sorted(r["id"] for r in recs), "author": recs[0]["author"] if recs else None,
                      "has_ticker": any(has_ticker(r) for r in recs)})
    # A: forum root posts with the whole text in the feed
    apool = []
    for r in feed:
        if r.get("source") != "wenxuecity" or r.get("source_kind") != "forum":
            continue
        if (r.get("thread_context") or {}).get("is_reply") or r.get("parent_post_id"):
            continue
        if int(r.get("content_chars") or 0) > 360:
            continue
        if r["id"] in used_ids or canon(r.get("url") or "") in used_urls:
            why["a_prior_use"] += 1
            continue
        text = f"{(r.get('title') or '').strip()}\n{(r.get('excerpt') or '').strip()}".strip()
        apool.append({"source": "A", "item_id": "v5-a-" + hashlib.sha256(r["id"].encode()).hexdigest()[:16],
                      "record_ids": [r["id"]], "url": canon(r.get("url") or ""), "author": r.get("author"),
                      "published_at": r.get("published_at"), "chars": len(text),
                      "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "has_ticker": has_ticker(r)})

    def order(rows):
        return sorted(rows, key=lambda x: (not x["has_ticker"], h(x["item_id"])))

    c_sorted = order(cpool)
    c_tick = [x for x in c_sorted if x["has_ticker"]]
    c_none = [x for x in c_sorted if not x["has_ticker"]]
    n_tick = min(len(c_tick), round(C_TEST * 0.6))
    c_test = c_tick[:n_tick] + c_none[:C_TEST - n_tick]
    c_dev = [x for x in c_sorted if x not in c_test]

    def take_a(rows, n, exclude):
        out, per = [], Counter()
        cap = int(n * AUTHOR_CAP)
        tick_target = round(n * 2 / 3)
        for want_tick in (True, False):
            for x in sorted(rows, key=lambda x: h(x["item_id"])):
                if len(out) >= (tick_target if want_tick else n):
                    break
                if x["has_ticker"] != want_tick or x["item_id"] in exclude or per[x["author"]] >= cap:
                    continue
                out.append(x)
                per[x["author"]] += 1
        for x in sorted(rows, key=lambda x: h(x["item_id"])):  # top up if a stratum ran short
            if len(out) >= n:
                break
            if x["item_id"] not in exclude and x not in out and per[x["author"]] < cap:
                out.append(x)
                per[x["author"]] += 1
        return out

    a_test = take_a(apool, A_TEST, set())
    a_dev = take_a(apool, A_DEV, {x["item_id"] for x in a_test})
    test, dev = c_test + a_test, c_dev + a_dev
    owner = sorted([x["item_id"] for x in sorted(c_test, key=lambda x: h("owner" + x["item_id"]))[:OWNER_C]] +
                   [x["item_id"] for x in sorted(a_test, key=lambda x: h("owner" + x["item_id"]))[:OWNER_A]])
    for x in test:
        x["owner_subset"] = x["item_id"] in owner

    def stats(rows):
        return {"posts": len(rows), "by_source": dict(Counter(x["source"] for x in rows)),
                "with_ticker": sum(x["has_ticker"] for x in rows), "by_author": dict(Counter(x["author"] for x in rows)),
                "chars_median": sorted(x["chars"] for x in rows)[len(rows) // 2] if rows else 0}
    assert not {x["item_id"] for x in test} & {x["item_id"] for x in dev}
    summary = {"spec": "s2 test set v5 v0.2", "seed": SEED, "cutoff": CUTOFF, "guideline": "v1.3",
               "pool": {"C": len(cpool), "A": len(apool)}, "prefilter": dict(why),
               "test": stats(test), "dev": stats(dev), "owner_subset": {"posts": len(owner), "C": OWNER_C, "A": OWNER_A},
               "note_a": "A target 60 per set; the 25% author cap allows at most 15 per author, and only authors with enough "
                         "unused root posts fill it, so A is smaller when few authors qualify",
               "phase_2": "B (YouTube transcripts, ~22 valid) is added after its transcripts are packed in Actions",
               "no_full_text_here": True}
    return {"summary": summary, "test": test, "dev": dev}


def render(res: dict) -> dict:
    return {"sample": json.dumps(res["summary"], ensure_ascii=False, indent=1) + "\n",
            "test": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in res["test"]),
            "dev": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in res["dev"])}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    out = render(run())
    if "--freeze-prior" in argv:
        feed = json.loads(FEED.read_text(encoding="utf-8"))["records"]
        ids, urls = scan_prior_use({r["id"] for r in feed})
        FROZEN_PRIOR.write_text(json.dumps({"note": "prior-use set frozen when the v5 sample was drawn (2026-11-09)",
                                            "used_ids": sorted(ids), "used_urls": sorted(urls)}, ensure_ascii=False,
                                           indent=0) + "\n", encoding="utf-8")
        print(len(ids), len(urls))
        return 0
    if "--check" in argv:
        bad = [OUT[k].name for k in OUT if not OUT[k].exists() or OUT[k].read_text(encoding="utf-8") != out[k]]
        print(json.dumps({"check": "FAIL" if bad else "PASS", "differs": bad}))
        return 1 if bad else 0
    for k, p in OUT.items():
        p.write_text(out[k], encoding="utf-8")
    print(json.dumps(json.loads(out["sample"]), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
