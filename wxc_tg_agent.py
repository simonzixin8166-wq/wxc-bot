#!/usr/bin/env python3
"""
Telegram 对话式抓取机器人(常驻运行)
你在 Telegram 里说一句话,它就去文学城抓取、整理,并把结果发回给你。
同时后台定时检查"已订阅"博主的新发言并自动推送。

依赖同目录的 wxc_scraper.py、wxc_tg_bot.py。

环境变量:
  TG_BOT_TOKEN       必填
  TG_CHAT_ID         必填。只响应这个 chat 的消息,其他人发的一律忽略
  ANTHROPIC_API_KEY  可选。有则用 Claude 理解自然语言指令并生成中文要点;无则用关键词规则
  DEFAULT_AUTHOR     默认博主,默认「三心三意」
  WATCH_MINUTES      订阅检查间隔(分钟),默认 30
  DATA_DIR           数据目录(订阅列表、已推送记录),默认 ./data,云端请挂持久卷

指令示例:
  抓一下三心三意最近3天的发言
  下载三心三意最近30页,只要长文
  订阅 三心三意 / 取消订阅 三心三意 / 订阅列表
"""
import json, os, re, shutil, threading, time, zipfile
from datetime import datetime, timedelta
import requests
import wxc_scraper as w
import wxc_tg_bot as b
import wxc_blog as blog

TOKEN = os.getenv("TG_BOT_TOKEN", "")
OWNER = str(os.getenv("TG_CHAT_ID", ""))
DEFAULT_AUTHOR = os.getenv("DEFAULT_AUTHOR", "三心三意")
WATCH_EVERY = int(os.getenv("WATCH_MINUTES", "30")) * 60
DATA = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA, exist_ok=True)
API = f"https://api.telegram.org/bot{TOKEN}"
WATCH_F = os.path.join(DATA, "watch.json")
MAX_JOB_POSTS = 150
MAX_IMAGES_JOB = 80      # 单次抓取最多下载的图片数
MAX_IMAGES_PER_POST = 12
MAX_PUSH_IMAGES = 10     # 订阅推送时最多发几张图
JOBS_DIR = os.getenv("JOBS_DIR", os.path.join(DATA, "jobs"))
job_lock = threading.Lock()

HELP = ("我可以帮你抓取文学城论坛和博客:\n"
        "• 抓一下三心三意最近3天的发言\n"
        "• 下载三心三意最近30页,只要长文\n"
        "• 订阅 三心三意(有新发言自动推送),可以一次订阅多位:订阅 yifan99 和 我是一只井底蛙\n"
        "• 下载 BrightLine 博客最近30天\n"
        "• 下载 BrightLine 博客 2026年6月\n"
        "• 取消订阅 三心三意 / 订阅列表")

# ---------- Telegram ----------
def say(text):
    for part in b.split_msg(text):
        requests.post(API + "/sendMessage", timeout=30, json={
            "chat_id": OWNER, "text": part, "disable_web_page_preview": True})
        time.sleep(0.5)

def send_doc(path, caption=""):
    with open(path, "rb") as f:
        requests.post(API + "/sendDocument", timeout=120,
                      data={"chat_id": OWNER, "caption": caption}, files={"document": f})

def send_image(path, caption=""):
    with open(path, "rb") as f:
        r = requests.post(API + "/sendPhoto", timeout=90, data={"chat_id": OWNER, "caption": caption[:1000]}, files={"photo": f})
    if not r.ok:  # 图片尺寸/大小不合规时,改用文件形式发送
        send_doc(path, caption)

# ---------- 状态 ----------
def load_watch():
    return json.load(open(WATCH_F, encoding="utf-8")) if os.path.exists(WATCH_F) else []

def save_watch(lst):
    json.dump(lst, open(WATCH_F, "w", encoding="utf-8"), ensure_ascii=False)

def seen_path(author):
    return os.path.join(DATA, f"seen_{author}.json")

def load_seen(author):
    p = seen_path(author)
    return set(json.load(open(p))) if os.path.exists(p) else set()

def save_seen(author, seen):
    json.dump(sorted(seen), open(seen_path(author), "w"))

