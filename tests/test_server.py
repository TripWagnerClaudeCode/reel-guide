"""Tests for server.py — temp DB, temp key, fake worker script, ephemeral port. No network."""
import json
import os
import sqlite3
import stat
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

FAKE_WORKER = textwrap.dedent("""
    import json, sys, time
    url = sys.argv[-1]
    log = sys.argv[1]
    with open(log, "a") as f:
        f.write(json.dumps({"url": url, "event": "start", "t": time.time()}) + "\\n")
    time.sleep(float(sys.argv[2]))
    with open(log, "a") as f:
        f.write(json.dumps({"url": url, "event": "end", "t": time.time()}) + "\\n")
    if "fail" in url:
        print("doing things")
        print("ERROR: download: boom", file=sys.stderr)
        sys.exit(3)
    print("GUIDE: /tmp/guide.md")
    print("VERDICT: Build it")
""")


class Env:
    def __init__(self, tmp_path, delay=0.0, start=True, prepopulate=None, worker_src=FAKE_WORKER,
                 **app_kw):
        self.tmp = tmp_path
        self.db = tmp_path / "queue.db"
        self.key_path = tmp_path / "cfg" / "key"
        self.log = tmp_path / "worker.log"
        script = tmp_path / "fake_worker.py"
        script.write_text(worker_src)
        self.notes = []
        if prepopulate:
            prepopulate(self)
        self.app = server.App(
            db_path=self.db, key_path=self.key_path,
            worker_cmd=[sys.executable, str(script), str(self.log), str(delay)],
            binds=["127.0.0.1"], port=0, cwd=tmp_path,
            notify=lambda *a: self.notes.append(a), **app_kw,
        )
        self.key = self.app.key
        if start:
            self.app.start()
        self.base = f"http://127.0.0.1:{self.app.port}"

    def req(self, method, path, body=None, key=True, ctype="application/json", headers=None):
        data = body if isinstance(body, (bytes, type(None))) else (
            json.dumps(body).encode() if ctype == "application/json" and not isinstance(body, str)
            else body.encode())
        h = {"Content-Type": ctype} if data is not None else {}
        if key:
            h["X-Reel-Key"] = self.key if key is True else key
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def wait_idle(self, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            h = self.app.queue.health()
            if h["queued"] == 0 and h["running"] is None:
                return
            time.sleep(0.05)
        raise AssertionError("worker did not go idle")

    def events(self):
        if not self.log.exists():
            return []
        return [json.loads(l) for l in self.log.read_text().splitlines()]


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.app.stop()


IG = "https://www.instagram.com/reel/ABC123/"


def test_key_file_created_0600(env):
    mode = stat.S_IMODE(os.stat(env.key_path).st_mode)
    assert mode == 0o600
    assert len(env.key) == 64
    # second load returns the same key
    assert server.load_or_create_key(env.key_path) == env.key


def test_auth_401(env):
    assert env.req("POST", "/reel", {"url": IG}, key=False)[0] == 401
    assert env.req("POST", "/reel", {"url": IG}, key="0" * 64)[0] == 401
    assert env.req("GET", "/jobs", key=False)[0] == 401
    assert env.app.queue.recent() == []


def test_bad_url_400(env):
    for body in ({"url": "https://example.com/reel/x"}, {"url": ""}, {"nope": 1},
                 {"url": "https://notinstagram.com/reel/x"}):
        assert env.req("POST", "/reel", body)[0] == 400
    assert env.req("POST", "/reel", "just some words", ctype="text/plain")[0] == 400
    assert env.app.queue.recent() == []


def test_body_limit_413(env):
    big = "x" * (server.MAX_BODY + 1)
    assert env.req("POST", "/reel", big, ctype="text/plain")[0] == 413


def test_queue_202_and_run(env):
    code, body = env.req("POST", "/reel", {"url": IG + "?igsh=abc123&utm_source=ig_web"})
    assert code == 202 and body["status"] == "queued" and isinstance(body["id"], int)
    env.wait_idle()
    job = env.app.queue.get(body["id"])
    assert job["url"] == IG  # tracking params stripped
    assert job["status"] == "done" and job["exit_code"] == 0
    assert job["guide"] == "/tmp/guide.md" and job["verdict"] == "Build it"
    assert env.notes == []  # success push is reel_guide.py's job
    code, jobs = env.req("GET", "/jobs")
    assert code == 200 and jobs["jobs"][0]["id"] == body["id"]


def test_failure_records_error_and_notifies(env):
    code, body = env.req("POST", "/reel", {"url": "https://www.instagram.com/reel/fail1/"})
    assert code == 202
    env.wait_idle()
    job = env.app.queue.get(body["id"])
    assert job["status"] == "failed" and job["exit_code"] == 3
    assert job["error"] == "download: boom"
    assert len(env.notes) == 1 and env.notes[0][0] == "Reel guide failed" and env.notes[0][2] == ""


@pytest.mark.parametrize("raw,expected", [
    ("Check this out! https://www.instagram.com/reel/XYZ789/?igsh=MTc4 so cool.",
     "https://www.instagram.com/reel/XYZ789/"),
    ("watch (https://youtu.be/dQw4w9WgXcQ?si=abcdef)", "https://youtu.be/dQw4w9WgXcQ"),
    ("https://example.com/a then https://m.youtube.com/watch?v=abc&utm_campaign=x",
     "https://www.youtube.com/watch?v=abc"),
    ("vm.tiktok.com/ZMabc/", "https://vm.tiktok.com/ZMabc/"),
])
def test_extract_from_caption_text(raw, expected):
    assert server.extract_url(raw.encode(), "text/plain") == expected


def test_extract_from_form_and_json_variants():
    form = b"url=https%3A%2F%2Fwww.instagram.com%2Freel%2FQQQ%2F%3Figsh%3Dzz"
    assert server.extract_url(form, "application/x-www-form-urlencoded") == "https://www.instagram.com/reel/QQQ/"
    assert server.extract_url(form, "") == "https://www.instagram.com/reel/QQQ/"
    cap = json.dumps({"url": "Look at this https://www.instagram.com/p/PPP/ wow"}).encode()
    assert server.extract_url(cap, "application/json") == "https://www.instagram.com/p/PPP/"
    lst = json.dumps({"url": ["https://www.tiktok.com/@x/video/9"]}).encode()
    assert server.extract_url(lst, "application/json") == "https://www.tiktok.com/@x/video/9"
    assert server.extract_url(b"https://evil.com/?u=https://instagram.com.evil.com/x", "text/plain") is None


def test_post_text_and_form_bodies(env):
    code, b1 = env.req("POST", "/reel", "Saw this: https://www.instagram.com/reel/T1/ lol", ctype="text/plain")
    assert code == 202
    code, b2 = env.req("POST", "/reel", "url=https%3A%2F%2Fwww.instagram.com%2Freel%2FT2%2F",
                       ctype="application/x-www-form-urlencoded")
    assert code == 202
    env.wait_idle()
    assert env.app.queue.get(b1["id"])["url"] == "https://www.instagram.com/reel/T1/"
    assert env.app.queue.get(b2["id"])["url"] == "https://www.instagram.com/reel/T2/"


def test_dedup(tmp_path):
    e = Env(tmp_path, delay=1.0)
    try:
        _, a = e.req("POST", "/reel", {"url": IG})
        _, b = e.req("POST", "/reel", {"url": IG + "?igsh=other"})  # same after cleaning
        _, c = e.req("POST", "/reel", {"url": "https://www.instagram.com/reel/OTHER/"})
        assert a["id"] == b["id"] and b.get("duplicate") is True
        assert c["id"] != a["id"]
        e.wait_idle()
        _, d = e.req("POST", "/reel", {"url": IG})  # finished -> new job allowed
        assert d["id"] not in (a["id"], c["id"])
        e.wait_idle()
    finally:
        e.app.stop()


def test_requeue_stale_running_on_startup(tmp_path):
    def prepop(env):
        q = server.Queue(env.db)
        jid, _ = q.enqueue("https://www.instagram.com/reel/STALE/")
        conn = sqlite3.connect(env.db)
        with conn:
            conn.execute("UPDATE jobs SET status='running', started=1 WHERE id=?", (jid,))
        conn.close()
        env.stale_id = jid

    e = Env(tmp_path, prepopulate=prepop)
    try:
        e.wait_idle()
        job = e.app.queue.get(e.stale_id)
        assert job["status"] == "done"
        assert [ev["url"] for ev in e.events() if ev["event"] == "start"] == ["https://www.instagram.com/reel/STALE/"]
    finally:
        e.app.stop()


def test_one_at_a_time_in_order(tmp_path):
    e = Env(tmp_path, delay=0.3)
    try:
        urls = [f"https://www.instagram.com/reel/ORD{i}/" for i in range(3)]
        for u in urls:
            assert e.req("POST", "/reel", {"url": u})[0] == 202
        e.wait_idle()
        ev = e.events()
        assert [x["url"] for x in ev if x["event"] == "start"] == urls
        # strictly sequential: start, end, start, end, ...
        assert [x["event"] for x in ev] == ["start", "end"] * 3
        for i in range(0, len(ev) - 2, 2):
            assert ev[i + 2]["t"] >= ev[i + 1]["t"]
    finally:
        e.app.stop()


def test_health_no_key_no_urls(tmp_path):
    e = Env(tmp_path, delay=1.0)
    try:
        e.req("POST", "/reel", {"url": "https://www.instagram.com/reel/SECRETCODE/"})
        e.req("POST", "/reel", {"url": "https://www.instagram.com/reel/SECRETCODE2/"})
        time.sleep(0.3)
        r = urllib.request.urlopen(e.base + "/health", timeout=5)
        raw = r.read().decode()
        h = json.loads(raw)
        assert h["ok"] is True and h["queued"] == 1 and h["running"]["id"] >= 1
        assert "instagram" not in raw and "SECRETCODE" not in raw and "http" not in raw
        e.wait_idle()
    finally:
        e.app.stop()


# ---------------------------------------------------------------- review fixes

GRANDCHILD_WORKER = textwrap.dedent("""
    import os, signal, subprocess, sys, time
    log = sys.argv[1]
    if os.environ.get("IGNORE_TERM"):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    gc = subprocess.Popen([sys.executable, "-c",
                           "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"])
    with open(log, "w") as f:
        f.write(f"{os.getpid()} {gc.pid}\\n")
    time.sleep(120)
""")


def _gone(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(") ", 1)[1][0] == "Z"  # zombie awaiting reaping == dead
    except FileNotFoundError:
        return True


@pytest.mark.parametrize("ignore_term", [False, True])
def test_timeout_kills_whole_process_group(tmp_path, monkeypatch, ignore_term):
    if ignore_term:
        monkeypatch.setenv("IGNORE_TERM", "1")  # forces the SIGKILL escalation path
    e = Env(tmp_path, worker_src=GRANDCHILD_WORKER, job_timeout=1.0, kill_grace=0.5)
    try:
        code, body = e.req("POST", "/reel", {"url": IG})
        assert code == 202
        e.wait_idle(timeout=20)
        job = e.app.queue.get(body["id"])
        assert job["status"] == "failed" and job["error"].startswith("timeout after")
        pids = [int(x) for x in e.log.read_text().split()]
        assert len(pids) == 2
        end = time.time() + 5
        while time.time() < end and not all(_gone(p) for p in pids):
            time.sleep(0.05)
        assert all(_gone(p) for p in pids), "worker or grandchild survived the timeout"
    finally:
        e.app.stop()


def test_job_timeout_exceeds_stage_timeouts():
    assert server.JOB_TIMEOUT >= 4560 + 300


def _raw(port, data, timeout=5):
    import socket
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall(data)
    s.shutdown(socket.SHUT_WR)  # EOF: a truncated body must not wait for the server timeout
    chunks = []
    try:
        while True:
            b = s.recv(65536)
            if not b:
                break
            chunks.append(b)
    finally:
        s.close()
    return b"".join(chunks)


def _status(resp: bytes) -> int:
    return int(resp.split(b" ", 2)[1])


def test_slowloris_capped_and_idle_closed(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(server.Handler, "timeout", 1.0)
    e = Env(tmp_path, max_connections=8)
    socks = []
    try:
        assert server.Handler.timeout == 1.0
        # 6 half-sent requests: below the cap, /health must still answer.
        for _ in range(6):
            s = socket.create_connection(("127.0.0.1", e.app.port), timeout=5)
            s.sendall(b"POST /reel HTTP/1.1\r\nHost: x\r\n")  # never finishes headers
            socks.append(s)
        time.sleep(0.2)
        assert urllib.request.urlopen(e.base + "/health", timeout=5).status == 200
        # Fill the remaining slots; extra connections are refused fast with 503, not queued.
        for _ in range(2):
            s = socket.create_connection(("127.0.0.1", e.app.port), timeout=5)
            s.sendall(b"GET /health HTTP/1.1\r\n")
            socks.append(s)
        time.sleep(0.2)
        t0 = time.time()
        resp = _raw(e.app.port, b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
        assert _status(resp) == 503 and time.time() - t0 < 1.0
        # Idle connections are closed by the server once the socket timeout passes.
        for s in socks:
            s.settimeout(5)
            assert s.recv(1024) == b""  # EOF from server (no response for a timed-out request)
        time.sleep(0.2)
        assert urllib.request.urlopen(e.base + "/health", timeout=5).status == 200
    finally:
        for s in socks:
            s.close()
        e.app.stop()


def test_default_handler_timeout_and_cap():
    assert server.Handler.timeout == 10
    assert server.MAX_CONNECTIONS == 16


def _post_raw(e, extra_headers: bytes, body: bytes) -> int:
    head = (b"POST /reel HTTP/1.1\r\nHost: x\r\nContent-Type: text/plain\r\nConnection: close\r\n"
            b"X-Reel-Key: " + e.key.encode() + b"\r\n" + extra_headers + b"\r\n")
    return _status(_raw(e.app.port, head + body))


def test_chunked_and_length_validation(env):
    te = b"Transfer-Encoding: chunked\r\n"
    good = b"https://www.instagram.com/reel/CHUNK1/"
    assert _post_raw(env, te, b"%x\r\n%s\r\n0\r\n\r\n" % (len(good), good)) == 202
    for bad in (b"-5\r\nabc\r\n0\r\n\r\n", b"+5\r\nabcde\r\n0\r\n\r\n", b"0x5\r\nabcde\r\n0\r\n\r\n",
                b"zz\r\n", b"5\r\nab"):
        assert _post_raw(env, te, bad) == 400, bad
    # total over the limit across several chunks -> 413
    piece = b"a" * 4096
    many = b"".join(b"1000\r\n" + piece + b"\r\n" for _ in range(5)) + b"0\r\n\r\n"
    assert _post_raw(env, te, many) == 413
    assert _post_raw(env, te, b"FFFFFFFF\r\n") == 413
    for cl in (b"-1", b"+5", b"abc", b"1e3"):
        assert _post_raw(env, b"Content-Length: " + cl + b"\r\n", b"xxxxx") == 400, cl
    assert _post_raw(env, b"Content-Length: %d\r\n" % (server.MAX_BODY + 1), b"x") == 413
    # server still healthy
    assert urllib.request.urlopen(env.base + "/health", timeout=5).status == 200


def test_deep_json_is_400_not_crash(env):
    for body in (b"[" * 15000, b"[" * 7000 + b"]" * 7000):
        assert env.req("POST", "/reel", body)[0] == 400
    nested = b"[" * 5000 + b'"https://www.instagram.com/reel/DEEP1/"' + b"]" * 5000
    code, _ = env.req("POST", "/reel", nested)
    assert code in (202, 400)  # caption fallback may still find it; must never 500 or hang
    assert server.extract_url(b"[" * 15000, "application/json") is None
    assert urllib.request.urlopen(env.base + "/health", timeout=5).status == 200


@pytest.mark.parametrize("url", [
    "https://l.instagram.com/?u=http://127.0.0.1",
    "https://l.instagram.com/?u=https%3A%2F%2Fevil.com&e=x",
    "https://www.youtube.com/redirect?q=https://evil.com",
    "https://youtube.com/redirect?q=https%3A%2F%2Fwww.instagram.com%2Freel%2FX%2F",
    "https://instagram.com.evil.com/reel/ABC/",
    "https://evil.com/?u=instagram.com",
    "https://evil.com/?u=instagram.com/reel/ABC/",
    "https://evil.com/?u=https://www.instagram.com/reel/ABC/",
    "https://user@www.instagram.com/reel/ABC/",
    "https://evil.com@www.instagram.com/reel/ABC/",
    "https://www.instagram.com@evil.com/reel/ABC/",
    "http://www.instagram.com/reel/ABC/",
    "ftp://www.instagram.com/reel/ABC/",
    "javascript://www.instagram.com/reel/ABC/",
    "https://www.instagram.com/",
    "https://www.instagram.com/someuser/",
    "https://www.youtube.com/watch",
    "https://www.youtube.com/results?search_query=x",
    "https://www.tiktok.com/@someone",
    "https://www.instagram.com:8443/reel/ABC/",
    "https://api.instagram.com/reel/ABC/",
])
def test_open_redirect_and_bad_urls_400(env, url):
    assert server.extract_url(url.encode(), "text/plain") is None
    assert env.req("POST", "/reel", {"url": url})[0] == 400
    assert env.req("POST", "/reel", f"look {url} wow", ctype="text/plain")[0] == 400


@pytest.mark.parametrize("url,expected", [
    ("https://www.instagram.com/reel/ABC123/", "https://www.instagram.com/reel/ABC123/"),
    ("https://instagram.com/p/ABC123/?igsh=x", "https://www.instagram.com/p/ABC123/"),
    ("https://m.instagram.com/reels/ABC123/", "https://www.instagram.com/reels/ABC123/"),
    ("https://www.tiktok.com/@some.one/video/7234567890123456789?_r=1",
     "https://www.tiktok.com/@some.one/video/7234567890123456789"),
    ("https://vm.tiktok.com/ZMabc123/", "https://vm.tiktok.com/ZMabc123/"),
    ("https://vt.tiktok.com/ZSabc123/", "https://vt.tiktok.com/ZSabc123/"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "https://www.youtube.com/shorts/dQw4w9WgXcQ"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ&si=z", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"),
])
def test_allowed_video_urls(url, expected):
    assert server.extract_url(url.encode(), "text/plain") == expected
    assert server.extract_url(f"so good: {url} !!".encode(), "text/plain") == expected


def test_allowed_url_fails_closed_without_reel_guide(monkeypatch):
    import reel_guide
    monkeypatch.delattr(reel_guide, "allowed_url")
    assert server.extract_url(IG.encode(), "text/plain") is None


def test_unbindable_secondary_address_does_not_block(tmp_path):
    e = Env(tmp_path, start=False)
    e.app.binds = ["127.0.0.1", "192.0.2.123"]  # TEST-NET, never local
    e.app.retry_seconds = 0.2
    try:
        e.app.start()
        e.base = f"http://127.0.0.1:{e.app.port}"
        assert urllib.request.urlopen(e.base + "/health", timeout=5).status == 200
        assert len(e.app.servers) == 1
    finally:
        e.app.stop()
