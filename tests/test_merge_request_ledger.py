"""COL-01: state/request_ledger.json is bumped by tg-bot and research-close; a rebase must merge the counters
instead of stopping on a conflict (2026-10-20 research-close lost two collection commits)."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import merge_request_ledger as mrl

# pure merge: increments from both sides survive, never below either side, paid is sticky, 45-day window
base = {"days": {"2026-10-20": {"telegram:send_message": {"count": 3, "paid": False}}}}
ours = {"days": {"2026-10-20": {"telegram:send_message": {"count": 5, "paid": False},
                                "telegram:get_updates": {"count": 1, "paid": False}}}}
theirs = {"days": {"2026-10-20": {"telegram:send_message": {"count": 4, "paid": True}},
                   "2026-10-21": {"myalphaview:server_action_status": {"count": 2, "paid": False}}}}
m = mrl.merge(base, ours, theirs)
assert m["days"]["2026-10-20"]["telegram:send_message"] == {"count": 6, "paid": True}, m
assert m["days"]["2026-10-20"]["telegram:get_updates"] == {"count": 1, "paid": False}
assert m["days"]["2026-10-21"]["myalphaview:server_action_status"]["count"] == 2
assert mrl.merge({}, {}, {}) == {"days": {}}
many = {"days": {f"2026-08-{d:02d}": {"k:v": {"count": 1, "paid": False}} for d in range(1, 32)}}
many["days"].update({f"2026-09-{d:02d}": {"k:v": {"count": 1, "paid": False}} for d in range(1, 31)})
assert len(mrl.merge({}, many, {})["days"]) == 45 and min(mrl.merge({}, many, {})["days"]) == "2026-08-17"

# end to end: the same rebase that failed in production now merges through .gitattributes + the driver
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    run = lambda *a, cwd=d: subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True)
    origin, work = d / "origin.git", d / "work"
    run("git", "init", "-q", "--bare", "-b", "main", str(origin))
    run("git", "clone", "-q", str(origin), str(work))
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        run("git", "config", k, v, cwd=work)
    shutil.copy(REPO / ".gitattributes", work / ".gitattributes")
    shutil.copy(REPO / "merge_request_ledger.py", work / "merge_request_ledger.py")
    (work / "state").mkdir()
    ledger = work / "state" / "request_ledger.json"
    write = lambda doc: ledger.write_text(json.dumps(doc, indent=2))
    write(base)
    run("git", "add", ".", cwd=work); run("git", "commit", "-qm", "base", cwd=work); run("git", "push", "-q", "origin", "main", cwd=work)
    other = d / "other"
    run("git", "clone", "-q", str(origin), str(other))
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        run("git", "config", k, v, cwd=other)
    (other / "state" / "request_ledger.json").write_text(json.dumps(theirs, indent=2))
    run("git", "commit", "-qam", "tg-bot", cwd=other); run("git", "push", "-q", "origin", "main", cwd=other)
    write(ours)
    run("git", "commit", "-qam", "research-close", cwd=work)
    # without the driver configured this is the 10-20 failure
    no_driver = subprocess.run(["git", "pull", "-q", "--rebase", "origin", "main"], cwd=work, capture_output=True, text=True)
    assert no_driver.returncode != 0, "expected the production conflict without the driver"
    run("git", "rebase", "--abort", cwd=work)
    run("git", "config", "merge.request-ledger.driver", f"{sys.executable} merge_request_ledger.py %O %A %B", cwd=work)
    run("git", "pull", "-q", "--rebase", "origin", "main", cwd=work)
    got = json.loads(ledger.read_text())
    assert got["days"]["2026-10-20"]["telegram:send_message"]["count"] == 6, got
    assert got["days"]["2026-10-21"]["myalphaview:server_action_status"]["count"] == 2

# both writers configure the driver before their rebase; nothing else in state/ is written by both
for wf in ("research-close.yml", "tg-bot.yml"):
    text = (REPO / ".github" / "workflows" / wf).read_text(encoding="utf-8")
    assert 'git config merge.request-ledger.driver "python merge_request_ledger.py %O %A %B"' in text, wf
    assert "git rebase --abort" in text, wf
assert "state/request_ledger.json merge=request-ledger" in (REPO / ".gitattributes").read_text()
print("PASS COL-01 request_ledger merge driver: counters merged, production conflict reproduced and resolved")
