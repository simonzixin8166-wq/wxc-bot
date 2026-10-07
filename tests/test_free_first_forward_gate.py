from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
yt=(ROOT/"youtube_research.py").read_text(encoding="utf-8")
agent=(ROOT/"wxc_tg_agent.py").read_text(encoding="utf-8")
wf=(ROOT/".github"/"workflows"/"tg-bot.yml").read_text(encoding="utf-8")

assert "content_ready=_content_ready(ch,aq)" in yt
assert "ready=content_ready and bool(published)" in yt
assert "learning_only=content_ready and not bool(published)" in yt
assert '"intake_class_hint"="backfill"' not in yt  # syntax guard; assignment is dict-style below
assert 'row["intake_class_hint"]="backfill"' in yt
assert 'row["capture_mode"]="youtube_timestamp_unknown_learning"' in yt
assert 'row["forward_evidence_eligible"]=False' in yt
assert "can never count as Forward/Promotion" in yt
assert 'USE_ANTHROPIC_INTENT' in agent
assert 'record_request("anthropic","intent_parse",1,paid=True)' in agent
assert 'REQUEST_LEDGER_F' in agent
assert 'cron: "*/30 * * * *"' in wf
assert 'USE_ANTHROPIC_INTENT: "0"' in wf
print("PASS free-first Telegram + YouTube forward/backfill timestamp gate")

actions=(ROOT/"wxc_actions.py").read_text(encoding="utf-8")
assert "SERVER_ACTION_URL" in actions
assert "check_myalpha_server_action" in actions
assert 'status=="action_required"' in actions
assert 'fp!=meta.get("myalpha_action_fingerprint")' in actions
assert "详细私有仓位未写入公开状态" in actions
print("PASS sanitized MyAlpha -> Telegram action bridge")
