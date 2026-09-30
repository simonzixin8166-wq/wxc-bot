#!/usr/bin/env python3
"""
文学城「财富智汇」博主发言抓取整理工具
用法示例:
  pip3 install requests beautifulsoup4
  python3 wxc_scraper.py --author 三心三意 --pages 1-30
  python3 wxc_scraper.py --author 三心三意 --pages 1-937 --since 2026-06-01
  python3 wxc_scraper.py --author 三心三意 --build-only --min-chars 200   # 只重新生成文档

输出目录: ./output_<作者>/
  posts/      每帖一个 JSON(断点续抓的缓存)
  images/     下载的图片
  posts.md    按时间排序的合集
  index.csv   索引(日期/标题/字数/股票代码/阅读数/链接)
"""
import argparse, csv, json, os, re, sys, time, hashlib
from datetime import datetime
from urllib.parse import urljoin, quote
import requests
from bs4 import BeautifulSoup

BASE = "https://bbs.wenxuecity.com/cfzh/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Apple Silicon Mac OS X) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
STOP = set("AI CEO IPO ETF FA EPS PE GDP CPI FOMC USA USD LOL OK IMO NEWS THE AND FOR ATH DCA IV RSI MACD OTM ITM API CPU GPU HBM AM PM ET PT".split())

sess = requests.Session()
sess.headers.update(HEADERS)

def get(url, retries=3, delay=2.5):
    for i in range(retries):
        try:
            r = sess.get(url, timeout=20)
            if r.status_code == 200:
                r.encoding = "utf-8"  # 站点为 UTF-8,避免误判编码
                time.sleep(delay)
                return r
            print(f"  ! HTTP {r.status_code}: {url}")
        except requests.RequestException as e:
            print(f"  ! {e}")
        time.sleep(delay * (i + 2))
    return None

# ---------- 列表页 ----------
def parse_list(html, author):
    """返回 [(post_id, url, title, date_str)],只保留指定作者。
    不依赖 <p> 父节点(原始 HTML 与浏览器保存版结构不同),
    而是取每个帖子链接之后紧跟的作者标签。"""
    soup = BeautifulSoup(html, "html.parser")
    posts = soup.select("a.post")
    out = []
    for i, a in enumerate(posts):
        sp = a.find_next("span", class_="b")
        if sp is None:
            continue
        nxt = posts[i + 1] if i + 1 < len(posts) else None
        if nxt is not None and (sp.sourceline, sp.sourcepos) > (nxt.sourceline, nxt.sourcepos):
            continue  # 该帖没有作者标签,别误取下一帖的
        au = sp.find("a")
        if not au or au.get_text(strip=True).casefold() != author.casefold():
            continue
        m = re.search(r"(\d+)\.html", a.get("href", ""))
        if not m:
            continue
        out.append((m.group(1), urljoin(BASE, a["href"]), a.get_text(strip=True), ""))
    return out

def list_latest(html):
    """列表页里最新一条帖子的时间(论坛自己的时钟),用来计算"最近N天",避免服务器时区差异"""
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    ts = []
    for d, t in re.findall(r"(\d{2}/\d{2}/\d{4})\s*(?:postreply)?\s*(\d{2}:\d{2}:\d{2})", text):
        try:
            ts.append(datetime.strptime(f"{d} {t}", "%m/%d/%Y %H:%M:%S"))
        except ValueError:
            pass
    return max(ts) if ts else None

def list_dates(html):
    return [datetime.strptime(d, "%m/%d/%Y") for d in re.findall(r"(\d{2}/\d{2}/\d{4})", html)]

# ---------- 帖子页 ----------
def parse_post(html, url, with_comments=False):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one("h1.title")
    body = soup.select_one("#msgbodyContent")
    if not title or not body:
        return None
    meta = soup.select_one("#postmeta")
    author = meta.select_one("a.username").get_text(strip=True) if meta and meta.select_one("a.username") else ""
    date = meta.select_one("span.date").get_text(strip=True) if meta and meta.select_one("span.date") else ""
    reads = meta.select_one("#countnum").get_text(strip=True) if meta and meta.select_one("#countnum") else ""
    likes = ""
    tip = soup.select_one("#tip-box")
    if tip:
        m = re.search(r"(\d+)", tip.get_text())
        likes = m.group(1) if m else ""
    images = []
    for im in body.find_all("img"):
        src = im.get("data-src") or im.get("data-original") or im.get("src")
        par = im.find_parent("a")
        if par and re.search(r"\.(?:jpe?g|png|gif|webp)(?:\?|$)", par.get("href", ""), re.I):
            src = par["href"]  # 缩略图外面套着原图链接时,取原图
        if src and not src.startswith("data:"):
            full = urljoin(url, src)
            if full not in images:
                images.append(full)
    for br in body.find_all("br"):
        br.replace_with("\n")
    text = body.get_text()
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    post = {
        "id": re.search(r"/(\d+)\.html", url).group(1),
        "url": url, "title": title.get_text(strip=True), "author": author,
        "date": date, "reads": reads, "likes": likes,
        "text": text, "images": images,
    }
    if with_comments:
        cs = []
        for p in soup.select("#comment #postlist p"):
            a = p.select_one("a.post"); n = p.select_one("a.nickname")
            if a and n:
                dm = re.search(r"(\d{2}/\d{2}/\d{4}).*?(\d{2}:\d{2}:\d{2})", p.get_text(" "), re.S)
                cs.append({"title": a.get_text(strip=True), "url": a["href"],
                           "author": n.get_text(strip=True),
                           "time": " ".join(dm.groups()) if dm else ""})
        post["comments"] = cs
    return post

