#!/usr/bin/env python3
"""WXC-RECOVERY-DIAGNOSTIC (Owner 2026-11-05): which public Wenxuecity entries does the collector's own runner reach?

Read-only, low-frequency, run manually from GitHub Actions (the environment the collectors run in), never from any
other network. Probes, in order and once each:
  A. finance category list          blog.wenxuecity.com/blog/?act=moreList&cat=cjjr
  B. configured blogger overviews     /myoverview/<blog_id>/   (BrightLine 82458, 麻你 78105, yifan99 31983)
  C. their current and previous month archives  /myblog/<blog_id>/<YYYYMM>/
  D. up to 2 recent article pages discovered by A-C (body readability only)
  E. forum list page 1                bbs.wenxuecity.com/cfzh/   (are the tracked forum authors visible?)
For each request it records URL, HTTP status, Content-Type, bytes, page title, expected-structure flags, article links
found and whether a body was readable, failure type and time. No HTML, cookies or request headers are stored. A 403
or 429 stops that entry family for the rest of the run (no retry, no proxy, no UA change, no captcha handling).
Search-engine snippets are never used.

  python wxc_source_diagnostic.py [--out diagnostics/wxc_source_diagnostic.json] [--delay 6]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import wxc_blog as blog

FORUM_LIST = "https://bbs.wenxuecity.com/cfzh/"
FORUM_AUTHORS = ["三心三意", "我是一只井底蛙", "bogbog", "yifan99"]
UA = blog.HEADERS["User-Agent"]  # the collector's own, unchanged User-Agent


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def probe(sess, url: str, family: str, stopped: set, delay: float, fetch=None) -> tuple[dict, str | None]:
    """One GET. Returns (record, html-or-None). html is kept in memory only for parsing, never written."""
    rec = {"family": family, "url": url, "at": now()}
    if family in stopped:
        rec.update(status="not_requested", failure="family_stopped_after_403_429")
        return rec, None
    try:
        r = (fetch or sess.get)(url, timeout=25)
    except requests.RequestException as e:
        rec.update(status=None, failure=f"network:{type(e).__name__}")
        return rec, None
    finally:
        time.sleep(delay)
    body = r.content or b""
    rec.update(status=r.status_code, content_type=(r.headers.get("Content-Type") or "").split(";")[0], bytes=len(body))
    if r.status_code in (403, 429):
        stopped.add(family)
        rec["failure"] = f"http_{r.status_code}_access_restricted"
        return rec, None
    if r.status_code != 200:
        rec["failure"] = f"http_{r.status_code}"
        return rec, None
    r.encoding = r.apparent_encoding or "utf-8"
    html = r.text
    t = BeautifulSoup(html, "html.parser").title
    rec["title"] = (t.get_text(" ", strip=True)[:120] if t else None)
    return rec, html


def run(delay: float = 6.0, fetch=None, today=None) -> dict:
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})
    stopped: set = set()
    out, article_candidates = [], []
    today = today or datetime.now(timezone.utc)
    months = [(today.year, today.month), (today.year - (today.month == 1), 12 if today.month == 1 else today.month - 1)]
    ids = {p["author"]: p["blog_id"] for p in blog.PROFILES.values()}

    rec, html = probe(sess, blog.CATEGORY_URL, "blog_category", stopped, delay, fetch)
    if html is not None:
        cat = blog.parse_category(html, ids.values())
        rec.update(structure_ok=cat["links_total"] > 0, article_links=cat["links_total"],
                   configured_author_links={a: len(cat["by_blog_id"][b]) for a, b in ids.items()},
                   unattributed_links=cat["unattributed_links"])
        for rows in cat["by_blog_id"].values():
            article_candidates += [r["url"] for r in rows]
    out.append(rec)

    for author, bid in ids.items():
        for kind, url in [("blog_overview", blog.overview_url(bid))] + [
                ("blog_archive", blog.archive_url(bid, y, m)) for y, m in months]:
            rec, html = probe(sess, url, "blog_author_pages", stopped, delay, fetch)
            rec["author"], rec["kind"] = author, kind
            if html is not None:
                rows = blog.parse_archive(html, bid)
                rec.update(structure_ok=bool(rows) or blog.archive_structure_ok(html, bid), article_links=len(rows))
                article_candidates += [r["url"] for r in rows]
            out.append(rec)

    seen = []
    for u in article_candidates:
        if u not in seen:
            seen.append(u)
    for url in seen[:2]:
        rec, html = probe(sess, url, "blog_article", stopped, delay, fetch)
        if html is not None:
            p = blog.parse_article(html, url, "?")
            rec.update(structure_ok=bool(p), body_readable=bool(p and p.get("text")), body_chars=len(p["text"]) if p else 0)
        out.append(rec)

    rec, html = probe(sess, FORUM_LIST, "forum_list", stopped, delay, fetch)
    if html is not None:
        rec.update(structure_ok=bool(re.search(r'class="post"', html)),
                   authors_visible={a: (a in html) for a in FORUM_AUTHORS})
    out.append(rec)

    fam = {}
    for r in out:
        f = fam.setdefault(r["family"], {"requests": 0, "ok": 0, "restricted": 0, "not_requested": 0, "other_failure": 0})
        if r.get("status") == "not_requested":
            f["not_requested"] += 1
            continue
        f["requests"] += 1
        if r.get("status") == 200 and r.get("structure_ok", True):
            f["ok"] += 1
        elif str(r.get("failure", "")).endswith("access_restricted"):
            f["restricted"] += 1
        else:
            f["other_failure"] += 1
    verdict = {k: ("REACHABLE" if v["ok"] and not v["restricted"] else "RESTRICTED" if v["restricted"] else
                   "UNKNOWN" if not v["requests"] else "FAILING") for k, v in fam.items()}
    return {"version": 1, "generated_at": now(), "runner": "github_actions (collector environment)",
            "policy": "read-only, low frequency, stop on 403/429, no bypass, no HTML/cookies stored, no search snippets",
            "delay_seconds": delay, "families": fam, "verdict": verdict, "probes": out,
            "blog_ids_unknown": {"三心三意": "UNKNOWN (no evidence of a blog id; forum author)",
                                 "我是一只井底蛙": "UNKNOWN (no evidence of a blog id; forum author)"}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="diagnostics/wxc_source_diagnostic.json")
    ap.add_argument("--delay", type=float, default=6.0)
    a = ap.parse_args(argv)
    rep = run(a.delay)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": rep["verdict"], "families": rep["families"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