# ---------- 意图理解 ----------
VERBS = ["取消订阅", "订阅列表", "订阅", "取消", "停止", "不再", "退订", "监控", "关注", "盯着", "盯",
         "抓一下", "抓取", "下载", "整理一下", "整理", "总结一下", "总结下", "总结", "获取", "拉取",
         "帮我", "麻烦", "请", "看看", "看下", "发我", "发给我"]
NOT_NAMES = {"帮助", "你好", "怎么用", "help", "start", "订阅列表"}

def extract_authors(text, known):
    """从一句话里找出博主名:先匹配已知名单,再取动作词之外的名字,支持多个(用 和/、/逗号/空格 分隔)"""
    t = text.strip()
    found = [k for k in known if k.casefold() in t.casefold()]
    body = t
    for v in sorted(VERBS, key=len, reverse=True):
        body = body.replace(v, " ")
    body = re.sub(r"(?:最近|近)?\s*\d+\s*[天页]", " ", body)
    body = re.sub(r"最近|今天|今日|昨天|一周|本周|这周|一个月|本月|只要长文|长文|长帖|的发言|的帖子|的帖|的文章|的观点|发言", " ", body)
    for tok in re.split(r"[\s、,，。;；和及与跟&+]+", body):
        tok = tok.strip()
        if len(tok) < 2 or tok.isdigit() or tok.casefold() in NOT_NAMES:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fff]{2,20}", tok):
            continue
        if any(tok.casefold() == f.casefold() for f in found):
            continue
        if any(tok.casefold() in f.casefold() for f in found):
            continue
        found.append(tok)
    # 已知名单用其规范写法
    canon = {k.casefold(): k for k in known}
    out = []
    for f in found:
        f = canon.get(f.casefold(), f)
        if f not in out:
            out.append(f)
    return out

def rule_intent(text, known):
    t = text.strip()
    it = {"action": "chat", "authors": [], "days": None, "pages": None, "min_chars": 0}
    if re.search(r"订阅列表|订阅了|监控列表", t): it["action"] = "watch_list"
    elif re.search(r"取消|停止|不再|退订", t): it["action"] = "watch_remove"
    elif re.search(r"订阅|监控|关注|盯", t): it["action"] = "watch_add"
    elif re.search(r"抓|下载|整理|获取|拉取|发我|发给我|最近|总结", t): it["action"] = "fetch"
    if it["action"] in ("fetch", "watch_add", "watch_remove"):
        it["authors"] = extract_authors(t, known)
    m = re.search(r"(\d+)\s*天", t)
    if m: it["days"] = int(m.group(1))
    elif "今天" in t or "今日" in t: it["days"] = 1
    elif "昨天" in t: it["days"] = 2
    elif re.search(r"一周|本周|这周|7天", t): it["days"] = 7
    elif re.search(r"一个月|本月|30天", t): it["days"] = 30
    m = re.search(r"(\d+)\s*页", t)
    if m: it["pages"] = int(m.group(1))
    if re.search(r"长文|长帖|只要长|有正文", t): it["min_chars"] = 150
    return it

def parse_intent(text, known):
    key = os.getenv("ANTHROPIC_API_KEY")
    if key:
        try:
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=40,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-sonnet-5-5", "max_tokens": 250,
                      "system": ("把用户消息解析成 JSON,只输出 JSON。字段: action(fetch|watch_add|watch_remove|watch_list|help|chat), "
                                 "authors(博主名数组,可以有多个,没有则空数组;名字必须原样保留,大小写不改), days(整数或null), pages(整数或null), "
                                 "min_chars(整数,只要长文时150,否则0)。"
                                 f"已知博主: {known}。用户想下载/整理/总结某些博主发言=fetch;订阅/监控=watch_add;取消订阅=watch_remove;查看订阅=watch_list。"),
                      "messages": [{"role": "user", "content": text}]})
            r.raise_for_status()
            raw = "".join(x.get("text", "") for x in r.json()["content"])
            it = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            it.setdefault("min_chars", 0)
            if not it.get("authors") and it.get("author"):
                it["authors"] = [it["author"]]
            return it
        except Exception as e:
            print("意图解析失败,改用规则:", e)
    return rule_intent(text, known)

