#!/usr/bin/env python3
"""Literature City blog collector used by the Telegram bot.

The first supported profile is BrightLine / BRGHTLINE / 亮线留痕 (blog id 82458).
The parser is intentionally defensive because old Wenxuecity blog pages use more
than one HTML template.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BLOG_ROOT = "https://blog.wenxuecity.com"
PROFILES = {
    "brightline": {
        "author": "BrightLine",
        "blog_id": "82458",
        "aliases": ["brightline", "brghtline", "亮线留痕"],
    },
    "mani": {
        "author": "麻你",
        "blog_id": "78105",
        "aliases": ["麻你"],
    },
    "yifan99": {
        "author": "yifan99",
        "blog_id": "31983",
        "aliases": ["yifan99", "yifan"],
    },
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Apple Silicon Mac OS X) AppleWebKit/537.36 Chrome/124 Safari/537.36"
}
sess = requests.Session()
sess.headers.update(HEADERS)


def resolve_profile(name: str):
    key = (name or "").strip().casefold()
    for profile in PROFILES.values():
        if key == profile["author"].casefold() or key in [x.casefold() for x in profile["aliases"]]:
            return dict(profile)
    return None


def archive_url(blog_id: str, year: int, month: int) -> str:
    return f"{BLOG_ROOT}/myblog/{blog_id}/{year:04d}{month:02d}/"

def overview_url(blog_id: str) -> str:
    """Author overview used as a second discovery path for recent posts."""
    return f"{BLOG_ROOT}/myoverview/{blog_id}/"


# Access-restriction bookkeeping for one process run (2026-11-05, WXC-RECOVERY-DIAGNOSTIC §4.1).
# A 403 or 429 means the site refused us: stop at once, never retry in the same run, and record it, so a refusal
# is never reported as "no new articles". Once the blog host refused one request, no further request goes to that
# host in this run (politeness; no bypass of any kind).
ACCESS_LOG: list[dict] = []
RESTRICTED_HOSTS: set[str] = set()


def _host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1).lower() if m else ""


def reset_access_state():
    ACCESS_LOG.clear()
    RESTRICTED_HOSTS.clear()


def get(url: str, retries: int = 3, delay: float = 2.5):
    """Low-frequency request with bounded retry for transient errors only; no anti-bot bypass.
    403/429 stop immediately (no retry) and mark the host as restricted for the rest of this run."""
    host = _host(url)
    if host in RESTRICTED_HOSTS:
        ACCESS_LOG.append({"url": url, "status": "skipped_host_restricted", "at": datetime.utcnow().isoformat() + "Z"})
        return None
    for i in range(retries):
        try:
            r = sess.get(url, timeout=25)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or "utf-8"
                time.sleep(delay)
                return r
            if r.status_code in (403, 429):
                print(f"  ! HTTP {r.status_code}: access restricted, stop (no retry this run): {url}")
                RESTRICTED_HOSTS.add(host)
                ACCESS_LOG.append({"url": url, "status": r.status_code, "at": datetime.utcnow().isoformat() + "Z"})
                return None
            print(f"  ! HTTP {r.status_code}: {url}")
        except requests.RequestException as e:
            print(f"  ! {e}")
        time.sleep(delay * (i + 2))
    ACCESS_LOG.append({"url": url, "status": "failed_after_retries", "at": datetime.utcnow().isoformat() + "Z"})
    return None


def access_restricted() -> bool:
    return bool(RESTRICTED_HOSTS)


def _article_id(url: str) -> str:
    path = re.search(r"/(\d{6})/(\d+)\.html", url or "")
    if path:
        return f"{path.group(1)}-{path.group(2)}"
    return hashlib.md5((url or "").encode()).hexdigest()[:16]


def parse_archive(html: str, blog_id: str):
    """Return unique article links found on an author archive page."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    patterns = (
        re.compile(rf"/myblog/{re.escape(str(blog_id))}/\d{{6}}/\d+\.html", re.I),
        re.compile(rf"/myblog/{re.escape(str(blog_id))}/\d+\.html", re.I),
    )
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not any(p.search(href) for p in patterns):
            continue
        url = urljoin(BLOG_ROOT, href)
        if url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "title": a.get_text(" ", strip=True)})
    return out


