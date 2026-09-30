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

print("PASS BrightLine Blog Collector V1")