# ---------- 任务 ----------
def collect_ids(author, max_pages, since, state):
    ids = {}
    day0 = since.replace(hour=0, minute=0, second=0, microsecond=0) if since else None
    for pg in range(1, max_pages + 1):
        r = b.fetch(f"{w.BASE}?page={pg}", state)
        if not r:
            continue
        for pid, href, _, _ in w.parse_list(r.text, author):
            ids[pid] = href
        if day0:
            ds = w.list_dates(r.text)
            if ds and max(ds) < day0:
                break
    return ids

def fetch_posts(pids, ids, state, since=None, progress=False):
    posts = []
    for i, pid in enumerate(pids, 1):
        r = b.fetch(ids[pid], state)
        p = w.parse_post(r.text, ids[pid]) if r else None
        if p:
            try:
                ok = not since or datetime.strptime(p["date"][:19], "%Y-%m-%d %H:%M:%S") >= since
            except ValueError:
                ok = True
            if ok:
                posts.append(p)
        if progress and i % 30 == 0:
            say(f"进度 {i}/{len(pids)}")
    posts.sort(key=lambda p: p["date"])
    return posts

def digest_text(posts, author, big_limit=6000):
    raw = b.build_raw_digest(posts)
    summary = b.ai_summary(raw, author)
    if summary:
        return "🧠 要点\n" + summary
    return raw if len(raw) < big_limit else f"共 {len(posts)} 条,内容较多,请看附件。"

def fetch_images(posts, outdir):
    imgdir = os.path.join(outdir, "images")
    total = 0
    for p in posts:
        p["local_images"] = []
        for u in p.get("images", [])[:MAX_IMAGES_PER_POST]:
            if total >= MAX_IMAGES_JOB:
                return total
            name = w.download_image(u, imgdir)
            if name:
                p["local_images"].append(name); total += 1
    return total

def make_zip(outdir, name):
    zp = os.path.join(outdir, name)
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in ("posts.md", "index.csv"):
            z.write(os.path.join(outdir, f), f)
        imgdir = os.path.join(outdir, "images")
        if os.path.isdir(imgdir):
            for fn in sorted(os.listdir(imgdir)):
                z.write(os.path.join(imgdir, fn), "images/" + fn)
    return zp

def parse_blog_request(text):
    """博客下载指令优先于论坛自然语言解析，避免把“博客”当作者名。"""
    if "博客" not in text:
        return None
    profile = None
    for p in blog.PROFILES.values():
        names = [p["author"]] + p.get("aliases", [])
        if any(n.casefold() in text.casefold() for n in names):
            profile = dict(p); break
    if not profile:
        return None
    m = re.search(r"(20\\d{2})年(1[0-2]|0?[1-9])月", text)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
        else:
            end = datetime(year, month + 1, 1) - timedelta(seconds=1)
        return {"profile": profile, "start": start, "end": end, "label": f"{year}年{month}月"}
    m = re.search(r"(\\d+)\\s*天", text)
    days = int(m.group(1)) if m else (90 if "90天" in text else 30)
    end = datetime.now()
    start = end - timedelta(days=days)
    return {"profile": profile, "start": start, "end": end, "label": f"最近{days}天"}


