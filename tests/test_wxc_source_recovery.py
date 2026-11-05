"""WXC-RECOVERY-DIAGNOSTIC (Owner 2026-11-05) §6: local mocks only, no network.

 1 category discovery         2 overview discovery        3 monthly archive discovery
 4 multi-entry dedup          5 403 stops at once         6 429 stops at once
 7 article failure -> not complete                        8 structure change -> not "zero new"
 9 a summary / listing title is never reported as full text
10 Research Feed is never shrunk or rewritten; first-capture times are kept
 + the diagnostic probe: 403 stops its family, the report holds no HTML.
"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wxc_blog as blog  # noqa: E402
import research_feed as rf  # noqa: E402
import wxc_source_diagnostic as diag  # noqa: E402

BID = "82458"
A1 = f"/myblog/{BID}/202609/111.html"
A2 = f"/myblog/{BID}/202609/222.html"
A3 = f"/myblog/{BID}/202609/333.html"
ARTICLE = """<html><head><title>t</title></head><body><h1 id="titleName">{t}</h1><div id="time">2026-09-30 08:00:00</div>
<div id="articalContent"><p>正文 {t} 第一段。</p></div></body></html>"""


def page(*hrefs, extra=""):
    return "<html><body>" + "".join(f'<a href="{h}">x</a>' for h in hrefs) + extra + "</body></html>"


class R:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.apparent_encoding = "utf-8"
        self.encoding = "utf-8"


def run_collect(routes, category=False):
    """routes(url) -> R | None, used as blog.get."""
    old = (blog.get, blog.download_image, blog.CATEGORY_DISCOVERY)
    blog.reset_access_state()
    blog._CATEGORY_CACHE.clear()
    blog.get = lambda url, delay=0: routes(url)
    blog.download_image = lambda *a, **k: None
    blog.CATEGORY_DISCOVERY = category
    try:
        with tempfile.TemporaryDirectory() as td:
            return blog.collect(blog.resolve_profile("BrightLine"), datetime(2026, 9, 30), datetime(2026, 9, 30, 23, 59, 59),
                                td, delay=0, max_articles=None, max_images=0)
    finally:
        blog.get, blog.download_image, blog.CATEGORY_DISCOVERY = old
        blog._CATEGORY_CACHE.clear()


def router(archive=page(), overview=page(f"/myoverview/{BID}/"), category=page(), article_fail=()):
    def f(url):
        if url.endswith(".html"):
            if any(url.endswith(x) for x in article_fail):
                return None
            return R(ARTICLE.format(t=url.rsplit("/", 1)[1]))
        if "act=moreList" in url:
            return R(category) if category is not None else None
        if "/myoverview/" in url:
            return R(overview) if overview is not None else None
        return R(archive) if archive is not None else None
    return f


# 1. category discovery (flag on): an article only the finance category lists is found and tagged
res = run_collect(router(archive=page(f"/myblog/{BID}/"), category=page(A3, "/myblog/99999/202609/9.html")), category=True)
assert [p["url"].rsplit("/", 1)[1] for p in res["posts"]] == ["333.html"], res["posts"]
assert res["posts"][0]["discovered_by"] == ["category_cjjr"]
assert res["category_success"] is True and res["scan_complete"] is True
cat = blog.parse_category(page(A3, "/myblog/99999/202609/9.html"), [BID])
assert cat["links_total"] == 2 and cat["unattributed_links"] == 1 and len(cat["by_blog_id"][BID]) == 1
# category on but unreadable -> not complete
res = run_collect(router(archive=page(A1), category=None), category=True)
assert res["category_success"] is False and res["scan_complete"] is False and res["partial_scan"] is True
print("PASS 1 category discovery")

# 2. overview discovery: archive is empty but valid; overview lists the post
res = run_collect(router(archive=page(f"/myblog/{BID}/"), overview=page(A2)))
assert [p["discovered_by"] for p in res["posts"]] == [["overview"]] and res["scan_complete"] is True
print("PASS 2 overview discovery")

# 3. monthly archive discovery
res = run_collect(router(archive=page(A1)))
assert [p["discovered_by"] for p in res["posts"]] == [["archive"]]
assert res["archive_success"] == ["2026-09"] and res["scan_complete"] is True
print("PASS 3 monthly archive discovery")

# 4. multi-entry dedup: same article from archive + overview + category is fetched and kept once
fetched = []
base = router(archive=page(A1, A1), overview=page(A1), category=page(A1))
res = run_collect(lambda u: (fetched.append(u) if u.endswith(".html") else None) or base(u), category=True)
assert len(res["posts"]) == 1 and res["article_links_found"] == 1 and len(fetched) == 1
assert res["posts"][0]["discovered_by"] == ["archive", "category_cjjr", "overview"]
print("PASS 4 multi-entry dedup")


# 5/6. 403 and 429 stop at once: one request, no retry, host marked, later requests to that host skipped
class FakeSess:
    def __init__(self, status):
        self.status, self.calls = status, []

    def get(self, url, timeout=25):
        self.calls.append(url)
        return R("denied", self.status)


for code in (403, 429):
    old_sess, old_sleep = blog.sess, blog.time.sleep
    blog.sess, blog.time.sleep = FakeSess(code), (lambda s: None)
    blog.reset_access_state()
    try:
        assert blog.get(blog.archive_url(BID, 2026, 9), retries=3, delay=0) is None
        assert len(blog.sess.calls) == 1, blog.sess.calls          # no retry
        assert blog.access_restricted() is True
        assert blog.get(blog.overview_url(BID), delay=0) is None
        assert len(blog.sess.calls) == 1                           # same host skipped, no request sent
        assert [x["status"] for x in blog.ACCESS_LOG] == [code, "skipped_host_restricted"]
    finally:
        blog.sess, blog.time.sleep = old_sess, old_sleep
        blog.reset_access_state()
    print(f"PASS {5 if code == 403 else 6} HTTP {code} stops immediately")

# a refused run is never complete (collector level, with the real get on a 403 session)
old_sess, old_sleep = blog.sess, blog.time.sleep
blog.sess, blog.time.sleep = FakeSess(403), (lambda s: None)
blog.reset_access_state()
try:
    with tempfile.TemporaryDirectory() as td:
        res = blog.collect(blog.resolve_profile("BrightLine"), datetime(2026, 9, 30), datetime(2026, 9, 30), td,
                           delay=0, max_images=0)
    assert len(blog.sess.calls) == 1 and res["access_restricted"] is True
    assert res["scan_complete"] is False and res["partial_scan"] is True and res["posts"] == []
finally:
    blog.sess, blog.time.sleep = old_sess, old_sleep
    blog.reset_access_state()

# 7. article fetch / parse failure blocks a complete scan
res = run_collect(router(archive=page(A1, A2), article_fail=("222.html",)))
assert res["scan_complete"] is False and res["article_fetch_failures"] == ["https://blog.wenxuecity.com" + A2]
assert res["fetch_status_counts"] == {"discovered_not_fetched": 1, "fulltext_fetched": 1}
res = run_collect(lambda u: R("<html><body>nothing</body></html>") if u.endswith(".html") else router(archive=page(A1))(u))
assert res["scan_complete"] is False and len(res["article_parse_failures"]) == 1
print("PASS 7 article failure blocks complete scan")

# 8. structure change: 200 page without links and without the author's blog id is a failure, not "0 new"
res = run_collect(router(archive="<html><body>维护中</body></html>", overview="<html><body>new layout</body></html>"))
assert res["scan_complete"] is False and res["archive_failures"] == ["2026-09"] and res["overview_ok"] is False
assert len(res["structure_unrecognized"]) == 2 and res["posts"] == []
print("PASS 8 structure change is not zero-new")

# 9. a listing title / summary is never reported as full text
res = run_collect(router(archive=page(A1, A2), article_fail=("222.html",)))
assert [p["fetch_status"] for p in res["posts"]] == ["fulltext_fetched"]   # the unfetched one is not a post at all
row = rf.normalize("blog", "BrightLine", {"title": "只有标题", "url": "https://blog.wenxuecity.com" + A2, "date": "2026-09-30"})
assert row["excerpt"] == "" and row["content_chars"] == 0 and "text" not in row
long = rf.normalize("blog", "BrightLine", {"title": "t", "text": "字" * 2000, "url": "u", "date": "2026-09-30"})
assert len(long["excerpt"]) <= 360 and "text" not in long and long["content_chars"] == 2000
print("PASS 9 summary never reported as full text")

# 10. Research Feed append-only: never shrinks, never rewrites captured_at / published_at
with tempfile.TemporaryDirectory() as td:
    old_feed = rf.FEED_PATH
    rf.FEED_PATH = Path(td) / "research_feed.json"
    try:
        r1 = rf.normalize("blog", "BrightLine", {"title": "a", "text": "正文", "url": "https://x/1", "date": "2026-09-01"})
        r1["captured_at"] = "2026-09-01T00:00:00Z"
        r2 = rf.normalize("blog", "BrightLine", {"title": "b", "text": "正文", "url": "https://x/2", "date": "2026-09-02"})
        r2["captured_at"] = "2026-09-02T00:00:00Z"
        assert rf.append_records([r1, r2]) == 2
        again = dict(r1, captured_at="2026-11-05T00:00:00Z", published_at="2026-11-05", title="改写")
        assert rf.append_records([again]) == 0
        assert rf.append_records([]) == 0
        recs = json.loads(rf.FEED_PATH.read_text(encoding="utf-8"))["records"]
        assert len(recs) == 2
        kept = {x["id"]: x for x in recs}[r1["id"]]
        assert kept["captured_at"] == "2026-09-01T00:00:00Z" and kept["published_at"] == "2026-09-01" and kept["title"] == "a"
    finally:
        rf.FEED_PATH = old_feed
print("PASS 10 research feed append-only, first capture kept")

# diagnostic probe: a 403 stops its family; HTML is never in the report
calls = []


def fake_fetch(url, timeout=25):
    calls.append(url)
    if "act=moreList" in url:
        return R(page(A1, extra="<p>SECRET_HTML_MARKER</p>"))
    if "/myoverview/" in url or "/myblog/" in url and not url.endswith(".html"):
        return R("denied", 403)
    if url.endswith(".html"):
        return R(ARTICLE.format(t="SECRET_HTML_MARKER"))
    return R('<div class="post">三心三意 SECRET_HTML_MARKER</div>')


rep = diag.run(delay=0, fetch=fake_fetch, today=datetime(2026, 11, 5))
author_req = [p for p in rep["probes"] if p["family"] == "blog_author_pages"]
assert sum(1 for p in author_req if p["status"] == 403) == 1                  # first refusal only
assert all(p["status"] == "not_requested" for p in author_req[1:])            # family stopped, nothing sent
assert sum(1 for u in calls if "/myoverview/" in u or ("/myblog/" in u and not u.endswith(".html"))) == 1
assert rep["verdict"]["blog_author_pages"] == "RESTRICTED"
assert rep["verdict"]["blog_category"] == "REACHABLE" and rep["verdict"]["forum_list"] == "REACHABLE"
art = [p for p in rep["probes"] if p["family"] == "blog_article"]
assert len(art) == 1 and art[0]["body_readable"] is True
assert rep["probes"][-1]["authors_visible"]["三心三意"] is True
assert "SECRET_HTML_MARKER" not in json.dumps(rep, ensure_ascii=False)
probe_keys = set().union(*(p.keys() for p in rep["probes"]))
assert not probe_keys & {"html", "body", "cookies", "headers", "request_headers", "set_cookie"}, probe_keys
print("PASS diagnostic: 403 stops family, no HTML / cookies in report")

print("PASS WXC source recovery tests")
