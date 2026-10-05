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
    assert r["excerpt"]==""

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


# Provider chrome is removed before semantic learning and public snippets stay bounded.
noisy="Scribe\nGet Chrome Extension\nBrowse\nFederal Reserve interest rate cuts and inflation matter.\n"
clean=yla.clean_learning_text(noisy)
assert "Get Chrome Extension" not in clean
assert "Federal Reserve" in clean

# Third-party examples are not retained as creator-owned operations in the historical archive.
old_acquire=yla.tr.acquire
old_extract=yla.rf.extract_structured_learning
try:
    yla.tr.acquire=lambda *args,**kwargs:{
        "text":"作者讨论巴菲特买入NVDA，也讲自己的计划。"*60,
        "quality":"Q2","provider":"test","provider_url":"u",
        "content_origin":"third_party_transcript","timestamp_evidence":True,
        "rule_candidate_allowed":True,
    }
    yla.rf.extract_structured_learning=lambda text:{
        "symbols":["NVDA"],
        "operations":[
            {"symbols":["NVDA"],"actions":["buy"],"attribution":"third_party_example"},
            {"symbols":["NVDA"],"actions":["hold"],"attribution":"author_plan"},
        ],
        "portfolio_rules":[],"lessons":[]
    }
    x=yla.build_probe({"author":"A","video_id":"x","title":"x","role":"rule_supply"})
    assert len(x["operations"])==1
    assert x["operations"][0]["attribution"]=="author_plan"
    assert x["excerpt"]==""
    assert x["representative_points"]==[]
finally:
    yla.tr.acquire=old_acquire
    yla.rf.extract_structured_learning=old_extract

print("PASS historical YouTube archive quality cleanup")


# Market-context archive filters ambiguous English ticker NOW unless ServiceNow is explicit.
old_acquire=yla.tr.acquire
old_extract=yla.rf.extract_structured_learning
try:
    yla.tr.acquire=lambda *args,**kwargs:{
        "text":"The Fed changed everything NOW and Tesla was mentioned. "*60,
        "quality":"Q2","provider":"test","provider_url":"u",
        "content_origin":"third_party_transcript","timestamp_evidence":True,
        "rule_candidate_allowed":True,
    }
    yla.rf.extract_structured_learning=lambda text:{
        "symbols":["NOW","TSLA"],"operations":[],"portfolio_rules":[],"lessons":[]
    }
    m=yla.build_probe({"author":"Andrei Jikh","video_id":"m","title":"Macro","role":"market_context"})
    assert "NOW" not in m["symbols"]
    assert "TSLA" in m["symbols"]
finally:
    yla.tr.acquire=old_acquire
    yla.rf.extract_structured_learning=old_extract

print("PASS structured-only historical learning persistence")


# Historical learning quality must be monotonic across provider outages.
prior={
    "video_id":"keep-q2","quality":"Q2","provider":"good-provider",
    "provider_url":"https://example/q2","content_origin":"third_party_transcript",
    "timestamp_evidence":True,"rule_candidate_capable_at_source":True,
    "historical_learning_eligible":True,"text_chars_seen":5000,"text_hash":"abc",
    "symbols":["QQQ"],"themes":["风险管理"],"macro_topics":["利率/Fed"],
    "operations":[],"portfolio_rules":[],"lessons":[],"representative_points":[],
}
current={
    "video_id":"keep-q2","quality":"Q5","provider":"metadata_only",
    "provider_url":"","content_origin":"metadata_only","timestamp_evidence":False,
    "rule_candidate_capable_at_source":False,"historical_learning_eligible":False,
    "text_chars_seen":0,"text_hash":None,"symbols":[],"themes":[],"macro_topics":[],
    "operations":[],"portfolio_rules":[],"lessons":[],"representative_points":[],
    "forward_evidence_eligible":False,"promotion_eligible":False,"event_score_eligible":False,
}
merged=yla.merge_with_prior(current,prior)
assert merged["quality"]=="Q2"
assert merged["provider"]=="good-provider"
assert merged["historical_learning_eligible"] is True
assert merged["retained_prior_best_quality"] is True
assert merged["last_probe_quality"]=="Q5"
assert merged["forward_evidence_eligible"] is False
print("PASS historical YouTube best-quality retention")


# One acquisition pass also derives non-gating provider health.
health=yla.provider_health_from_rows([
    {"author":"A","video_id":"x","title":"x","role":"rule_supply","quality":"Q2","provider":"pickscribe.com","provider_url":"u","content_origin":"third_party_transcript","timestamp_evidence":True,"rule_candidate_capable_at_source":True,"text_chars_seen":2500},
    {"author":"B","video_id":"y","title":"y","role":"market_context","quality":"Q5","provider":"metadata_only","provider_url":"","content_origin":"metadata_only","timestamp_evidence":False,"rule_candidate_capable_at_source":False,"text_chars_seen":0},
])
assert health["non_gating"] is True
assert health["probe_count"]==2
assert health["available_count"]==1
assert health["rule_candidate_capable_count"]==1
assert all("text" not in x for x in health["probes"])
print("PASS single-pass provider health derivation")


# Static historical probes use retry backoff; explicit force refresh overrides.
from datetime import datetime, timezone, timedelta
recent={"quality":"Q5","last_probe_at":datetime.now(timezone.utc).isoformat()}
assert yla.should_probe(recent,datetime.now(timezone.utc)) is False
old={"quality":"Q5","last_probe_at":(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()}
assert yla.should_probe(old,datetime.now(timezone.utc)) is True
kept=yla.reuse_prior_probe({"video_id":"x","quality":"Q2","historical_learning_eligible":True,"forward_evidence_eligible":False,"promotion_eligible":False,"event_score_eligible":False})
assert kept["probe_skipped_backoff"] is True
assert kept["historical_learning_eligible"] is True
print("PASS historical YouTube retry backoff")


# Legacy archive rows can inherit document generated_at for retry backoff migration.
legacy_doc={"generated_at":datetime.now(timezone.utc).isoformat(),"records":[{"video_id":"legacy","quality":"Q2","historical_learning_eligible":True}]}
row=dict(legacy_doc["records"][0]);row["last_probe_at"]=legacy_doc["generated_at"]
assert yla.should_probe(row,datetime.now(timezone.utc)) is False
print("PASS legacy generated_at retry migration")
