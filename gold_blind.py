#!/usr/bin/env python3
"""Blind second-label workflow for the claims gold corpus (quant-dashboard#133 6106896435).

export : ~20% stratified sample (titles + article sentences, dev and test) as research/gold/blind_v1_request.json
         with ids, public URL, the public title text or the ≤40-char locator + sentence index — never Claude's
         labels or extractor output.
kappa  : compare the second labeler's file (same blind ids) with the gold labels: Cohen's κ over
         (item, symbol) decisions with categories long/reduce/hold/bullish/bearish/avoid/none, plus the
         list of disagreement types. Items the second labeler marks unavailable/ambiguous are reported apart.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from eval_claims_gold import COARSE  # noqa: E402

GOLD = ROOT / "research" / "gold" / "claims_gold_v1.jsonl"
REQ = ROOT / "research" / "gold" / "blind_v1_request.json"
FEED = ROOT / "state" / "research_feed.json"
INSTRUCTIONS = ("For each item, open the URL (or read the title) and list the AUTHOR'S OWN position/view per ticker: "
                "stance ∈ buy/add/sell/trim/hold/avoid/bullish/bearish; status ∈ executed/planned/conditional/opinion; "
                "instrument ∈ stock/sell_put/covered_call/leaps/other. Quotes of other people, third-party trades and "
                "examples are NOT the author's claims. No ticker or no own view → labels: []. "
                "If the page cannot be opened or the sentence cannot be found → status 'unavailable'; if genuinely "
                "unclear → 'ambiguous'. Do not guess. Sentence items: judge the sentence that contains the locator, "
                "using the article only as context.")


def blind_id(item_id):
    return "b-" + hashlib.sha256(("blind|" + item_id).encode()).hexdigest()[:10]


def sample(items, frac=0.2):
    keyed = sorted(items, key=lambda i: hashlib.sha256(("sample|" + i["item_id"]).encode()).hexdigest())
    out, quota = [], Counter()
    target = {k: max(1, round(frac * sum(1 for i in items if i["kind"] == k))) for k in ("title", "sentence")}
    for it in keyed:
        if quota[it["kind"]] < target[it["kind"]]:
            out.append(it); quota[it["kind"]] += 1
    return out


def export(items):
    titles = {r["id"]: r.get("title") for r in json.loads(FEED.read_text(encoding="utf-8"))["records"]}
    req = []
    for it in sample(items):
        row = {"blind_id": blind_id(it["item_id"]), "kind": it["kind"], "author": it["author"], "url": it.get("url"),
               "published_at": it.get("published_at")}
        if it["kind"] == "title":
            row["title"] = titles.get(it["item_id"])
        else:
            row.update({"sentence_index": it["sentence_index"], "locator": it["locator"]})
        req.append(row)
    return {"version": "blind-v1", "items": len(req), "instructions": INSTRUCTIONS, "requests": req,
            "answer_format": {"blind_id": "b-…", "status": "ok|unavailable|ambiguous",
                              "labels": [{"symbol": "TICKER", "stance": "…", "status": "…", "instrument": "…"}]}}


def kappa(gold_items, answers):
    gmap = {blind_id(i["item_id"]): i for i in gold_items}
    pairs, disagreements, skipped = [], Counter(), Counter()
    status_pairs = []
    for a in answers:
        it = gmap.get(a["blind_id"])
        if not it:
            continue
        if a.get("status") in ("unavailable", "ambiguous") or it.get("ambiguous"):
            skipped[a.get("status") if a.get("status") in ("unavailable", "ambiguous") else "gold_ambiguous"] += 1
            continue
        g = {l["symbol"].upper(): COARSE[l["stance"]] for l in it["labels"]}
        b = {l["symbol"].upper(): COARSE.get(l["stance"], l["stance"]) for l in a.get("labels") or []}
        gs = {l["symbol"].upper(): l.get("status") for l in it["labels"]}
        bs = {l["symbol"].upper(): l.get("status") for l in a.get("labels") or []}
        for sym in set(g) & set(b):
            if g[sym] == b[sym] and g[sym] != "hold":
                status_pairs.append(gs.get(sym) == bs.get(sym))
        syms = set(g) | set(b) or {"_none_"}
        for s in syms:
            x, y = g.get(s, "none"), b.get(s, "none")
            pairs.append((x, y))
            if x != y:
                disagreements["claim_vs_none" if "none" in (x, y) else "stance"] += 1
    n = len(pairs)
    if not n:
        return {"pairs": 0}
    po = sum(x == y for x, y in pairs) / n
    cx, cy = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum(cx[k] * cy[k] for k in set(cx) | set(cy)) / (n * n)
    k = (po - pe) / (1 - pe) if pe < 1 else 1.0
    return {"pairs": n, "observed_agreement": round(po, 3), "kappa": round(k, 3), "disagreements": dict(disagreements),
            "skipped": dict(skipped), "status_agreement_non_hold": (round(sum(status_pairs) / len(status_pairs), 3) if status_pairs else None),
            "status_pairs": len(status_pairs)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    ap.add_argument("--gold", default=str(GOLD))
    ap.add_argument("--req", default=str(REQ))
    sub.add_parser("export")
    k = sub.add_parser("kappa"); k.add_argument("answers")
    a = ap.parse_args(argv)
    items = [json.loads(x) for x in Path(a.gold).read_text(encoding="utf-8").splitlines() if x.strip()]
    if a.cmd == "export":
        rep = export(items)
        rep["version"] = Path(a.req).stem.replace("_request", "")
        Path(a.req).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"exported": rep["items"]}))
    else:
        print(json.dumps(kappa(items, json.loads(Path(a.answers).read_text(encoding="utf-8"))), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
