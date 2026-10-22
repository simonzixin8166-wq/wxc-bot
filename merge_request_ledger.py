"""Git merge driver for state/request_ledger.json (COL-01).

tg-bot and research-close both bump the same per-day request counters and run in different concurrency
groups, so `git pull --rebase` used to stop on a content conflict and the research-close run lost its
whole collection commit (2026-10-20, twice). Counters only ever grow, so the merge is
    count = ours + theirs - base   (never below either side)
which keeps every writer's increments. Days outside the newest 45 are pruned, as record_request() does.

Usage (configured by the workflows):  git config merge.request-ledger.driver "python merge_request_ledger.py %O %A %B"
Git passes base / current / other file paths; the result is written to the current path, exit 0 = merged.
"""
import json
import sys

KEEP_DAYS = 45


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _count(doc, day, key):
    row = ((doc.get("days") or {}).get(day) or {}).get(key) or {}
    try:
        return int(row.get("count") or 0)
    except (TypeError, ValueError):
        return 0


def merge(base, ours, theirs):
    out = {k: v for k, v in theirs.items() if k != "days"}
    out.update({k: v for k, v in ours.items() if k != "days"})
    days = {}
    for day in sorted(set(ours.get("days") or {}) | set(theirs.get("days") or {})):
        keys = set(((ours.get("days") or {}).get(day) or {})) | set(((theirs.get("days") or {}).get(day) or {}))
        rows = {}
        for key in sorted(keys):
            o, t, b = _count(ours, day, key), _count(theirs, day, key), _count(base, day, key)
            paid = any(bool((((d.get("days") or {}).get(day) or {}).get(key) or {}).get("paid")) for d in (ours, theirs))
            rows[key] = {"count": max(o + t - b, o, t), "paid": paid}
        days[day] = rows
    out["days"] = {d: days[d] for d in sorted(days)[-KEEP_DAYS:]}
    return out


def main(argv):
    if len(argv) != 4:
        print("usage: merge_request_ledger.py BASE CURRENT OTHER", file=sys.stderr)
        return 2
    base, ours, theirs = (_load(p) for p in argv[1:])
    with open(argv[2], "w", encoding="utf-8") as f:
        json.dump(merge(base, ours, theirs), f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
