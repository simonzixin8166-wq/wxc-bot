#!/usr/bin/env python3
"""Non-gating health probe for public YouTube transcript providers.

Uses known historical/public videos only to verify provider capability.
Never appends to research_feed and never creates forward evidence.
"""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
import transcript_router as tr

DATA_DIR=Path(os.getenv("DATA_DIR","state"))
OUT=DATA_DIR/"youtube_provider_health.json"

PROBES=[
    {
        "author":"RhinoFinance / 视野环球财经",
        "video_id":"gm7968MOWmo",
        "title":"美股 QQQ收盘新高！AMZN出售芯片不过了？SOXX跟随SMH突破！TSLA交付超预期！APP下个避险位置！",
        "role":"rule_supply",
    },
    {
        "author":"老李玩钱",
        "video_id":"qVSoCX8pVDg",
        "title":"10月必买3支股票",
        "role":"rule_supply",
    },
    {
        "author":"Andrei Jikh",
        "video_id":"5E-9UYj7mqo",
        "title":"Federal Reserve",
        "role":"market_context",
    },
    {
        "author":"老李玩钱",
        "video_id":"PQTHnECMKkQ",
        "title":"2025年底前，我打算卖出和买入的5支股票",
        "role":"rule_supply",
    },
    {
        "author":"老李玩钱",
        "video_id":"-Wz5ML0OMMk",
        "title":"2026存储和太空两大热门板块！如何布局，买入什么股票",
        "role":"rule_supply",
    },
    {
        "author":"老李玩钱",
        "video_id":"FqN2N9NJ00M",
        "title":"美股：TSLA，GOOG！财报解读，操作建议",
        "role":"rule_supply",
    },
    {
        "author":"Andrei Jikh",
        "video_id":"gRrHFoDzRHs",
        "title":"The Stock Market Is About To Flip",
        "role":"market_context",
    },
    {
        "author":"Andrei Jikh",
        "video_id":"tTaIuYhWloE",
        "title":"How The Fed Is Crashing The Market",
        "role":"market_context",
    },
    {
        "author":"Andrei Jikh",
        "video_id":"W9If7NZiTDU",
        "title":"Official Announcement: Recession Is Here",
        "role":"market_context",
    },
    {
        "author":"Andrei Jikh",
        "video_id":"3FZipnSI_po",
        "title":"Japan Just Broke the Global Economy (Worse Than Greece)",
        "role":"market_context",
    },
    {
        "author":"Andrei Jikh",
        "video_id":"9X3h3swRftY",
        "title":"BREAKING: The Bond Market Is Collapsing (JPMorgan’s Final Warning)",
        "role":"market_context",
    },
    {
        "author":"Andrei Jikh",
        "video_id":"T9h9BMhpdaA",
        "title":"The Tariffs Just Broke the System (And It's All On Purpose)",
        "role":"market_context",
    },
    {
        "author":"Andrei Jikh",
        "video_id":"nY234RoQeHw",
        "title":"I Asked ChatGPT To Make Me As Much Money As Possible",
        "role":"market_context",
    },
    {
        "author":"老李玩钱",
        "video_id":"5382scR8EJ8",
        "title":"12月美股：需谨慎！我的买卖、操作计划",
        "role":"rule_supply",
    },
    {
        "author":"老李玩钱",
        "video_id":"A4Nl1xhmlqo",
        "title":"20万美股账户，2025复盘总结，我的经验教训！2026股票持仓计划",
        "role":"rule_supply",
    },
]

def main():
    rows=[]
    for p in PROBES:
        result=tr.acquire(p["video_id"],p["title"],p["author"])
        public=tr.public_view(result)
        rows.append({**p,**public})
    out={
        "version":1,
        "generated_at":datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "non_gating":True,
        "historical_diagnostic_only":True,
        "probe_count":len(rows),
        "available_count":sum(1 for r in rows if r.get("quality")!="Q5"),
        "rule_candidate_capable_count":sum(1 for r in rows if r.get("rule_candidate_allowed")),
        "probes":rows,
        "guardrail":"Diagnostic probes never enter research_feed, Source Store, Rule Registry, EventScore, Promotion, or Readiness.",
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:out[k] for k in ("probe_count","available_count","rule_candidate_capable_count")},ensure_ascii=False))

if __name__=="__main__":
    main()
