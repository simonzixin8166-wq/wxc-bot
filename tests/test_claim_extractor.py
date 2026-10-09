import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import claim_extractor as ce

t = "我准备长期持有VGT，跌到110会继续加仓。英伟达这个价位看好，上涨空间还有。TSLA可以买入了吗？今天天气不错，提到AAPL而已。"
cl = ce.extract_claims(t)
by = {(c["symbol"], c["stance"]) for c in cl}
assert ("VGT", "add") in by or ("VGT", "hold") in by, cl
vgt = [c for c in cl if c["symbol"] == "VGT"][0]
assert vgt["horizon"] == "long" and vgt["conditional"] is True and vgt["price"] == 110.0
assert ("NVDA", "bullish") in by
tsla = [c for c in cl if c["symbol"] == "TSLA"][0]
assert tsla["question"] is True and not ce.checkable(tsla)
assert not any(c["symbol"] == "AAPL" for c in cl)          # mention without stance is not a claim
# no source wording stored
blob = json.dumps(cl, ensure_ascii=False)
for frag in ("准备长期", "上涨空间", "天气"):
    assert frag not in blob
assert all(len(c["evidence_sha256"]) == 64 for c in cl)
# unpunctuated transcript is chunked, claims stay local
long = "今天我们来聊一聊市场 " * 30 + "我觉得美光MU现在值得买"
assert any(c["symbol"] == "MU" and c["stance"] == "buy" for c in ce.extract_claims(long))
# English
assert any(c["symbol"] == "QQQ" and c["stance"] == "bearish" for c in ce.extract_claims("I am bearish on QQQ for the next few months."))
# provider boilerplate
junk = "Scribe Like it? Make Scribe even better by leaving a review Get Chrome Extension Browse Popular Videos Recent Videos All Channels Free Tools Video Subtitle Downloader"
assert ce.provider_boilerplate(junk) and not ce.provider_boilerplate(t)
assert not ce.provider_boilerplate(junk + " real transcript words" * 200)
print("PASS claim_extractor")
