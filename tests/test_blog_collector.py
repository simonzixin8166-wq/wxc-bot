from datetime import datetime
import tempfile
from pathlib import Path
import wxc_blog as blog
import wxc_tg_agent as agent

ARCHIVE = """
<html><body>
<a href="/myblog/82458/202609/12345.html">测试文章</a>
<a href="/myblog/82458/202609/12345.html">重复</a>
<a href="/myblog/99999/202609/888.html">其他作者</a>
</body></html>
"""

ARTICLE = """
<html><body>
<h1 id="titleName">BrightLine 测试文章</h1>
<div id="time">2026-09-30 08:00:00</div>
<div id="articalContent">
<p>这是正文第一段。</p><p>这是正文第二段。</p>
<img src="https://example.com/chart.png">
</div>
</body></html>
"""

assert blog.resolve_profile("BRGHTLINE")["blog_id"] == "82458"
assert blog.resolve_profile("亮线留痕")["author"] == "BrightLine"
assert blog.resolve_profile("yifan99")["blog_id"] == "31983"

rows = blog.parse_archive(ARCHIVE, "82458")
assert len(rows) == 1
assert rows[0]["url"].endswith("/myblog/82458/202609/12345.html")

p = blog.parse_article(ARTICLE, rows[0]["url"], "BrightLine")
assert p["title"] == "BrightLine 测试文章"
assert p["date"] == "2026-09-30"
assert "正文第一段" in p["text"]
assert p["images"] == ["https://example.com/chart.png"]

req = agent.parse_blog_request("下载 BRGHTLINE 博客 2026年6月")
assert req["profile"]["blog_id"] == "82458"
assert req["start"] == datetime(2026, 6, 1)
assert req["end"].month == 6

req2 = agent.parse_blog_request("下载 BrightLine 博客最近30天")
assert req2["label"] == "最近30天"
assert (req2["end"] - req2["start"]).days == 30

with tempfile.TemporaryDirectory() as td:
    blog.build(td, [p])
    assert (Path(td) / "posts.md").exists()
    assert (Path(td) / "index.csv").exists()
    assert (Path(td) / "posts.json").exists()

# Collector completeness is explicit: every requested monthly archive must
# succeed. Overview is an independent recovery path, not a substitute for a
# failed archive month.
old_get=blog.get
old_download=blog.download_image
try:
    def fake_get(url, delay=0):
        class R:
            def __init__(self,text): self.text=text
        if "myblog" in url: return R(ARTICLE)
        return R(ARCHIVE)
    blog.get=fake_get
    blog.download_image=lambda *args,**kwargs: None
    with tempfile.TemporaryDirectory() as td:
        result=blog.collect(
            blog.resolve_profile("BrightLine"),
            datetime(2026,9,30),datetime(2026,9,30,23,59,59),td,
            delay=0,max_articles=None,max_images=0
        )
        assert result["scan_complete"] is True
        assert result["archive_failures"]==[]
        assert result["retention_policy"]=="no_article_count_cap"

    def archive_failure(url, delay=0):
        class R:
            def __init__(self,text): self.text=text
        if "/myblog/" in url: return R(ARTICLE)
        if "blogtitle" in url or "archive" in url: return None
        return R(ARCHIVE)
    # Directly verify the contract via a deterministic one-month failure.
    calls={"n":0}
    def fail_first_archive(url, delay=0):
        class R:
            def __init__(self,text): self.text=text
        if "myblog" in url: return R(ARTICLE)
        calls["n"]+=1
        if calls["n"]==1:return None
        return R(ARCHIVE)
    blog.get=fail_first_archive
    with tempfile.TemporaryDirectory() as td:
        result=blog.collect(
            blog.resolve_profile("BrightLine"),
            datetime(2026,9,30),datetime(2026,9,30,23,59,59),td,
            delay=0,max_articles=None,max_images=0
        )
        assert result["scan_complete"] is False
        assert result["archive_failures"]==["2026-09"]
finally:
    blog.get=old_get
    blog.download_image=old_download

print("PASS blog completeness accounting / no article-count cap")

print("PASS BrightLine Blog Collector V1")
