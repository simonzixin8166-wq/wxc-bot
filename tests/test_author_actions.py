"""麻你 VGT/SGOV action extraction: plans never become executions; HOLD keeps allocation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import author_actions as aa

# 2026-09-25 title: continue 87% VGT / 13% SGOV next week → HOLD, not a trade
a = aa.extract_author_actions("麻你", "下个星期继续保持87%仓位在VGT，13%在SGOV", "")
vgt = [x for x in a if x["symbol"] == "VGT"][0]
assert vgt["action_type"] == "HOLD" and vgt["allocation_pct"] == {"VGT": 87.0, "SGOV": 13.0}, a
assert aa.headline(a) == "VGT：继续持有 VGT 87% / SGOV 13%", aa.headline(a)

# 2026-09-11 mixed: hold 87/13 AND set 117.57 take-profit selling 4% → HOLD + SELL_PLANNED (not executed)
a = aa.extract_author_actions("麻你", "", "继续持有87% VGT、13% SGOV。设117.57止盈，卖出VGT总仓位4%。")
types = {(x["symbol"], x["action_type"]) for x in a}
assert ("VGT", "HOLD") in types and ("VGT", "SELL_PLANNED") in types, a
sp = [x for x in a if x["action_type"] == "SELL_PLANNED"][0]
assert sp["price"] == 117.57 and sp["size_pct"] == 4.0
assert not any(x["action_type"].endswith("EXECUTED") for x in a)
assert aa.headline(a) == "VGT：计划减仓（非成交） 4% @ 117.57", aa.headline(a)

# explicit execution
a = aa.extract_author_actions("麻你", "", "今天117.57成交了，已卖出VGT 4%。")
assert any(x["action_type"] == "SELL_EXECUTED" for x in a), a
# rebalance
a = aa.extract_author_actions("麻你", "", "把一部分VGT转到SGOV，调仓了。")
assert any(x["action_type"] == "REBALANCE" for x in a), a
# commentary only
a = aa.extract_author_actions("麻你", "为什么要多仓VGT", "VGT 是科技指数，长期看好。")
assert all(x["action_type"] in ("COMMENTARY", "HOLD") for x in a), a
# untracked author → nothing (no fuzzy matching of people quoting 麻你)
assert aa.extract_author_actions("bogbog", "麻你说继续持有VGT", "") == []
assert all(len(x["evidence_quote"]) <= 40 for x in aa.extract_author_actions("麻你", "", "继续持有87% VGT、13% SGOV，这是一个比较长的句子用于测试截断长度是否正确并且不超过四十个字符的限制"))
print("PASS author_actions")
