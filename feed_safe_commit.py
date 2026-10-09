#!/usr/bin/env python3
"""Conflict-safe persistence for long-running feed writers (e.g. a 30-minute author backfill).

A long job's `git pull --rebase` conflicts on state/research_feed.json whenever another writer pushed
meanwhile, and the collected rows were lost with the runner. Instead:
  export : save the records this job added (ids absent from origin/main) plus the listed seen-state
           files to a side file;
  apply  : on top of a fresh origin/main checkout, append those records through research_feed
           (dedup by id, feed + manifest written together) and union the seen-state lists.
The workflow then commits, runs verify_research_feed.py and pushes, retrying from a fresh checkout.
"""
from __future__ import annotations
import argparse, glob, json, subprocess, sys
from pathlib import Path


def origin_ids(ref="origin/main"):
    try:
        raw = subprocess.run(["git", "show", f"{ref}:state/research_feed.json"], capture_output=True, check=True).stdout
        return {r.get("id") for r in json.loads(raw.decode("utf-8")).get("records") or []}
    except Exception:
        return set()


def export(out, patterns):
    feed = json.loads(Path("state/research_feed.json").read_text(encoding="utf-8"))
    have = origin_ids()
    new = [r for r in feed.get("records") or [] if r.get("id") not in have]
    seen = {}
    for pat in patterns:
        for f in glob.glob(pat):
            try:
                seen[f] = json.loads(Path(f).read_text(encoding="utf-8"))
            except Exception:
                pass
    Path(out).write_text(json.dumps({"records": new, "seen": seen}, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"exported_records": len(new), "seen_files": sorted(seen)}, ensure_ascii=False))


def merge_seen(cur, mine):
    if isinstance(cur, list) and isinstance(mine, list):
        return sorted({json.dumps(x, sort_keys=True) if not isinstance(x, (str, int)) else x for x in cur + mine},
                      key=lambda x: str(x))
    return mine if cur is None else cur  # dict-shaped scan states: keep the newer remote state


def apply(inp):
    import research_feed as rf
    data = json.loads(Path(inp).read_text(encoding="utf-8"))
    added = rf.append_records(data.get("records") or []) if data.get("records") else 0
    for f, mine in (data.get("seen") or {}).items():
        p = Path(f)
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        p.write_text(json.dumps(merge_seen(cur, mine), ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"applied_records": added, "seen_files": len(data.get("seen") or {})}, ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export"); e.add_argument("--out", required=True); e.add_argument("--seen", nargs="*", default=[])
    a = sub.add_parser("apply"); a.add_argument("--in", dest="inp", required=True)
    args = ap.parse_args(argv)
    export(args.out, args.seen) if args.cmd == "export" else apply(args.inp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