def archive_structure_ok(html: str, blog_id: str) -> bool:
    """A real author archive / overview page links to the author's own blog space. A 200 page with no article links
    AND no trace of the author's blog id is an unrecognised page (layout change, interstitial, error page), not
    "zero new articles"."""
    return bool(re.search(rf"/(?:myblog|myoverview)/{re.escape(str(blog_id))}(?:/|\b)", html or ""))


CATEGORY_URL = f"{BLOG_ROOT}/blog/?act=moreList&cat=cjjr"
# Off until the diagnostic shows the finance category page is reachable and parseable from the collector's runner.
CATEGORY_DISCOVERY = os.getenv("WXC_BLOG_CATEGORY_DISCOVERY", "0") == "1"
_CATEGORY_CACHE: dict = {}


def parse_category(html: str, blog_ids) -> dict:
    """Article links on the finance category list, attributed ONLY by the blog id in the link path. Links of blog ids
    that are not configured are counted but never attributed to a configured author."""
    soup = BeautifulSoup(html or "", "html.parser")
    wanted = {str(b) for b in blog_ids}
    by_id, unattributed, seen = {b: [] for b in wanted}, 0, set()
    for a in soup.find_all("a", href=True):
        m = re.search(r"/myblog/(\d+)/\d{6}/\d+\.html", a["href"])
        if not m:
            continue
        url = urljoin(BLOG_ROOT, a["href"])
        if url in seen:
            continue
        seen.add(url)
        if m.group(1) in wanted:
            by_id[m.group(1)].append({"url": url, "title": a.get_text(" ", strip=True)})
        else:
            unattributed += 1
    return {"by_blog_id": by_id, "unattributed_links": unattributed, "links_total": len(seen)}


def category_links(blog_id: str, delay: float = 2.5):
    """One category fetch per run, shared by all profiles. None when the page could not be read."""
    if "result" not in _CATEGORY_CACHE:
        r = get(CATEGORY_URL, delay=delay)
        ids = [p["blog_id"] for p in PROFILES.values()]
        _CATEGORY_CACHE["result"] = parse_category(r.text, ids) if r else None
    res = _CATEGORY_CACHE["result"]
    return None if res is None else res["by_blog_id"].get(str(blog_id), [])


def _pick(soup, selectors):
    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            return node
    return None


def _parse_date(text: str):
    text = re.sub(r"\s+", " ", text or "").strip()
    patterns = [
        (r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})", "%Y-%m-%d"),
        (r"(\d{1,2})/(\d{1,2})/(20\d{2})", "%m/%d/%Y"),
    ]
    for pat, fmt in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        raw = "-".join(m.groups()) if fmt == "%Y-%m-%d" else "/".join(m.groups())
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    return None


def parse_article(html: str, url: str, author: str = "BrightLine"):
    soup = BeautifulSoup(html, "html.parser")
    title = _pick(soup, [
        "#titleName", ".titleName", "h1.titleName", "h1.article-title",
        ".blog_title h1", "article h1", "h1",
    ])
    body = _pick(soup, [
        "#articalContent", "#articleContent", ".articalContent", ".articleContent",
        ".article-content", ".blog_content", "article",
    ])
    if not title or not body:
        return None

    for x in body.select("script,style,noscript,.share,.ad,.adsbygoogle"):
        x.decompose()

    images = []
    for im in body.find_all("img"):
        src = im.get("data-src") or im.get("data-original") or im.get("src")
        if src and not src.startswith("data:"):
            full = urljoin(url, src)
            if full not in images:
                images.append(full)

    for br in body.find_all("br"):
        br.replace_with("\n")
    text = body.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    date_node = _pick(soup, ["#time", ".time", ".blog_time", ".article-time", "time"])
    surrounding = " ".join([
        date_node.get_text(" ", strip=True) if date_node else "",
        soup.get_text(" ", strip=True)[:2500],
        url,
    ])
    dt = _parse_date(surrounding)
    if not dt:
        m = re.search(r"/(20\d{2})(\d{2})/", url)
        if m:
            dt = datetime(int(m.group(1)), int(m.group(2)), 1)

    return {
        "id": _article_id(url),
        "source": "wenxuecity_blog",
        "blog_id": re.search(r"/myblog/(\d+)/", url).group(1) if re.search(r"/myblog/(\d+)/", url) else "",
        "url": url,
        "title": title.get_text(" ", strip=True),
        "author": author,
        "date": dt.strftime("%Y-%m-%d") if dt else "",
        "text": text,
        "images": images,
    }


