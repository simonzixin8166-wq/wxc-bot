#!/usr/bin/env python3
"""S2 challenger: Gemini (free tier) reads a whole public post and returns author claims in the guideline v1.3
label schema (Owner: Gemini text understanding approved for public content only, free tier, 2026-11-03).

Shadow only: nothing here writes the research feed or any production artifact. It is used to compare against the
rule extractor (ce-4 / ce-6) on the S2 v5 dev set and on the frozen v5 test set (gold frozen 2026-11-10, wxc-bot
#93). The test set is measured once: the prompt is not changed after seeing test results.

Guardrails
- Off unless GEMINI_API_KEY is set; free tier only. Budget GEMINI_CLAIMS_DAILY_CAP calls per Pacific-time day
  (default 80), recorded in state/gemini_claims_budget.json; HTTP 429 stops the run.
- Only public text goes to the model (forum root posts already in the feed; Owner-forwarded public articles read
  at runtime from the private textpack). Outputs are labels only: no source text is written anywhere.
- Every returned label is validated against the v1.3 value sets; anything else is dropped and counted.

- The free tier allows only a few calls a day, so a run can resume: --resume <previous report> keeps every
  answered post and only calls the model for the rest (posts whose answer was "unavailable" are retried).

  python gemini_claims.py --set test --resume prev.json --out diagnostics/gemini_claims_test.json
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent
GOLD = ROOT / "research" / "gold"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
MODELS = [m.strip() for m in os.getenv("GEMINI_CLAIMS_MODELS", "gemini-3.5-flash,gemini-3.8-flash").split(",") if m.strip()]
DAILY_CAP = int(os.getenv("GEMINI_CLAIMS_DAILY_CAP", "80"))
PAUSE = float(os.getenv("GEMINI_CLAIMS_PAUSE", "5"))
TIMEOUT = int(os.getenv("GEMINI_CLAIMS_TIMEOUT", "120"))
VERSION = "gemini-claims-0.2"
ENUMS = {"stance": {"buy", "add", "sell", "trim", "hold", "avoid", "bullish", "bearish"},
         "status": {"executed", "planned", "conditional", "opinion"},
         "instrument": {"stock", "sell_put", "covered_call", "leaps", "other"},
         "holder": {"author", "author_system"}, "ticker_source": {"text", "context"}}
NOTES = {None, "needs_article_check", "holdings_list", "unavailable"}

PROMPT = """You label author claims in one public investment post (Chinese forum post or blog article).
Return ONLY JSON: {"labels": [ {"symbol": "...", "stance": "...", "status": "...", "instrument": "...",
"holder": "author", "ticker_source": "text"} ], "note": null}

Rules (frozen guideline v1.3, whole post is the target):
- Only claims by the AUTHOR about a specific US-listed stock or ETF. Not claims: quotes of other people,
  third-party trades (Buffett, 段永平, 黄仁勋, 13F, "他买入"), examples, price or index reports, market statistics,
  news, questions, "开始关注", advice to others without the author's own view, history or hypothetical
  calculations.
- symbol: the US ticker in upper case; map clear company names (谷歌 GOOGL, 英伟达 NVDA, 台积电 TSM, 英特尔 INTC,
  亚马逊 AMZN, 微软 MSFT, 特斯拉 TSLA, 苹果 AAPL, Meta META, 博通 AVGO, 美光 MU). Index: SPY, QQQ, SPX, ...
- stance: buy | add | sell | trim | hold | avoid | bullish | bearish. Selling puts = bullish with instrument sell_put.
- status: executed | planned | conditional | opinion. Pre-set buy tiers or sell lines ("第一档 180，卖出线 250")
  are conditional (buy-side = buy/add, sell line = sell/trim).
- instrument: stock | sell_put | covered_call | leaps | other.  holder: author | author_system.
  ticker_source: text (ticker in the sentence) | context (ticker only elsewhere in the post).
- An executed sale after a gain plus a stated positive view on the same ticker = trim/executed + bullish/opinion.
- hold only with explicit "I hold" wording; a holdings list of more than 5 tickers -> labels [] and
  note "holdings_list". One label per ticker+stance+status.
- No author claim -> {"labels": [], "note": null}. note must be null, "needs_article_check", "holdings_list" or
  "unavailable". No free text anywhere.

