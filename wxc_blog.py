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


def get(url: str, retries: int = 3, delay: float = 2.5):
    """Low-frequency request with bounded retry; no anti-bot bypass."""
    for i in range(retries):
        try:
            r = sess.get(url, timeout=25)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or "utf-8"
                time.sleep(delay)
                return r
            if r.status_code in (403, 429):
                print(f"  ! HTTP {r.status_code}, stop/retry later: {url}")
                time.sleep(delay * (i + 2))
            else:
                print(f"  ! HTTP {r.status_code}: {url}")
        except requests.RequestException as e:
            print(f"  ! {e}")
            time.sleep(delay * (i + 2))
    return None


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
    archive_months_requested=month_range(start,end)
    archive_months_ok=[]
    archive_failures=[]
    for year, month in archive_months_requested:
        url = archive_url(profile["blog_id"], year, month)
        print(f"[博客归档] {year:04d}-{month:02d} {url}")
        r = get(url, delay=delay)
        if not r:
            archive_failures.append(f"{year:04d}-{month:02d}")
            continue
        archive_months_ok.append(f"{year:04d}-{month:02d}")
        for row in parse_archive(r.text, profile["blog_id"]):
            links[row["url"]] = row

    # A monthly archive can lag or temporarily omit a new post. Merge the
    # author's overview as an independent recent-post discovery path so the
    # next scheduled run can recover missed posts without manual insertion.
    overview = overview_url(profile["blog_id"])
    print(f"[博客概览] {overview}")
    r = get(overview, delay=delay)
    overview_ok=bool(r)
    if r:
        for row in parse_archive(r.text, profile["blog_id"]):
            links[row["url"]] = row

    posts = []
    image_count = 0
    selected_links=list(links.values()) if max_articles is None else list(links.values())[:max_articles]
    for i, row in enumerate(selected_links, 1):
        url = row["url"]
        print(f"[博客文章] {i}/{len(selected_links)} {url}")
        r = get(url, delay=delay)
        if not r:
            continue
        p = parse_article(r.text, url, profile["author"])
        if not p:
            print("  ! 文章解析失败")
            continue
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
        "scan_complete":not archive_failures,
        "retention_policy":"no_article_count_cap",
    }
