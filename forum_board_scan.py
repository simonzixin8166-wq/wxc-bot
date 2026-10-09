#!/usr/bin/env python3
"""Daily scan of watched authors who post on boards other than cfzh (e.g. 麻你 on tzlc).

state/board_authors.json : [{"author": "麻你", "board": "tzlc"}]
Per board, the first listing pages are scanned with the same exact-username parser as cfzh. List
continuity is proven by finding the previous run's anchor (the newest post id seen last time); only
then, and only for authors already seeded, are new entries admitted as live candidates. A newly added
author/board, or a scan without continuity, is recorded as backfill (never Genuine Forward).
Entries become "seen" only after their feed rows are durably written.
"""
from __future__ import annotations
import json, os, re
from contextlib import contextmanager
from pathlib import Path

import research_feed as rf
import wxc_scraper as w
import wxc_tg_agent as agent

STATE = Path(os.getenv("DATA_DIR", "state"))
CONFIG = STATE / "board_authors.json"
SCAN_STATE = STATE / "forum_board_scan_state.json"
PAGES = int(os.getenv("BOARD_DAILY_PAGES", "5"))
MAX_PAGES = int(os.getenv("BOARD_MAX_PAGES", "20"))


def _read(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _write(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def board_base(board: str) -> str:
    if not re.fullmatch(r"[a-z0-9]{2,16}", board or ""):
        raise ValueError(f"invalid board {board!r}")
    return f"https://bbs.wenxuecity.com/{board}/"


@contextmanager
def on_board(board: str):
    """Point the shared scraper at another board for the duration of a scan."""
    old = w.BASE
    w.BASE = board_base(board)
    try:
        yield w.BASE
    finally:
        w.BASE = old


def ids_in(htmls):
    out = []
    for h in htmls:
        out += [int(x) for x in re.findall(r'href="(?:[^"]*/)?(\d{5,9})\.html"', h)]
    return out


def classify(author_seeded: bool, continuity: bool) -> dict:
    if not author_seeded:
        return {"intake_class_hint": "backfill", "capture_mode": "board_author_bootstrap", "forward_evidence_eligible": False,
                "source_notice": "新关注作者/版块的首轮采集：发布早于开始关注，作为历史学习，不计入 Genuine Forward。"}
    if not continuity:
        return {"intake_class_hint": "backfill", "capture_mode": "board_scan_incomplete", "forward_evidence_eligible": False,
                "source_notice": "版块列表本轮未证明连续；记录保留用于历史学习，但不计入 Genuine Forward。"}
    return {"intake_class_hint": "live_candidate", "capture_mode": "scheduled_board_anchor_scan"}


def scan_board(board, authors, scan_state, fetch_state):
    prev = scan_state.get(board) or {}
    anchor = prev.get("anchor")
    with on_board(board):
        pages, htmls = PAGES, []
        while True:
            htmls = agent.list_pages(pages, fetch_state)
            ids = ids_in(htmls)
            found = anchor is not None and anchor in set(ids)
            if found or anchor is None or pages >= MAX_PAGES:
                break
            pages = min(MAX_PAGES, pages * 2)
        continuity = bool(htmls) and found
        report = {"board": board, "pages": pages, "html_pages": len(htmls), "anchor_found": found, "authors": {}}
        for author in authors:
            seen_path = STATE / f"seen_forum_entries_{board}_{author}.json"
            seeded = seen_path.exists()
            seen = set(_read(seen_path, []))
            entries = agent.entries_for(author, htmls)
            new = [e for k, e in entries.items() if k not in seen]
            posts = agent.fetch_entries(new, fetch_state) if new else []
            rows = []
            for p in posts:
                row = rf.normalize("forum", author, p)
                row.update(classify(seeded, continuity))
                row["forum_board"] = board
                rows.append(row)
            added = rf.append_records(rows) if rows else 0  # raises on write failure → nothing marked seen
            seen.update(str(p.get("source_entry_key")) for p in posts if p.get("source_entry_key"))
            _write(seen_path, sorted(seen))
            report["authors"][author] = {"visible": len(entries), "new": len(new), "processed": len(posts), "added": added}
        if htmls and ids_in(htmls[:1]):
            scan_state[board] = {"anchor": max(ids_in(htmls[:1])), "complete": continuity}
    return report


def main():
    cfg = _read(CONFIG, [])
    boards = {}
    for x in cfg:
        boards.setdefault(x["board"], []).append(x["author"])
    scan_state, fetch_state, out = _read(SCAN_STATE, {}), {}, []
    for board, authors in boards.items():
        out.append(scan_board(board, authors, scan_state, fetch_state))
    _write(SCAN_STATE, scan_state)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
