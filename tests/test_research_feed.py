from pathlib import Path
import tempfile
import research_feed as rf

assert "INTC" in rf.detect_themes("Intel INTC thesis")
assert "Sell Put" in rf.detect_themes("sell put on QQQ")
assert "失败复盘" in rf.detect_themes("这次看错了，割肉复盘")

row = rf.normalize("forum", "yifan99", {
    "title": "INTC sell put 复盘",
    "text": "作者讨论风险和失败复盘",
    "url": "https://bbs.wenxuecity.com/cfzh/123.html#comment_1",
    "date": "2026-09-30 12:00:00",
    "images": [],
})
assert row["author"] == "yifan99"
assert row["url"].endswith("/123.html")
assert "INTC" in row["themes_hint"]
assert row["source_notice"].startswith("作者原始观点")

with tempfile.TemporaryDirectory() as td:
    old = rf.FEED_PATH
    rf.FEED_PATH = Path(td) / "research_feed.json"
    try:
        assert rf.append_records([row]) == 1
        original=rf._read(rf.FEED_PATH,{"records":[]})["records"][0]
        original_captured=original["captured_at"]
        enriched=dict(row)
        enriched["captured_at"]="2099-01-01T00:00:00Z"
        enriched["method_signals"]=[{
            "condition_id":"price_above_ma50","machine_ready":True,
            "evidence_excerpt":"价格站上 MA50","evidence_hash":"a"*64,
            "source_derived_only":True
        }]
        assert rf.append_records([enriched]) == 0
        after=rf._read(rf.FEED_PATH,{"records":[]})["records"][0]
        assert after["captured_at"]==original_captured
        assert after["published_at"]==row["published_at"]
        assert after["method_signals"][0]["condition_id"]=="price_above_ma50"
        assert rf.append_records([enriched]) == 0
    finally:
        rf.FEED_PATH = old

print("PASS source intelligence research feed")


sample = """NBIS：第一档 180，第二档 150，卖出线 250。
QCOM：不直接买股票，先卖 150 行权价的现金担保 put，140 是第二档。接到货再说。
现金底线不破，核心仓位不上杠杆。每次只用一档，不允许一次打完。
这不是我预判精准，这是运气。7月加得太快太猛，子弹在半山腰就打光。过程是错的。"""
learning = rf.extract_structured_learning(sample)
assert any(x.get("entry_1") == 180 for x in learning["operations"])
assert any(x.get("sell_put_strike") == 150 for x in learning["operations"])
assert "cash_floor" in learning["portfolio_rules"]
assert "no_core_leverage" in learning["portfolio_rules"]
assert "one_tranche_at_a_time" in learning["portfolio_rules"]
assert "luck_not_skill" in learning["lessons"]
assert "cash_too_early" in learning["lessons"]
assert "process_wrong" in learning["lessons"]


attr_sample = """子弹与耐心
我在跌之前卖了一批。
现在的做法是：在跌之前把点位写下来。
NBIS：第一档 180，第二档 150，卖出线 250。"""
al = rf.extract_structured_learning(attr_sample)
nb = [x for x in al["operations"] if "NBIS" in (x.get("symbols") or [])][0]
assert nb["attribution"] == "author_plan"

third_sample = """段永平的93条语录
2025年3月，他以116.7美元买入10万股英伟达。"""
tl = rf.extract_structured_learning(third_sample)
if tl["operations"]:
    assert all(x["attribution"] == "third_party_example" for x in tl["operations"])


# Ticker hygiene: English prose must not create false positives.
assert "NOW" not in rf.detect_symbols("SMH also flying, 620 now!")
assert "MU" not in rf.detect_symbols('RSP "must" hold above it or dead :)')
assert "NOW" in rf.detect_symbols("ServiceNow looks extended")
assert "NOW" in rf.detect_symbols("NOW is breaking out")
assert "MU" in rf.detect_symbols("MU up 30, told u guys don't panic")

# English method routing.
themes = rf.detect_themes("We buy when they panic, but with very clear stop loss in place. Need a strong close.")
assert "逆向交易" in themes
assert "止损纪律" in themes
assert "风险管理" in themes
assert "趋势确认" in themes


assert "BrightLine" in rf.BLOG_PROFILES
assert "yifan99" in rf.BLOG_PROFILES
assert rf.blog_seen_path("yifan99").name == "seen_blog_yifan99.json"


# Full-text method extraction must survive the public 360-char excerpt cap.
# The later PPO/MA50 conditions are intentionally placed after the excerpt.
long_method_text=(
    "AMZN趋势观察。" + "前文背景说明。"*80 +
    "\nTCDS 从深度负值持续回升，今天 TCDS = 0。"
    "\nPPO 已经向上交叉 Signal，Histogram 从负值转正。"
    "\n价格随后站上 MA50；如果连续两个交易日守住 MA50，再视为趋势确认。"
)
signals=rf.extract_method_signals(long_method_text)
ids={x["condition_id"] for x in signals}
assert "tcds_cross_zero" in ids
assert "ppo_above_signal" in ids
assert "ppo_hist_positive" in ids
assert "price_above_ma50" in ids
assert "ma50_hold_two_sessions" in ids
assert next(x for x in signals if x["condition_id"]=="price_above_ma50")["machine_ready"] is True
assert next(x for x in signals if x["condition_id"]=="ppo_above_signal")["machine_ready"] is False

method_row=rf.normalize("blog","yifan99",{
    "title":"Amazon，要突破了？","text":long_method_text,
    "url":"https://blog.wenxuecity.com/myblog/31983/202610/3830.html",
    "date":"2026-10-06","images":[]
})
assert len(method_row["excerpt"])<=rf.MAX_EXCERPT
assert "PPO" not in method_row["excerpt"]  # proves the old excerpt-only path would miss it
method_ids={x["condition_id"] for x in method_row["method_signals"]}
assert {"tcds_cross_zero","ppo_above_signal","ppo_hist_positive","price_above_ma50","ma50_hold_two_sessions"} <= method_ids
assert all(len(x["evidence_excerpt"])<=180 for x in method_row["method_signals"])
assert all(len(x["evidence_hash"])==64 for x in method_row["method_signals"])
print("PASS full-text method signals survive bounded excerpt")
