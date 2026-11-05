#!/usr/bin/env python3
"""Claims gold v4.1 round 1 agreement: GPT vs Claude on the 120 textpack items (spec v0.3, guideline v1.3).

Same units as round 1 of v4 (claims_gold_v4_agreement_round1.json):
  kappa      post-level binary - the post has >= 1 author claim (any ticker); item-level reported too
  direction  (record_id, symbol) pairs labelled by both; agree when the polarities overlap (guideline v1.3 §3)
Gate (spec v0.2 §3.4): kappa >= 0.60, polarity agreement >= 0.85, Owner disagreements <= 3 of 20.
The Owner did not label this round (Owner 2026-11-05, #133 6648511823), so the Owner gate is NOT_EVALUATED and the
result can be at most PARTIAL. Writes research/gold/claims_gold_v4.1_agreement_round1.json.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
G = ROOT / "research" / "gold"
POS = {"buy", "add", "bullish", "hold"}
ENUMS = {"stance": {"buy", "add", "sell", "trim", "hold", "avoid", "bullish", "bearish"},
         "status": {"executed", "planned", "conditional", "opinion"},
         "instrument": {"stock", "sell_put", "covered_call", "leaps", "other"},
         "holder": {"author", "author_system"}, "ticker_source": {"text", "context"}}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def validate(answers: list, order: list) -> list:
    errs = []
    if [a.get("blind_id") for a in answers] != order:
        errs.append("blind_id set or order differs from the textpack")
    for a in answers:
        if set(a) != {"blind_id", "labels", "ambiguous", "note", "reply_role"}:
            errs.append(f"{a.get('blind_id')}: keys")
        for l in a.get("labels") or []:
            if set(l) != set(ENUMS) | {"symbol"} or any(l.get(k) not in v for k, v in ENUMS.items()):
                errs.append(f"{a['blind_id']}: label {l}")
        if a.get("note") not in (None, "needs_article_check", "holdings_list", "unavailable"):
            errs.append(f"{a['blind_id']}: note")
        if a.get("reply_role") not in (None, "agree", "disagree", "answer", "question", "social", "none"):
            errs.append(f"{a['blind_id']}: reply_role")
    return errs


def kappa(pairs: list) -> dict:
    n = len(pairs)
    obs = sum(p == q for p, q in pairs) / n
    p1, p2 = sum(p for p, _ in pairs) / n, sum(q for _, q in pairs) / n
    pe = p1 * p2 + (1 - p1) * (1 - p2)
    return {"n": n, "observed_agreement": round(obs, 3), "kappa": round((obs - pe) / (1 - pe), 3) if pe < 1 else None}


def wilson(k: int, n: int, z: float = 1.96):
    if not n:
        return None
    p = k / n
    d, c = 1 + z * z / n, p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - s) / d, 3), round((c + s) / d, 3)]


def status(a: dict) -> str:
    return "claim" if a["labels"] else ("needs_article_check" if a["note"] == "needs_article_check" else "none")


def build() -> dict:
    pack = json.loads((G / "blind_test_v4.1_textpack.json").read_text(encoding="utf-8"))["items"]
    key = {k["blind_id"]: k["item_id"] for k in json.loads((G / "blind_test_v4.1_key.json").read_text(encoding="utf-8"))["key"]}
    test = {json.loads(x)["item_id"]: json.loads(x) for x in (G / "claims_gold_test_v4.1.unlabeled.jsonl").read_text(encoding="utf-8").splitlines() if x}
    gpt = json.loads((G / "blind_test_v4.1_gpt_answers.json").read_text(encoding="utf-8"))["answers"]
    cla = json.loads((G / "blind_test_v4.1_claude_answers.json").read_text(encoding="utf-8"))["answers"]
    order = [i["blind_id"] for i in pack]
    errs = {"gpt": validate(gpt, order), "claude": validate(cla, order)}
    assert not errs["gpt"] and not errs["claude"], errs
    g, c, meta = {a["blind_id"]: a for a in gpt}, {a["blind_id"]: a for a in cla}, {i["blind_id"]: i for i in pack}

    item = kappa([(bool(c[b]["labels"]), bool(g[b]["labels"])) for b in order])
    item["status_matrix_claude_vs_gpt"] = dict(Counter(f"{status(c[b])}|{status(g[b])}" for b in order))
    posts = defaultdict(lambda: [False, False])
    for b in order:
        r = test[key[b]]["record_id"]
        posts[r][0] |= bool(c[b]["labels"]); posts[r][1] |= bool(g[b]["labels"])
    pp = [tuple(v) for v in posts.values()]
    post = kappa(pp)
    post["confusion"] = dict(Counter("both_claim" if p and q else "claude_only" if p else "gpt_only" if q else "neither" for p, q in pp))

    def pairs(src):
        d = defaultdict(set)
        for b in order:
            for l in src[b]["labels"]:
                d[(test[key[b]]["record_id"], l["symbol"])].add("pos" if l["stance"] in POS else "neg")
        return d
    pc, pg = pairs(c), pairs(g)
    both = sorted(set(pc) & set(pg))
    agree = sum(1 for k in both if pc[k] & pg[k])
    direction = {"pairs_claude": len(pc), "pairs_gpt": len(pg), "pairs_both": len(both), "agree": agree,
                 "rate": round(agree / len(both), 3) if both else None, "wilson95": wilson(agree, len(both)),
                 "claude_only_symbols": sorted(k[1] for k in set(pc) - set(pg)),
                 "gpt_only_symbols": sorted(k[1] for k in set(pg) - set(pc))}
    channels = {}
    for name, f in (("title", lambda b: meta[b]["kind"] == "title"), ("excerpt", lambda b: meta[b]["kind"] == "excerpt"),
                    ("reply", lambda b: meta[b]["is_reply"]), ("root", lambda b: not meta[b]["is_reply"])):
        channels[name] = kappa([(bool(c[b]["labels"]), bool(g[b]["labels"])) for b in order if f(b)])
    gate = {"kappa_ge_0.60": "PASS" if post["kappa"] >= 0.60 else "FAIL",
            "polarity_agreement_ge_0.85": "PASS" if direction["rate"] is not None and direction["rate"] >= 0.85 else "FAIL",
            "owner_disagreements_le_3_of_20": "NOT_EVALUATED (Owner did not label this round, #133 6648511823)"}
    gate["result"] = "PARTIAL" if all(v == "PASS" for k, v in gate.items() if k.startswith(("kappa", "polarity"))) else "FAIL"
    return {
        "version": "gold_v4.1_agreement_round1", "date": "2026-11-05", "guideline": "v1.3", "spec": "v0.3",
        "sample": f"GPT 120 test items / {len(pp)} posts", "labelers": ["claude (sealed 6648335477)", "gpt (relayed by the Owner)"],
        "inputs_sha256": {n: sha(G / n) for n in ("blind_test_v4.1_textpack.json", "blind_test_v4.1_gpt_answers.json",
                                                   "blind_test_v4.1_claude_answers.json", "claims_gold_test_v4.1.claude_first.jsonl")},
        "kappa_unit": "post-level binary: post has >= 1 author claim (any ticker); needs_article_check counts as no claim",
        "direction_unit": "(record_id, symbol) pairs labelled by both; agree if the polarities overlap",
        "post_level": post, "item_level": item, "direction": direction, "channels_item_level": channels, "gate": gate,
        "not_claimed": "Not frozen, not adjudicated, no S2 pass: the Owner gate is not evaluated and disagreements are not adjudicated.",
    }


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    out = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    p = G / "claims_gold_v4.1_agreement_round1.json"
    if "--check" in argv:
        ok = p.exists() and p.read_text(encoding="utf-8") == out
        print(json.dumps({"check": "PASS" if ok else "FAIL"}))
        return 0 if ok else 1
    p.write_text(out, encoding="utf-8")
    d = json.loads(out)
    print(json.dumps({k: d[k] for k in ("post_level", "direction", "gate")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
