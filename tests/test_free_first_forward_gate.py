from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
yt=(ROOT/"youtube_research.py").read_text(encoding="utf-8")
agent=(ROOT/"wxc_tg_agent.py").read_text(encoding="utf-8")
wf=(ROOT/".github"/"workflows"/"tg-bot.yml").read_text(encoding="utf-8")

assert "ready=_content_ready(ch,aq) and bool(published)" in yt
assert '"pending_reason":"missing_published_at"' in yt
assert "missing reliable published_at remain pending" in yt
assert 'USE_ANTHROPIC_INTENT' in agent
assert 'record_request("anthropic","intent_parse",1,paid=True)' in agent
assert 'REQUEST_LEDGER_F' in agent
assert 'cron: "*/30 * * * *"' in wf
assert 'USE_ANTHROPIC_INTENT: "0"' in wf
print("PASS free-first Telegram + YouTube forward published_at gate")

actions=(ROOT/"wxc_actions.py").read_text(encoding="utf-8")
assert "SERVER_ACTION_URL" in actions
assert "check_myalpha_server_action" in actions
assert 'status=="action_required"' in actions
assert 'fp!=meta.get("myalpha_action_fingerprint")' in actions
assert "详细私有仓位未写入公开状态" in actions
print("PASS sanitized MyAlpha -> Telegram action bridge")
