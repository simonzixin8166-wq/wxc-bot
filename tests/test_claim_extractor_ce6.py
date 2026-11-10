"""ce-6 (shadow, S2 v5 dev fixes): synthetic sentences only; production still uses ce-4."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import claim_extractor as ce  # noqa: E402


def got(text):
    return {(c["symbol"], c["stance"]) for c in ce.extract_claims_v6(text) if not c["question"]}


# colloquial views
assert ("MU", "bullish") in got("MU目标价依然是1400-1500，12个月目标。")
assert ("SPY", "bullish") in got("我觉得SPY跌到753左右是好事。")
assert ("QQQ", "bearish") in got("QQQ 现在不是buy buy buy的时候，as it's getting close to the local top。")
assert ("QQQ", "buy") not in got("QQQ 现在不是buy buy buy的时候，as it's getting close to the local top。")
assert ("SPX", "bullish") in got("Look for SPX to reach 7860 at least before some pullback")
# ticker carried from the title of a short post, marked as context
c = ce.extract_claims_v6("INTC今天跌到86了？\n那还可以的价格了。")
assert any(x["symbol"] == "INTC" and x["stance"] == "bullish" and x["ticker_source"] == "context" for x in c)
c = ce.extract_claims_v6("TSLA上一次大跌后探底花了3个月。\n到时候我还要进场加仓")
assert any(x["symbol"] == "TSLA" and x["stance"] == "add" and x["conditional"] for x in c)
# no carry when the post names several tickers
assert not any(x["ticker_source"] == "context" for x in ce.extract_claims_v6("NVDA 和 AMD 都跌了。\n那还可以的价格了。"))
# historical / hypothetical sentences without the author are not claims
assert not got("同一个QQQ，如果是1999年高点买进，到今天年化只有10.5%左右。")
assert not got("亚马逊在2000年互联网泡沫破裂后，股价从高点跌掉九成多。")
assert ("AMZN", "buy") in got("2000年那次我在低位买了亚马逊。")
# production entry point unchanged
assert ce.EXTRACTOR_VERSION == "ce-4"
print("PASS claim extractor ce-6 (shadow)")
