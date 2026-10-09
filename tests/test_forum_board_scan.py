import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forum_board_scan as fbs, wxc_scraper as w, wxc_blog as wb

base = w.BASE
with fbs.on_board("tzlc") as b:
    assert b == "https://bbs.wenxuecity.com/tzlc/" and w.BASE == b
assert w.BASE == base                       # always restored
try:
    fbs.board_base("../x"); raise SystemExit("bad board accepted")
except ValueError:
    pass
assert fbs.ids_in(['<a href="2380206.html">x</a><a href="/tzlc/2380100.html">y</a>']) == [2380206, 2380100]
# new author/board → bootstrap backfill; seeded but no continuity → backfill; seeded + continuity → live
assert fbs.classify(False, True)["forward_evidence_eligible"] is False
assert fbs.classify(True, False)["intake_class_hint"] == "backfill"
assert fbs.classify(True, True)["intake_class_hint"] == "live_candidate"
cfg = json.loads((Path(fbs.__file__).parent / "state" / "board_authors.json").read_text(encoding="utf-8"))
assert {"author": "麻你", "board": "tzlc"}.items() <= cfg[0].items()
assert wb.resolve_profile("麻你")["blog_id"] == "78105"
assert "麻你" not in json.loads((Path(fbs.__file__).parent / "state" / "watch.json").read_text(encoding="utf-8"))
print("PASS forum_board_scan")
