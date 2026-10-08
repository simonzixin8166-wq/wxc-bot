from types import SimpleNamespace
import wxc_scraper as w
import wxc_tg_agent as agent
import research_feed as rf

html = """
<html><body>
<p><a class="post" href="/cfzh/120001.html">主帖观点</a>
<span class="b"><a>三心三意</a></span> 10/08/2026 08:01:02</p>
<p><a class="post" href="/cfzh/120002.html">回复一：MU 不受影响</a>
<span class="b"><a>三心三意</a></span> 10/08/2026 postreply 08:02:03</p>
<p><a class="post" href="/cfzh/120003.html">回复二：继续看现金流</a>
<span class="b"><a>三心三意</a></span> 10/08/2026 postreply 08:03:04</p>
</body></html>
"""
rows=w.parse_list_entries(html,"三心三意")
assert len(rows)==3
assert len({x["entry_key"] for x in rows})==3
assert [x["entry_kind"] for x in rows]==["post","reply","reply"]
assert rows[1]["parent_post_id"]=="120002"

old_fetch=agent.b.fetch
old_parse=agent.w.parse_post
try:
    agent.b.fetch=lambda url,state: SimpleNamespace(text="<html/>")
    # Simulate a reply URL resolving to a parent body by another author.
    agent.w.parse_post=lambda html,url: {
        "id":"999","url":url,"title":"父帖","author":"别人","date":"2026-10-08 08:00:00",
        "reads":"","likes":"","text":"别人正文","images":[]
    }
    p=agent._forum_entry_post("三心三意",rows[1],{})
    assert p["author"]=="三心三意"
    assert p["text"]=="回复一：MU 不受影响"
    assert p["attribution_fallback"]=="list_visible_reply_text"
    assert p["source_entry_key"]==rows[1]["entry_key"]

    feed_row=rf.normalize("forum","三心三意",p)
    assert feed_row["forum_entry_kind"]=="reply"
    assert feed_row["attribution_fallback"]=="list_visible_reply_text"
    assert "MU" in feed_row["symbols"]
finally:
    agent.b.fetch=old_fetch
    agent.w.parse_post=old_parse

print("PASS forum post/reply entry preservation and author-attribution fail-closed")
