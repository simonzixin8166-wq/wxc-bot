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
        # A stale manifest (feed rewritten outside rf._write) is rejected in strict mode and only
        # tolerated with the explicit legacy switch.
        rf.FEED_PATH.write_text(json.dumps(dict(doc, updated_at="2099-01-01T00:00:00Z")))
        try:
            vf.verify(rf.FEED_PATH, man, 700); raise AssertionError("stale manifest must fail strict")
        except SystemExit as e:
            assert "FEED_MANIFEST_STALE" in str(e)
        assert vf.verify(rf.FEED_PATH, man, 700, legacy_ok=True)["manifest"] == "stale"
        man.unlink()
        try:
            vf.verify(rf.FEED_PATH, man, 700); raise AssertionError("missing manifest must fail strict")
        except SystemExit as e:
            assert "FEED_MANIFEST_ABSENT" in str(e)

        # Append-only beyond the count: same-count delete+add, and same-id provenance rewrite.
        rf.FEED_PATH.write_bytes(before)
        base = json.loads(before)["records"]
        swapped = base[:-1] + [rec(5000)]
        try:
            rf._write(rf.FEED_PATH, {"version": 1, "records": swapped}); raise AssertionError("delete+add")
        except rf.FeedIntegrityError as e:
            assert "lost_ids" in str(e)
        tampered_url = [dict(base[0], captured_at="2030-01-01T00:00:00Z")] + base[1:]
        try:
            rf._write(rf.FEED_PATH, {"version": 1, "records": tampered_url}); raise AssertionError("rewrite")
        except rf.FeedIntegrityError as e:
            assert "rewritten" in str(e)
        assert rf.FEED_PATH.read_bytes() == before
        # Filling an empty provenance field is allowed; an explicit revision is allowed.
        filled = [dict(base[0], intake_class_hint="backfill")] + base[1:]
        assert rf.immutable_violations(base, filled) == ([], [])
        revised = [dict(base[0], captured_at="2026-10-09T00:00:00Z",
                        revision={"fields": ["captured_at"], "reason": "clock fix", "revised_at": "2026-10-09"})] + base[1:]
        assert rf.immutable_violations(base, revised) == ([], [])
        # Pre-push verify compares record by record against origin/main.
        rf._write(rf.FEED_PATH, {"version": 1, "updated_at": "2026-10-09T00:00:00Z", "records": base + [rec(7000)]})
        assert vf.verify(rf.FEED_PATH, man, base)["manifest"] == "verified"
        try:
            vf.verify(rf.FEED_PATH, man, base + [rec(8000)]); raise AssertionError("lost vs origin")
        except SystemExit as e:
            assert "FEED_SHRINK" in str(e) or "FEED_LOST_IDS" in str(e)
        try:
            vf.verify(rf.FEED_PATH, man, [dict(base[0], captured_at="1999-01-01T00:00:00Z")] + base[1:]); raise AssertionError("prov")
        except SystemExit as e:
            assert "FEED_PROVENANCE_REWRITE" in str(e)
    finally:
        rf.FEED_PATH = old

print("PASS P2-11 feed integrity: atomic write, append-only, manifest, pre-push verify")
