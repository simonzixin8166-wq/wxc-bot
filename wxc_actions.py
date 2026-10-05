#!/usr/bin/env python3
"""
GitHub Actions 版:每次运行只做一轮,然后退出(由 cron 每 5 分钟触发)。
  1) 读取 Telegram 里你发来的新指令并执行
  2) 到点则检查已订阅博主的新发言并推送
  3) 状态(已处理到哪条消息、订阅列表、已推送记录)存在 state/ 目录,由工作流提交回仓库
"""
import json, os, time
import requests
import wxc_tg_agent as a

META = os.path.join(a.DATA, "meta.json")
SERVER_ACTION_URL = os.getenv("MYALPHA_SERVER_ACTION_URL", "https://myalphaview.com/research/server_action_status.json")


def check_myalpha_server_action(meta):
    """Bridge sanitized MyAlpha server status to the existing private Telegram channel."""
    try:
        a.record_request("myalphaview","server_action_status")
        r=requests.get(SERVER_ACTION_URL,params={"t":int(time.time())},timeout=20)
        r.raise_for_status()
        s=r.json()
        fp=str(s.get("alert_fingerprint") or "")
        status=str(s.get("status") or "")
        trust=((s.get("data_trust") or {}).get("overall") or "")
        should=status=="action_required" or (status=="cannot_judge" and trust=="attention")
        if should and fp and fp!=meta.get("myalpha_action_fingerprint"):
            counts=s.get("action_counts") or {}
            if status=="action_required":
                msg=("⚠️ MyAlpha 有需要处理的事项\n"
                     f"L3 {counts.get('l3',0)} · L2 {counts.get('l2',0)} · Thesis复核 {counts.get('thesis_review',0)}\n"
                     "详细私有仓位未写入公开状态，请打开 MyAlpha 查看。")
            else:
                msg=("⚠️ MyAlpha 当前无法可靠判断\n"
                     "关键数据状态异常，系统已停止给出“无需操作”结论。请打开系统状态查看。")
            a.say(msg)
            meta["myalpha_action_fingerprint"]=fp
        return meta
    except Exception as exc:
        print("MyAlpha alert bridge skipped:",exc)
        return meta

def main():
    if not a.TOKEN or not a.OWNER:
        raise SystemExit("请设置 Secrets: TG_BOT_TOKEN 和 TG_CHAT_ID")
    meta = json.load(open(META)) if os.path.exists(META) else {}
    params = {"timeout": 0, "limit": 50}
    if meta.get("offset"):
        params["offset"] = meta["offset"]  # 只确认已经处理并提交过的消息
    a.record_request("telegram","get_updates")
    res = requests.get(a.API + "/getUpdates", params=params, timeout=30).json()
    if not res.get("ok"):
        raise SystemExit(f"getUpdates 失败: {res}")

    offset = meta.get("offset")
    for u in res.get("result", []):
        offset = u["update_id"] + 1
        m = u.get("message") or {}
        if str(m.get("chat", {}).get("id")) != a.OWNER:
            continue  # 忽略陌生人
        text = (m.get("text") or "").strip()
        if text:
            print("收到指令:", text)
            a.handle(text, sync=True)

    # 无状态的"到点"判断:每个 WATCH_MINUTES 周期的前 7 分钟内检查(cron 每 5 分钟一次,保证至少命中一次)
    gap = max(a.WATCH_EVERY // 60, 10)
    if int(time.time() // 60) % gap < 7:
        authors = a.load_watch()
        if authors:
            a.guarded(a.check_watch, authors)

    meta = check_myalpha_server_action(meta)

    if offset is not None:
        meta["offset"] = offset
    json.dump(meta, open(META, "w"))

if __name__ == "__main__":
    main()
