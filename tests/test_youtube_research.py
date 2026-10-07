from pathlib import Path
import tempfile
import youtube_research as yt
import research_feed as rf

entries={
 "@RhinoFinance":[{"id":"r2","title":"new"},{"id":"r1","title":"old"}],
 "@老李玩钱":[{"id":"l1","title":"l"}],
 "@AndreiJikh":[{"id":"a1","title":"a"}],
}

def list_channel(url):
    for handle,rows in entries.items():
        if handle in url:return rows
    return []

def meta(url):
    vid=url.split("v=")[-1]
    return {"id":vid,"title":"TITLE "+vid,"webpage_url":url,"upload_date":"20261005"}

def transcript(vid):
    if vid=="a1":return "","unavailable:NoTranscriptFound"
    return "QQQ 第一档 700，第二档 680。TSLA 持有。","youtube_transcript_api"

with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    old_seen,old_status,old_pending,old_feed=yt.SEEN_PATH,yt.STATUS_PATH,yt.PENDING_PATH,rf.FEED_PATH
    yt.SEEN_PATH=td/"seen_youtube.json"
    yt.STATUS_PATH=td/"youtube_source_status.json"
    yt.PENDING_PATH=td/"pending_youtube.json"
    rf.FEED_PATH=td/"research_feed.json"
    try:
        # Initial deployment is baseline-only; old/current videos never enter feed.
        out=yt.collect(list_channel,meta,transcript)
        assert out["status"]=="baseline_established"
        assert out["feed_records_added"]==0
        assert out["discovered_new_videos"]==0
        assert not rf.FEED_PATH.exists()
        assert len(out["channels"])==3
        andrei=[x for x in out["channels"] if x["handle"]=="@AndreiJikh"][0]
        assert andrei["role"]=="market_context"
        assert andrei["latest"]["transcript_available"] is False

        # Re-running same inventory is idempotent.
        out2=yt.collect(list_channel,meta,transcript)
        assert out2["status"]=="ok"
        assert out2["feed_records_added"]==0
        assert out2["discovered_new_videos"]==0

        # A genuinely new video after baseline enters feed exactly once.
        entries["@RhinoFinance"].insert(0,{"id":"r3","title":"brand new"})
        out3=yt.collect(list_channel,meta,transcript)
        assert out3["discovered_new_videos"]==1
        assert out3["feed_records_added"]==1
        feed=rf._read(rf.FEED_PATH,{"records":[]})
        row=feed["records"][0]
        assert row["source"]=="youtube"
        assert row["source_kind"]=="video"
        assert row["author"].startswith("RhinoFinance")
        assert row["transcript_status"]=="youtube_transcript_api"
        assert len(row["excerpt"])<=360
        assert "QQQ" in row["symbols"]
        assert row["source_role"]=="rule_supply"

        # Same video cannot be appended again.
        out4=yt.collect(list_channel,meta,transcript)
        assert out4["feed_records_added"]==0
        assert len(rf._read(rf.FEED_PATH,{"records":[]})["records"])==1
    finally:
        yt.SEEN_PATH,yt.STATUS_PATH,yt.PENDING_PATH,rf.FEED_PATH=old_seen,old_status,old_pending,old_feed

print("PASS youtube source pool baseline/forward-only/idempotency/transcript fallback")


# RSS publication date is preferred when flat yt-dlp metadata lacks upload_date/timestamp.
assert yt._entry_published({"rss_published_at":"2026-10-05T12:34:56+00:00"})=="2026-10-05"
print("PASS YouTube RSS publication-date fallback")


# Active pool deliberately excludes sources without a reliable learning-text path.
handles={x["handle"] for x in yt.CHANNELS}
assert handles=={"@RhinoFinance","@老李玩钱","@AndreiJikh"}
assert "@TianCompounding" not in handles
assert "@NaNaShuoMeiGu" not in handles
print("PASS focused three-author YouTube pool")


# Q3/Q4/Q5 text is context-only and must not create formal operations/rules.
q3row=yt.make_feed_row(
 {"author":"老李玩钱","role":"rule_supply"},
 {"id":"q3","title":"测试","webpage_url":"https://www.youtube.com/watch?v=q3","upload_date":"20261005"},
 {"text":"QQQ 第一档 700，第二档 680。","status":"available","quality":"Q3","provider":"stockvoice.cmoney.tw","provider_url":"x","content_origin":"structured_summary","timestamp_evidence":True,"rule_candidate_allowed":False}
)
assert q3row["operations"]==[]
assert q3row["portfolio_rules"]==[]
assert q3row["rule_candidate_allowed"] is False
print("PASS Q3-Q5 no formal rule extraction")


