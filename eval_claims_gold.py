#!/usr/bin/env python3
"""Evaluate claim_extractor against the human gold corpus (quant-dashboard#133 6106703460 / 6106896435).

Gold items reference public text by id/locator + sha256; labels are the author's OWN stance per symbol
(quotes, third-party examples and other people's trades are not claims). Coarse direction compared:
long (buy/add) / reduce (sell/trim) / hold / bullish / bearish / avoid. Items marked ambiguous are
excluded from scoring and counted separately.

  title items    : text = stored public title (verified by sha256)
  sentence items : text is fetched at runtime (--fetch, Actions only); the sentence is located by sha256.
                   Not found → unavailable (counts against traceability, never guessed).

Metrics per split: precision, recall, abstain rate, correct-abstain items, traceability, error types.
The test split is frozen (claims_gold_v1.freeze.json); report it once per extractor version, never tune on it.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import claim_extractor as ce  # noqa: E402

GOLD_DIR = ROOT / "research" / "gold"
FEED = ROOT / "state" / "research_feed.json"
COARSE = {"buy": "long", "add": "long", "sell": "reduce", "trim": "reduce", "hold": "hold",
          "bullish": "bullish", "bearish": "bearish", "avoid": "avoid"}


def sha(t):
    return hashlib.sha256((t or "").encode("utf-8")).hexdigest()


def classify_errors(pred, gold, it, detected):
    errs = Counter()
    gsym = {g[0] for g in gold}
    for p in pred - gold:
        if p[0] in gsym:
            errs["wrong_stance"] += 1
            if any(l.get("instrument") == "sell_put" for l in it["labels"]):
                errs["wrong_stance_option_semantics"] += 1
        elif not gold:
            errs["claim_where_none"] += 1
        else:
            errs["wrong_symbol"] += 1
    for g in gold - pred:
        if g[0] in {p[0] for p in pred}:
            errs["stance_mismatch"] += 1
        elif g[0] not in detected:
            errs["missed_symbol_not_detected"] += 1
        else:
            errs["missed_stance"] += 1
    return errs


def evaluate(items, texts, extractor=None, splits=("dev", "test")):
    extractor = extractor or ce.extract_claims
    res = {}
    for split in splits:
        tp = fp = fn = 0
        errors = Counter()
        gates = defaultdict(lambda: [0, 0])
        n = scored = amb = unavailable = abstain = abstain_ok = 0
        for it in (x for x in items if x["split"] == split):
            n += 1
            if it.get("ambiguous"):
                amb += 1
                continue
            text = texts.get(it["item_id"])
            if text is None:
                unavailable += 1
                continue
            scored += 1
            claims = [c for c in extractor(text) if ce.checkable(c)]
            for c in claims:
                gate = c.get("hp_gate")
                if gate:
                    ok = (c["symbol"], COARSE.get(c["stance"], c["stance"])) in {(l["symbol"], COARSE[l["stance"]]) for l in it["labels"]}
                    gates[gate][0 if ok else 1] += 1
            pred = {(c["symbol"], COARSE.get(c["stance"], c["stance"])) for c in claims}
            gold = {(l["symbol"], COARSE[l["stance"]]) for l in it["labels"]}
            if not pred:
                abstain += 1
                abstain_ok += not gold
            tp += len(pred & gold)
            fp += len(pred - gold)
            fn += len(gold - pred)
            errors += classify_errors(pred, gold, it, set(ce.symbols_in(text)))
        res[split] = {"items": n, "scored": scored, "ambiguous_excluded": amb, "unavailable": unavailable,
                      "traceability": round(scored / (n - amb), 3) if n - amb else None,
                      "gold_claims": tp + fn, "pred_claims": tp + fp, "tp": tp, "fp": fp, "fn": fn,
                      "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                      "recall": round(tp / (tp + fn), 3) if tp + fn else None,
                      "abstain_rate": round(abstain / scored, 3) if scored else None,
                      "correct_abstain_items": abstain_ok, "errors": dict(errors),
                      "coverage": round((tp + fp) / (tp + fn), 3) if tp + fn else None,
                      "by_gate": {g: {"correct": v[0], "wrong": v[1]} for g, v in gates.items()}}
    return res


def load_texts(items, fetch=False):
    recs = {r["id"]: r for r in json.loads(FEED.read_text(encoding="utf-8"))["records"]}
    texts = {}
    for it in items:
        if it.get("kind", "title") == "title":
            t = (recs.get(it.get("record_id") or it["item_id"]) or {}).get("title") or ""
            if sha(t) == it["text_sha256"]:
                texts[it["item_id"]] = t
        elif it.get("kind") == "excerpt":  # stored public title + ≤360-char excerpt, located by sentence sha
            r = recs.get(it["record_id"]) or {}
            for s_ in ce.sentences(f"{r.get('title') or ''}\n{r.get('excerpt') or ''}"):
                if sha(s_) == it["text_sha256"]:
                    texts[it["item_id"]] = s_
                    break
    if fetch:
        import time, random
        from pilot_fulltext_claims import fetch_text
        by_url = defaultdict(list)
        for it in items:
            if it.get("kind") == "sentence" and not it.get("ambiguous"):
                by_url[it["url"]].append(it)
        for url, its in by_url.items():
            time.sleep(random.uniform(2.0, 4.0))
            status, _, text = fetch_text({"url": url, "author": its[0].get("author")})
            if status in (403, 429):
                break
            if not text:
                continue
            sents = {sha(s): s for s in ce.sentences(text)}
            for it in its:
                if it["text_sha256"] in sents:
                    texts[it["item_id"]] = sents[it["text_sha256"]]
            text = None  # runtime only
    return texts


def apply_adjudication(items, path):
    """Append-only adjudication overlay (second-labeler disagreements resolved with a reason).
    The gold file itself is never rewritten; adjudications may only touch dev items."""
    if not path.exists():
        return items, 0
    adj = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    by = {i["item_id"]: i for i in items}
    for a in adj:
        it = by[a["item_id"]]
        if it["split"] != "dev":
            raise SystemExit(f"adjudication touches frozen test item {a['item_id']}")
        it.update(a["after"])
    return items, len(adj)


def freeze(items):
    test = sorted(json.dumps(i, ensure_ascii=False, sort_keys=True) for i in items if i["split"] == "test")
    return {"test_items": len(test), "test_sha256": sha("\n".join(test))}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="claims_gold_v1.jsonl")
    ap.add_argument("--fetch", action="store_true", help="fetch article sentences at runtime (Actions)")
    ap.add_argument("--out", default=str(ROOT / "state" / "claims_gold_eval.json"))
    ap.add_argument("--mode", choices=("ce", "hp"), default="ce", help="hp = ce-5 high-precision shadow")
    ap.add_argument("--split", choices=("dev", "test", "both"), default="both")
    a = ap.parse_args(argv)
    path = GOLD_DIR / a.gold
    items = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    fz = GOLD_DIR / path.name.replace(".jsonl", ".freeze.json")
    frozen_ok = None
    if fz.exists():
        frozen_ok = json.loads(fz.read_text(encoding="utf-8"))["test_sha256"] == freeze(items)["test_sha256"]
    frozen_items = [dict(i) for i in items]
    items, n_adj = apply_adjudication(items, GOLD_DIR / path.name.replace(".jsonl", "_adjudication.jsonl"))
    if freeze(items)["test_sha256"] != freeze(frozen_items)["test_sha256"]:
        raise SystemExit("adjudication changed the frozen test split")
    texts = load_texts(items, fetch=a.fetch)
    fn = ce.extract_claims_hp if a.mode == "hp" else ce.extract_claims
    sp = ("dev", "test") if a.split == "both" else (a.split,)
    by_kind = {k: evaluate([i for i in items if i.get("kind", "title") == k], texts, fn, sp) for k in ("title", "sentence", "excerpt")}
    rep = {"extractor_version": ce.HP_VERSION if a.mode == "hp" else ce.EXTRACTOR_VERSION, "splits": list(sp), "gold": path.name, "test_frozen_intact": frozen_ok, "adjudications": n_adj,
           "fetched_sentences": a.fetch, "results": evaluate(items, texts, fn, sp), "by_kind": by_kind,
           "note": "single labeler until the blind second label is in; scored only where text is traceable"}
    Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"extractor": rep["extractor_version"], "frozen": frozen_ok,
                      **{s_: {k: rep["results"][s_][k] for k in ("scored", "precision", "recall", "coverage", "traceability")} for s_ in sp}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
