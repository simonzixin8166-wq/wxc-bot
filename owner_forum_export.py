#!/usr/bin/env python3
"""Owner forum export intake (Owner 2026-11-10): topic files the Owner exports himself, sent to the Telegram bot.

Input: a .md topic file (or a .zip of them) with this layout, one file per forum topic:
  # <root title>
  - **楼主**：<author>　**时间**：YYYY-MM-DD HH:MM
  - **参与的目标用户**：a, b
  - **链接**：https://bbs.wenxuecity.com/<board>/<id>.html
  ## 主帖
  <root body | （无正文，标题即内容） | （正文为空）>
  ## 跟帖
  - [<title>](<url>) — <author | **author** ⭐> MM-DD HH:MM (N bytes)
    > <body line>            (optional; replies nest by two spaces)

Each utterance by a target author (the root post if he wrote it, and every ⭐ reply) becomes one entry: author,
time, link, the post it answers and the replies it received. The bot never opens any link. The collection method is
declared by the Owner (he exports the topics himself); MyAlpha does not fetch these pages and does not automate the
export. Full topic files go only to the private textpack repo; the public index keeps title (<=120), <=360-char
excerpt, link, hashes and counts.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

MAX_EXCERPT = 360
MAX_TITLE = 120
HEAD_RE = re.compile(r"\*\*楼主\*\*\s*[:：]\s*(?P<author>[^\s　*]+)(?:\s*　?\s*\*\*时间\*\*\s*[:：]\s*(?P<time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}))?")
LINK_RE = re.compile(r"\*\*链接\*\*\s*[:：]\s*(https?://\S+)")
TARGETS_RE = re.compile(r"\*\*参与的目标用户\*\*\s*[:：]\s*(.+)")
REPLY_RE = re.compile(r"^(?P<indent> *)- \[(?P<title>.*)\]\((?P<url>https?://[^)\s]+)\) — (?P<who>.+?) "
                      r"(?P<md>\d{2}-\d{2}) (?P<hm>\d{2}:\d{2})(?: \((?P<bytes>\d+) bytes\))?\s*$")
POST_ID_RE = re.compile(r"bbs\.wenxuecity\.com/(?P<board>[^/]+)/(?P<id>\d+)\.html")
EMPTY_BODY = ("（无正文，标题即内容）", "（正文为空）")


def is_topic(md: str) -> bool:
    return "**楼主**" in md and "## 跟帖" in md and "## 主帖" in md


def _post_id(url: str) -> tuple[str | None, str | None]:
    m = POST_ID_RE.search(url or "")
    return (m.group("board"), m.group("id")) if m else (None, None)


def own_text(lines: list[str]) -> str:
    """The author's own words from an exported reply body: drop the '本帖于…编辑' line and the quoted
    '回答: <parent> 由 <who> 于 <time>' block that the forum prepends."""
    lines = [l for l in lines if not re.match(r"^本帖于.*编辑$", l.strip())]
    if lines and lines[0].strip() in ("回答:", "回答："):
        for i, l in enumerate(lines):
            if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$", l.strip()) and i >= 2 and lines[i - 1].strip() == "于":
                return "\n".join(x.strip() for x in lines[i + 1:] if x.strip())
        return ""
    return "\n".join(x.strip() for x in lines if x.strip())


def parse_topic(md: str) -> dict | None:
    if not is_topic(md):
        return None
    lines = md.splitlines()
    title = next((l[2:].strip() for l in lines if l.startswith("# ")), "")
    head = HEAD_RE.search(md)
    link = LINK_RE.search(md)
    if not head or not link:
        return None
    board, root_id = _post_id(link.group(1))
    if not root_id:
        return None
    root_time = head.group("time")
    year = int(root_time[:4]) if root_time else None
    root_month = int(root_time[5:7]) if root_time else None
    targets = {t.strip() for t in (TARGETS_RE.search(md).group(1).split(",") if TARGETS_RE.search(md) else []) if t.strip()}
    a, b = md.index("## 主帖"), md.index("## 跟帖")
    body = "\n".join(l for l in md[a + len("## 主帖"):b].strip().splitlines() if not re.match(r"^本帖于.*编辑$", l.strip())).strip()
    pending = body.startswith("（") and "尚未抓取" in body
    root = {"post_id": root_id, "url": f"https://bbs.wenxuecity.com/{board}/{root_id}.html", "board": board,
            "author": head.group("author"), "title": title, "published_at": (root_time + ":00") if root_time else None,
            "depth": 0, "parent": None, "body": "" if (body in EMPTY_BODY or pending) else body,
            "body_bytes": 0 if body in EMPTY_BODY else None, "target": head.group("author") in targets}
    nodes, stack = [root], [root]
    for l in md[b:].splitlines()[1:]:
        m = REPLY_RE.match(l)
        if m:
            depth = len(m.group("indent")) // 2 + 1
            who = m.group("who").strip()
            target = who.endswith("⭐")
            author = who.replace("⭐", "").strip().strip("*").strip()
            mo, d = int(m.group("md")[:2]), int(m.group("md")[3:])
            y = year + (1 if (year and root_month and mo < root_month) else 0) if year else None
            _, pid = _post_id(m.group("url"))
            parent = stack[min(depth, len(stack)) - 1]
            node = {"post_id": pid, "url": m.group("url"), "board": board, "author": author, "title": m.group("title"),
                    "published_at": f"{y:04d}-{mo:02d}-{d:02d} {m.group('hm')}:00" if y else None, "depth": depth,
                    "parent": parent["post_id"], "body_lines": [], "body_bytes": int(m.group("bytes") or 0),
                    "target": target}
            nodes.append(node)
            stack = stack[:depth] + [node]
            continue
        q = re.match(r"^ *> ?(.*)$", l)
        if q and len(nodes) > 1:
            nodes[-1]["body_lines"].append(q.group(1))
    by_id = {n["post_id"]: n for n in nodes}
    entries = []
    for n in nodes:
        if not n["target"]:
            continue
        if n["depth"] == 0:
            text = n["body"]
            status = "body_exported" if text else ("title_only" if n["body_bytes"] == 0 else "body_missing")
        else:
            text = own_text(n.pop("body_lines"))
            text = "" if "尚未抓取" in text and len(text) < 40 else text
            status = "title_only" if n["body_bytes"] == 0 else ("body_exported" if text else "body_missing")
        utter = (n["title"] + ("\n" + text if text else "")).strip()
        par = by_id.get(n["parent"]) if n["parent"] else None
        kids = [c for c in nodes if c["parent"] == n["post_id"]]
        entries.append({
            "post_id": n["post_id"], "url": n["url"], "board": board, "author": n["author"],
            "kind": "post" if n["depth"] == 0 else "reply", "published_at": n["published_at"],
            "title": n["title"][:MAX_TITLE], "text": utter, "body_status": status, "body_bytes": n["body_bytes"],
            "root_post_id": root_id, "root_title": title[:MAX_TITLE],
            "parent": ({"post_id": par["post_id"], "author": par["author"], "title": par["title"][:MAX_TITLE],
                        "published_at": par["published_at"]} if par else None),
            "replies": [{"post_id": c["post_id"], "author": c["author"], "title": c["title"][:MAX_TITLE],
                         "depth": c["depth"], "in_reply_to": n["post_id"], "body_bytes": c["body_bytes"],
                         "published_at": c["published_at"]} for c in kids],
            "sha256": hashlib.sha256(utter.encode("utf-8")).hexdigest()})
    for n in nodes:
        n.pop("body_lines", None)
    return {"root_post_id": root_id, "board": board, "root_title": title, "root_author": root["author"],
            "topic_sha256": hashlib.sha256(md.encode("utf-8")).hexdigest(), "posts": len(nodes), "entries": entries}


# ---------------------------------------------------------------- per-author digest (Owner 2026-11-21)
# "文学城博主整理" mail: one .md per author, his utterances grouped by topic:
#   # <author> 的发言整理
#   ## <topic title>
#   楼主 <root author> · YYYY-MM-DD HH:MM · [原帖](https://bbs.wenxuecity.com/<board>/<id>.html)
#   ### YYYY-MM-DD HH:MM · <utterance title>
#   > 回复 <who>「<parent title>」：<parent excerpt>        (optional)
#   <body> | （标题即全文） | （正文未抓到…） | [图片](…)
# Replies carry no link of their own, so a reply's id is "<root id>r<YYYYMMDDHHMM>" and it is also matched to the
# daily export by (author, minute, title) so the same utterance is never stored twice.
DIGEST_HEAD_RE = re.compile(r"^# (?P<author>\S+) 的发言整理\s*$", re.M)
DIGEST_TOPIC_RE = re.compile(r"^楼主 (?P<author>\S+) · (?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · \[原帖\]\((?P<url>https?://[^)\s]+)\)")
DIGEST_UTT_RE = re.compile(r"^### (?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · (?P<title>.*)$")
DIGEST_REPLY_RE = re.compile(r"^> 回复 (?P<who>\S+?)「(?P<title>.*?)」(?:：.*)?$")
IMAGE_RE = re.compile(r"^!?\[[^\]]*\]\([^)]*\)\s*$")


def is_author_digest(md: str) -> bool:
    return bool(DIGEST_HEAD_RE.search(md or "")) and "### " in md and "楼主 " in md


def utterance_key(author: str, published_at: str | None, title: str) -> str:
    return f"{(author or '').casefold()}|{(published_at or '')[:16]}|{(title or '').strip()[:40]}"


def parse_author_digest(md: str) -> dict | None:
    head = DIGEST_HEAD_RE.search(md or "")
    if not head or not is_author_digest(md):
        return None
    author = head.group("author")
    entries, topic, cur = [], None, None

    def close():
        if cur is None:
            return
        lines = [l for l in cur.pop("lines") if l.strip() and not IMAGE_RE.match(l.strip())]
        body = "\n".join(lines).strip()
        if body.startswith("（标题即全文）"):
            status, body = "title_only", ""
        elif body.startswith("（") and "未抓到" in body:
            status, body = "body_missing", ""
        else:
            status = "body_exported" if body else "title_only"
        utter = (cur["title"] + ("\n" + body if body else "")).strip()
        cur.update(text=utter, body_status=status, body_bytes=0 if status == "title_only" else len(body.encode("utf-8")),
                   sha256=hashlib.sha256(utter.encode("utf-8")).hexdigest())
        entries.append(cur)

    for l in md.splitlines():
        if l.startswith("## ") and not l.startswith("### "):
            close(); cur = None
            topic = {"title": l[3:].strip(), "root": None}
            continue
        m = DIGEST_TOPIC_RE.match(l)
        if m and topic is not None:
            board, rid = _post_id(m.group("url"))
            topic.update(root={"post_id": rid, "board": board, "author": m.group("author"), "time": m.group("time"),
                               "url": f"https://bbs.wenxuecity.com/{board}/{rid}.html" if rid else m.group("url")})
            continue
        m = DIGEST_UTT_RE.match(l)
        if m and topic and topic["root"] and topic["root"]["post_id"]:
            close()
            root, t = topic["root"], m.group("time")
            is_root = root["author"] == author and t == root["time"]
            rid = f"{root['post_id']}r{t.replace('-', '').replace(' ', '').replace(':', '')}{hashlib.sha1(author.encode('utf-8')).hexdigest()[:4]}"
            cur = {"post_id": root["post_id"] if is_root else rid,
                   "url": root["url"], "board": root["board"], "author": author, "kind": "post" if is_root else "reply",
                   "published_at": t + ":00", "title": m.group("title").strip()[:MAX_TITLE],
                   "root_post_id": root["post_id"], "root_title": topic["title"][:MAX_TITLE],
                   "parent": None if is_root else {"post_id": root["post_id"], "author": root["author"],
                                                   "title": topic["title"][:MAX_TITLE], "published_at": root["time"] + ":00"},
                   "replies": [], "url_is_topic": not is_root, "lines": []}
            continue
        if cur is not None:
            r = DIGEST_REPLY_RE.match(l.strip())
            if r and not any(x.strip() for x in cur["lines"]):
                cur["parent"] = {"post_id": None, "author": r.group("who"), "title": r.group("title")[:MAX_TITLE],
                                 "published_at": None}
            else:
                cur["lines"].append(l)
    close()
    if not entries:
        return None
    # two replies by the same author in the same topic and minute: tell them apart by title (stable per utterance)
    ids = [x["post_id"] for x in entries]
    for x in entries:
        if x["kind"] == "reply" and ids.count(x["post_id"]) > 1:
            x["post_id"] += "t" + hashlib.sha1(x["title"].encode("utf-8")).hexdigest()[:4]
    return {"digest_author": author, "board": entries[0]["board"], "root_post_id": entries[0]["root_post_id"],
            "root_title": f"{author} 的发言整理", "topic_sha256": hashlib.sha256(md.encode("utf-8")).hexdigest(),
            "posts": len(entries), "entries": entries}


def parse_any(md: str) -> dict | None:
    """A daily topic file or a per-author digest."""
    return parse_topic(md) if is_topic(md) else parse_author_digest(md)


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        t = parse_topic(open(p, encoding="utf-8").read())
        print(json.dumps({k: v for k, v in (t or {}).items() if k != "entries"}, ensure_ascii=False),
              len((t or {}).get("entries", [])))


# ---------------------------------------------------------------- storage + Telegram routing (called by owner_forward)
import base64  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402


def index_path() -> Path:
    return Path(os.getenv("DATA_DIR", "./data")) / "owner_forum_index.jsonl"


def textpack_path(topic: dict) -> str:
    if topic.get("digest_author"):
        safe = re.sub(r"[^0-9A-Za-z_-]", "_", topic["digest_author"])
        return f"s2_v5_textpack/F_owner_forum/digest_{safe}_{topic['topic_sha256'][:12]}.md"
    return f"s2_v5_textpack/F_owner_forum/{topic['board']}_{topic['root_post_id']}_{topic['topic_sha256'][:12]}.md"


def _store(path: str, md: str, http) -> str:
    token, repo = os.getenv("TEXTPACK_TOKEN", ""), os.getenv("TEXTPACK_REPO", "")
    if not token or not repo:
        return "unavailable (TEXTPACK_TOKEN / TEXTPACK_REPO not set; full text not stored)"
    r = http.put(f"https://api.github.com/repos/{repo}/contents/{path}", timeout=30,
                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                 json={"message": f"owner forum export {path.rsplit('/', 1)[-1]}",
                       "content": base64.b64encode(md.encode("utf-8")).decode("ascii")})
    code = getattr(r, "status_code", 0)
    if code in (200, 201):
        return "stored"
    if code == 422:  # same path already exists = this exact topic version was stored before
        return "stored"
    return f"failed (GitHub {code})"


def existing() -> dict:
    out = {}
    p = index_path()
    for line in p.read_text(encoding="utf-8").splitlines() if p.exists() else []:
        if line.strip():
            r = json.loads(line)
            out[r["post_id"]] = r
    return out


def _seen_keys(seen: dict) -> set:
    return {utterance_key(r.get("author"), r.get("published_at"), r.get("title")) for r in seen.values()}


def ingest_topic(md: str, retrieved_at: str, now, http, seen: dict, input_kind: str) -> dict:
    """Store one exported topic (or a per-author digest). Returns counts {new, duplicate, failed, entries, ...}.
    An utterance already stored under another id (daily export vs digest) is a duplicate: same author, minute, title."""
    c = {"new": 0, "duplicate": 0, "failed": 0, "entries": 0, "title_only": 0, "body_missing": 0}
    t = parse_any(md)
    if not t:
        c["failed"] += 1
        return c
    keys = _seen_keys(seen)
    fresh = [e for e in t["entries"] if e["post_id"] not in seen
             and utterance_key(e["author"], e["published_at"], e["title"]) not in keys]
    c["entries"], c["duplicate"] = len(t["entries"]), len(t["entries"]) - len(fresh)
    if not fresh:
        return c
    path = textpack_path(t)
    status = _store(path, md, http)
    p = index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for e in fresh:
            row = {k: e[k] for k in ("post_id", "url", "board", "author", "kind", "published_at", "title", "body_status",
                                     "body_bytes", "root_post_id", "root_title", "sha256")}
            row.update(excerpt=e["text"][:MAX_EXCERPT], text_chars=len(e["text"]),
                       parent_post_id=(e["parent"] or {}).get("post_id"), replies_received=len(e["replies"]),
                       topic_sha256=t["topic_sha256"], textpack_path=path, textpack=status, retrieved_at=retrieved_at,
                       url_is_topic=bool(e.get("url_is_topic")),
                       input=input_kind, collection="owner_export (exported by the Owner himself; MyAlpha does not fetch these pages)",
                       indexed_at=now.isoformat(timespec="seconds"))
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            seen[e["post_id"]] = row
            c["new"] += 1
            c["title_only"] += e["body_status"] == "title_only"
            c["body_missing"] += e["body_status"] == "body_missing"
    if status != "stored":
        c["failed"] += 1
    return c


def summary_zh(topics: int, c: dict) -> str:
    return (f"论坛话题 {topics} 个：目标作者发言新收录 {c['new']} 条，已收录过 {c['duplicate']} 条；"
            f"其中只有标题（0 字节，标题即全文）{c['title_only']} 条，正文未导出 {c['body_missing']} 条（只按标题理解，不猜正文）。"
            + (f"\n⚠️ {c['failed']} 个话题没有存进私有仓库（TEXTPACK_TOKEN？），下次重发即可。" if c["failed"] else "")
            + "\n全文只存私有仓库；公开仓库只记标题、摘录、链接和哈希。")


# ---------------------------------------------------------------- structured export (index/posts.jsonl), Owner 2026-11-10
def is_index_bundle(names: list[str]) -> bool:
    return any(n.endswith("posts.jsonl") for n in names)


def _hm(t: str | None) -> tuple[str, str]:
    t = (t or "").replace("T", " ")
    return t[:16], (t[5:16] if len(t) >= 16 else "")


def topics_from_index(posts_jsonl: str) -> tuple[list[str], list[dict]]:
    """Rebuild topic files (the same layout as the .md export) from posts.jsonl, so both formats share one parser,
    one dedupe (post_id) and one storage path. Returns (topic markdown list, non-forum rows such as blog posts)."""
    rows, other = [], []
    for line in posts_jsonl.splitlines():
        if not line.strip():
            continue
        p = json.loads(line)
        if str(p.get("source") or "").startswith("blog") or not p.get("topic_id"):
            other.append(p)
            continue
        rows.append(p)
    by_topic: dict[str, list[dict]] = {}
    for p in rows:
        by_topic.setdefault(str(p["topic_id"]), []).append(p)
    out = []
    for tid, ps in by_topic.items():
        root = next((p for p in ps if str(p.get("post_id")) == tid or int(p.get("depth") or 0) == 0), None)
        if not root:
            continue
        kids: dict[str, list[dict]] = {}
        for p in ps:
            if p is not root:
                kids.setdefault(str(p.get("parent_id")), []).append(p)
        targets = sorted({p["author"] for p in ps if p.get("is_target")})
        full, _ = _hm(root.get("time"))
        body = (root.get("body") or "").strip()
        lines = [f"# {root.get('title') or ''}", "",
                 f"- **楼主**：{root['author']}　**时间**：{full}" if full else f"- **楼主**：{root['author']}",
                 f"- **参与的目标用户**：{', '.join(targets)}", f"- **链接**：{root['url']}",
                 f"- **跟帖数**：{len(ps) - 1}", "", "## 主帖", "",
                 body or ("（无正文，标题即内容）" if int(root.get("bytes") or 0) == 0 else "（正文为空）"), "", "## 跟帖", ""]

        def walk(pid: str, depth: int):
            for c in sorted(kids.get(pid, []), key=lambda x: (str(x.get("time") or ""), str(x.get("post_id")))):
                ind = "  " * (depth - 1)
                who = f"**{c['author']}** ⭐" if c.get("is_target") else c["author"]
                size = f" ({int(c['bytes'])} bytes)" if int(c.get("bytes") or 0) > 0 else ""
                lines.append(f"{ind}- [{c.get('title') or ''}]({c['url']}) — {who} {_hm(c.get('time'))[1]}{size}")
                for bl in (c.get("body") or "").splitlines():
                    if bl.strip():
                        lines.append(f"{ind}  > {bl}")
                walk(str(c["post_id"]), depth + 1)
        walk(tid, 1)
        out.append("\n".join(lines) + "\n")
    return out, other