POST
Title: {title}
Text:
{text}
"""


FORUM_PROMPT = """You label author claims in short Chinese/English forum utterances (posts and replies) by a tracked
investor. Same rules as below, plus: each item may show REPLYING TO, the post it answers. Use REPLYING TO ONLY to
tell which ticker the item refers to (then ticker_source "context"); never label a claim made in REPLYING TO.
Colloquial wording counts: 进/进的/买回 = buy, 被止损/退出来/卖掉 = sell, 卖葡萄/卖 put = bullish + sell_put,
"long hold"/"我的X" = hold. Return ONLY JSON:
{"answers": [ {"id": "...", "labels": [ {"symbol": "...", "stance": "...", "status": "...", "instrument": "...",
"holder": "author", "ticker_source": "text"} ], "note": null} ]}  -- exactly one answer per item, same ids.

""" + PROMPT.split("POST\n")[0] + """ITEMS
{items}
"""


def _today():
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def _budget_path() -> Path:
    return Path(os.getenv("DATA_DIR", "state")) / "gemini_claims_budget.json"


def _budget(bump: int = 0) -> dict:
    p = _budget_path()
    doc = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"days": {}}
    day = doc["days"].setdefault(_today(), {"calls": 0, "errors": 0})
    day["calls"] += bump
    if bump:
        p.parent.mkdir(parents=True, exist_ok=True)
        doc["days"] = dict(sorted(doc["days"].items())[-30:])
        p.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return day


def _extract_json(raw):
    texts = []

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("text"), str):
                texts.append(x["text"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(raw)
    joined = "\n".join(dict.fromkeys(t for t in texts if t.strip()))
    m = re.search(r"\{.*\}", joined, re.S)
    return json.loads(m.group(0)) if m else None


def clean(parsed) -> tuple[dict, int]:
    """Keep only labels that fit the v1.3 schema; returns (answer, dropped)."""
    if not isinstance(parsed, dict):
        return {"labels": [], "ambiguous": False, "note": "unavailable", "reply_role": None}, 0
    out, dropped, seen = [], 0, set()
    for l in parsed.get("labels") or []:
        if not isinstance(l, dict):
            dropped += 1
            continue
        l = {k: (str(l.get(k) or "").strip() or None) for k in ("symbol", "stance", "status", "instrument", "holder", "ticker_source")}
        l["holder"] = l["holder"] or "author"
        l["ticker_source"] = l["ticker_source"] or "text"
        l["instrument"] = l["instrument"] or "stock"
        sym = (l["symbol"] or "").upper().lstrip("$")
        if not re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z])?", sym) or any(l[k] not in v for k, v in ENUMS.items()):
            dropped += 1
            continue
        l["symbol"] = sym
        key = tuple(l[k] for k in ("symbol", "stance", "status"))
        if key not in seen:
            seen.add(key)
            out.append(l)
    note = parsed.get("note")
    note = note if note in NOTES else None
    return {"labels": out, "ambiguous": False, "note": note, "reply_role": None}, dropped


def label_post(title: str, text: str, post=None) -> tuple[dict, dict]:
    """One call. Returns (answer, meta). Raises RuntimeError('quota') on 429."""
    post = post or requests.post
    headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip(), "Content-Type": "application/json",
               "User-Agent": "MyAlphaView-S2-challenger/0.1"}
    prompt = PROMPT.replace("{title}", title or "").replace("{text}", text or "(no body; the title is the whole post)")
    last = None
    for i, model in enumerate(MODELS):
        if i:
            time.sleep(PAUSE)
        _budget(1)
        try:
            r = post(ENDPOINT, json={"model": model, "input": [{"type": "text", "text": prompt}]}, timeout=TIMEOUT,
                     headers=headers)
        except requests.RequestException as e:  # a timeout or dropped connection skips to the next model, not the run
            last = type(e).__name__
            continue
        last = r.status_code
        if r.status_code == 429:
            raise RuntimeError("quota")
        if r.status_code == 200:
            ans, dropped = clean(_extract_json(r.json()))
            return ans, {"model": model, "status": 200, "dropped_labels": dropped}
    return {"labels": [], "ambiguous": False, "note": "unavailable", "reply_role": None}, {"model": None, "status": last}


def label_batch(items: list[dict], post=None) -> tuple[dict, dict]:
    """Forum mode: several short utterances in one call (free-tier budget). items: {id, text, context}.
    Returns ({id: answer}, meta); an id the model skipped is 'unavailable' (retried by --resume)."""
    post = post or requests.post
    headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip(), "Content-Type": "application/json",
               "User-Agent": "MyAlphaView-S2-challenger/0.1"}
    lines = []
    for it in items:
        lines.append(f"- id: {it['id']}\n  TEXT: {it['text']}")
        if it.get("context"):
            lines.append(f"  REPLYING TO: {it['context']}")
    prompt = FORUM_PROMPT.replace("{items}", "\n".join(lines))
    unavailable = {"labels": [], "ambiguous": False, "note": "unavailable", "reply_role": None}
    last = None
    for i, model in enumerate(MODELS):
        if i:
            time.sleep(PAUSE)
        _budget(1)
        try:
            r = post(ENDPOINT, json={"model": model, "input": [{"type": "text", "text": prompt}]}, timeout=TIMEOUT,
                     headers=headers)
        except requests.RequestException as e:
            last = type(e).__name__
            continue
        last = r.status_code
        if r.status_code == 429:
            raise RuntimeError("quota")
        if r.status_code == 200:
            parsed = _extract_json(r.json()) or {}
            got, dropped = {}, 0
            for a in parsed.get("answers") or []:
                if isinstance(a, dict) and str(a.get("id")) in {it["id"] for it in items}:
                    ans, d = clean(a)
                    got[str(a["id"])] = ans
                    dropped += d
            return ({it["id"]: got.get(it["id"], unavailable) for it in items},
                    {"model": model, "status": 200, "dropped_labels": dropped, "missing": len(items) - len(got)})
    return {it["id"]: unavailable for it in items}, {"model": None, "status": last}


def load_forum_dev() -> list[dict]:
    """Forum dev set (research/forum/claims_gold_forum_dev_v1): utterance text and the post it answers, both already
    in the public feed (titles and <=360-char excerpts only)."""
    ids = {json.loads(x)["post_id"] for x in (ROOT / "research" / "forum" / "claims_gold_forum_dev_v1.claude_first.jsonl")
           .read_text(encoding="utf-8").splitlines() if x.strip()}
    out = []
    for r in json.loads((ROOT / "state" / "research_feed.json").read_text(encoding="utf-8"))["records"]:
        pid = str(r.get("source_entry_key") or "")
        if r.get("intake_provenance") != "owner_forum_export" or pid not in ids:
            continue
        title, ex = (r.get("title") or "").strip(), (r.get("excerpt") or "").strip()
        par = (r.get("thread_context") or {}).get("in_reply_to") or {}
        out.append({"item_id": pid, "source": "forum", "title": title, "text": title if ex in ("", title) else f"{title}\n{ex}",
                    "context": f"{par.get('author')}: {par.get('title')}" if par.get("title") else None})
    return sorted(out, key=lambda x: x["item_id"])


def _textpack_text(item_id: str) -> str | None:
    token, repo = os.getenv("TEXTPACK_TOKEN", ""), os.getenv("TEXTPACK_REPO", "")
    if not token or not repo:
        return None
    r = requests.get(f"https://api.github.com/repos/{repo}/contents/s2_v5_textpack/C_owner_forward/{item_id}.txt",
                     headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=30)
    return base64.b64decode(r.json()["content"]).decode("utf-8").strip() if r.status_code == 200 else None


def load_set(which: str) -> list[dict]:
    """Rebuild the exact texts the labellers saw, checked against the frozen text hashes."""
    rows = [json.loads(x) for x in (GOLD / f"claims_gold_{which}_v5.unlabeled.jsonl").read_text(encoding="utf-8").splitlines() if x]
    feed = {r["id"]: r for r in json.loads((ROOT / "state" / "research_feed.json").read_text(encoding="utf-8"))["records"]}
    index = {}
    p = ROOT / "state" / "owner_forward_index.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines() if p.exists() else []:
        if line.strip():
            x = json.loads(line)
            index[x["item_id"]] = x
    out = []
    for x in rows:
        if x["source"] == "C":
            body = _textpack_text(x["owner_forward_item_id"])
            title = (index.get(x["owner_forward_item_id"]) or {}).get("title") or ""
            ok = body is not None and hashlib.sha256(body.encode()).hexdigest() == x["text_sha256"]
        else:
            r = feed.get(x["record_ids"][0]) or {}
            title, body = (r.get("title") or "").strip(), (r.get("excerpt") or "").strip()
            ok = hashlib.sha256(f"{title}\n{body}".strip().encode()).hexdigest() == x["text_sha256"]
        out.append({"item_id": x["item_id"], "source": x["source"], "title": title, "text": body if ok else None})
    return out


def score(answers: dict, gold: dict) -> dict:
    """Post x ticker pairs; direction agreement by polarity (guideline v1.3 §3)."""
    pos = {"buy", "add", "bullish", "hold"}

    def pairs(src):
        d = {}
        for iid, a in src.items():
            for l in a.get("labels") or []:
                d.setdefault((iid, l["symbol"]), set()).add("pos" if l["stance"] in pos else "neg")
        return d
    g, p = pairs(gold), pairs({k: v for k, v in answers.items() if k in gold})
    tp = set(g) & set(p)
    return {"gold_pairs": len(g), "pred_pairs": len(p), "matched": len(tp),
            "precision": round(len(tp) / len(p), 3) if p else None, "recall": round(len(tp) / len(g), 3) if g else None,
            "direction_agree": sum(1 for k in tp if g[k] & p[k])}


GOLD_FILES = {"dev": "claims_gold_dev_v5.claude_first.jsonl", "test": "claims_gold_test_v5.jsonl",
              "forum_dev": "../forum/claims_gold_forum_dev_v1.claude_first.jsonl"}
FORUM_BATCH = int(os.getenv("GEMINI_FORUM_BATCH", "8"))


def _load_gold(which: str) -> dict:
    p = GOLD / GOLD_FILES[which]
    out = {}
    for x in p.read_text(encoding="utf-8").splitlines() if p.exists() else []:
        if x.strip():
            g = json.loads(x)
            out[g.get("item_id") or g["post_id"]] = g
    return out


def _load_previous(path: str | None, which: str) -> dict:
    """Answers from an earlier run of the same set and version; 'unavailable' answers are dropped so they retry."""
    if not path or not Path(path).exists():
        return {}
    try:
        prev = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if prev.get("set") != which or prev.get("version") != VERSION:
        return {}
    return {k: v for k, v in (prev.get("answers") or {}).items() if v.get("note") != "unavailable"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=("dev", "test", "forum_dev"), default="dev")
    ap.add_argument("--resume", default=None, help="previous report of the same set to continue from")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    out = a.out or f"diagnostics/gemini_claims_{a.set}.json"
    if not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not set: challenger off")
        return 0
    items = load_forum_dev() if a.set == "forum_dev" else load_set(a.set)
    answers = _load_previous(a.resume, a.set)
    resumed = len(answers)
    meta = {"calls": 0, "resumed": resumed, "unavailable_text": 0, "model_unavailable": 0, "dropped_labels": 0,
            "quota_stop": False, "models": {}}
    todo = [it for it in items if it["item_id"] not in answers]
    if a.set == "forum_dev":
        for k in range(0, len(todo), FORUM_BATCH):
            if _budget()["calls"] >= DAILY_CAP:
                meta["quota_stop"] = "daily_cap"
                break
            chunk = todo[k:k + FORUM_BATCH]
            try:
                got, m = label_batch([{"id": it["item_id"], "text": it["text"], "context": it.get("context")} for it in chunk])
            except RuntimeError:
                meta["quota_stop"] = "http_429"
                break
            meta["calls"] += 1
            meta["dropped_labels"] += m.get("dropped_labels", 0)
            meta["models"][str(m.get("model"))] = meta["models"].get(str(m.get("model")), 0) + 1
            for iid, ans in got.items():
                meta["model_unavailable"] += ans.get("note") == "unavailable"
                answers[iid] = ans
            time.sleep(PAUSE)
        todo = []
    for it in todo:
        if it["text"] is None:
            meta["unavailable_text"] += 1
            continue
        if _budget()["calls"] >= DAILY_CAP:
            meta["quota_stop"] = "daily_cap"
            break
        try:
            ans, m = label_post(it["title"], it["text"])
        except RuntimeError:
            meta["quota_stop"] = "http_429"
            break
        meta["calls"] += 1
        meta["dropped_labels"] += m.get("dropped_labels", 0)
        meta["models"][str(m.get("model"))] = meta["models"].get(str(m.get("model")), 0) + 1
        if ans.get("note") == "unavailable":
            meta["model_unavailable"] += 1
        answers[it["item_id"]] = ans
        time.sleep(PAUSE)
    gold = _load_gold(a.set)
    scored = {k: v for k, v in answers.items() if v.get("note") != "unavailable"}
    rep = {"version": VERSION, "set": a.set, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "items": len(items), "answered": len(scored), "complete": len(scored) == len(items), "meta": meta,
           "gold": GOLD_FILES[a.set],
           "score": score(scored, {k: v for k, v in gold.items() if k in scored}) if gold else None,
           "answers": answers, "production_use": False, "note": "labels only; no source text stored"}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("items", "answered", "complete", "meta", "score")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
