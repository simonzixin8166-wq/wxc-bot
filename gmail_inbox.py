#!/usr/bin/env python3
"""Owner e-mail inbox (Owner 2026-11-17): the Owner's own daily "文学城每日整理" export arrives by Gmail as a zip;
a Google Apps Script in the Owner's own Google account copies each new attachment into the PRIVATE textpack repo
under inbox/gmail/. The Telegram bot picks those files up on its periodic check and runs exactly the same intake
as a zip the Owner forwards by hand (owner_forward.handle), then replies in Telegram.

- Only the Owner's own exports (Owner confirmed 2026-11-17: produced by his own browsing/saving, not a scraper).
- The bot never contacts the forum or any link; only api.github.com (private textpack repo) and Telegram.
- Full text stays in the private repo; the public repo keeps the usual index rows (title, excerpt, link, hash).
- state/gmail_inbox_seen.json records every processed file (path + git sha) so nothing is ingested twice.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

import owner_forward

INBOX = "inbox/gmail"
NAME_RE = re.compile(r"^(\d{8}T\d{6}Z)_")          # <received UTC>_<gmail message id>_<attachment name>
PREFIX_RE = re.compile(r"^\d{8}T\d{6}Z_[0-9A-Za-z]+_")


def _seen_path() -> Path:
    return Path(os.getenv("DATA_DIR", "./data")) / "gmail_inbox_seen.json"


def _load_seen() -> dict:
    p = _seen_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"files": {}}


def _save_seen(doc: dict) -> None:
    p = _seen_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _received_ts(name: str, now: datetime) -> int:
    m = NAME_RE.match(name)
    if m:
        try:
            return int(datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            pass
    return int(now.timestamp())


def check(say, http=requests, now=None) -> dict:
    """Process new files in the private inbox. Returns counts; never raises for one bad file."""
    token, repo = os.getenv("TEXTPACK_TOKEN", ""), os.getenv("TEXTPACK_REPO", "")
    if not token or not repo:
        return {"status": "off (TEXTPACK_TOKEN / TEXTPACK_REPO not set)"}
    now = now or datetime.now(timezone.utc)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = http.get(f"https://api.github.com/repos/{repo}/contents/{INBOX}", headers=headers, timeout=30)
    if getattr(r, "status_code", 0) == 404:
        return {"status": "empty"}
    if getattr(r, "status_code", 0) != 200:
        return {"status": f"list failed (GitHub {getattr(r, 'status_code', '?')})"}
    seen = _load_seen()
    out = {"status": "ok", "new": 0, "processed": 0, "failed": 0}
    for f in sorted((x for x in r.json() if x.get("type") == "file"), key=lambda x: x["name"]):
        key = f["path"]
        if seen["files"].get(key) == f.get("sha"):
            continue
        out["new"] += 1
        raw = http.get(f"https://api.github.com/repos/{repo}/contents/{f['path']}",
                       headers={**headers, "Accept": "application/vnd.github.raw"}, timeout=60)
        if getattr(raw, "status_code", 0) != 200:
            out["failed"] += 1
            continue
        data = raw.content
        name = PREFIX_RE.sub("", f["name"])
        msg = {"date": _received_ts(f["name"], now), "caption": "",
               "document": {"file_name": name, "file_size": len(data)}, "_bytes": data}
        try:
            say(f"📧 邮件自动收录：{name}")
            owner_forward.handle(msg, say, http=http, now=now)
            out["processed"] += 1
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the bot
            out["failed"] += 1
            say(f"邮件附件 {name} 收录失败（{type(exc).__name__}），已跳过。")
        seen["files"][key] = f.get("sha")
        _save_seen(seen)
    return out
