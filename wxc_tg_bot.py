#!/usr/bin/env python3
"""
文学城博主新发言 -> 整理 -> Telegram 推送
需要与 wxc_scraper.py 放在同一目录。

环境变量:
  TG_BOT_TOKEN        Telegram 机器人 token (找 @BotFather 创建)
  TG_CHAT_ID          你的 chat id
  ANTHROPIC_API_KEY   可选。设置后会先用 Claude 生成一段中文要点总结

用法:
  python3 wxc_tg_bot.py --test                       # 发一条测试消息
  python3 wxc_tg_bot.py --author 三心三意 --dry-run   # 只打印不发送
  python3 wxc_tg_bot.py --author 三心三意             # 抓新帖并推送
"""
import argparse, json, os, random, re, sys, time
from datetime import datetime
import requests
import wxc_scraper as w

STATE = "seen_{author}.json"
EXTRA_STOP = set("BTW HH HL LH LL MM VM FY AT SP LOL TA ATR EMA WOW YES NOT ALL OUT NOW BUT ONE".split())
LONG_CHARS = 150  # 正文超过这个字数算"长文"

def fetch(url, state):
    """带随机间隔;连续失败 5 次则中止,避免被封后继续硬抓。"""
    time.sleep(random.uniform(2.0, 4.5))
    r = w.get(url, retries=2, delay=0)
    if r is None:
        state["fails"] = state.get("fails", 0) + 1
        if state["fails"] >= 5:
            sys.exit("连续请求失败 5 次,疑似被限制,已停止。请稍后再试。")
        return None
    state["fails"] = 0
    return r

def tickers(text):
    return [t for t in w.tickers(text) if t not in EXTRA_STOP]

def build_raw_digest(posts):
    longs = [p for p in posts if len(p["text"]) >= LONG_CHARS]
    shorts = [p for p in posts if len(p["text"]) < LONG_CHARS]
    lines = []
    if longs:
        lines.append("【长文】")
        for p in longs:
            body = p["text"] if len(p["text"]) <= 700 else p["text"][:700] + "…"
            lines.append(f"▪ {p['date'][5:16]} {p['title']}\n{body}\n{p['url']}")
    by_tk, other = {}, []
    for p in shorts:
        content = p["title"] + (" " + p["text"] if p["text"] else "")
        tks = tickers(content)
        if tks:
            for t in tks:
                by_tk.setdefault(t, []).append(p)
        else:
            other.append(p)
    if by_tk:
        lines.append("\n【按股票】")
        for t, ps in sorted(by_tk.items(), key=lambda x: -len(x[1])):
            lines.append(f"# {t}")
            for p in ps:
                lines.append(f"  · {p['date'][5:16]} {p['title']}")
    if other:
        lines.append("\n【其他短评】")
        for p in other:
            lines.append(f"  · {p['date'][5:16]} {p['title']}")
    return "\n".join(lines)

def ai_summary(raw, author):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return ""
    prompt = (f"以下是论坛博主「{author}」最近的发言(多为回复别人的短句,缺少上下文)。"
              "请用中文整理成要点:按股票/主题分组,写出他的观点、点位和操作;"
              "只依据原文,不要编造;上下文不足的句子标注“语境不明”;不超过 400 字。\n\n" + raw[:12000])
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=90,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-sonnet-5-5", "max_tokens": 1000,
                  "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])
    except Exception as e:
        print("AI 总结失败,改发原始整理:", e)
        return ""

def split_msg(text, limit=3800):
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur); cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts

def send_tg(text):
    tok, chat = os.getenv("TG_BOT_TOKEN"), os.getenv("TG_CHAT_ID")
    if not tok or not chat:
        sys.exit("请先设置环境变量 TG_BOT_TOKEN 和 TG_CHAT_ID")
    for part in split_msg(text):
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=30,
                          json={"chat_id": chat, "text": part, "disable_web_page_preview": True})
        if not r.ok:
            sys.exit(f"Telegram 发送失败: {r.status_code} {r.text}")
        time.sleep(1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--author", default="三心三意")
    ap.add_argument("--pages", type=int, default=3, help="每次检查最新几页列表")
    ap.add_argument("--max-new", type=int, default=40, help="单次最多处理的新帖数(首次运行防刷屏)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()

    if a.test:
        send_tg("✅ 文学城监控机器人连通正常"); print("已发送测试消息"); return

    sf = STATE.format(author=a.author)
    seen = set(json.load(open(sf))) if os.path.exists(sf) else set()
    first_run = not seen
    state = {}

    ids = {}
    for pg in range(1, a.pages + 1):
        r = fetch(f"{w.BASE}?page={pg}", state)
        if r:
            for pid, href, _, _ in w.parse_list(r.text, a.author):
                ids[pid] = href
    new = sorted((i for i in ids if i not in seen), key=int, reverse=True)[: a.max_new]
    print(f"发现 {len(new)} 条新发言" + ("(首次运行)" if first_run else ""))
    if not new:
        return

    posts = []
    for pid in sorted(new, key=int):
        r = fetch(ids[pid], state)
        p = w.parse_post(r.text, ids[pid]) if r else None
        if p:
            posts.append(p)
    posts.sort(key=lambda p: p["date"])
    if not posts:
        return

    raw = build_raw_digest(posts)
    head = f"📌 {a.author} 新发言 {len(posts)} 条 ({datetime.now():%m-%d %H:%M})"
    summary = ai_summary(raw, a.author)
    msg = head + "\n\n" + (f"🧠 要点\n{summary}\n\n———\n" if summary else "") + raw

    if a.dry_run:
        print(msg); return
    send_tg(msg)
    seen.update(new)
    json.dump(sorted(seen), open(sf, "w"))
    print("已推送并记录")

if __name__ == "__main__":
    main()
