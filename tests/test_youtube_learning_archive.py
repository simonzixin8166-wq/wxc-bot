import tempfile
from pathlib import Path
import youtube_learning_archive as yla

# Deterministic local stubs: one Q2 rule-supply sample, one Q2 market-context,
# one Q5 unavailable sample.
old_acquire=yla.tr.acquire
try:
    def fake_acquire(video_id,title,author):
        if video_id=="rule":
            return {
                "text":"QQQ 第一档 700，第二档 680，跌破 650 退出。"*60,
                "quality":"Q2","provider":"test","provider_url":"u",
                "content_origin":"third_party_transcript","timestamp_evidence":True,
                "rule_candidate_allowed":True,
            }
        if video_id=="macro":
            return {
                "text":"Federal Reserve interest rate cuts, inflation, Treasury yields, dollar, gold and Bitcoin matter for the economy. "*80,
                "quality":"Q2","provider":"test","provider_url":"u",
                "content_origin":"third_party_transcript","timestamp_evidence":True,
                "rule_candidate_allowed":True,
            }
        return {
            "text":"","quality":"Q5","provider":"metadata_only","provider_url":"",
            "content_origin":"metadata_only","timestamp_evidence":False,
            "rule_candidate_allowed":False,
        }
    yla.tr.acquire=fake_acquire

    r=yla.build_probe({"author":"A","video_id":"rule","title":"计划","role":"rule_supply"})
    assert r["historical_learning_eligible"] is True
    assert r["forward_evidence_eligible"] is False
    assert r["promotion_eligible"] is False
    assert r["event_score_eligible"] is False
    assert r["text_hash"]
    assert len(r["excerpt"])<=360

    m=yla.build_probe({"author":"B","video_id":"macro","title":"Fed","role":"market_context"})
    assert m["historical_learning_eligible"] is True
    assert "利率/Fed" in m["macro_topics"]
    assert "黄金" in m["macro_topics"]
    assert "加密资产" in m["macro_topics"]

    q5=yla.build_probe({"author":"C","video_id":"none","title":"none","role":"rule_supply"})
    assert q5["historical_learning_eligible"] is False
    assert q5["operations"]==[]
    assert q5["representative_points"]==[]
finally:
    yla.tr.acquire=old_acquire

print("PASS historical YouTube learning archive isolation/quality")
