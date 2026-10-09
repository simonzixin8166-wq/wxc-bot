import json, os, sys, subprocess, tempfile
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import feed_safe_commit as fsc
assert fsc.merge_seen(["a", "b"], ["b", "c"]) == ["a", "b", "c"]
assert fsc.merge_seen(None, ["x"]) == ["x"]
assert fsc.merge_seen({"k": 1}, {"k": 2}) == {"k": 1}
# end-to-end in a temp git repo: export from a diverged feed, apply on top of a newer origin
with tempfile.TemporaryDirectory() as d:
    run = lambda *a: subprocess.run(a, cwd=d, check=True, capture_output=True)
    run("git", "init", "-q", "-b", "main"); run("git", "config", "user.email", "t@t"); run("git", "config", "user.name", "t")
    (Path(d) / "state").mkdir()
    feed = lambda ids: json.dumps({"version": 1, "records": [{"id": i, "captured_at": "2026-10-01T00:00:00Z"} for i in ids]})
    (Path(d) / "state/research_feed.json").write_text(feed(["a"])); run("git", "add", "."); run("git", "commit", "-qm", "base")
    run("git", "update-ref", "refs/remotes/origin/main", "HEAD")
    (Path(d) / "state/research_feed.json").write_text(feed(["a", "mine1", "mine2"]))
    (Path(d) / "state/seen_x.json").write_text(json.dumps(["p1"]))
    cwd = os.getcwd(); os.chdir(d)
    try:
        fsc.export("/tmp/_fsc_test.json", ["state/seen_x.json"])
        exp = json.loads(Path("/tmp/_fsc_test.json").read_text())
        assert [r["id"] for r in exp["records"]] == ["mine1", "mine2"] and exp["seen"] == {"state/seen_x.json": ["p1"]}
        # newer origin from another writer
        Path("state/research_feed.json").write_text(feed(["a", "other"])); Path("state/seen_x.json").write_text(json.dumps(["p0"]))
        os.environ["DATA_DIR"] = str(Path(d) / "state")
        import importlib, research_feed as rf; importlib.reload(rf)
        fsc.apply("/tmp/_fsc_test.json")
        ids = [r["id"] for r in json.loads(Path("state/research_feed.json").read_text())["records"]]
        assert ids == ["a", "other", "mine1", "mine2"], ids
        assert json.loads(Path("state/seen_x.json").read_text()) == ["p0", "p1"]
    finally:
        os.chdir(cwd); os.environ.pop("DATA_DIR", None)
print("PASS feed_safe_commit")
