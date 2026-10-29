"""YT-01 daily Telegram digest: which videos Gemini read on the previous Pacific-time quota day, which failed and why, with links.

Sent at most once per quota day from the tg-bot run (meta["yt_report_day"] dedupes). A send failure leaves the day
unmarked so the next run retries; it never blocks the bot. Reads state files only; no positions, no keys."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

REASONS = {
    "admitted": "已收录", "identity_mismatch": "身份不符（模型可能没看到原片）", "safety_contract": "安全规则拒收",
    "thin_content": "内容过少", "no_json": "输出无法解析", "exception": "超时或网络异常",
    "http_403": "403 无权限", "http_429": "429 免费额度用完", "http_503_all_models": "503 服务繁忙（已退还额度）",
}


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _reason(row):
    o = str(row.get("outcome") or "")
    base = REASONS.get(o) or (f"HTTP {o[5:]}" if o.startswith("http_") else o)
    if o == "exception" and row.get("detail"):
        base += f"（{str(row['detail'])[:30]}）"
    return base


def build(day, budget, status, unsupported=()):
    d = (budget.get("days") or {}).get(day)
    pending = status.get("pending_total")
    lines = [f"📺 YouTube 采集日报 {day}（美西时间日，Gemini 免费额度按此重置）"]
    if not d:
        lines.append("当天没有调用 Gemini。")
    else:
        rec = d.get("reconciliation") or {}
        lines.append(f"Gemini 调用 {d.get('calls', 0)} 次 · 收录 {d.get('admitted', 0)} · 拒收 {d.get('rejected', 0)} · "
                     f"错误 {d.get('errors', 0)}（对账 {rec.get('status', '未知')}）")
        rows = [r for r in (d.get("recent") or []) if isinstance(r, dict) and r.get("video_id")]
        ok = [r for r in rows if r.get("outcome") == "admitted"]
        bad = [r for r in rows if r.get("outcome") != "admitted"]
        if ok:
            lines.append("✅ 已读到：")
            lines += [f"- {r.get('author') or '?'} · {(r.get('title') or '')[:40]} https://youtu.be/{r['video_id']}" for r in ok]
        if bad:
            lines.append("❌ 未读到（可用 NotebookLM 总结后发送：/yt 视频链接 摘要）：")
            seen = set()
            for r in bad:
                if r["video_id"] in seen:
                    continue
                seen.add(r["video_id"])
                lines.append(f"- {r.get('author') or '?'} · {_reason(r)} https://youtu.be/{r['video_id']}")
        skipped = d.get("skip_authors_403") or []
        if skipped:
            lines.append("⏭ 当天已跳过（403）：" + "、".join(skipped))
    if unsupported:
        lines.append("🚫 Gemini 连续多天无法读取（暂停调用，改为手动）：" + "、".join(unsupported))
    if pending is not None:
        lines.append(f"待处理积压：{pending} 条（新视频优先使用额度）")
    return "\n".join(lines)


def maybe_send(meta, say, now=None, data_dir=None):
    """Send yesterday's digest once. Returns meta (marked only after a successful send)."""
    now = now or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        local = now.astimezone(ZoneInfo("America/Los_Angeles"))  # budget days follow Gemini's Pacific quota reset
    except Exception:
        return meta
    if local.hour < 1:  # leave time for the last intake run of the quota day to commit
        return meta
    day = (local - timedelta(days=1)).strftime("%Y-%m-%d")
    if meta.get("yt_report_day") == day:
        return meta
    base = Path(data_dir or os.getenv("DATA_DIR", "state"))
    try:
        budget = _load(base / "gemini_video_budget.json", {})
        status = _load(base / "youtube_source_status.json", {})
        try:
            import gemini_video
            unsupported = gemini_video.unsupported_authors(budget)
        except Exception:
            unsupported = []
        say(build(day, budget, status, unsupported))
        meta["yt_report_day"] = day
    except Exception as exc:  # never blocks the bot; unmarked day is retried next run
        print("YT daily report skipped:", type(exc).__name__)
    return meta
