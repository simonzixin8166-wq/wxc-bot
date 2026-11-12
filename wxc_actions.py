#!/usr/bin/env python3
"""
GitHub Actions 版。BOT_RUN_MINUTES=0(默认):只做一轮后退出。BOT_RUN_MINUTES>0(Owner 2026-11-11):在这段时间里
用 Telegram 长轮询连续值守,收到消息几十秒内处理,处理后立刻把 state/ 提交回仓库(BOT_COMMIT_STATE=1)。
  1) 读取 Telegram 里你发来的新指令/转发/导出文件并执行
  2) 订阅博主检查: 文学城暂停访问期间(wxc_access_policy, 至 2027-05-11)完全跳过,不发任何请求
  3) MyAlpha 服务器状态和 YouTube 日报: 每 30 分钟最多一次
GitHub 公开仓库的标准 runner 不计费;单个 job 最长 6 小时。
"""
import json, os, subprocess, time
import requests
import wxc_access_policy as access_policy
import wxc_tg_agent as a
import yt_daily_report
import owner_forward

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
                     # Public status is presence-only (0/1) since quant-dashboard#154: show 有/无, not counts.
                     f"L3 {'有' if counts.get('l3') else '无'} · L2 {'有' if counts.get('l2') else '无'} · Thesis复核 {'有' if counts.get('thesis_review') else '无'}\n"
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

RUN_MINUTES = float(os.getenv("BOT_RUN_MINUTES", "0") or 0)
POLL_SECONDS = 50            # Telegram long-poll window (free; returns at once when a message arrives)
PERIODIC_SECONDS = 30 * 60   # server status / YouTube report / (paused) watch at most this often
MAX_BACKOFF = 300            # transient Telegram/network errors: back off up to 5 min, never end the run


class TransientTelegramError(Exception):
    """A 5xx / 429 / connection problem talking to Telegram: retried in long-run mode (11/11-12: 502, reset)."""


def save_state(reason: str) -> None:
    """Commit state/ right after something was handled, so research-close sees forwards the same day.
    Same rules as the workflow's final Save state step (never stages the canonical research feed)."""
    if os.getenv("BOT_COMMIT_STATE") != "1":
        return
    sh = lambda *c: subprocess.run(c, capture_output=True, text=True)  # noqa: E731
    sh("git", "add", "state", ":!state/research_feed.json", ":!state/research_feed_manifest.json")
    if sh("git", "diff", "--cached", "--quiet").returncode == 0:
        return
    sh("git", "commit", "-m", f"update state ({reason})")
    for i in range(3):
        if sh("git", "pull", "--rebase", "origin", "main").returncode == 0 and sh("git", "push", "origin", "HEAD:main").returncode == 0:
            return
        sh("git", "rebase", "--abort")
        time.sleep(5 * (i + 1))
    print("::warning title=tg-bot::state push failed mid-run; the final Save state step retries")


def _poll(meta, timeout):
    params = {"timeout": timeout, "limit": 50}
    if meta.get("offset"):
        params["offset"] = meta["offset"]  # 只确认已经处理并提交过的消息
    a.record_request("telegram", "get_updates")
    try:
        res = requests.get(a.API + "/getUpdates", params=params, timeout=timeout + 20).json()
    except (requests.RequestException, ValueError) as exc:
        raise TransientTelegramError(f"{type(exc).__name__}: {exc}") from exc
    if not res.get("ok"):
        code = int(res.get("error_code") or 0)
        if code >= 500 or code == 429:
            raise TransientTelegramError(f"getUpdates {code}: {res.get('description')}")
        raise SystemExit(f"getUpdates 失败: {res}")  # 401/404 etc.: a configuration problem, stop
    handled = 0
    for u in res.get("result", []):
        meta["offset"] = u["update_id"] + 1
        m = u.get("message") or {}
        if str(m.get("chat", {}).get("id")) != a.OWNER:
            continue  # 忽略陌生人
        handled += 1
        try:
            if owner_forward.is_forward(m):
                # Owner's own forward/export; full text only to the private textpack repo, never re-fetched
                owner_forward.handle(m, a.say, tg_api=a.API, tg_file_base=f"https://api.telegram.org/file/bot{a.TOKEN}")
                continue
            text = (m.get("text") or "").strip()
            if text:
                print("收到指令:", text)
                a.handle(text, sync=True)
        except Exception as exc:  # noqa: BLE001 - one bad message must not stop the bot or be retried forever
            print(f"::warning title=tg-bot::message {u.get('update_id')} failed: {type(exc).__name__}: {exc}")
            try:
                a.say(f"这条消息处理失败（{type(exc).__name__}），已跳过，请稍后重发。")
            except Exception:  # noqa: BLE001
                pass
    return handled


def _periodic(meta):
    if not access_policy.paused():
        authors = a.load_watch()
        if authors:
            a.guarded(a.check_watch, authors)
    meta = check_myalpha_server_action(meta)
    return yt_daily_report.maybe_send(meta, a.say)


def _write_meta(meta):
    json.dump(meta, open(META, "w"))


def main():
    if not a.TOKEN or not a.OWNER:
        raise SystemExit("请设置 Secrets: TG_BOT_TOKEN 和 TG_CHAT_ID")
    meta = json.load(open(META)) if os.path.exists(META) else {}
    deadline = time.time() + RUN_MINUTES * 60
    last_periodic = float("-inf")
    failures = 0
    while True:
        long_run = RUN_MINUTES > 0
        try:
            handled = _poll(meta, POLL_SECONDS if long_run else 0)
            failures = 0
        except TransientTelegramError as exc:
            if not long_run:
                raise SystemExit(f"getUpdates 失败: {exc}")
            failures += 1
            wait = min(MAX_BACKOFF, 5 * 2 ** min(failures, 6))
            print(f"::warning title=tg-bot::Telegram transient error ({exc}); retry in {wait}s")
            _write_meta(meta)
            if time.time() + wait + POLL_SECONDS + 30 >= deadline:
                break
            time.sleep(wait)
            continue
        if time.time() - last_periodic >= PERIODIC_SECONDS or not long_run:
            try:
                meta = _periodic(meta)
            except Exception as exc:  # noqa: BLE001 - status bridge / report must not end the bot
                print(f"::warning title=tg-bot::periodic task failed: {type(exc).__name__}: {exc}")
            last_periodic = time.time()
        _write_meta(meta)
        if handled:
            save_state("bot handled messages")
        if not long_run or time.time() + POLL_SECONDS + 30 >= deadline:
            break


if __name__ == "__main__":
    main()