def run_blog_fetch(req):
    p, start, end, label = req["profile"], req["start"], req["end"], req["label"]
    say(f"收到，开始下载「{p['author']}」博客 {label}，会按月低频扫描并整理正文与图片。")
    outdir = os.path.join(JOBS_DIR, f"blog_{p['author']}_{datetime.now():%Y%m%d_%H%M%S}")
    result = blog.collect(p, start, end, outdir)
    posts = result["posts"]
    if not posts:
        say("没有抓到符合时间范围的博客文章。可能是该月份无文章，或文学城暂时限制访问。")
        return
    zp = os.path.join(outdir, f"{p['author']}_blog_{datetime.now():%Y%m%d}.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in ("posts.md", "index.csv", "posts.json"):
            fp = os.path.join(outdir, fn)
            if os.path.exists(fp):
                z.write(fp, fn)
        imgdir = os.path.join(outdir, "images")
        if os.path.isdir(imgdir):
            for fn in sorted(os.listdir(imgdir)):
                z.write(os.path.join(imgdir, fn), "images/" + fn)
    say(f"✅ BrightLine 博客下载完成：{len(posts)} 篇，归档月份 {result['archive_months']}，发现文章链接 {result['article_links_found']}，下载图片 {result['images_downloaded']} 张。")
    if os.path.getsize(zp) < 45 * 1024 * 1024:
        send_doc(zp, "BrightLine 博客整理包：posts.md + index.csv + posts.json + 图片")
    else:
        send_doc(os.path.join(outdir, "posts.md"), "BrightLine 博客正文合集")
        send_doc(os.path.join(outdir, "index.csv"), "BrightLine 博客索引")


def run_fetch(author, days=None, pages=None, min_chars=0):
    if not days and not pages:
        days = 3
    since = None
    if days:
        # 以论坛自己的时钟为基准(取列表页最新帖子的时间),不用服务器时间,避免时区差导致漏帖
        r0 = b.fetch(f"{w.BASE}?page=1", {})
        ref = (w.list_latest(r0.text) if r0 else None) or datetime.now()
        since = ref - timedelta(days=days)
    say(f"收到,开始抓取「{author}」" + (f"最近 {days} 天" if days else f"前 {pages} 页") + "的发言,请稍等…")
    state = {}
    ids = collect_ids(author, pages or 60, since, state)
    pids = sorted(ids, key=int, reverse=True)[:MAX_JOB_POSTS]
    if not pids:
        say("没有找到这位博主的发言。"); return
    posts = fetch_posts(pids, ids, state, since, progress=True)
    if not posts:
        say("这个时间范围内没有发言。"); return
    outdir = os.path.join(JOBS_DIR, f"{author}_{datetime.now():%Y%m%d_%H%M%S}")
    os.makedirs(os.path.join(outdir, "posts"), exist_ok=True)
    n_have = sum(len(p.get("images", [])) for p in posts)
    n_img = fetch_images(posts, outdir) if n_have else 0
    for p in posts:
        json.dump(p, open(os.path.join(outdir, "posts", f"{p['id']}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    w.build(outdir, min_chars)
    img_note = ""
    if n_have:
        img_note = f",图片 {n_img}/{n_have} 张已下载" + ("(其余下载失败或被过滤,posts.md 里保留了链接)" if n_img < n_have else "")
    say(f"✅ 抓到 {len(posts)} 条({posts[0]['date'][:10]} ~ {posts[-1]['date'][:10]}){img_note}\n\n" + digest_text(posts, author))
    zp = make_zip(outdir, f"{author}_{datetime.now():%Y%m%d}.zip") if n_img else None
    if zp and os.path.getsize(zp) < 45 * 1024 * 1024:
        send_doc(zp, f"整理包:posts.md + index.csv + {n_img} 张图片")
    else:
        if zp:
            say("图片打包后超过 Telegram 50MB 上限,只发送文本。")
        send_doc(os.path.join(outdir, "posts.md"), "完整发言合集")
        send_doc(os.path.join(outdir, "index.csv"), "索引表")

def list_pages(n, state):
    htmls = []
    for pg in range(1, n + 1):
        r = b.fetch(f"{w.BASE}?page={pg}", state)
        if r:
            htmls.append(r.text)
    return htmls

def ids_for(author, htmls):
    ids = {}
    for h in htmls:
        for pid, href, _, _ in w.parse_list(h, author):
            ids[pid] = href
    return ids

def baseline(authors):
    """订阅时先把现有帖子标记为已读,避免一次性刷屏"""
    htmls = list_pages(3, {})
    for au in authors:
        seen = load_seen(au); seen.update(ids_for(au, htmls)); save_seen(au, seen)

def check_watch(authors):
    state = {}
    htmls = list_pages(3, state)  # 所有博主共用这几页,不重复请求
    for au in authors:
        ids = ids_for(au, htmls)
        seen = load_seen(au)
        new = sorted((i for i in ids if i not in seen), key=int, reverse=True)[:40]
        if not new:
            continue
        posts = fetch_posts(new, ids, state)
        if not posts:
            continue
        say(f"📌 {au} 新发言 {len(posts)} 条 ({datetime.now():%m-%d %H:%M})\n\n" + digest_text(posts, au))
        seen.update(p["id"] for p in posts); save_seen(au, seen)
        sent = 0  # 带图的帖子:把图片直接发到聊天里
        for p in posts:
            for u in p.get("images", [])[:4]:
                if sent >= MAX_PUSH_IMAGES:
                    break
                name = w.download_image(u, os.path.join(JOBS_DIR, "push"))
                if name:
                    send_image(os.path.join(JOBS_DIR, "push", name), f"{au} · {p['title'][:60]}\n{p['url']}")
                    sent += 1

def guarded(fn, *args):
    if not job_lock.acquire(blocking=False):
        say("上一个任务还没跑完,请稍等一下再发。"); return
    try:
        fn(*args)
    except SystemExit as e:
        say(f"⚠️ {e}")
    except Exception as e:
        say(f"⚠️ 出错了: {e}")
    finally:
        job_lock.release()

def dispatch(fn, *args, sync=False):
    if sync:
        guarded(fn, *args)
    else:
        threading.Thread(target=guarded, args=(fn,) + args, daemon=True).start()

def run_fetch_many(authors, days, pages, min_chars):
    for au in authors:
        run_fetch(au, days, pages, min_chars)

MAX_WATCH = 10

def handle(text, sync=False):
    blog_req = parse_blog_request(text)
    if blog_req:
        dispatch(run_blog_fetch, blog_req, sync=sync)
        return
    watch = load_watch()
    it = parse_intent(text, [DEFAULT_AUTHOR] + watch)
    act = it.get("action")
    authors = it.get("authors") or []
    if act == "fetch":
        authors = authors or [DEFAULT_AUTHOR]
        dispatch(run_fetch_many, authors, it.get("days"), it.get("pages"), it.get("min_chars") or 0, sync=sync)
    elif act == "watch_add":
        if not authors:
            say("请告诉我要订阅谁,例如:订阅 三心三意"); return
        added = []
        for au in authors:
            if au.casefold() not in [x.casefold() for x in watch] and len(watch) < MAX_WATCH:
                watch.append(au); added.append(au)
        save_watch(watch)
        if len(added) < len(authors):
            say(f"部分博主已在订阅里或超过上限({MAX_WATCH} 个)。")
        say(f"已订阅:{'、'.join(added) or '无新增'}\n当前共订阅 {len(watch)} 位,大约每 {WATCH_EVERY // 60} 分钟检查一次,有新发言会推送给你。")
        if added:
            dispatch(baseline, added, sync=sync)
    elif act == "watch_remove":
        if not authors:
            say("请告诉我要取消谁,例如:取消订阅 yifan99"); return
        keep = [x for x in watch if x.casefold() not in [a_.casefold() for a_ in authors]]
        removed = [x for x in watch if x not in keep]
        save_watch(keep)
        say(f"已取消订阅:{'、'.join(removed)}" if removed else "订阅里没有这位博主。")
    elif act == "watch_list":
        say("当前订阅: " + ("、".join(watch) if watch else "无"))
    else:
        say(HELP)

def watch_loop():
    time.sleep(60)
    while True:
        if load_watch():
            guarded(check_watch, load_watch())
        time.sleep(WATCH_EVERY)

def main():
    if not TOKEN or not OWNER:
        raise SystemExit("请设置 TG_BOT_TOKEN 和 TG_CHAT_ID")
    threading.Thread(target=watch_loop, daemon=True).start()
    print("机器人已启动,等待消息…")
    offset = None
    while True:
        try:
            r = requests.get(API + "/getUpdates", params={"timeout": 50, "offset": offset}, timeout=65)
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                m = u.get("message") or {}
                if str(m.get("chat", {}).get("id")) != OWNER:
                    continue  # 忽略陌生人
                text = (m.get("text") or "").strip()
                if text:
                    handle(text)
        except Exception as e:
            print("轮询异常:", e); time.sleep(5)

if __name__ == "__main__":
    main()
