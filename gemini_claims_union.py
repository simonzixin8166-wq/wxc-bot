#!/usr/bin/env python3
"""Score option B (ce-4 production + Gemini fills what ce-4 missed) on a frozen test set, from a finished
gemini_claims report: no Gemini call. Prints A (Gemini alone), C (ce-4 alone) and B (union of the two label
sets per post x ticker). Owner 2026-11-16 asked for the union score before choosing A or B. Labels only."""
from __future__ import annotations

import argparse
import json
import sys

import claim_extractor as ce
from gemini_claims import FORUM_SETS, _load_gold, load_forum_dev, load_set, score


def ce4_answers(which: str) -> dict:
    """ce-4 exactly as measured before: v5 on 'title\\ntext' (score_extractors_test_v5), forum on the feed text."""
    items = load_forum_dev(which) if which in FORUM_SETS else load_set(which)
    out = {}
    for it in items:
        if it["text"] is None:
            continue
        txt = it["text"] if which in FORUM_SETS else f"{it['title']}\n{it['text'] or ''}"
        out[it["item_id"]] = {"labels": [{"symbol": c["symbol"], "stance": c["stance"]} for c in ce.extract_claims(txt, limit=20)]}
    return out


def union(a: dict, b: dict) -> dict:
    out = {}
    for k in set(a) | set(b):
        out[k] = {"labels": list((a.get(k) or {}).get("labels") or []) + list((b.get(k) or {}).get("labels") or [])}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True)
    ap.add_argument("--report", required=True)
    a = ap.parse_args(argv)
    rep = json.load(open(a.report, encoding="utf-8"))
    if not rep.get("complete"):
        print(json.dumps({"union": "skipped", "reason": "gemini report not complete"}))
        return 0
    gold = _load_gold(a.set)
    gem = {k: v for k, v in rep["answers"].items() if v.get("note") != "unavailable"}
    c4 = ce4_answers(a.set)
    res = {"set": a.set, "A_gemini": score(gem, gold), "C_ce4": score(c4, gold), "B_union": score(union(c4, gem), gold),
           "ce4_items": len(c4), "gemini_items": len(gem)}
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
