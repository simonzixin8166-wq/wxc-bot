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
import json, os, re, threading, time
from datetime import datetime, timedelta
import requests
import wxc_scraper as w
import wxc_tg_bot as b

TOKEN = os.getenv("TG_BOT_TOKEN", "")
OWNER = str(os.getenv("TG_CHAT_ID", ""))
DEFAULT_AUTHOR = os.getenv("DEFAULT_AUTHOR", "三心三意")
WATCH_EVERY = int(os.getenv("WATCH_MINUTES", "30")) * 60
DATA = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA, exist_ok=True)
API = f"https://api.telegram.org/bot{TOKEN}"
WATCH_F = os.path.join(DATA, "watch.json")
MAX_JOB_POSTS = 150
JOBS_DIR = os.getenv("JOBS_DIR", os.path.join(DATA, "jobs"))
job_lock = threading.Lock()

HELP = ("我可以帮你抓取文学城「财富智汇」博主的发言:\n"
        "• 抓一下三心三意最近3天的发言\n"
        "• 下载三心三意最近30页,只要长文\n"
        "• 订阅 三心三意(有新发言自动推送)\n"
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
def rule_intent(text, known):
    t = text.strip()
    author = next((k for k in known if k in t), None)
    if not author:
        m = re.search(r"[「“\"]?([A-Za-z0-9_\u4e00-\u9fff]{2,12})[」”\"]?的(?:发言|帖|文章|观点)", t)
        author = m.group(1) if m else None
        if author:  # 去掉前面的动词和时间词,只留博主名
            author = re.sub(r"^(?:请|帮我|帮忙|麻烦)?(?:抓一下|抓取|抓|下载|整理一下|整理|总结一下|总结下|总结|获取|拉取|看看|看下)", "", author)
            author = re.sub(r"(?:今天|昨天|今日|最近\d*[天页]?|\d+[天页])$", "", author) or None
    it = {"action": "chat", "author": author, "days": None, "pages": None, "min_chars": 0}
    if re.search(r"取消|停止|不再|退订", t): it["action"] = "watch_remove"
    elif re.search(r"订阅列表|订阅了|监控列表", t): it["action"] = "watch_list"
    elif re.search(r"订阅|监控|关注|盯", t): it["action"] = "watch_add"
    elif re.search(r"抓|下载|整理|获取|拉取|发我|发给我|最近|总结", t): it["action"] = "fetch"
    elif re.search(r"帮助|help|怎么用|/start|/help", t, re.I): it["action"] = "help"
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
                json={"model": "claude-sonnet-5-5", "max_tokens": 200,
                      "system": ("把用户消息解析成 JSON,只输出 JSON。字段: action(fetch|watch_add|watch_remove|watch_list|help|chat), "
                                 "author(博主名或null), days(整数或null), pages(整数或null), min_chars(整数,只要长文时150,否则0)。"
                                 f"已知博主: {known}。用户想下载/整理/总结某博主发言=fetch;订阅/监控=watch_add;取消订阅=watch_remove。"),
                      "messages": [{"role": "user", "content": text}]})
            r.raise_for_status()
            raw = "".join(x.get("text", "") for x in r.json()["content"])
            it = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            it.setdefault("min_chars", 0)
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

def run_fetch(author, days=None, pages=None, min_chars=0):
    if not days and not pages:
        days = 3
    since = datetime.now() - timedelta(days=days) if days else None
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
    for p in posts:
        json.dump(p, open(os.path.join(outdir, "posts", f"{p['id']}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    w.build(outdir, min_chars)
    say(f"✅ 抓到 {len(posts)} 条({posts[0]['date'][:10]} ~ {posts[-1]['date'][:10]})\n\n" + digest_text(posts, author))
    send_doc(os.path.join(outdir, "posts.md"), "完整发言合集")
    send_doc(os.path.join(outdir, "index.csv"), "索引表")

def baseline(author):
    """订阅时先把现有帖子标记为已读,避免一次性刷屏"""
    state = {}
    ids = collect_ids(author, 3, None, state)
    seen = load_seen(author); seen.update(ids); save_seen(author, seen)

def check_watch(author):
    state = {}
    ids = collect_ids(author, 3, None, state)
    seen = load_seen(author)
    new = sorted((i for i in ids if i not in seen), key=int, reverse=True)[:40]
    if not new:
        return
    posts = fetch_posts(new, ids, state)
    if not posts:
        return
    say(f"📌 {author} 新发言 {len(posts)} 条 ({datetime.now():%m-%d %H:%M})\n\n" + digest_text(posts, author))
    seen.update(p["id"] for p in posts); save_seen(author, seen)

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

def handle(text, sync=False):
    watch = load_watch()
    it = parse_intent(text, [DEFAULT_AUTHOR] + watch)
    act, author = it.get("action"), it.get("author") or DEFAULT_AUTHOR
    if act == "fetch":
        dispatch(run_fetch, author, it.get("days"), it.get("pages"), it.get("min_chars") or 0, sync=sync)
    elif act == "watch_add":
        if author not in watch:
            watch.append(author); save_watch(watch)
        say(f"已订阅「{author}」,大约每 {WATCH_EVERY // 60} 分钟检查一次,有新发言会推送给你。")
        dispatch(baseline, author, sync=sync)
    elif act == "watch_remove":
        if author in watch:
            watch.remove(author); save_watch(watch)
        say(f"已取消订阅「{author}」。")
    elif act == "watch_list":
        say("当前订阅: " + ("、".join(watch) if watch else "无"))
    else:
        say(HELP)

def watch_loop():
    time.sleep(60)
    while True:
        for au in load_watch():
            guarded(check_watch, au)
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
