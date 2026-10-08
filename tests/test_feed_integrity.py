"""P2-11 research feed integrity: atomic writes, append-only guard, manifest sidecar, pre-push verify."""
import hashlib, json, os, tempfile
from pathlib import Path
import research_feed as rf
import verify_research_feed as vf

def rec(i, **kw):
    return {"id": f"r{i}", "captured_at": f"2026-10-0{1 + i % 8}T00:00:00Z", "title": "t" * 50, **kw}

with tempfile.TemporaryDirectory() as td:
    old = rf.FEED_PATH
    rf.FEED_PATH = Path(td) / "research_feed.json"
    man = Path(td) / rf.MANIFEST_NAME
    try:
        # >1 MiB feed is written atomically with a verifying manifest.
        big = [rec(i, text="x" * 2000) for i in range(700)]
        assert rf.append_records(big) == 700
        payload = rf.FEED_PATH.read_bytes()
        assert len(payload) > 1024 * 1024
        m = json.loads(man.read_text())
        assert m["record_count"] == 700 and m["unique_ids"] == 700
        assert m["content_sha256"] == hashlib.sha256(payload).hexdigest() and m["bytes"] == len(payload)
        assert m["feed_updated_at"] == json.loads(payload)["updated_at"]
        assert vf.verify(rf.FEED_PATH, man, 700)["records"] == 700

        # Append-only: a shorter feed is refused and the file on disk is untouched.
        before = rf.FEED_PATH.read_bytes()
        try:
            rf._write(rf.FEED_PATH, {"version": 1, "records": big[:10]})
            raise AssertionError("shrink must be refused")
        except rf.FeedIntegrityError:
            pass
        try:
            rf._write(rf.FEED_PATH, {"version": 1, "records": "oops"})
            raise AssertionError("invalid structure must be refused")
        except rf.FeedIntegrityError:
            pass
        assert rf.FEED_PATH.read_bytes() == before

        # Crash during replace: the previous complete file survives, no temp litter.
        real = os.replace
        os.replace = lambda *a: (_ for _ in ()).throw(OSError("disk full"))
        try:
            rf.append_records([rec(9999)])
            raise AssertionError("write failure must propagate")
        except OSError:
            pass
        finally:
            os.replace = real
        assert rf.FEED_PATH.read_bytes() == before
        assert not [p for p in Path(td).iterdir() if p.name.endswith(".tmp")]

        # Pre-push verify: duplicate ids, shrink vs origin/main, torn/merged content vs manifest.
        doc = json.loads(before)
        dup = dict(doc, records=doc["records"] + [doc["records"][0]])
        rf.FEED_PATH.write_text(json.dumps(dup))
        for bad, why in ((lambda: vf.verify(rf.FEED_PATH, man, None), "FEED_INVALID"),):
            try:
                bad(); raise AssertionError(why)
            except SystemExit as e:
                assert why in str(e)
        rf.FEED_PATH.write_bytes(before)
        try:
            vf.verify(rf.FEED_PATH, man, 701); raise AssertionError("shrink")
        except SystemExit as e:
            assert "FEED_SHRINK" in str(e)
        tampered = dict(doc, records=doc["records"][:-1] + [dict(doc["records"][-1], title="merged")])
        rf.FEED_PATH.write_text(json.dumps(tampered, ensure_ascii=False, indent=2))
        try:
            vf.verify(rf.FEED_PATH, man, 700); raise AssertionError("mismatch")
        except SystemExit as e:
            assert "FEED_MANIFEST_MISMATCH" in str(e)
        rf.FEED_PATH.write_text("{\"records\": [")  # truncated JSON
        try:
            vf.verify(rf.FEED_PATH, man, 700); raise AssertionError("truncated")
        except json.JSONDecodeError:
            pass
        # A stale manifest (feed rewritten by an older tool with a new updated_at) is not a mismatch.
        rf.FEED_PATH.write_text(json.dumps(dict(doc, updated_at="2099-01-01T00:00:00Z")))
        assert vf.verify(rf.FEED_PATH, man, 700)["records"] == 700
    finally:
        rf.FEED_PATH = old

print("PASS P2-11 feed integrity: atomic write, append-only, manifest, pre-push verify")
