"""Owner forward intake (S2 v5 source C): local mocks only, no network."""
import base64
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import owner_forward as fw  # noqa: E402

BODY = "这是正文第一段，作者解释了为什么在下跌中分批买入。" * 20
PAGE = f"""<html><head><title>测试标题 - 博客 | 文学城</title><script>var x=1</script></head><body>
<div class="nav">博客首页 退出登录 模板 宽屏 普通</div><h1 id="titleName">测试标题</h1>
<div id="articalContent"><p>{BODY}</p><p>不是推荐股票。</p></div><div>最新评论 某读者：谢谢</div></body></html>"""
NOW = datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc)
URL = "https://blog.wenxuecity.com/myblog/82458/202611/3461.html"


class Resp:
    def __init__(self, status=200, js=None, content=b""):
        self.status_code, self._js, self.content = status, js, content

    def json(self):
        return self._js


class Http:
    def __init__(self, file_bytes=PAGE.encode("utf-8"), put_status=201):
        self.gets, self.puts, self.file_bytes, self.put_status = [], [], file_bytes, put_status

    def get(self, url, params=None, timeout=None):
        self.gets.append(url)
        assert url.startswith("https://api.telegram.org/"), f"must never open other hosts: {url}"
        if url.endswith("/getFile"):
            return Resp(js={"ok": True, "result": {"file_path": "documents/file_1.html"}})
        return Resp(content=self.file_bytes)

    def put(self, url, headers=None, timeout=None, json=None):
        assert url.startswith("https://api.github.com/repos/owner/textpack/contents/s2_v5_textpack/C_owner_forward/")
        assert headers["Authorization"] == "Bearer tok"
        self.puts.append((url, base64.b64decode(json["content"]).decode("utf-8")))
        return Resp(status=self.put_status)


def run(msg, http, env=True):
    said = []
    os.environ.pop("TEXTPACK_TOKEN", None)
    os.environ.pop("TEXTPACK_REPO", None)
    if env:
        os.environ.update(TEXTPACK_TOKEN="tok", TEXTPACK_REPO="owner/textpack")
    row = fw.handle(msg, said.append, tg_api="https://api.telegram.org/botX", tg_file_base="https://api.telegram.org/file/botX",
                    http=http, now=NOW)
    return row, said


with tempfile.TemporaryDirectory() as td:
    os.environ["DATA_DIR"] = td
    idx = Path(td) / "owner_forward_index.jsonl"

    # routing
    assert fw.is_forward({"text": "/fw " + URL}) and fw.is_forward({"document": {"file_name": "a.HTML"}})
    assert not fw.is_forward({"text": "订阅 三心三意"}) and not fw.is_forward({"document": {"file_name": "a.pdf"}})

    # 1. link only -> asks for the text, never opens the link, stores nothing
    h = Http()
    row, said = run({"text": "/fw " + URL, "date": 1762398000}, h)
    assert row is None and h.gets == [] and h.puts == [] and not idx.exists()
    assert "不会自己打开链接" in said[0]
    print("PASS link-only is refused, link never opened")

    # 2. no link -> refused
    row, said = run({"text": "/fw " + BODY}, Http())
    assert row is None and "链接" in said[0] and not idx.exists()
    print("PASS missing link refused")

    # 3. text forward -> full text only to the private repo; public row has <=360 excerpt and no full text
    h = Http()
    row, said = run({"text": f"/fw {URL}\n{BODY}", "date": 1762398000}, h)
    assert row["textpack"] == "stored" and row["source_url"] == URL and row["input"] == "message_text"
    assert [u.rsplit("/", 1)[1] for u, _ in h.puts] == [row["item_id"] + ".txt", row["item_id"] + ".meta.json"]
    assert h.puts[0][1].strip() == BODY and json.loads(h.puts[1][1])["sha256"] == row["sha256"]
    public = idx.read_text(encoding="utf-8")
    assert len(row["excerpt"]) <= 360 and BODY not in public and "text" not in row
    assert row["retrieved_at"] == datetime.fromtimestamp(1762398000, timezone.utc).isoformat(timespec="seconds")
    assert "已收录" in said[0]
    print("PASS text forward: full text private only, public excerpt <= 360")

    # 4. duplicate -> not stored again
    h = Http()
    row, said = run({"text": f"/fw {URL}\n{BODY}"}, h)
    assert row is None and h.puts == [] and "已经收录" in said[0]
    assert len(idx.read_text(encoding="utf-8").splitlines()) == 1
    print("PASS duplicate not stored twice")

    # 5. html file ("save page as") -> body only (no nav / comments / script), link from caption
    h = Http()
    row, said = run({"document": {"file_id": "F1", "file_name": "page.html", "file_size": 5000}, "caption": URL}, h)
    assert row["title"] == "测试标题" and row["input"] == "html_file" and row["textpack"] == "stored"
    stored = h.puts[0][1]
    assert BODY in stored and "不是推荐股票" in stored
    assert all(x not in stored for x in ("退出登录", "最新评论", "var x"))
    assert all(u.startswith("https://api.telegram.org/") for u in h.gets)
    print("PASS html file: article body extracted, only Telegram contacted")

    # 6. no token -> full text not stored anywhere, status says so
    h = Http()
    row, said = run({"text": f"/fw https://example.com/a\n{BODY}再来一篇"}, h, env=False)
    assert h.puts == [] and row["textpack"].startswith("unavailable") and "unavailable" in said[0]
    print("PASS no token: full text not stored")

    # 7. GitHub failure is reported, not hidden
    row, said = run({"text": f"/fw https://example.com/b\n{BODY}第三篇"}, Http(put_status=403))
    assert row["textpack"] == "failed (GitHub 403)"
    print("PASS textpack failure reported")

    # 8. oversized file refused before download
    h = Http()
    row, said = run({"document": {"file_id": "F2", "file_name": "big.html", "file_size": 5_000_000}, "caption": URL}, h)
    assert row is None and h.gets == []
    print("PASS oversized file refused")

    # public index never contains a full body
    for line in idx.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        assert len(r["excerpt"]) <= 360 and set(r) >= {"item_id", "source_url", "sha256", "chars", "textpack"}

print("PASS owner forward intake")
