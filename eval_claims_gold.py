#!/usr/bin/env python3
"""Evaluate claim_extractor against the human gold corpus (quant-dashboard#133 6106703460, phase 1).

Gold items reference stored public text (titles / stored excerpts) by id + sha256; labels are the
author's OWN stance per symbol (quotes/examples are not claims). Coarse direction is compared:
long (buy/add) / reduce (sell/trim) / hold / bullish / bearish / avoid. Reports precision, recall,
abstain rate and error types per split; the test split must not be used to tune rules.
"""
from __future__ import annotations
import argparse, json, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import claim_extractor as ce  # noqa: E402

GOLD = ROOT / "research" / "gold" / "claims_gold_v0.jsonl"
FEED = ROOT / "state" / "research_feed.json"
COARSE = {"buy": "long", "add": "long", "sell": "reduce", "trim": "reduce", "hold": "hold",
          "bullish": "bullish", "bearish": "bearish", "avoid": "avoid"}


def evaluate(items, texts):
    res = {}
    for split in ("dev", "test"):
        tp = fp = fn = 0
        errors = Counter()
        n_items = abstain_ok = 0
        for it in (x for x in items if x["split"] == split):
            n_items += 1
            text = texts.get(it["item_id"], "")
            pred = {(c["symbol"], COARSE.get(c["stance"], c["stance"])) for c in ce.extract_claims(text) if ce.checkable(c)}
            gold = {(l["symbol"], COARSE[l["stance"]]) for l in it["labels"]}
            if not gold and not pred:
                abstain_ok += 1
            tp += len(pred & gold)
            for p in pred - gold:
                fp += 1
                errors["wrong_stance" if any(p[0] == g[0] for g in gold) else "no_claim_in_gold"] += 1
            for g in gold - pred:
                fn += 1
                errors["stance_mismatch" if any(g[0] == p[0] for p in pred) else "missed"] += 1
        res[split] = {"items": n_items, "gold_claims": tp + fn, "pred_claims": tp + fp, "tp": tp, "fp": fp, "fn": fn,
                      "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                      "recall": round(tp / (tp + fn), 3) if tp + fn else None,
                      "correct_abstain_items": abstain_ok, "errors": dict(errors)}
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "state" / "claims_gold_eval.json"))
    a = ap.parse_args(argv)
    items = [json.loads(x) for x in GOLD.read_text(encoding="utf-8").splitlines() if x.strip()]
    recs = {r["id"]: r for r in json.loads(FEED.read_text(encoding="utf-8"))["records"]}
    texts = {}
    for it in items:
        r = recs.get(it["item_id"]) or {}
        t = r.get("title") or "" if it["source"] == "title" else r.get("excerpt") or ""
        import hashlib
        if hashlib.sha256(t.encode()).hexdigest() != it["text_sha256"]:
            raise SystemExit(f"text changed for {it['item_id']}: gold label no longer applies")
        texts[it["item_id"]] = t
    rep = {"extractor_version": ce.EXTRACTOR_VERSION, "gold": GOLD.name, "results": evaluate(items, texts),
           "note": "single labeler (claude-v0); second blinded label pending; small n — not a pass/fail gate yet"}
    Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
