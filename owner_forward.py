#!/usr/bin/env python3
"""Owner forward intake (S2 v5 source C, Owner 2026-11-06).

The Owner reads a public article in his own browser and forwards it to the Telegram bot:
  /fw <link>            followed by the article text (same message), or
  an .html / .htm / .txt file ("save page as"), with the link in the caption, or
  a .md / .txt file whose header carries 原文链接 (link read from the file), or
  a .zip of such files (read in memory; each article needs its own 原文链接 line).

What happens:
- Full text goes ONLY to the dedicated private repo TEXTPACK_REPO (token TEXTPACK_TOKEN, scoped to that repo) and is
  kept there long-term for personal, non-commercial learning; it is never published (Owner charter 2026-11-09).
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
import io
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

MAX_EXCERPT = 360
MIN_BODY_CHARS = 80          # less than this after removing the link = "link only"
MAX_FILE_BYTES = 3_000_000
DOC_EXT = (".html", ".htm", ".txt", ".md", ".zip")
ZIP_EXT = (".html", ".htm", ".txt", ".md")
MAX_ZIP_FILES = 300
MAX_ZIP_UNCOMPRESSED = 30_000_000
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


def parse_markdown(md: str) -> tuple[str | None, str | None, str | None, str]:
    """(title, source_url, published_at, body) from a saved .md / .txt article.
    Header lines before the first '---' may carry 发布时间 / 原文链接 (also Published / Source / URL)."""
    title = url = published = None
    head, sep, rest = md.partition("\n---")
    body = rest.lstrip("-").strip() if sep and re.search(r"原文链接|Source|URL", head, re.I) else md.strip()
    for line in (head if sep else md).splitlines()[:12]:
        t = line.strip()
        if t.startswith("# ") and not title:
            title = t[2:].strip()
        if re.search(r"原文链接|原文|Source|URL", t, re.I) and not url:
            m = URL_RE.search(t)
            url = canonical(m.group(0)) if m else None
        m = re.search(r"(?:发布时间|Published)\**\s*[:：]\**\s*(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?)", t, re.I)
        if m and not published:
            published = m.group(1)
    if body.startswith("# "):
        body = body.split("\n", 1)[1].strip() if "\n" in body else ""
    return title, url, published, body


def _ingest(text: str, title: str | None, url: str | None, published: str | None, input_kind: str,
            retrieved_at: str, now: datetime, http, seen: dict, seen_urls: dict) -> tuple[str, dict | None]:
    """Store one article. Returns (outcome, row): stored / duplicate / no_link / no_text / failed:..."""
    if not url:
        return "no_link", None
    if len(text) < MIN_BODY_CHARS:
        return "no_text", None
    title = title or text.splitlines()[0].strip()[:80]
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if sha in seen or seen_urls.get(url, {}).get("textpack") == "stored":
        return "duplicate", seen.get(sha) or seen_urls.get(url)
    item = {"item_id": "C-" + sha[:12], "source_family": "C_owner_forward", "source_url": url,
            "host": urlsplit(url).netloc, "title": title, "chars": len(text), "sha256": sha,
            "published_at": published, "retrieved_at": retrieved_at,
            "retrieved_by": "owner (own browser, forwarded via Telegram)", "input": input_kind,
            "retention": "private long-term for personal non-commercial learning; never published (Owner charter 2026-11-09)",
            "claims_status": "experimental_unvalidated"}
    status = _store_textpack(item, text, http)
    row = {k: item[k] for k in ("item_id", "source_family", "source_url", "host", "title", "chars", "sha256",
                                "published_at", "retrieved_at", "input")}
    row.update(excerpt=text[:MAX_EXCERPT], textpack=status, indexed_at=now.isoformat(timespec="seconds"))
    p = index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    seen[sha] = row
    seen_urls[url] = row
    return ("stored" if status == "stored" else status), row


def _zip_members(data: bytes) -> list[tuple[str, str]] | str:
    """(name, text) of article files inside a zip, read in memory only. A string means refused."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return "不是有效的 zip 文件"
    infos = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(ZIP_EXT)
             and not os.path.basename(i.filename).startswith(".") and "__MACOSX" not in i.filename]
    if len(infos) > MAX_ZIP_FILES:
        return f"文件太多（{len(infos)} 个，上限 {MAX_ZIP_FILES}）"
    if sum(i.file_size for i in infos) > MAX_ZIP_UNCOMPRESSED:
        return "解压后太大（上限 30MB）"
    return [(i.filename, z.read(i).decode("utf-8", errors="replace")) for i in sorted(infos, key=lambda x: x.filename)]


