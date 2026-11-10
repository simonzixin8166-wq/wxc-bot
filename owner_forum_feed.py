#!/usr/bin/env python3
"""Owner forum export -> research feed (Owner 2026-11-10). Runs in research-close after owner_forward_feed.

For each row of state/owner_forum_index.jsonl (one target-author utterance) whose topic file is stored in the
private textpack and that is not yet in the feed, it reads the topic at RUNTIME ONLY, takes that utterance and runs
the normal understanding path (research_feed.normalize: claims, author actions, method signals) as a forum record
with its conversation (thread_context: the post it answers and the replies it received, titles <=120 chars).
The public feed keeps only the usual fields (title, <=360-char excerpt, structured claims, hashes).

Timeliness (same rule as owner forwards, Owner 2026-11-09): exported within 7 days of the post ->
intake_class_hint=live_candidate, capture_mode=owner_forum_export_timely (forward scoring starts at captured_at,
never at the post time); later -> backfill, forward_evidence_eligible=False. Utterances whose body was not exported
are understood from the title only (body_status=body_missing): nothing is guessed.
Existing feed records are never rewritten: a link already in the feed for the same author is skipped.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import owner_forum_export as forum
import research_feed as rf
from owner_forward_feed import TIMELY_DAYS, _dt

STATE = "owner_forum_feed_state.json"


def _data() -> Path:
    return Path(os.getenv("DATA_DIR", "state"))


def fetch_topic(path: str, http=requests) -> str | None:
    token, repo = os.getenv("TEXTPACK_TOKEN", ""), os.getenv("TEXTPACK_REPO", "")
    if not token or not repo:
        return None
    r = http.get(f"https://api.github.com/repos/{repo}/contents/{path}",
                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=30)
    if getattr(r, "status_code", 0) != 200:
        return None
    return base64.b64decode(r.json()["content"]).decode("utf-8")


def run(http=requests, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    idx = forum.index_path()
    if not idx.exists():
        return {"pending": 0, "appended": 0}
    st_path = _data() / STATE
    st = json.loads(st_path.read_text(encoding="utf-8")) if st_path.exists() else {"done": {}}
    feed = json.loads(rf.FEED_PATH.read_text(encoding="utf-8")) if rf.FEED_PATH.exists() else {"records": []}
    have = {(str(x.get("author") or "").casefold(), rf._canonical(str(x.get("url") or ""))) for x in feed.get("records", [])}
    topics: dict[str, dict | None] = {}
    rows, rep = [], {"pending": 0, "appended": 0, "timely": 0, "backfill": 0, "already_in_feed": 0,
                     "text_unavailable": 0, "title_only": 0, "body_missing": 0}
    for line in idx.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("textpack") != "stored" or r["post_id"] in st["done"]:
            continue
        rep["pending"] += 1
        if (r["author"].casefold(), rf._canonical(r["url"])) in have:
            st["done"][r["post_id"]] = "already_in_feed"
            rep["already_in_feed"] += 1
            continue
        path = r["textpack_path"]
        if path not in topics:
            md = fetch_topic(path, http)
            topics[path] = forum.parse_topic(md) if md else None
        t = topics[path]
        e = next((x for x in (t or {}).get("entries", []) if x["post_id"] == r["post_id"]), None)
        if e is None:
            rep["text_unavailable"] += 1  # retried next run
            continue
        thread = {"root_post_id": e["root_post_id"], "is_reply": e["kind"] == "reply", "parent": e["parent"],
                  "replies": e["replies"]}
        post = {"title": e["title"] if e["kind"] == "post" else e["title"], "text": e["text"], "url": e["url"],
                "date": e["published_at"] or "", "images": [], "forum_entry_kind": e["kind"],
                "source_entry_key": e["post_id"], "parent_post_id": (e["parent"] or {}).get("post_id"),
                "attribution_fallback": "owner_export_title_only" if e["body_status"] != "body_exported" else None,
                "thread": thread}
        row = rf.normalize("forum", e["author"], post)
        pub, got = _dt(e["published_at"]), _dt(r.get("retrieved_at"))
        lag_h = round((got - pub).total_seconds() / 3600, 1) if pub and got else None
        timely = lag_h is not None and -24 <= lag_h <= TIMELY_DAYS * 24
        row.update({"intake_provenance": "owner_forum_export", "forum_board": e["board"], "body_status": e["body_status"],
                    "owner_export_retrieved_at": r.get("retrieved_at"), "publication_lag_hours": lag_h,
                    "content_sha256": e["sha256"]})
        if timely:
            row.update(intake_class_hint="live_candidate", capture_mode="owner_forum_export_timely")
            rep["timely"] += 1
        else:
            row.update(intake_class_hint="backfill", capture_mode="owner_forum_export_backfill",
                       forward_evidence_eligible=False,
                       source_notice="Owner 事后导出（超过 7 天或时间未知）：仅用于理解与历史检验，不计入前瞻验证。")
            rep["backfill"] += 1
        rep["title_only"] += e["body_status"] == "title_only"
        rep["body_missing"] += e["body_status"] == "body_missing"
        rows.append(row)
        have.add((e["author"].casefold(), rf._canonical(e["url"])))
        st["done"][r["post_id"]] = row["capture_mode"]
    if rows:
        rep["appended"] = rf.append_records(rows)
    st["updated_at"] = now.isoformat(timespec="seconds")
    st_path.write_text(json.dumps(st, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return rep


if __name__ == "__main__":
    out = run()
    print(json.dumps({"owner_forum_feed": out}, ensure_ascii=False))
    if out.get("text_unavailable"):
        print(f"::warning title=owner forum export::{out['text_unavailable']} utterances could not be read from the "
              "textpack (TEXTPACK_TOKEN missing or expired?); retried next run")
    sys.exit(0)
