"""#133 P1-4 round 2: stratified title-only sampling + reviewer excerpts (no full text)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import claim_extractor as ce
import diagnose_title_only as d


def recs():
    out = []
    for a, n in (("A", 300), ("B", 20), ("C", 5)):
        for i in range(n):
            out.append({"author": a, "url": f"https://x/{a}/{i}", "excerpt": "", "content_chars": 0,
                        "published_at": f"{2024 + i % 3}-01-01"})
    return out


def test_allocation_min_and_cap():
    picks, pop, alloc = d.stratified_sample(recs(), 60, min_per_author=12)
    assert pop == {"A": 300, "B": 20, "C": 5}
    assert alloc["C"] == 5 and alloc["B"] == 12 and alloc["A"] >= 12
    assert all(len(picks[a]) <= alloc[a] for a in picks)
    years = {r["published_at"][:4] for r in picks["A"]}
    assert len(years) == 3  # every year stratum represented


def test_exclude_round1():
    ex = {f"https://x/C/{i}" for i in range(5)}
    picks, pop, _ = d.stratified_sample(recs(), 60, exclude=ex)
    assert "C" not in pop


def test_wilson_and_estimate():
    assert d.wilson(0, 0) is None
    lo, hi = d.wilson(11, 12)
    assert 0.6 < lo < 0.92 < hi <= 1
    rows = [{"author": "A", "reason": "genuinely_empty"}] * 3 + [{"author": "A", "reason": "image_only"}] + \
           [{"author": "B", "reason": "image_only"}] * 2 + [{"author": "B", "reason": "http_error"}]
    per, w = d.estimate(rows, {"A": 300, "B": 100})
    assert per["B"]["probed"] == 2  # http errors excluded from shares
    assert abs(w["image_only"] - (300 * 0.25 + 100 * 1.0) / 400) < 0.001


def test_review_excerpts_short_and_located():
    text = "这是一段很长的开场白，没有任何股票。我觉得长期来看英伟达值得买入，因为数据中心需求还在增长。NVDA最近的财报不错。"
    r = ce.review_material(text)
    assert r["claim_sentences"] and all(len(x["excerpt"]) <= 40 for x in r["claim_sentences"])
    assert "英伟达" in r["claim_sentences"][0]["excerpt"]
    assert r["mention_without_stance_total"] == 1 and len(r["mention_without_stance"][0]["sha256"]) == 64


def test_negated_sell_is_hold_and_take_profit_is_trim():
    c = ce.extract_claims("没有减仓，VGT的比例肯定增加了。")
    assert c and c[0]["symbol"] == "VGT" and c[0]["stance"] == "hold"
    assert ce.extract_claims("No, LITE 没有那么speculative，不卖")[0]["stance"] == "hold"
    assert ce.extract_claims("Taking some profit on AMAT")[0]["stance"] == "trim"
    assert ce.extract_claims("今天卖出了部分VGT在117.57")[0]["stance"] == "sell"


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("test_learning_round2 PASS")
