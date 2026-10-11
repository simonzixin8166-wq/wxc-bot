#!/usr/bin/env python3
"""Read-only learning-data inventory (quant-dashboard#133 6107236790, item 1).

Reports what wxc-bot has actually collected and what each record can be used for, without fetching
anything: per source kind / author / month — stored text form (title only, title + stored excerpt,
video transcript excerpt), image-only diagnosis, duplicates (same URL / same title+excerpt hash),
provenance (live vs backfill), and which gold sets already used the record (so frozen tests are never
reused). Article-level overlap between gold_context_v1 (36) and test v2 (73) is checked explicitly.
Output: state/wxc_learning_inventory.json (counts + record ids only, no text).
"""
from __future__ import annotations
import hashlib, json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
S = ROOT / "state"
G = ROOT / "research" / "gold"
OUT = S / "wxc_learning_inventory.json"


def jl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def j(p, d=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return d


def text_form(r):
    if r.get("source_kind") == "video":
        return "video_transcript_excerpt" if int(r.get("content_chars") or 0) > 0 else "video_title_only"
    if int(r.get("content_chars") or 0) > 0 and str(r.get("excerpt") or "").strip():
        return "title_plus_excerpt"
    return "title_only"


def build():
    feed = j(S / "research_feed.json", {}).get("records", [])
    by_id = {r["id"]: r for r in feed}
    used = defaultdict(set)
    for name, key in (("gold_v0", "claims_gold_v0.jsonl"), ("gold_v1", "claims_gold_v1.jsonl"), ("test_v2", "claims_gold_test_v2.jsonl")):
        for it in jl(G / key):
            used[name].add(it.get("url") or by_id.get(it["item_id"], {}).get("url"))
    ctx1 = {a["url"] for a in (j(S / "gold_context_v1.json", {}) or {}).get("articles", [])}
    ctx2 = {a["url"] for a in (j(S / "gold_context_test_v2.json", {}) or {}).get("articles", [])}
    r2 = {a["url"] for a in (j(S / "fulltext_claims_pilot_round2.json", {}) or {}).get("rows", [])}
    used["context_v1"], used["context_test_v2"], used["pilot_round2"] = ctx1, ctx2, r2
    img = {x["url"]: x["reason"] for d in ("title_only_diagnosis.json", "title_only_diagnosis_round2.json")
           for x in (j(S / d, {}) or {}).get("rows", []) if x.get("url")}

    url_count = Counter(r.get("url") for r in feed if r.get("url"))
    content_hash = Counter(hashlib.sha256(f"{r.get('title')}|{r.get('excerpt')}".encode()).hexdigest() for r in feed)
    rows, agg = [], defaultdict(Counter)
    for r in feed:
        form = text_form(r)
        h = hashlib.sha256(f"{r.get('title')}|{r.get('excerpt')}".encode()).hexdigest()
        tags = sorted(k for k, v in used.items() if r.get("url") in v)
        rec = {"id": r["id"], "kind": r.get("source_kind"), "author": r.get("author"),
               "month": str(r.get("published_at") or "")[:7], "text_form": form,
               "image_only_diagnosed": img.get(r.get("url")) == "image_only",
               "provenance": r.get("intake_class_hint") or r.get("capture_mode") or "unknown",
               "dup_url": url_count.get(r.get("url"), 0) > 1, "dup_content": content_hash[h] > 1,
               "used_in": tags, "available_for_new_test": not tags and not (url_count.get(r.get("url"), 0) > 1)}
        rows.append(rec)
        for dim in ("kind", "author", "text_form", "month", "provenance"):
            agg[dim][str(rec[dim])] += 1
    unused = [x for x in rows if x["available_for_new_test"]]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "records": len(rows),
        "by": {k: dict(sorted(v.items())) for k, v in agg.items()},
        "duplicates": {"same_url": sum(1 for x in rows if x["dup_url"]), "same_title_excerpt": sum(1 for x in rows if x["dup_content"])},
        "image_only_diagnosed": sum(1 for x in rows if x["image_only_diagnosed"]),
        "gold_usage_urls": {k: len(v) for k, v in used.items()},
        "article_overlap": {"context_v1": len(ctx1), "context_test_v2": len(ctx2), "overlap_v1_v2": len(ctx1 & ctx2),
                            "pilot_round2": len(r2), "overlap_round2_v1": len(r2 & ctx1), "overlap_round2_v2": len(r2 & ctx2),
                            "distinct_articles_with_runtime_context": len(ctx1 | ctx2 | r2)},
        "available_for_new_frozen_test": {"records": len(unused), "by_text_form": dict(Counter(x["text_form"] for x in unused)),
                                          "by_author": dict(Counter(x["author"] for x in unused))},
        "storage_note": "feed stores titles and ≤360-char excerpts (public); full article text is runtime-only",
        "rows": rows,
    }


def main():
    rep = build()
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("records", "duplicates", "image_only_diagnosed", "article_overlap",
                                         "available_for_new_frozen_test")}, ensure_ascii=False))
    print(json.dumps(rep["by"]["text_form"], ensure_ascii=False), json.dumps(rep["by"]["kind"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