# Content admission: metadata-only discovery stays outside research_feed, then
# enters exactly once when Q2 text becomes available on a later run.
with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    old_seen,old_status,old_pending,old_feed=yt.SEEN_PATH,yt.STATUS_PATH,yt.PENDING_PATH,rf.FEED_PATH
    yt.SEEN_PATH=td/"seen_youtube.json"
    yt.STATUS_PATH=td/"youtube_source_status.json"
    yt.PENDING_PATH=td/"pending_youtube.json"
    rf.FEED_PATH=td/"research_feed.json"

    local_entries={
      "@RhinoFinance":[{"id":"rb","title":"baseline"}],
      "@老李玩钱":[{"id":"lb","title":"baseline"}],
      "@AndreiJikh":[{"id":"ab","title":"baseline"}],
    }
    phase={"ready":False}
    def local_list(url):
        for handle,rows in local_entries.items():
            if handle in url:return rows
        return []
    def local_meta(url):
        vid=url.split("v=")[-1]
        return {"id":vid,"title":"TITLE "+vid,"webpage_url":url,"upload_date":"20261006"}
    def routed(vid,title="",author=""):
        if vid=="lnew" and phase["ready"]:
            return {
              "text":"00:01 "+"完整转录与明确条件。"*250,
              "status":"available","quality":"Q2","provider":"reducer.xgoose.org",
              "provider_url":"https://reducer.xgoose.org/items/999",
              "content_origin":"third_party_transcript","timestamp_evidence":True,
              "rule_candidate_allowed":True,
            }
        return {
          "text":"","status":"metadata_only","quality":"Q5","provider":"metadata_only",
          "provider_url":"","content_origin":"metadata_only","timestamp_evidence":False,
          "rule_candidate_allowed":False,
        }

    try:
        base=yt.collect(local_list,local_meta,routed)
        assert base["first_run"] is True
        assert base["feed_records_added"]==0
        assert base["pending_total"]==0

        local_entries["@老李玩钱"].insert(0,{
          "id":"lnew","title":"新视频：QQQ分批计划","rss_published_at":"2026-10-06T01:00:00Z"
        })
        q5=yt.collect(local_list,local_meta,routed)
        assert q5["discovered_new_videos"]==1
        assert q5["feed_records_added"]==0
        assert q5["pending_total"]==1
        assert not rf.FEED_PATH.exists()
        pending=yt._read(yt.PENDING_PATH,{"records":[]})["records"]
        assert pending[0]["video_id"]=="lnew"
        assert pending[0]["published_at"]=="2026-10-06"

        # Same video is already seen but is explicitly retried from pending.
        phase["ready"]=True
        q2=yt.collect(local_list,local_meta,routed)
        assert q2["discovered_new_videos"]==0
        assert q2["pending_retried"]==1
        assert q2["admitted_from_pending"]==1
        assert q2["feed_records_added"]==1
        assert q2["pending_total"]==0
        feed=yt._read(rf.FEED_PATH,{"records":[]})["records"]
        assert len(feed)==1
        assert feed[0]["content_quality"]=="Q2"
        assert feed[0]["content_provider"]=="reducer.xgoose.org"
        assert feed[0]["published_at"]=="2026-10-06"

        # No duplicate admission on subsequent run.
        again=yt.collect(local_list,local_meta,routed)
        assert again["feed_records_added"]==0
        assert len(yt._read(rf.FEED_PATH,{"records":[]})["records"])==1
    finally:
        yt.SEEN_PATH,yt.STATUS_PATH,yt.PENDING_PATH,rf.FEED_PATH=old_seen,old_status,old_pending,old_feed

print("PASS pending-content first-admission gate")


