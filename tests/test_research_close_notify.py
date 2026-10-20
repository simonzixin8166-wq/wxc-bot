"""research-close: a Telegram delivery failure is reported but never fails the collection run (run 39351856353)."""
import os, sys, types
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TG_TOKEN", "x"); os.environ.setdefault("TG_CHAT_ID", "1")
import daily_close_research as d  # noqa: E402

sent = []
assert d.notify_digest("hello", send=sent.append) == "sent" and sent == ["hello"]

def boom(_):
    raise TimeoutError("read timed out")
assert d.notify_digest("hello", send=boom) == "failed:TimeoutError"

src = (ROOT / "daily_close_research.py").read_text(encoding="utf-8")
assert "agent.say(digest" not in src and "notify_digest(digest" in src  # main() goes through the non-gating wrapper
print("PASS research-close notification is non-gating")
