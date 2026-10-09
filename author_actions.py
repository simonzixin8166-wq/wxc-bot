#!/usr/bin/env python3
"""Author position-action extraction for tracked authors (quant-dashboard#133 item 9: 麻你 · VGT/SGOV).

These are the author's own statements about their account — research signals, never MyAlpha actions
and never instructions for the user. Each action keeps: symbol, action_type, size_pct / price only when
the author states them explicitly, the allocation if stated, a short evidence quote (≤40 chars, the
public feed already carries short excerpts), the sentence sha256, and a confidence.

action_type
  BUY_EXECUTED / SELL_EXECUTED : only explicit completed wording by the author (已买入/买了/成交/已卖/卖掉了…)
  BUY_PLANNED / SELL_PLANNED   : intent or resting orders (准备/计划/打算/设…止盈/挂单/下周/将…)
  HOLD                         : keep / continue holding / keep X% allocation
  REBALANCE                    : explicit move between symbols (VGT↔SGOV 调仓/转到)
  COMMENTARY                   : symbol discussed without a position statement
  UNCLEAR                      : contradictory cues in one sentence (both executed and planned)
Plans are never reported as executed; historical restatements keep the post's own date.
"""
from __future__ import annotations
import hashlib, re

TRACKED = {"麻你": ("VGT", "SGOV")}

EXECUTED = r"已经?买入|已经?买了|买了|已建仓|成交了?|已成交|已经?卖出|卖出了|已卖|卖掉了|已减仓|减仓了|已加仓|加仓了|止盈了|已止盈|filled|bought|sold"
PLANNED = r"准备|计划|打算|将会?|设(?:定|了)?\s*[0-9.]+\s*(?:止盈|卖|挂)|挂单|止盈单|下(?:个)?(?:星期|周|礼拜)|明天|如果|到了?\s*[0-9.]+\s*(?:就|再)"
HOLD = r"继续保持|继续持有|保持|不动|拿着|持有不变|仓位不变|hold"
REBAL = r"调仓|换成|转到|转入|移到|再平衡|rebalanc"
SELL = r"卖出|卖掉|减仓|止盈|清仓|sell|trim"
BUY = r"买入|买了|加仓|建仓|补仓|buy|add"


def _sentences(text):
    parts = re.split(r"(?<=[。！？!?；;\n])", text or "")
    return [re.sub(r"\s+", " ", p).strip() for p in parts if len(re.sub(r"\s+", " ", p).strip()) >= 4]


def _pct_for(sym, s):
    m = re.search(rf"([0-9]{{1,3}}(?:\.[0-9]+)?)\s*%\s*(?:的)?(?:仓位)?\s*(?:在|于|放|是)?\s*{sym}", s, re.I) or \
        re.search(rf"{sym}\s*(?:仓位|总仓位|占)?\s*(?:的)?\s*([0-9]{{1,3}}(?:\.[0-9]+)?)\s*%", s, re.I)
    return float(m.group(1)) if m else None


def classify_sentence(s, symbols):
    hits = [sym for sym in symbols if re.search(rf"(?<![A-Za-z]){sym}(?![A-Za-z])", s, re.I)]
    if not hits:
        return []
    low = s.lower()
    executed, planned = bool(re.search(EXECUTED, low)), bool(re.search(PLANNED, low))
    hold, rebal = bool(re.search(HOLD, low)), bool(re.search(REBAL, low))
    sell, buy = bool(re.search(SELL, low)), bool(re.search(BUY, low))
    price = re.search(r"(?:设|在|到|价格?|@)\s*\$?([0-9]{2,4}\.[0-9]{1,2}|[0-9]{2,4})\s*(?:美元|元)?\s*(?:止盈|卖|挂|买|成交)?", s)
    size = re.search(r"(?:卖出|卖掉|减仓|买入|加仓|止盈)[^0-9%]{0,12}?([0-9]{1,3}(?:\.[0-9]+)?)\s*%", s) or \
        re.search(r"占[^0-9%]{0,10}?总仓位的?\s*([0-9]{1,3}(?:\.[0-9]+)?)\s*%", s)
    # "如果下周没有触发止盈点，那就继续保持90%仓位" is a conditional HOLD, not a sell plan.
    hold_if_not_triggered = hold and bool(re.search(r"没有触发|未触发|不触发|没触发", s))
    out = []
    allocation = {sym: _pct_for(sym, s) for sym in symbols if _pct_for(sym, s) is not None}
    digest = hashlib.sha256(s.encode("utf-8")).hexdigest()
    for sym in hits:
        if executed and planned and not re.search(r"了", s):
            t, conf = "UNCLEAR", "low"
        elif rebal and len(hits) > 1:
            t, conf = ("REBALANCE", "high" if executed else "medium")
        elif hold_if_not_triggered:
            t, conf = "HOLD", "medium"
        elif executed and (sell or buy):
            t, conf = ("SELL_EXECUTED" if sell else "BUY_EXECUTED"), "high"
        elif planned and (sell or buy):
            t, conf = ("SELL_PLANNED" if sell else "BUY_PLANNED"), "high"
        elif hold:
            t, conf = "HOLD", "high" if allocation else "medium"
        elif sell or buy:
            t, conf = ("SELL_PLANNED" if sell else "BUY_PLANNED") if planned else "UNCLEAR", "low"
        else:
            t, conf = "COMMENTARY", "medium"
        out.append({"symbol": sym.upper(), "action_type": t, "confidence": conf,
                    "size_pct": float(size.group(1)) if size and t not in ("HOLD", "COMMENTARY") else None,
                    "price": float(price.group(1)) if price and t not in ("HOLD", "COMMENTARY") else None,
                    "allocation_pct": allocation or None,
                    "evidence_quote": s[:40], "evidence_sha256": digest})
    return out


def extract_author_actions(author, title, text):
    symbols = TRACKED.get(author)
    if not symbols:
        return []
    acts, seen = [], set()
    for s in _sentences(f"{title or ''}\n{text or ''}"):
        for a in classify_sentence(s, symbols):
            key = (a["symbol"], a["action_type"], a["evidence_sha256"])
            if key not in seen:
                seen.add(key); acts.append(a)
    return acts[:20]


def headline(actions):
    """One-line priority: executed > planned > rebalance > hold > commentary; plans labelled 非成交."""
    order = ["SELL_EXECUTED", "BUY_EXECUTED", "REBALANCE", "SELL_PLANNED", "BUY_PLANNED", "HOLD", "UNCLEAR", "COMMENTARY"]
    if not actions:
        return None
    a = sorted(actions, key=lambda x: order.index(x["action_type"]))[0]
    zh = {"SELL_EXECUTED": "已卖出", "BUY_EXECUTED": "已买入", "REBALANCE": "调仓", "SELL_PLANNED": "计划减仓（非成交）",
          "BUY_PLANNED": "计划买入（非成交）", "HOLD": "继续持有", "UNCLEAR": "表述不明确", "COMMENTARY": "仅观点"}[a["action_type"]]
    extra = f" {a['size_pct']:g}%" if a.get("size_pct") else ""
    extra += f" @ {a['price']:g}" if a.get("price") else ""
    alloc = a.get("allocation_pct") or {}
    if a["action_type"] == "HOLD" and alloc:
        extra = " " + " / ".join(f"{k} {v:g}%" for k, v in alloc.items())
    return f"{a['symbol']}：{zh}{extra}"
