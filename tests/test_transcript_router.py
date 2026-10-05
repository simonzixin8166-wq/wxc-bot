import transcript_router as tr

def official_ok(video_id):
    return ("这是完整字幕 "*120, "youtube_transcript_api")

q1=tr.acquire("abc","标题","作者",official_fetcher=official_ok)
assert q1["quality"]=="Q1"
assert q1["provider"]=="youtube_official"
assert q1["rule_candidate_allowed"] is True
assert q1["chars"]>=500

def official_fail(video_id):
    return ("","unavailable:RequestBlocked")

# Fail-closed when no provider is found.
old_direct=tr._direct_pickscribe
old_search=tr._duckduckgo_links
try:
    tr._direct_pickscribe=lambda *args,**kwargs: None
    tr._duckduckgo_links=lambda *args,**kwargs: []
    q5=tr.acquire("none","No transcript","Author",official_fetcher=official_fail)
    assert q5["quality"]=="Q5"
    assert q5["provider"]=="metadata_only"
    assert q5["rule_candidate_allowed"] is False
    assert q5["text"]==""
finally:
    tr._direct_pickscribe=old_direct
    tr._duckduckgo_links=old_search

# Quality policy: structured summaries remain thesis-only.
text="Detailed brief\nOriginal source\n原片 · 跳到 5:47\n"+"投资观点与条件。"*180
quality,ts,allowed=tr._quality_for("stockvoice.cmoney.tw",text)
assert quality=="Q3"
assert allowed is False

# Full third-party transcript can form a candidate, but provenance remains third-party.
full="Transcript\n00:01 "+"This is a full transcript with investment reasoning. "*100
quality,ts,allowed=tr._quality_for("pickscribe.com",full)
assert quality=="Q2"
assert allowed is True
assert ts is True

pub=tr.public_view({
    "status":"available","quality":"Q2","provider":"pickscribe.com",
    "provider_url":"https://pickscribe.com/v/x/","content_origin":"third_party_transcript",
    "timestamp_evidence":True,"rule_candidate_allowed":True,"chars":3000,
    "note":"test","text":"DO NOT EXPOSE"
})
assert "text" not in pub
assert pub["quality"]=="Q2"

print("PASS transcript acquisition router quality/provenance/fail-closed")


# Provider-native xgoose lookup requires exact source YouTube video id.
class FakeResp:
    def __init__(self,data,ok=True): self._data=data; self.ok=ok
    def json(self): return self._data

old_get=tr.requests.get
try:
    def fake_get(url,params=None,headers=None,timeout=None,allow_redirects=True):
        if url.endswith("/api/items"):
            return FakeResp([{
                "id":4008,
                "title":"10月必买3支股票",
                "source_url":"https://www.youtube.com/watch?v=qVSoCX8pVDg",
            }])
        if url.endswith("/api/items/4008"):
            return FakeResp({
                "id":4008,
                "source_url":"https://www.youtube.com/watch?v=qVSoCX8pVDg",
                "transcript":{"text":"00:01 "+"完整视频转录内容。"*500,"segments":[{"start":1,"text":"x"}]},
                "summary":{"markdown":"summary"}
            })
        return FakeResp({},False)
    tr.requests.get=fake_get
    got=tr._xgoose_native("qVSoCX8pVDg","10月必买3支股票","老李玩钱")
    assert got is not None
    assert got.quality=="Q2"
    assert got.provider=="reducer.xgoose.org"
    assert got.rule_candidate_allowed is True
    assert got.timestamp_evidence is True

    # Similar title but wrong original video id must not match.
    miss=tr._xgoose_native("WRONGID","10月必买3支股票","老李玩钱")
    assert miss is None
finally:
    tr.requests.get=old_get

assert tr._source_video_id("https://www.youtube.com/watch?v=abc123&t=10")=="abc123"
assert tr._source_video_id("https://youtu.be/xyz987")=="xyz987"
print("PASS xgoose provider-native exact-video-id transcript lookup")


# Historical author discovery accepts only rows whose provider author identity matches.
old_get=tr.requests.get
try:
    def fake_author_get(url,params=None,headers=None,timeout=None,allow_redirects=True):
        if url.endswith("/api/items"):
            return FakeResp([
                {"id":1,"author":"Other","title":"美股","source_url":"https://www.youtube.com/watch?v=wrong"},
                {"id":2,"author":"视野环球财经","title":"美股 QQQ","source_url":"https://www.youtube.com/watch?v=rhino1","published_at":"2026-09-22"},
            ])
        if url.endswith("/api/items/2"):
            return FakeResp({
                "id":2,"author":"视野环球财经","title":"美股 QQQ",
                "source_url":"https://www.youtube.com/watch?v=rhino1",
                "published_at":"2026-09-22",
                "transcript":{"text":"00:01 "+"完整公开视频转录。"*500,"segments":[{"start":1,"text":"x"}]},
            })
        return FakeResp({},False)
    tr.requests.get=fake_author_get
    sample=tr.discover_xgoose_author_sample(["视野环球财经","rhinofinance"],["美股"])
    assert sample is not None
    assert sample["video_id"]=="rhino1"
    assert sample["acquisition"]["quality"]=="Q2"
    assert sample["acquisition"]["provider"]=="reducer.xgoose.org"
finally:
    tr.requests.get=old_get
print("PASS xgoose historical author Q2 discovery")
