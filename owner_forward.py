#!/usr/bin/env python3
"""Owner forward intake (S2 v5 source C, Owner 2026-11-06).

The Owner reads a public article in his own browser and forwards it to the Telegram bot:
  /fw <link>            followed by the article text (same message), or
  an .html / .htm / .txt file ("save page as"), with the link in the caption.

What happens:
- Full text goes ONLY to the dedicated private repo TEXTPACK_REPO (token TEXTPACK_TOKEN, scoped to that repo),
  temporarily, for S2 v5 labelling; it is deleted after the test-set freeze (Owner #133 6648886468).
- The public repo keeps only title, <=360-char excerpt, link, sha256, chars and status in
  state/owner_forward_index.jsonl.
- The bot NEVER opens the forwarded link. A link without text is answered with "please attach the text".
  The only hosts contacted are api.telegram.org (to download the Owner's own file) and api.github.com.
- Without TEXTPACK_TOKEN the full text is not stored anywhere; the index row says textpack=unavailable.
- Paywalled / login-only / private content must not be forwarded (Owner's responsibility; stated in the reply).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

MAX_EXCERPT = 360
MIN_BODY_CHARS = 80          # less than this after removing the link = "link only"
MAX_FILE_BYTES = 3_000_000
DOC_EXT = (".html", ".htm", ".txt")
URL_RE = re.compile(r"https?://[^\s<>\"'，。）)]+")


def _data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "./data"))


def index_path() -> Path:
    return _data_dir() / "owner_forward_index.jsonl"


def canonical(url: str) -> str:
    p = urlsplit(url.strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, p.query, ""))


def is_forward(msg: dict) -> bool:
    text = (msg.get("text") or "").strip()
    if text.lower().startswith("/fw"):
        return True
    doc = msg.get("document") or {}
    return bool(doc) and str(doc.get("file_name") or "").lower().endswith(DOC_EXT)


def extract_html(html: str) -> tuple[str | None, str]:
    """(title, body text). Wenxuecity blog/forum bodies first, otherwise the page text without chrome."""
    s = BeautifulSoup(html or "", "html.parser")
    # <title> before <h1>: on Wenxuecity blog pages the h1 is the blog's name, the <title> is the post's
    node = s.select_one("#titleName")
    title = node.get_text(" ", strip=True) if node else None
    if not title and s.title and s.title.get_text(strip=True):
        title = s.title.get_text(" ", strip=True).split(" - ")[0].strip()
    if not title and s.select_one("h1"):
        title = s.select_one("h1").get_text(" ", strip=True)
    for t in s(["script", "style", "noscript", "nav", "header", "footer", "form"]):
        t.decompose()
    body = (s.select_one("#articalContent") or s.select_one(".articalContent") or s.select_one("#postbody")
            or s.select_one("article") or s.body or s)
    text = re.sub(r"\n\s*\n+", "\n", body.get_text("\n", strip=True)).strip()
    return title, text


def _download_owner_file(file_id: str, tg_api: str, tg_file_base: str, http) -> bytes | None:
    r = http.get(f"{tg_api}/getFile", params={"file_id": file_id}, timeout=30).json()
    path = ((r or {}).get("result") or {}).get("file_path")
    if not path:
        return None
    f = http.get(f"{tg_file_base}/{path}", timeout=60)
    return f.content if getattr(f, "status_code", 200) == 200 else None


def _store_textpack(item: dict, text: str, http) -> str:
    token, repo = os.getenv("TEXTPACK_TOKEN", ""), os.getenv("TEXTPACK_REPO", "")
    if not token or not repo:
        return "unavailable (TEXTPACK_TOKEN / TEXTPACK_REPO not set; full text not stored)"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    base = f"https://api.github.com/repos/{repo}/contents/s2_v5_textpack/C_owner_forward/{item['item_id']}"
    for suffix, payload in ((".txt", text + "\n"),
                            (".meta.json", json.dumps(item, ensure_ascii=False, indent=1) + "\n")):
        r = http.put(base + suffix, headers=headers, timeout=30, json={
            "message": f"owner forward {item['item_id']}",
            "content": base64.b64encode(payload.encode("utf-8")).decode("ascii")})
        if getattr(r, "status_code", 0) not in (200, 201):
            return f"failed (GitHub {getattr(r, 'status_code', '?')})"
    return "stored"


def _existing() -> dict:
    p = index_path()
    out = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                out[row["sha256"]] = row
    return out


def handle(msg: dict, say, tg_api: str = "", tg_file_base: str = "", http=requests, now=None) -> dict | None:
    """Process one Owner message. Returns the public index row (or None when nothing was stored)."""
    now = now or datetime.now(timezone.utc)
    raw = (msg.get("text") or msg.get("caption") or "").strip()
    raw = re.sub(r"^/fw\b", "", raw, flags=re.I).strip()
    urls = URL_RE.findall(raw)
    url = canonical(urls[0]) if urls else None
    title, text = None, URL_RE.sub("", raw).strip()

    doc = msg.get("document") or {}
    if doc:
        if int(doc.get("file_size") or 0) > MAX_FILE_BYTES:
            say("文件太大（超过 3MB），没有收录。请改为复制正文加链接发送。")
            return None
        data = _download_owner_file(doc.get("file_id", ""), tg_api, tg_file_base, http)
        if data is None:
            say("没能下载你发的文件，没有收录。请重发一次。")
            return None
        body = data.decode("utf-8", errors="replace")
        if str(doc.get("file_name") or "").lower().endswith(".txt"):
            text = body.strip()
        else:
            title, text = extract_html(body)

    if not url:
        say("请附上原文链接（地址栏的网址），这条没有收录。")
        return None
    if len(text) < MIN_BODY_CHARS:
        say("只收到链接，没有正文。我不会自己打开链接，请把正文复制进来（或发送“另存为”的网页文件），再附上链接。")
        return None
    if not title:
        first = text.splitlines()[0].strip()
        title = first[:80]

    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    seen = _existing()
    if sha in seen:
        say(f"这篇已经收录过了（{seen[sha]['item_id']}），没有重复保存。")
        return None

    item = {"item_id": "C-" + sha[:12], "source_family": "C_owner_forward", "source_url": url,
            "host": urlsplit(url).netloc, "title": title, "chars": len(text), "sha256": sha,
            "retrieved_at": datetime.fromtimestamp(int(msg.get("date") or now.timestamp()), timezone.utc)
                            .isoformat(timespec="seconds"),
            "retrieved_by": "owner (own browser, forwarded via Telegram)",
            "input": "html_file" if doc and not str(doc.get("file_name", "")).lower().endswith(".txt")
                     else ("txt_file" if doc else "message_text"),
            "retention": "temporary for S2 v5 labelling; delete after test-set freeze (Owner #133 6648886468)",
            "claims_status": "experimental_unvalidated"}
    status = _store_textpack(item, text, http)
    row = {k: item[k] for k in ("item_id", "source_family", "source_url", "host", "title", "chars", "sha256",
                                "retrieved_at", "input")}
    row.update(excerpt=text[:MAX_EXCERPT], textpack=status, indexed_at=now.isoformat(timespec="seconds"))
    p = index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    say(f"已收录 {row['item_id']}：{title}\n{len(text)} 字 · 全文：{status}\n"
        "公开仓库只记标题、摘录、链接和哈希。付费、需登录或私人内容请不要转发。")
    return row