def download_image(url: str, imgdir: str, min_bytes: int = 3000, max_bytes: int = 15_000_000):
    os.makedirs(imgdir, exist_ok=True)
    stem = hashlib.md5(url.encode()).hexdigest()[:12]
    for f in os.listdir(imgdir):
        if f.startswith(stem):
            return f
    try:
        r = sess.get(url, timeout=25, headers={**HEADERS, "Referer": BLOG_ROOT + "/"})
    except requests.RequestException:
        return None
    ct = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if r.status_code != 200 or not ct.startswith("image") or not (min_bytes <= len(r.content) <= max_bytes):
        return None
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}.get(ct, ".jpg")
    name = stem + ext
    with open(os.path.join(imgdir, name), "wb") as f:
        f.write(r.content)
    return name


def build(outdir: str, posts: list[dict]):
    posts = sorted(posts, key=lambda p: (p.get("date") or "", p.get("id") or ""))
    with open(os.path.join(outdir, "posts.md"), "w", encoding="utf-8") as md:
        md.write(f"# {posts[0]['author'] if posts else ''} 博客合集（{len(posts)} 篇）\n\n")
        for p in posts:
            md.write(f"## {p.get('date','')} | {p.get('title','')}\n\n")
            md.write(f"原文: {p.get('url','')}\n\n{p.get('text','')}\n\n")
            for im in p.get("local_images", []):
                md.write(f"![](images/{im})\n\n")
            if p.get("images") and not p.get("local_images"):
                md.write("图片链接: " + " ".join(p["images"]) + "\n\n")
            md.write("---\n\n")

    with open(os.path.join(outdir, "index.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["日期", "作者", "标题", "字数", "图片数", "链接", "来源"])
        for p in posts:
            w.writerow([
                p.get("date", ""), p.get("author", ""), p.get("title", ""),
                len(p.get("text", "")), len(p.get("images", [])),
                p.get("url", ""), p.get("source", "wenxuecity_blog"),
            ])

    with open(os.path.join(outdir, "posts.json"), "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def month_range(start: datetime, end: datetime):
    y, m = start.year, start.month
    out = []
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out


def collect(profile: dict, start: datetime, end: datetime, outdir: str, delay: float = 2.5,
            max_articles: int | None = None, max_images: int = 80, per_post_images: int = 12):
    os.makedirs(os.path.join(outdir, "posts"), exist_ok=True)
    os.makedirs(os.path.join(outdir, "images"), exist_ok=True)

    links = {}
    discovered_by = {}
    archive_months_requested=month_range(start,end)
    archive_months_ok=[]
    archive_failures=[]
    structure_unrecognized=[]
    for year, month in archive_months_requested:
        url = archive_url(profile["blog_id"], year, month)
        print(f"[博客归档] {year:04d}-{month:02d} {url}")
        r = get(url, delay=delay)
        if not r:
            archive_failures.append(f"{year:04d}-{month:02d}")
            continue
        rows = parse_archive(r.text, profile["blog_id"])
        if not rows and not archive_structure_ok(r.text, profile["blog_id"]):
            structure_unrecognized.append(url)
            archive_failures.append(f"{year:04d}-{month:02d}")
            continue
        archive_months_ok.append(f"{year:04d}-{month:02d}")
        for row in rows:
            links[row["url"]] = row
            discovered_by.setdefault(row["url"], set()).add("archive")

    # A monthly archive can lag or temporarily omit a new post. Merge the
    # author's overview as an independent recent-post discovery path so the
    # next scheduled run can recover missed posts without manual insertion.
    overview = overview_url(profile["blog_id"])
    print(f"[博客概览] {overview}")
    r = get(overview, delay=delay)
    overview_ok=bool(r)
    if r:
        rows = parse_archive(r.text, profile["blog_id"])
        if not rows and not archive_structure_ok(r.text, profile["blog_id"]):
            structure_unrecognized.append(overview)
            overview_ok = False
        for row in rows:
            links[row["url"]] = row
            discovered_by.setdefault(row["url"], set()).add("overview")

    category_ok = None
    if CATEGORY_DISCOVERY:
        cat = category_links(profile["blog_id"], delay=delay)
        category_ok = cat is not None
        for row in cat or []:
            links.setdefault(row["url"], row)
            discovered_by.setdefault(row["url"], set()).add("category_cjjr")

    posts = []
    image_count = 0
    selected_links=list(links.values()) if max_articles is None else list(links.values())[:max_articles]
    fetch_status = {}
    article_fetch_failures, article_parse_failures = [], []
    for i, row in enumerate(selected_links, 1):
        url = row["url"]
        print(f"[博客文章] {i}/{len(selected_links)} {url}")
        r = get(url, delay=delay)
        if not r:
            fetch_status[url] = "discovered_not_fetched"
            article_fetch_failures.append(url)
            continue
        p = parse_article(r.text, url, profile["author"])
        if not p:
            print("  ! 文章解析失败")
            fetch_status[url] = "fetched_not_parsed"
            article_parse_failures.append(url)
            continue
        fetch_status[url] = "fulltext_fetched" if p.get("text") else "fetched_not_parsed"
        p["fetch_status"] = fetch_status[url]
        p["discovered_by"] = sorted(discovered_by.get(url, []))
        try:
            dt = datetime.strptime(p.get("date", ""), "%Y-%m-%d")
        except ValueError:
            dt = None
        if dt and not (start.date() <= dt.date() <= end.date()):
            continue

        p["local_images"] = []
        for img in p.get("images", [])[:per_post_images]:
            if image_count >= max_images:
                break
            name = download_image(img, os.path.join(outdir, "images"))
            if name:
                p["local_images"].append(name)
                image_count += 1

        with open(os.path.join(outdir, "posts", f"{p['id']}.json"), "w", encoding="utf-8") as fh:
            json.dump(p, fh, ensure_ascii=False, indent=2)
        posts.append(p)

    build(outdir, posts)
    return {
        "posts": posts,
        "images_downloaded": image_count,
        "archive_months": len(archive_months_requested),
        "archive_months_requested":[f"{y:04d}-{m:02d}" for y,m in archive_months_requested],
        "archive_months_ok":archive_months_ok,
        "archive_failures":archive_failures,
        "overview_ok":overview_ok,
        "article_links_found": len(links),
        "posts_parsed":len(posts),
        "archive_success":archive_months_ok,
        "overview_success":overview_ok,
        "category_success":category_ok,
        "structure_unrecognized":structure_unrecognized,
        "article_fetch_success":sum(1 for v in fetch_status.values() if v != "discovered_not_fetched"),
        "article_fetch_failures":article_fetch_failures,
        "article_parse_success":sum(1 for v in fetch_status.values() if v == "fulltext_fetched"),
        "article_parse_failures":article_parse_failures,
        "fetch_status_counts":{k: sum(1 for v in fetch_status.values() if v == k) for k in sorted(set(fetch_status.values()))},
        "access_restricted":access_restricted(),
        "access_log":list(ACCESS_LOG),
        # complete only when every discovery path and every article read succeeded and nothing was refused
        "scan_complete":(not archive_failures and overview_ok and not article_fetch_failures and not article_parse_failures
                         and not access_restricted() and category_ok is not False),
        "partial_scan":bool(archive_failures or not overview_ok or article_fetch_failures or article_parse_failures
                            or access_restricted() or category_ok is False),
        "retention_policy":"no_article_count_cap",
    }
