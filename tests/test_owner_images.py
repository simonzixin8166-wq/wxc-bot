"""Images in the Owner's own zips (Owner 2026-11-21; intake only, no understanding yet): stored once by hash in the
private textpack, public index keeps hash/size/type/references only, tiny GIFs skipped, caps respected, 20MB file
limit, articles in the same zip still ingested. Invented bytes only; no network."""
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
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["TEXTPACK_TOKEN"], os.environ["TEXTPACK_REPO"] = "t", "o/r"
import owner_forward as of  # noqa: E402
import owner_images as oi  # noqa: E402


class R:
    def __init__(self, code):
        self.status_code = code


class Http:
    def __init__(self, code=201):
        self.puts, self.code = [], code

    def put(self, url, **k):
        self.puts.append(url)
        return R(self.code)


PNG = b"\x89PNG\r\n\x1a\n" + b"chart-bytes" * 500
JPG = b"\xff\xd8\xff" + b"photo" * 900
TINY_GIF = b"GIF89a" + b"x" * 100
BIG_GIF = b"GIF89a" + b"y" * 5000
DIGEST = """# zmimg 的发言整理

## 股市也许快到底了

楼主 zmimg · 2026-11-19 09:00 · [原帖](https://bbs.wenxuecity.com/cfzh/700001.html)

### 2026-11-19 09:00 · 股市也许快到底了

![图](images/sig.png)
"""


def make_zip(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, d in files:
            z.writestr(n, d)
    return b.getvalue()


NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
ZIP = make_zip([("zmimg.md", DIGEST), ("images/sig.png", PNG), ("images/photo.jpeg", JPG),
                ("images/smile.gif", TINY_GIF), ("images/anim.gif", BIG_GIF), ("__MACOSX/images/._sig.png", PNG)])

# zip_images: tiny gif skipped, __MACOSX ignored
imgs, skipped = oi.zip_images(ZIP)
assert sorted(n for n, _ in imgs) == ["images/anim.gif", "images/photo.jpeg", "images/sig.png"] and skipped["tiny_gif"] == 1
assert oi.references([("zmimg.md", DIGEST)]) == {"sig.png": ["zmimg.md"]}
assert oi.references([("a.md", "[图片](https://example.com/x.png)")]) == {}      # web image links are never followed

# through the normal zip path (Telegram / Gmail): article + images
http, said = Http(), []
oi.PUT_PAUSE_S = 0
out = of.handle({"date": int(NOW.timestamp()), "caption": "", "_bytes": ZIP,
                 "document": {"file_name": "wxc_2026-11-23.zip", "file_size": len(ZIP)}}, said.append, http=http, now=NOW)
assert out["images"]["new"] == 3 and out["images"]["tiny_gif"] == 1, out
img_puts = [u for u in http.puts if "/G_owner_images/" in u]
assert len(img_puts) == 3 and all(u.endswith((".png", ".jpg", ".gif")) for u in img_puts), img_puts
rows = [json.loads(x) for x in oi.index_path().read_text(encoding="utf-8").splitlines()]
sig = next(r for r in rows if r["member"] == "images/sig.png")
assert sig["referenced_in"] == ["zmimg.md"] and sig["understanding"].startswith("not_started") and sig["bytes"] == len(PNG)
assert all(set(r) >= {"sha256", "ext", "bytes", "textpack_path", "retrieved_at"} and "content" not in r for r in rows)
assert any("图片 3 张：新收录 3" in s and "跳过小 gif 1 张" in s for s in said), said
assert out.get("forum_zip", {}).get("new") == 1                                 # the digest utterance is still ingested

# same zip again: no image stored twice
http2 = Http()
out2 = of.handle({"date": int(NOW.timestamp()), "caption": "", "_bytes": ZIP,
                  "document": {"file_name": "wxc_2026-11-23.zip", "file_size": len(ZIP)}}, said.append, http=http2, now=NOW)
assert out2["images"]["duplicate"] == 3 and not [u for u in http2.puts if "/G_owner_images/" in u]

# a zip with images only
ONLY = make_zip([("images/new.png", PNG + b"2")])
said.clear()
out3 = of.handle({"date": int(NOW.timestamp()), "caption": "", "_bytes": ONLY,
                  "document": {"file_name": "pics.zip", "file_size": len(ONLY)}}, said.append, http=Http(), now=NOW)
assert out3 == {"images": out3["images"]} and out3["images"]["new"] == 1 and said[-1].startswith("图片 1 张")

# GitHub failure: not indexed, so a re-send retries it
FAIL = make_zip([("images/f.png", PNG + b"3")])
c = oi.ingest_zip(FAIL, [], NOW.isoformat(), NOW, Http(500), pause=0)
assert c["failed"] == 1 and c["new"] == 0 and not any(r["member"] == "images/f.png" for r in
                                                       (json.loads(x) for x in oi.index_path().read_text().splitlines()))
# per-zip cap
old = oi.MAX_IMAGES_PER_ZIP
oi.MAX_IMAGES_PER_ZIP = 2
assert oi.zip_images(make_zip([(f"images/{i}.png", PNG + bytes([i])) for i in range(4)]))[1]["over_cap"] == 2
oi.MAX_IMAGES_PER_ZIP = old

# 20MB limit (Telegram getFile limit), Apps Script the same
said.clear()
assert of.MAX_FILE_BYTES == 20_000_000
assert of.handle({"date": 0, "caption": "", "_bytes": b"", "document": {"file_name": "big.zip", "file_size": 20_000_001}},
                 said.append, http=Http(), now=NOW) is None and "20MB" in said[-1]
gs = (ROOT / "tools" / "gmail" / "myalpha_gmail_inbox.gs").read_text(encoding="utf-8")
assert "var MAX_BYTES = 20 * 1000 * 1000;" in gs
src = (ROOT / "owner_images.py").read_text(encoding="utf-8")
assert "generativelanguage" not in src and "import requests" not in src and "http.get(" not in src   # intake only: no model, no fetch
print("PASS owner images: zip images stored once in private textpack, hash-only index, tiny gif skipped, 20MB cap")
