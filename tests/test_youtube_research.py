from pathlib import Path
import tempfile
import youtube_research as yt
import research_feed as rf

entries={
 "@RhinoFinance":[{"id":"r2","title":"new"},{"id":"r1","title":"old"}],
 "@TianCompounding":[{"id":"t1","title":"t"}],
 "@NaNaShuoMeiGu":[{"id":"n1","title":"n"}],
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
    old_seen,old_status,old_feed=yt.SEEN_PATH,yt.STATUS_PATH,rf.FEED_PATH
    yt.SEEN_PATH=td/"seen_youtube.json"
    yt.STATUS_PATH=td/"youtube_source_status.json"
    rf.FEED_PATH=td/"research_feed.json"
    try:
        # Initial deployment is baseline-only; old/current videos never enter feed.
        out=yt.collect(list_channel,meta,transcript)
        assert out["status"]=="baseline_established"
        assert out["feed_records_added"]==0
        assert out["discovered_new_videos"]==0
        assert not rf.FEED_PATH.exists()
        assert len(out["channels"])==5
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
        yt.SEEN_PATH,yt.STATUS_PATH,rf.FEED_PATH=old_seen,old_status,old_feed

print("PASS youtube source pool baseline/forward-only/idempotency/transcript fallback")


# RSS publication date is preferred when flat yt-dlp metadata lacks upload_date/timestamp.
assert yt._entry_published({"rss_published_at":"2026-10-05T12:34:56+00:00"})=="2026-10-05"
print("PASS YouTube RSS publication-date fallback")
