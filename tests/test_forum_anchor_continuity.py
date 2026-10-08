from pathlib import Path
import tempfile
import daily_close_research as d

with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    old_scan,old_status=d.FORUM_SCAN_STATE,d.FORUM_STATUS
    old_watch=d.agent.load_watch
    old_seen=d.agent.load_seen
    old_list=d.agent.list_pages
    old_entries=d.agent.entries_for
    old_fetch=d.agent.fetch_entries
    try:
        d.FORUM_SCAN_STATE=root/"scan.json"
        d.FORUM_STATUS=root/"status.json"
        d._write(d.FORUM_SCAN_STATE,{
            "version":1,"anchor_id":"113867","complete":True,"next_scan_pages":8
        })
        d.agent.load_watch=lambda:["A"]
        d.agent.load_seen=lambda author:{"114162"}
        d.agent.list_pages=lambda n,state:[
            '<a href="/cfzh/114200.html">x</a><a href="114162.html">anchor</a>'
        ]+['<a href="/cfzh/114180.html">x</a>']*(n-1)
        d.agent.entries_for=lambda author,htmls:{}
        d.agent.fetch_entries=lambda entries,state:[]
        added,scan=d.collect_forum()
        assert added==0
        assert scan["version"]==2
        assert scan["previous_anchor_id"]=="114162"
        assert scan["legacy_seen_anchor_id"]=="114162"
        assert scan["complete"] is True
        assert scan["anchor_id"]=="114200"

        # If continuity to the prior anchor cannot be proved, the scan must stay
        # partial, keep the old anchor, and expand depth on the next run.
        d._write(d.FORUM_SCAN_STATE,{
            "version":2,"anchor_id":"114162","complete":False,"next_scan_pages":8
        })
        d.agent.list_pages=lambda n,state:(
            ['<a href="/cfzh/114250.html">new</a><a href="/cfzh/114240.html">new2</a>']*(n-1)
            + [('<a href="/cfzh/114162.html">old anchor</a>' if n>=16 else '<a href="/cfzh/114230.html">new3</a>')]
        )
        added2,scan2=d.collect_forum()
        assert added2==0
        assert scan2["complete"] is True
        assert scan2["anchor_id"]=="114250"
        assert scan2["scan_budget"]==16
        assert [x["pages"] for x in scan2["scan_attempts"]]==[8,16]

        # Even at the safety ceiling, missing continuity never becomes complete.
        d._write(d.FORUM_SCAN_STATE,{
            "version":2,"anchor_id":"114162","complete":False,"next_scan_pages":8
        })
        d.agent.list_pages=lambda n,state:[
            '<a href="/cfzh/114300.html">new</a>'
        ]*n
        _,scan3=d.collect_forum()
        assert scan3["complete"] is False
        assert scan3["anchor_id"]=="114162"
        assert scan3["scan_budget"]==d.FORUM_MAX_SCAN_PAGES
        assert scan3["next_scan_pages"]==d.FORUM_MAX_SCAN_PAGES
    finally:
        d.FORUM_SCAN_STATE,d.FORUM_STATUS=old_scan,old_status
        d.agent.load_watch=old_watch
        d.agent.load_seen=old_seen
        d.agent.list_pages=old_list
        d.agent.entries_for=old_entries
        d.agent.fetch_entries=old_fetch

print("PASS forum anchor continuity / no false complete")