def download_image(url, imgdir, min_bytes=3000, max_bytes=15_000_000):
    """下载一张图片,返回文件名;失败或是小图标(表情等)返回 None"""
    os.makedirs(imgdir, exist_ok=True)
    stem = hashlib.md5(url.encode()).hexdigest()[:12]
    for f in os.listdir(imgdir):
        if f.startswith(stem):
            return f
    try:
        r = sess.get(url, timeout=25, headers={"Referer": BASE})
    except requests.RequestException:
        return None
    ct = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if r.status_code != 200 or not ct.startswith("image") or not (min_bytes <= len(r.content) <= max_bytes):
        return None
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}.get(ct, ".jpg")
    name = stem + ext
    with open(os.path.join(imgdir, name), "wb") as f:
        f.write(r.content)
    time.sleep(1)
    return name

def tickers(text):
    found = re.findall(r"(?<![A-Za-z])([A-Z]{2,5})(?![A-Za-z])", text)
    return sorted({t for t in found if t not in STOP})

# ---------- 输出 ----------
def build(outdir, min_chars):
    pdir = os.path.join(outdir, "posts")
    posts = [json.load(open(os.path.join(pdir, f), encoding="utf-8")) for f in os.listdir(pdir) if f.endswith(".json")]
    posts = [p for p in posts if len(p["text"]) >= min_chars]
    posts.sort(key=lambda p: p["date"])
    with open(os.path.join(outdir, "posts.md"), "w", encoding="utf-8") as md:
        md.write(f"# {posts[0]['author'] if posts else ''} 发言合集({len(posts)} 篇)\n\n")
        for p in posts:
            md.write(f"## {p['date']} | {p['title']}\n\n")
            md.write(f"原帖: {p['url']}  阅读 {p['reads']}  点赞 {p['likes']}\n\n{p['text']}\n\n")
            for im in p.get("local_images", []):
                md.write(f"![](images/{im})\n\n")
            if p.get("images") and not p.get("local_images"):
                md.write("图片链接: " + " ".join(p["images"]) + "\n\n")
            md.write("---\n\n")
    with open(os.path.join(outdir, "index.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["日期", "标题", "字数", "股票代码", "阅读", "点赞", "图片数", "链接"])
        for p in posts:
            w.writerow([p["date"], p["title"], len(p["text"]), " ".join(tickers(p["title"] + " " + p["text"])),
                        p["reads"], p["likes"], len(p["images"]), p["url"]])
    print(f"已生成 {len(posts)} 篇 -> {outdir}/posts.md, index.csv")

# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--author", required=True)
    ap.add_argument("--pages", default="1-10", help="列表页范围,如 1-30")
    ap.add_argument("--since", help="只抓此日期之后的帖子 YYYY-MM-DD;整页都更早则停止翻页")
    ap.add_argument("--comments", action="store_true", help="同时记录跟帖列表")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--min-chars", type=int, default=0, help="输出时过滤短帖")
    ap.add_argument("--delay", type=float, default=2.5)
    ap.add_argument("--build-only", action="store_true")
    a = ap.parse_args()

    outdir = f"output_{a.author}"
    pdir = os.path.join(outdir, "posts"); os.makedirs(pdir, exist_ok=True)
    if a.build_only:
        return build(outdir, a.min_chars)

    lo, hi = [int(x) for x in a.pages.split("-")]
    since = datetime.strptime(a.since, "%Y-%m-%d") if a.since else None

    # 1) 收集链接
    targets = {}
    for pg in range(lo, hi + 1):
        url = f"{BASE}?page={pg}"
        print(f"[列表] 第 {pg} 页")
        r = get(url, delay=a.delay)
        if r is None:
            continue
        found = parse_list(r.text, a.author)
        n_all = len(BeautifulSoup(r.text, "html.parser").select("a.post"))
        print(f"  页面 {len(r.text)} 字符, 帖子链接 {n_all} 个, 匹配 {a.author} {len(found)} 个")
        if n_all == 0 or (not found and pg == lo):
            dbg = os.path.join(outdir, f"debug_page{pg}.html")
            open(dbg, "w", encoding="utf-8").write(r.text)
            print(f"  (已保存原始页面到 {dbg} 供排查)")
        for pid, href, title, d in found:
            targets[pid] = href
        if since:
            ds = list_dates(r.text)
            if ds and max(ds) < since:
                print("  已翻到早于 --since 的页面,停止")
                break
    print(f"共找到 {len(targets)} 个 {a.author} 的帖子")

    # 2) 逐帖抓取(已抓过的跳过)
    for i, (pid, href) in enumerate(sorted(targets.items(), reverse=True), 1):
        fp = os.path.join(pdir, f"{pid}.json")
        if os.path.exists(fp):
            continue
        print(f"[帖子] {i}/{len(targets)} {href}")
        r = get(href, delay=a.delay)
        if r is None:
            continue
        p = parse_post(r.text, href, a.comments)
        if not p:
            print("  ! 解析失败(可能需要登录或页面结构不同)")
            continue
        if since and p["date"] and datetime.strptime(p["date"][:10], "%Y-%m-%d") < since:
            continue
        p["local_images"] = [] if a.no_images else [n for n in (download_image(u, os.path.join(outdir, "images")) for u in p["images"]) if n]
        json.dump(p, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    build(outdir, a.min_chars)

if __name__ == "__main__":
    main()
