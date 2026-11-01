"""Forum conversation context (Owner 2026-11-01): root / parent / reply tree from the already-fetched page.
Fixtures mirror the real wenxuecity structure (canonical link, #postparent, #comment #postlist with
20px-per-level margins) with invented text only — no third-party content."""
import wxc_scraper as w
import research_feed as rf

MAIN = """<html><head><link rel="canonical" href="https://bbs.wenxuecity.com/cfzh/500.html"/></head><body>
<h1 class="title">主帖：示例观点</h1>
<div id="postmeta"><a class="username" href="#">甲作者</a><span class="date">2026-10-30 09:00:00</span></div>
<div id="msgbodyContent">示例正文，没有真实内容。</div>
<div id="comment"><h3>所有跟帖</h3><div id="postlist"><div>
<p style="margin:2px 0 2px 0px;"><a class="post" href="https://bbs.wenxuecity.com/cfzh/501.html">回复一</a><span class="b"><a class="nickname">乙</a></span></p>
<p style="margin:2px 0 2px 0px;"><a class="post" href="https://bbs.wenxuecity.com/cfzh/502.html">回复二</a><span class="b"><a class="nickname">丙</a></span></p>
<p style="margin:2px 0 2px 20px;"><a class="post" href="https://bbs.wenxuecity.com/cfzh/503.html">甲回复丙</a><span class="b"><a class="nickname">甲作者</a></span></p>
<p style="margin:2px 0 2px 40px;"><a class="post" href="https://bbs.wenxuecity.com/cfzh/504.html">丙再回</a><span class="b"><a class="nickname">丙</a></span></p>
<p style="margin:2px 0 2px 0px;"><a class="post" href="https://bbs.wenxuecity.com/cfzh/505.html">回复三</a><span class="b"><a class="nickname">丁</a></span></p>
</div></div></div></body></html>"""

REPLY = """<html><head><link rel="canonical" href="https://bbs.wenxuecity.com/cfzh/500.html"/></head><body>
<h1 class="title">甲回复丙</h1>
<div id="postmeta"><a class="username" href="#">甲作者</a><span class="date">2026-10-30 10:00:00</span></div>
<div class="postbody"><div id="postparent">回复：<a href="https://bbs.wenxuecity.com/cfzh/502.html">回复二</a> - <a class="username" href="#">丙</a> <span class="date">2026-10-30 09:30:00</span></div>
<div id="msgbodyContent">同意，我也加了一点。</div></div>
<div id="comment"><div id="postlist"><div>
<p style="margin:2px 0 2px 0px;"><a class="post" href="https://bbs.wenxuecity.com/cfzh/504.html">丙再回</a><span class="b"><a class="nickname">丙</a></span></p>
</div></div></div></body></html>"""

m = w.parse_post(MAIN, "https://bbs.wenxuecity.com/cfzh/500.html")
t = m["thread"]
assert t["post_id"] == "500" and t["root_post_id"] == "500" and t["is_reply"] is False and t["parent"] is None
tree = {r["post_id"]: (r["depth"], r["in_reply_to"]) for r in t["replies"]}
assert tree == {"501": (0, "500"), "502": (0, "500"), "503": (1, "502"), "504": (2, "503"), "505": (0, "500")}, tree

r = w.parse_post(REPLY, "https://bbs.wenxuecity.com/cfzh/503.html")
t = r["thread"]
assert t["post_id"] == "503" and t["root_post_id"] == "500" and t["is_reply"] is True
assert t["parent"] == {"post_id": "502", "title": "回复二", "author": "丙", "published_at": "2026-10-30 09:30:00"}
assert [(x["post_id"], x["in_reply_to"]) for x in t["replies"]] == [("504", "503")]
assert r["text"] == "同意，我也加了一点。"  # post body parsing unchanged

row = rf.normalize("forum", "甲作者", r)
tc = row["thread_context"]
assert tc == {"root_post_id": "500", "is_reply": True,
              "in_reply_to": {"post_id": "502", "author": "丙", "title": "回复二", "published_at": "2026-10-30 09:30:00"},
              "reply_count": 1, "reply_ids": ["504"]}, tc
assert "回复一" not in str(rf.normalize("forum", "甲作者", m)["thread_context"])  # others' reply titles not stored

# Old pages without these blocks, and broken markup: post still parses, context degrades to None/empty.
bare = w.parse_post('<h1 class="title">t</h1><div id="msgbodyContent">x</div>', "https://bbs.wenxuecity.com/cfzh/9.html")
assert bare["thread"]["root_post_id"] == "9" and bare["thread"]["parent"] is None and bare["thread"]["replies"] == []
assert rf.normalize("forum", "a", {"title": "t", "text": "x", "url": "https://bbs.wenxuecity.com/cfzh/9.html"})["thread_context"] is None

long_t = "长" * 300
p2 = w.parse_post(REPLY.replace(">回复二<", f">{long_t}<", 1), "https://bbs.wenxuecity.com/cfzh/503.html")
assert len(p2["thread"]["parent"]["title"]) == 120
print("PASS forum thread context (root/parent/tree from the fetched page, titles <=120, others' replies not stored)")
