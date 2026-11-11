"""ce-7 (forum shadow): synthetic sentences only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import claim_extractor as ce  # noqa: E402


def st(text, ctx=None):
    return {(c["symbol"], c["stance"], c["ticker_source"]) for c in ce.extract_claims_v7(text, ctx) if not c["question"]}


assert ("QQQ", "add", "text") in st("加仓qqq")                                   # one-line reply under 6 chars
assert ("AMD", "hold", "context") in st("That is my long hold, no way I am going to close it", "AMD Jan 400 put 关吗？")
assert st("我们应该是同一天进的", "我的 NVDA 和 AMD 都卖了") == set()           # two tickers in the parent: no carry
assert ("TMF", "sell", "context") in st("可以完成它的历史使命了，卖掉", "TMF up 20%")
assert ("AMD", "bullish", "text") in st("Sell Jan AMD 400 put for 40")             # selling puts is bullish, never sell
assert ("AVGO", "bullish", "text") in st("Sold AVGO March put 290 for 32")
assert ("SOXL", "buy", "text") in st("今天盘后42又进 SOXL")
assert ("TSLA", "bearish", "context") in st("I think it is a good short target as it gets to 480-500", "短期 TSLA")
assert ("META", "hold", "text") in st("我的meta股票就靠他了") or ("META", "hold", "text") in st("我的 META 股票就靠他了")
assert st("如果你在300上方卖掉MRVL，170买回，就不会惦记了") == set()             # advice to "you", not the author's
assert st("他今天买入了 NVDA") == set()                                           # third party
assert ce.extract_claims("加仓qqq") == []                                          # production ce-4 is unchanged
print("PASS ce-7 forum shadow: short replies, parent-context ticker, colloquial/English cues, abstentions")
