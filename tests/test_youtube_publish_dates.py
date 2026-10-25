"""SRC-01: YouTube publication dates - RSS failures are recorded (not silent), a just-discovered undated video waits
for its date instead of being admitted as permanently non-forward, and dates found later are recorded append-only
without rewriting the feed row (#133 6391860281: b_ZVO8_QfJ0 lost its date to one failed RSS fetch)."""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import youtube_research as yt

yt.time.sleep = lambda s: None
XML = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<entry><yt:videoId>b_ZVO8_QfJ0</yt:videoId><published>2026-10-24T03:10:00+00:00</published><title>t</title></entry></feed>"""


class R:
    def __init__(self, code, text=""):
        self.status_code, self.text = code, text

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(self.status_code)


calls = []
def flaky(url, timeout=None, headers=None):
    calls.append(url)
    return R(500) if len(calls) == 1 else R(200, XML)
got = yt._rss_entries("UC1", get=flaky)
assert len(calls) == 2 and got["b_ZVO8_QfJ0"]["rss_published_at"].startswith("2026-10-24") and yt.RSS_STATUS["UC1"] == "ok"
assert yt._rss_entries("UC2", get=lambda *a, **k: R(503)) == {} and yt.RSS_STATUS["UC2"] == "error:RuntimeError"
assert yt._rss_entries("UC3", get=lambda *a, **k: R(200, "<feed xmlns='http://www.w3.org/2005/Atom'/>")) == {}
assert yt.RSS_STATUS["UC3"] == "empty"
assert yt._rss_entries("", get=flaky) == {}

now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
assert yt._within_date_hold(None, now) is True                                   # discovered this run
assert yt._within_date_hold({"first_discovered_at": iso(now - timedelta(hours=10))}, now) is True
assert yt._within_date_hold({"first_discovered_at": iso(now - timedelta(hours=49))}, now) is False
assert yt._within_date_hold({"first_discovered_at": "2026-10-08T04:06:13Z"}, now) is False  # old backlog unaffected

with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "youtube_published_dates.jsonl"
    feed = [{"id": "r1", "source": "youtube", "url": "https://www.youtube.com/watch?v=b_ZVO8_QfJ0", "published_at": ""},
            {"id": "r2", "source": "youtube", "url": "https://www.youtube.com/watch?v=DATED000000", "published_at": "2026-10-20"},
            {"id": "r3", "source": "wenxuecity", "url": "https://bbs/x", "published_at": ""}]
    ch = {"author": "RhinoFinance / 视野环球财经"}
    entries = {"b_ZVO8_QfJ0": (ch, {"rss_published_at": "2026-10-24T03:10:00+00:00"}),
               "DATED000000": (ch, {"rss_published_at": "2026-10-20T01:00:00+00:00"}),
               "NODATE00000": (ch, {})}
    out = yt.resolve_feed_dates(entries, feed, path=p, now="T")
    assert [x["video_id"] for x in out] == ["b_ZVO8_QfJ0"] and out[0]["feed_row_id"] == "r1"
    assert out[0]["forward_evidence_eligible"] is False and out[0]["source"] == "youtube_rss"
    assert yt.resolve_feed_dates(entries, feed, path=p, now="T2") == []          # append-only, once per video
    assert len(p.read_text().splitlines()) == 1 and feed[0]["published_at"] == ""  # feed row never rewritten

src = (REPO / "youtube_research.py").read_text(encoding="utf-8")
assert '"rss_status":newest.get("rss_status")' in src and '"publication_dates_resolved"' in src
wf = (REPO / ".github" / "workflows" / "youtube-forward-intake.yml").read_text(encoding="utf-8")
assert "state/youtube_published_dates.jsonl" in wf
print("PASS SRC-01 YouTube publication dates: RSS failures recorded + retried, undated new videos wait, late dates appended")
