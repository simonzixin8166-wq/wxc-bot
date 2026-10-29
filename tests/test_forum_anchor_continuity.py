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
        assert scan["version"]==3
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

        # Continuity alone is not enough: an unresolved newly visible main
        # post keeps the cycle partial and prevents anchor advancement.
        d._write(d.FORUM_SCAN_STATE,{
            "version":3,"anchor_id":"114162","complete":True,"next_scan_pages":8
        })
        d.agent.list_pages=lambda n,state:[
            '<a href="/cfzh/114200.html">x</a><a href="114162.html">anchor</a>'
        ]+['<a href="/cfzh/114180.html">x</a>']*(n-1)
        d.agent.entries_for=lambda author,htmls:{
            "k1":{"entry_key":"k1","entry_kind":"post","parent_post_id":"114200","published_at":"10/08/2026 08:00:00"}
        }
        d.agent.fetch_entries=lambda entries,state:[]
        _,scan_unresolved=d.collect_forum()
        assert scan_unresolved["continuity_complete"] is True
        assert scan_unresolved["processing_complete"] is False
        assert scan_unresolved["complete"] is False
        assert scan_unresolved["anchor_id"]=="114162"

        d.agent.entries_for=lambda author,htmls:{}
        d.agent.fetch_entries=lambda entries,state:[]

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
        # 10/28-10/29: the latest anchor post is no longer visible (e.g. deleted). An earlier anchor from the
        # history still proves continuity -> complete at the daily depth, no 8->256 escalation.
        d._write(d.FORUM_SCAN_STATE,{
            "version":3,"anchor_id":"117591","previous_anchor_id":"117523","legacy_seen_anchor_id":"117428",
            "complete":True,"next_scan_pages":8
        })
        asked=[]
        def pages_without_latest(n,state):
            asked.append(n)
            return ['<a href="/cfzh/117650.html">new</a><a href="/cfzh/117523.html">older anchor</a>']+['<a href="/cfzh/117600.html">x</a>']*(n-1)
        d.agent.list_pages=pages_without_latest
        _,scan4=d.collect_forum()
        assert asked==[8] and scan4["complete"] is True and scan4["anchor_id"]=="117650"
        assert scan4["scan_attempts"][0]["anchor_matched"]=="117523"
        assert scan4["anchor_history"][:3]==["117650","117591","117523"]
        # a history id NEWER than the anchor is never accepted as proof
        d._write(d.FORUM_SCAN_STATE,{"version":3,"anchor_id":"117591","anchor_history":["117700"],"complete":True,"next_scan_pages":8})
        d.agent.list_pages=lambda n,state:['<a href="/cfzh/117800.html">new</a><a href="/cfzh/117700.html">x</a>']*n
        old_secs=d.FORUM_SCAN_SECONDS
        d.FORUM_SCAN_SECONDS=10**9
        _,scan5=d.collect_forum()
        assert scan5["complete"] is False and scan5["anchor_id"]=="117591"

        # Time budget: when deepening would overrun the wall-clock budget the scan stops early, stays partial
        # (fail-closed), keeps the anchor and writes its state instead of being killed by the job timeout.
        clock=[0.0]
        old_time=d.time.monotonic
        d.time.monotonic=lambda:clock[0]
        def slow_pages(n,state):
            clock[0]+=3.0*n            # 3 s per page
            return ['<a href="/cfzh/118000.html">new</a>']*n
        d.agent.list_pages=slow_pages
        d.FORUM_SCAN_SECONDS=200       # 8 pages = 24 s; 16 more pages would reach 72 s; 32 more -> 168 s; 64 more -> 360 s > 200
        d._write(d.FORUM_SCAN_STATE,{"version":3,"anchor_id":"117591","complete":True,"next_scan_pages":8})
        try:
            _,scan6=d.collect_forum()
        finally:
            d.time.monotonic=old_time
            d.FORUM_SCAN_SECONDS=old_secs
        assert [x["pages"] for x in scan6["scan_attempts"]]==[8,16,32]
        assert scan6["scan_attempts"][-1]["stopped"]=="time_budget"
        assert scan6["complete"] is False and scan6["anchor_id"]=="117591" and scan6["next_scan_pages"]==64
        assert d.FORUM_SCAN_STATE.exists()
    finally:
        d.FORUM_SCAN_STATE,d.FORUM_STATUS=old_scan,old_status
        d.agent.load_watch=old_watch
        d.agent.load_seen=old_seen
        d.agent.list_pages=old_list
        d.agent.entries_for=old_entries
        d.agent.fetch_entries=old_fetch

print("PASS forum anchor continuity / no false complete / fallback anchors / scan time budget")
