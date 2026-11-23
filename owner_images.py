#!/usr/bin/env python3
"""Images in the Owner's own exports (Owner 2026-11-21: zip with an images/ folder; understanding comes later).

Intake only. An image inside a zip the Owner sends (Telegram or Gmail) is stored once, by content hash, in the
PRIVATE textpack repo (s2_v5_textpack/G_owner_images/<sha256>.<ext>). The public repo keeps only the hash, size,
type, the zip member name and which exported .md files / utterances refer to it (state/owner_image_index.jsonl).
Nothing here calls Gemini or any model: every row says understanding=not_started until the ~20-image test the Owner
agreed to has passed. Tiny GIFs (<=3KB: emoji, icons) are skipped. No web page or image URL is ever fetched.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import time
import zipfile
from pathlib import Path

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
TINY_GIF_BYTES = 3 * 1024
MAX_IMAGE_BYTES = 8_000_000          # one image
MAX_IMAGES_PER_ZIP = 150             # GitHub content-creation limits: ~80 writes/minute
MAX_IMAGES_UNCOMPRESSED = 60_000_000
PUT_PAUSE_S = 0.8
TEXTPACK_DIR = "s2_v5_textpack/G_owner_images"
REF_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")


def index_path() -> Path:
    return Path(os.getenv("DATA_DIR", "./data")) / "owner_image_index.jsonl"


def existing() -> dict:
    p = index_path()
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines() if p.exists() else []:
        if line.strip():
            r = json.loads(line)
            out[r["sha256"]] = r
    return out


def zip_images(data: bytes) -> tuple[list[tuple[str, bytes]], dict]:
    """(member name, bytes) of the images in a zip, read in memory; plus skip counts."""
    skipped = {"tiny_gif": 0, "too_large": 0, "over_cap": 0}
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return [], skipped
    infos = sorted((i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(IMAGE_EXT)
                    and "__MACOSX" not in i.filename and not os.path.basename(i.filename).startswith(".")),
                   key=lambda i: i.filename)
    out, total = [], 0
    for i in infos:
        if i.filename.lower().endswith(".gif") and i.file_size <= TINY_GIF_BYTES:
            skipped["tiny_gif"] += 1
            continue
        if i.file_size > MAX_IMAGE_BYTES:
            skipped["too_large"] += 1
            continue
        if len(out) >= MAX_IMAGES_PER_ZIP or total + i.file_size > MAX_IMAGES_UNCOMPRESSED:
            skipped["over_cap"] += 1
            continue
        out.append((i.filename, z.read(i)))
        total += i.file_size
    return out, skipped


def references(md_files: list[tuple[str, str]]) -> dict[str, list[str]]:
    """image basename -> the exported .md files that link to it (e.g. ![](images/a.png) or [图片](images/a.png))."""
    refs: dict[str, list[str]] = {}
    for fname, body in md_files:
        for target in REF_RE.findall(body or ""):
            if target.lower().startswith(("http://", "https://")):
                continue
            refs.setdefault(os.path.basename(target), [])
            if fname not in refs[os.path.basename(target)]:
                refs[os.path.basename(target)].append(fname)
    return refs


def _store(path: str, blob: bytes, http) -> str:
    token, repo = os.getenv("TEXTPACK_TOKEN", ""), os.getenv("TEXTPACK_REPO", "")
    if not token or not repo:
        return "unavailable (TEXTPACK_TOKEN / TEXTPACK_REPO not set; image not stored)"
    r = http.put(f"https://api.github.com/repos/{repo}/contents/{path}", timeout=60,
                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                 json={"message": f"owner image {path.rsplit('/', 1)[-1]}",
                       "content": base64.b64encode(blob).decode("ascii")})
    code = getattr(r, "status_code", 0)
    return "stored" if code in (200, 201, 422) else f"failed (GitHub {code})"   # 422 = same hash stored before


def ingest_zip(data: bytes, md_files: list[tuple[str, str]], retrieved_at: str, now, http, pause=PUT_PAUSE_S) -> dict:
    """Store the zip's images once each. Returns counts {images, new, duplicate, failed, tiny_gif, too_large, over_cap}."""
    imgs, skipped = zip_images(data)
    c = {"images": len(imgs), "new": 0, "duplicate": 0, "failed": 0, **skipped}
    if not imgs:
        return c
    seen, refs = existing(), references(md_files)
    p = index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    for member, blob in imgs:
        sha = hashlib.sha256(blob).hexdigest()
        if sha in seen:
            c["duplicate"] += 1
            continue
        ext = os.path.splitext(member)[1].lower().replace(".jpeg", ".jpg")
        path = f"{TEXTPACK_DIR}/{sha}{ext}"
        status = _store(path, blob, http)
        if status != "stored":
            c["failed"] += 1        # not indexed: the next send of the same zip retries it
            continue
        row = {"sha256": sha, "ext": ext.lstrip("."), "bytes": len(blob), "member": member,
               "referenced_in": refs.get(os.path.basename(member), []), "textpack_path": path, "textpack": status,
               "retrieved_at": retrieved_at, "understanding": "not_started (image test pending)",
               "collection": "owner_export (exported by the Owner himself; MyAlpha does not fetch images)",
               "indexed_at": now.isoformat(timespec="seconds")}
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        seen[sha] = row
        c["new"] += 1
        if pause:
            time.sleep(pause)
    return c


def summary_zh(c: dict) -> str:
    if not (c.get("images") or c.get("tiny_gif") or c.get("too_large") or c.get("over_cap")):
        return ""
    extra = "；".join(x for x in (f"跳过小 gif {c['tiny_gif']} 张" if c.get("tiny_gif") else "",
                                 f"单张超过 8MB {c['too_large']} 张" if c.get("too_large") else "",
                                 f"超过单次上限 {c['over_cap']} 张（请分包重发）" if c.get("over_cap") else "",
                                 f"保存失败 {c['failed']} 张（重发即可）" if c.get("failed") else "") if x)
    return (f"图片 {c['images']} 张：新收录 {c['new']}，已收录过 {c['duplicate']}" + (f"；{extra}" if extra else "")
            + "。图片只存私有仓库，暂不理解（等 20 张图测试通过）。")
