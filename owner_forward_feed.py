#!/usr/bin/env python3
"""Owner forwards -> research feed (S2 v5 source C, Owner 2026-11-09).

Runs in research-close. For each row of state/owner_forward_index.jsonl whose full text is stored in the private
textpack repo and that is not yet in the feed, it reads the full text at RUNTIME ONLY (GitHub Contents API,
TEXTPACK_TOKEN), runs the normal understanding path (research_feed.normalize: claims, author actions, method
signals) and appends the record. The feed keeps only the usual fields (title, <=360-char excerpt, structured
claims, hashes); the full text is never written to the public repo.

Timeliness (Owner 2026-11-09: one week, bloggers do not always post on time):
- forwarded within 7 days of publication -> intake_class_hint=live_candidate, capture_mode=owner_forward_timely.
  Forward scoring always starts at captured_at (when MyAlpha received it), never at the publication date.
- later than 7 days, or publication date unknown -> backfill, capture_mode=owner_forward_backfill,
  forward_evidence_eligible=False (understanding and historical testing only).
Existing feed records are never rewritten: a link already in the feed for the same author is skipped.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import owner_forward as fw
import research_feed as rf
import wxc_blog as blog

TIMELY_DAYS = 7
STATE = "owner_forward_feed_state.json"


def _data() -> Path:
    return Path(os.getenv("DATA_DIR", "state"))


def _dt(s: str | None):
    if not s:
        return None
    s = str(s).strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19] if " " in s else s[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def attribute(url: str) -> tuple[str, str]:
    """(source_kind, author) from the link only. Unknown blogs / other sites stay unattributed."""
    m = re.search(r"blog\.wenxuecity\.com/myblog/(\d+)/", url or "")
    if m:
        for p in blog.PROFILES.values():
            if p["blog_id"] == m.group(1):
                return "blog", p["author"]
        return "blog", f"wxc_blog_{m.group(1)}"
    if "bbs.wenxuecity.com" in (url or ""):
        return "forum", "owner_forward_unattributed"
    return "owner_forward", "owner_forward_unattributed"


def fetch_text(item_id: str, http=requests) -> str | None:
    token, repo = os.getenv("TEXTPACK_TOKEN", ""), os.getenv("TEXTPACK_REPO", "")
    if not token or not repo:
        return None
    r = http.get(f"https://api.github.com/repos/{repo}/contents/s2_v5_textpack/C_owner_forward/{item_id}.txt",
                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=30)
    if getattr(r, "status_code", 0) != 200:
        return None
    return base64.b64decode(r.json()["content"]).decode("utf-8")


def run(http=requests, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    idx = fw.index_path()
    if not idx.exists():
        return {"pending": 0, "appended": 0}
    st_path = _data() / STATE
    st = json.loads(st_path.read_text(encoding="utf-8")) if st_path.exists() else {"done": {}}
    feed = json.loads(rf.FEED_PATH.read_text(encoding="utf-8")) if rf.FEED_PATH.exists() else {"records": []}
    have = {(str(x.get("author") or "").casefold(), rf._canonical(str(x.get("url") or ""))) for x in feed.get("records", [])}
    rows, report = [], {"pending": 0, "appended": 0, "timely": 0, "backfill": 0, "already_in_feed": 0,
                        "text_unavailable": 0}
    for line in idx.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("textpack") != "stored" or r["item_id"] in st["done"]:
            continue
        report["pending"] += 1
        kind, author = attribute(r["source_url"])
        if (author.casefold(), rf._canonical(r["source_url"])) in have:
            st["done"][r["item_id"]] = "already_in_feed"
            report["already_in_feed"] += 1
            continue
        text = fetch_text(r["item_id"], http)
        if text is None:
            report["text_unavailable"] += 1  # retried next run; nothing recorded as done
            continue
        pub, got = _dt(r.get("published_at")), _dt(r.get("retrieved_at"))
        lag_h = round((got - pub).total_seconds() / 3600, 1) if pub and got else None
        timely = lag_h is not None and -24 <= lag_h <= TIMELY_DAYS * 24
        post = {"title": r.get("title"), "text": text, "url": r["source_url"],
                "date": (r.get("published_at") or "")[:10], "images": []}
        row = rf.normalize(kind if kind != "owner_forward" else "blog", author, post)
        row.update({"intake_provenance": "owner_forward", "owner_forward_item_id": r["item_id"],
                    "owner_forward_retrieved_at": r.get("retrieved_at"), "publication_lag_hours": lag_h,
                    "content_sha256": r.get("sha256")})
        if kind == "owner_forward":
            row["source_kind"] = "owner_forward"
        if timely:
            row.update(intake_class_hint="live_candidate", capture_mode="owner_forward_timely")
            report["timely"] += 1
        else:
            row.update(intake_class_hint="backfill", capture_mode="owner_forward_backfill", forward_evidence_eligible=False,
                       source_notice="Owner 事后转发（超过 7 天或发布时间未知）：仅用于理解与历史检验，不计入前瞻验证。")
            report["backfill"] += 1
        rows.append(row)
        have.add((author.casefold(), rf._canonical(r["source_url"])))
        st["done"][r["item_id"]] = row["capture_mode"]
    if rows:
        report["appended"] = rf.append_records(rows)
    st["updated_at"] = now.isoformat(timespec="seconds")
    st_path.write_text(json.dumps(st, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    rep = run()
    print(json.dumps({"owner_forward_feed": rep}, ensure_ascii=False))
    if rep.get("text_unavailable"):
        print(f"::warning title=owner forward::{rep['text_unavailable']} forwarded items could not be read from the textpack "
              "(TEXTPACK_TOKEN missing or expired?); retried next run")
    sys.exit(0)