def _parse_file(name: str, body: str, caption_url: str | None):
    n = name.lower()
    if n.endswith((".md", ".txt")):
        title, url, published, text = parse_markdown(body)
        return title, (url or caption_url), published, text, ("md_file" if n.endswith(".md") else "txt_file")
    title, text = extract_html(body)
    return title, caption_url, None, text, "html_file"


def handle(msg: dict, say, tg_api: str = "", tg_file_base: str = "", http=requests, now=None) -> dict | None:
    """Process one Owner message. Returns the public index row of a single stored article (None otherwise);
    a zip returns a summary dict {"zip": counts}."""
    now = now or datetime.now(timezone.utc)
    raw = (msg.get("text") or msg.get("caption") or "").strip()
    raw = re.sub(r"^/fw\b", "", raw, flags=re.I).strip()
    urls = URL_RE.findall(raw)
    url = canonical(urls[0]) if urls else None
    retrieved_at = datetime.fromtimestamp(int(msg.get("date") or now.timestamp()), timezone.utc).isoformat(timespec="seconds")
    seen, seen_urls = _existing(), {}
    for r in seen.values():
        seen_urls.setdefault(r.get("source_url"), r)

    doc = msg.get("document") or {}
    if not doc:
        outcome, row = _ingest(URL_RE.sub("", raw).strip(), None, url, None, "message_text", retrieved_at, now, http,
                               seen, seen_urls)
        _reply_one(say, outcome, row)
        return row if outcome not in ("duplicate", "no_link", "no_text") else None

    if int(doc.get("file_size") or 0) > MAX_FILE_BYTES:
        say("文件太大（超过 3MB），没有收录。请改为复制正文加链接发送，或分成几个小 zip。")
        return None
    data = _download_owner_file(doc.get("file_id", ""), tg_api, tg_file_base, http)
    if data is None:
        say("没能下载你发的文件，没有收录。请重发一次。")
        return None
    name = str(doc.get("file_name") or "")

    if name.lower().endswith(".zip"):
        members = _zip_members(data)
        if isinstance(members, str):
            say(f"zip 没有收录：{members}。")
            return None
        counts = {"stored": 0, "duplicate": 0, "no_link": 0, "no_text": 0, "failed": 0}
        problems = []
        for fname, body in members:
            title, furl, published, text, kind = _parse_file(fname, body, None)
            outcome, _row = _ingest(text, title, furl, published, "zip:" + kind, retrieved_at, now, http, seen, seen_urls)
            key = outcome if outcome in counts else "failed"
            counts[key] += 1
            if key in ("no_link", "no_text", "failed"):
                problems.append(f"{os.path.basename(fname)[:40]}（{ {'no_link': '缺原文链接', 'no_text': '正文太短'}.get(key, outcome)}）")
        say(f"zip 共 {len(members)} 篇：新收录 {counts['stored']}，已收录过 {counts['duplicate']}，"
            f"缺链接 {counts['no_link']}，正文太短 {counts['no_text']}，保存失败 {counts['failed']}。"
            + ("\n未收录：" + "；".join(problems[:10]) if problems else "")
            + "\n全文只存私有仓库，公开仓库只记标题、摘录、链接和哈希。")
        return {"zip": counts, "files": len(members)}

    title, furl, published, text = _parse_file(name, data.decode("utf-8", errors="replace"), url)[:4]
    kind = _parse_file(name, "", None)[4]
    outcome, row = _ingest(text, title, furl, published, kind, retrieved_at, now, http, seen, seen_urls)
    _reply_one(say, outcome, row)
    return row if outcome not in ("duplicate", "no_link", "no_text") else None


def _reply_one(say, outcome: str, row: dict | None) -> None:
    if outcome == "no_link":
        say("请附上原文链接（地址栏的网址），这条没有收录。")
    elif outcome == "no_text":
        say("只收到链接，没有正文。我不会自己打开链接，请把正文复制进来（或发送“另存为”的网页文件），再附上链接。")
    elif outcome == "duplicate":
        say(f"这篇已经收录过了（{(row or {}).get('item_id', '?')}），没有重复保存。")
    else:
        say(f"已收录 {row['item_id']}：{row['title']}\n{row['chars']} 字 · 全文：{row['textpack']}\n"
            "公开仓库只记标题、摘录、链接和哈希。付费、需登录或私人内容请不要转发。")
