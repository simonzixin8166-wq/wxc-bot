"""Owner e-mail inbox: files the Owner's Apps Script copies into the private textpack inbox go through the same
intake as a zip forwarded in Telegram; each file once (path + sha); no forum or link is ever fetched."""
import io
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=tmp, TEXTPACK_TOKEN="t", TEXTPACK_REPO="owner/textpack")
import gmail_inbox as gi

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("a.md", "# 标题\n原文链接：https://example.com/post/1\n发布时间：2026-11-17\n---\n" + "正文内容。" * 40)
ZIP = buf.getvalue()


class R:
    def __init__(self, code, js=None, content=b""):
        self.status_code, self._js, self.content = code, js, content
    def json(self):
        return self._js


class Http:
    def __init__(self):
        self.calls = []
    def get(self, url, headers=None, timeout=None, params=None):
        self.calls.append(("GET", url))
        if url.endswith("/contents/inbox/gmail"):
            return R(200, [{"type": "file", "name": "20261117T013000Z_m1_wxc_daily.zip", "path": "inbox/gmail/20261117T013000Z_m1_wxc_daily.zip", "sha": "s1"}])
        if url.endswith("20261117T013000Z_m1_wxc_daily.zip") and headers.get("Accept") == "application/vnd.github.raw":
            return R(200, content=ZIP)
        return R(404)
    def put(self, url, headers=None, timeout=None, json=None):
        self.calls.append(("PUT", url))
        return R(201)


said, http = [], Http()
NOW = datetime(2026, 11, 17, 2, tzinfo=timezone.utc)
out = gi.check(said.append, http=http, now=NOW)
assert out == {"status": "ok", "new": 1, "processed": 1, "failed": 0}, out
assert said[0].startswith("📧 邮件自动收录：wxc_daily.zip") and any("新收录 1" in s for s in said), said
assert all("api.github.com/repos/owner/textpack" in u for _, u in http.calls), http.calls   # nothing else contacted
row = json.loads((Path(tmp) / "owner_forward_index.jsonl").read_text(encoding="utf-8").splitlines()[0])
assert row["retrieved_at"] == "2026-11-17T01:30:00+00:00" and row["input"] == "zip:md_file"
# second check: same path + sha -> skipped
said.clear()
assert gi.check(said.append, http=Http(), now=NOW) == {"status": "ok", "new": 0, "processed": 0, "failed": 0} and said == []
# no token -> off; empty inbox -> empty
os.environ["TEXTPACK_TOKEN"] = ""
assert gi.check(said.append, http=Http())["status"].startswith("off")
print("PASS gmail inbox: Owner's e-mailed zip -> same intake as a Telegram forward, once per file, GitHub only")