# Pending videos must recover when a later channel/RSS listing supplies a
# publication date that was missing at first discovery.
with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    old_seen,old_status,old_pending,old_feed=yt.SEEN_PATH,yt.STATUS_PATH,yt.PENDING_PATH,rf.FEED_PATH
    yt.SEEN_PATH=td/"seen_youtube.json"
    yt.STATUS_PATH=td/"youtube_source_status.json"
    yt.PENDING_PATH=td/"pending_youtube.json"
    rf.FEED_PATH=td/"research_feed.json"

    refresh_entries={
      "@RhinoFinance":[{"id":"rr0","title":"baseline"}],
      "@老李玩钱":[{"id":"ll0","title":"baseline"}],
      "@AndreiJikh":[{"id":"aa0","title":"baseline"}],
    }
    def refresh_list(url):
        for handle,rows in refresh_entries.items():
            if handle in url:return rows
        return []
    def refresh_meta(url):
        vid=url.split("v=")[-1]
        return {"id":vid,"title":"TITLE "+vid,"webpage_url":url}
    refresh_phase={"ready":False}
    def refresh_transcript(vid,title="",author=""):
        if vid=="recover1" and refresh_phase["ready"]:
            return {
              "text":"00:01 "+"完整转录与明确条件。"*250,
              "status":"available","quality":"Q2","provider":"reducer.xgoose.org",
              "provider_url":"https://reducer.xgoose.org/items/recover1",
              "content_origin":"third_party_transcript","timestamp_evidence":True,
              "rule_candidate_allowed":True,
            }
        return {"text":"","status":"metadata_only","quality":"Q5","provider":"metadata_only",
                "provider_url":"","content_origin":"metadata_only","timestamp_evidence":False,
                "rule_candidate_allowed":False}
    try:
        yt.collect(refresh_list,refresh_meta,refresh_transcript)
        refresh_entries["@老李玩钱"].insert(0,{"id":"recover1","title":"新视频，无日期"})
        first=yt.collect(refresh_list,refresh_meta,refresh_transcript)
        assert first["pending_total"]==1
        assert first["feed_records_added"]==0

        # Same seen video now has RSS publication metadata. It must be retried
        # with the refreshed entry rather than stale pending metadata.
        refresh_entries["@老李玩钱"][0]["rss_published_at"]="2026-10-07T01:00:00Z"
        refresh_phase["ready"]=True
        recovered=yt.collect(refresh_list,refresh_meta,refresh_transcript)
        assert recovered["discovered_new_videos"]==0
        assert recovered["pending_retried"]==1
        assert recovered["admitted_from_pending"]==1
        assert recovered["pending_total"]==0
        assert recovered["feed_records_added"]==1
        feed=yt._read(rf.FEED_PATH,{"records":[]})["records"]
        assert feed[-1]["published_at"]=="2026-10-07"
        assert feed[-1]["content_quality"]=="Q2"
    finally:
        yt.SEEN_PATH,yt.STATUS_PATH,yt.PENDING_PATH,rf.FEED_PATH=old_seen,old_status,old_pending,old_feed

print("PASS pending YouTube metadata refresh from live listing")


# High-quality YouTube text without a reproducible publication timestamp is
# useful for semantic learning but must be admitted only as backfill/non-forward.
with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    old_seen,old_status,old_pending,old_feed=yt.SEEN_PATH,yt.STATUS_PATH,yt.PENDING_PATH,rf.FEED_PATH
    yt.SEEN_PATH=td/"seen_youtube.json"
    yt.STATUS_PATH=td/"youtube_source_status.json"
    yt.PENDING_PATH=td/"pending_youtube.json"
    rf.FEED_PATH=td/"research_feed.json"
    unknown_entries={
      "@RhinoFinance":[{"id":"ub","title":"baseline"}],
      "@老李玩钱":[{"id":"ulb","title":"baseline"}],
      "@AndreiJikh":[{"id":"uab","title":"baseline"}],
    }
    def unknown_list(url):
        for handle,rows in unknown_entries.items():
            if handle in url:return rows
        return []
    def unknown_meta(url):
        vid=url.split("v=")[-1]
        return {"id":vid,"title":"TITLE "+vid,"webpage_url":url}
    def unknown_transcript(vid,title="",author=""):
        if vid=="u1":
            return {
              "text":"00:01 "+"完整转录与明确条件。"*250,
              "status":"available","quality":"Q2","provider":"reducer.xgoose.org",
              "provider_url":"https://reducer.xgoose.org/items/u1",
              "content_origin":"third_party_transcript","timestamp_evidence":True,
              "rule_candidate_allowed":True,
            }
        return {"text":"","status":"metadata_only","quality":"Q5","provider":"metadata_only",
                "provider_url":"","content_origin":"metadata_only","timestamp_evidence":False,
                "rule_candidate_allowed":False}
    try:
        yt.collect(unknown_list,unknown_meta,unknown_transcript)
        unknown_entries["@老李玩钱"].insert(0,{"id":"u1","title":"有正文但缺发布时间"})
        out=yt.collect(unknown_list,unknown_meta,unknown_transcript)
        assert out["feed_records_added"]==1
        assert out["pending_total"]==0
        assert out["nonforward_timestamp_unknown_admitted"]==1
        row=yt._read(rf.FEED_PATH,{"records":[]})["records"][-1]
        assert row["published_at"]==""
        assert row["intake_class_hint"]=="backfill"
        assert row["capture_mode"]=="youtube_timestamp_unknown_learning"
        assert row["timestamp_confidence"]=="missing"
        assert row["forward_evidence_eligible"] is False
    finally:
        yt.SEEN_PATH,yt.STATUS_PATH,yt.PENDING_PATH,rf.FEED_PATH=old_seen,old_status,old_pending,old_feed

print("PASS timestamp-unknown YouTube text is learning-only/backfill")
