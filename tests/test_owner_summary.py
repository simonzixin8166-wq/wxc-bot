"""YT-01 manual path: /yt <link> <summary> from the Owner is stored append-only without full text, all claims
author_claim_unverified, and admitted by the intake as a learning-only Q3 row (never rule / forward evidence)."""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = tmp
import owner_summary as osm

LONG = ("一、宏观市场\n布伦特原油逼近 120 美元关口，对道琼斯指数造成打压（跌逾 1%）。\n"
        "四、大盘技术面\nQQQ（纳指 100——核心风向标）：\n关键生命线：698（上方阻力关注 728）。\n"
        "RG（避险标的）：逆势走强，但需警惕 470~500 震荡区间上沿阻力。\n微软 / 谷歌：仓位保持不动。\n" + "补充说明。" * 80 + "结尾独有标记甲乙丙")

# parse: link forms, URL token removed, too short / no link rejected with a reason
for link in ("https://www.youtube.com/watch?v=b_ZVO8_QfJ0&t=12s", "https://youtu.be/b_ZVO8_QfJ0?si=x",
             "https://youtube.com/shorts/b_ZVO8_QfJ0"):
    vid, url, summary = osm.parse(f"/yt {link} {LONG}")
    assert vid == "b_ZVO8_QfJ0" and url.endswith("v=b_ZVO8_QfJ0") and "youtu" not in summary.split("\n")[0][:40]
assert osm.parse(f"/yt {LONG[:200]} https://youtu.be/b_ZVO8_QfJ0")[0] == "b_ZVO8_QfJ0"      # link after text
for bad, why in (("/yt " + LONG, "没有找到"), ("/yt https://youtu.be/b_ZVO8_QfJ0 太短了", "太短")):
    try:
        osm.parse(bad)
        raise AssertionError(bad)
    except ValueError as e:
        assert why in str(e)

# claims: lines with a ticker or number, ticker-shaped token kept but unverified, heading context as a hint only
cl = osm.claims(LONG)
by = {c["claim"][:6]: c for c in cl}
assert by["QQQ（纳指"]["symbol"] == "QQQ" and by["QQQ（纳指"]["symbol_check"] == "owner_text_unverified"
assert by["关键生命线："]["symbol"] is None and by["关键生命线："]["context_symbol"] == "QQQ"
assert by["RG（避险标"]["symbol"] == "RG"                     # NotebookLM's ISRG typo is kept AND flagged, never fixed
assert all(c["claim_status"] == "author_claim_unverified" and c["evidence_mode"] == "owner_supplied_summary" for c in cl)
assert not any(c["claim"].startswith("微软") for c in cl) and len(cl) <= osm.MAX_CLAIMS
assert all(len(c["claim"]) <= osm.CLAIM_CHARS for c in cl)

# submit: append-only file, no full text, dedupe by content hash, readable reply
r1 = osm.submit(f"/yt https://youtu.be/b_ZVO8_QfJ0 {LONG}")
assert r1.startswith("✅") and "作者主张·未核实" in r1
assert osm.submit(f"/yt https://youtu.be/b_ZVO8_QfJ0 {LONG}").startswith("ℹ️")
assert osm.submit("/yt 没有链接").startswith("❌")
rows = osm.load()
assert len(rows) == 1
rec = rows[0]
raw = osm.path().read_text(encoding="utf-8")
assert len(rec["excerpt"]) <= 360 and rec["summary_chars"] > 360 and "结尾独有标记甲乙丙" not in raw
assert rec["forward_evidence_eligible"] is False and rec["rule_candidate_allowed"] is False
assert rec["validation_status"] == "pending_owner_spot_check" and rec["published_at"] is None
osm.submit(f"/yt https://youtu.be/b_ZVO8_QfJ0 第二段：NVDA 下方强支撑在 196，波动空间较大，需要耐心等待。" + "。" * 40)
merged = osm.by_video()["b_ZVO8_QfJ0"]
assert len(merged["submission_ids"]) == 2 and any(c["symbol"] == "NVDA" for c in merged["claims"])

# intake: owner acquisition is admitted as learning-only Q3 for any role, never rule-eligible, no Gemini call
import youtube_research as yr
aq = yr._owner_acquisition(merged)
assert aq["content_origin"] == "owner_supplied_summary" and aq["quality"] == "Q3" and "[QQQ] 关键生命线" in aq["text"]
for role in ("rule_supply", "market_context", "other"):
    assert yr._content_ready({"role": role}, aq) is True
assert yr._content_ready({"role": "rule_supply"}, dict(aq, structured=None)) is False
row = yr.make_feed_row({"handle": "@RhinoFinance", "author": "RhinoFinance / 视野环球财经", "role": "rule_supply"},
                       {"id": "b_ZVO8_QfJ0", "title": "美股 对冲基金8天7减偏紧！", "upload_date": "20261024"}, aq)
assert row["evidence_mode"] == "owner_supplied_summary" and row["claims_status"] == "author_claim_unverified"
assert row["forward_evidence_eligible"] is False and row["rule_candidate_allowed"] is False
assert row["operations"] == [] and row["portfolio_rules"] == [] and len(row["excerpt"]) <= 360
assert {"QQQ", "NVDA"} <= set(row["symbols"]) and row["owner_submission_ids"] == merged["submission_ids"]
assert yr._owner_summaries()["b_ZVO8_QfJ0"]["video_id"] == "b_ZVO8_QfJ0"
src = (REPO / "youtube_research.py").read_text(encoding="utf-8")
assert "if vid in owner_subs:\n                    aq=_owner_acquisition(owner_subs[vid])" in src
assert "0 if kv[0] in owner_subs else 1" in src

# Telegram: /yt is routed before any other intent and replies once
import wxc_tg_agent as agent
said = []
saved = agent.say
try:
    agent.say = said.append
    agent.handle("/yt https://youtu.be/AAAAAAAAAAA " + "TSLA 支撑 380，跌破则观望。" * 5, sync=True)
finally:
    agent.say = saved
assert len(said) == 1 and said[0].startswith("✅") and "AAAAAAAAAAA" in osm.by_video()
print("PASS YT-01 owner /yt summaries: append-only, no full text, unverified claims, learning-only Q3 intake")

# reply tells the truth about whether the intake will use it
base = Path(tmp)
(base / "pending_youtube.json").write_text(json.dumps({"records": [{"video_id": "PPPPPPPPPPP"}]}))
(base / "seen_youtube.json").write_text(json.dumps({"video_ids": ["PPPPPPPPPPP", "SSSSSSSSSSS"]}))
assert "下一次 YouTube 采集时收录" in osm.queue_note("PPPPPPPPPPP", base)
assert "供抽查时对照" in osm.queue_note("SSSSSSSSSSS", base)
assert "暂不进入资料库" in osm.queue_note("XXXXXXXXXXX", base)
print("PASS owner /yt reply queue note")
