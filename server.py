#!/usr/bin/env python3
"""reel-guide v1: tiny share-sheet endpoint + single-worker job queue.

POST /reel   (X-Reel-Key required)  body: JSON {"url": ...}, form-encoded, or plain text
             containing the link -> 202 {"status": "queued", "id": N}
GET  /health (no key)               -> {"ok": true, "queued": N, "running": {...} | null}
GET  /jobs   (X-Reel-Key required)  -> last 20 jobs

Stdlib only. Binds 127.0.0.1 by default. Add a private address (for example your Tailscale IP)
with --bind or REEL_GUIDE_BIND=127.0.0.1,100.x.y.z. The first address must bind; any others
that are not up yet (VPN still connecting) are retried every 30 s.
"""
from __future__ import annotations

import argparse
import errno
import hmac
import json
import os
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent
KEY_HEADER = "X-Reel-Key"
DEFAULT_PORT = 8765
DEFAULT_BINDS = ("127.0.0.1",)
DEFAULT_DB = ROOT / "queue.db"
DEFAULT_KEY = Path.home() / ".config" / "reel-guide" / "key"
DEFAULT_WORKER_CMD = [sys.executable, str(ROOT / "reel_guide.py")]
# Must exceed the sum of reel_guide.py's per-stage timeouts so a slow-but-legal run is never cut
# off: download 600 + info 60 + ffmpeg 300 + transcribe 900 + ffprobe 60 + 12 frames x 120
# + claude 1200 = 4560 s, plus a 5-minute margin.
JOB_TIMEOUT = 4560 + 300
KILL_GRACE = 10          # seconds between SIGTERM and SIGKILL of the job's process group
MAX_BODY = 16 * 1024
MAX_CONNECTIONS = 16     # concurrent HTTP connections across all listeners
SOCKET_TIMEOUT = 10      # per-socket-operation timeout for HTTP connections
BIND_RETRY_SECONDS = 30
MAX_QUEUED = 20          # waiting jobs; more -> 429 (each job is one claude run on your plan)
# Exact-host + video-path allowlist lives in reel_guide.allowed_url (l.instagram.com and
# youtube.com/redirect are open redirectors, so no wildcard subdomains).
# Characters allowed immediately before a URL in free text. Anything else (e.g. "=", "/", "@",
# "%") means the match is embedded inside some other URL (?u=..., userinfo, ...) -> ignored.
_URL_PREFIX_OK = set("([{<\"'“‘«:,;|>*")
TRACKING_PARAMS = {"igsh", "igshid", "fbclid", "gclid", "si", "feature", "_r", "_t",
                   "is_from_webapp", "sender_device", "share_app_id", "share_link_id"}

_URL_RE = re.compile(
    r"(?:https?://)?(?:[a-z0-9-]+\.)*(?:instagram\.com|tiktok\.com|youtube\.com|youtu\.be)"
    r"(?![a-z0-9.-])(?:[/?#][^\s\"'<>]*)?",
    re.IGNORECASE,
)
_TRAILING = ".,;:!?)]}'\"»”’"


def log(msg: str) -> None:
    print(f"[reel-guide-server] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- URL handling
def allowed_url(url: str) -> str | None:
    """reel_guide.allowed_url is the single source of truth (exact hosts + a video path; returns
    the normalized URL). If it can't be imported, fail closed: the job would fail anyway."""
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import reel_guide  # lazy: its heavy deps are imported lazily too
        res = reel_guide.allowed_url(url)
    except Exception as e:
        log(f"reel_guide.allowed_url unavailable/failed: {type(e).__name__}: {e}")
        return None
    return res if isinstance(res, str) and res else None


def clean_url(raw: str) -> str | None:
    """Normalize one candidate URL; return None if it is not on the allowlist."""
    raw = raw.strip().rstrip(_TRAILING)
    if not raw:
        return None
    m = re.match(r"^([a-z][a-z0-9+.-]*):", raw, re.IGNORECASE)
    if m and not raw[m.end():].startswith("//") and "." in m.group(1):
        m = None  # "host.tld:..." rather than a scheme
    if m:
        if m.group(1).lower() != "https":
            return None  # http, ftp, javascript, ... -> rejected
    else:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
        parts.port  # noqa: B018  (raises ValueError on a bad port)
    except ValueError:
        return None
    if not parts.hostname or parts.username is not None or "@" in parts.netloc:
        return None
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")]
    path = parts.path or "/"
    url = urlunsplit(("https", parts.netloc.lower(), path, urlencode(query), ""))
    return allowed_url(url)


def _candidate_texts(body: bytes, content_type: str) -> list[str]:
    text = body.decode("utf-8", errors="replace")
    ctype = (content_type or "").split(";")[0].strip().lower()
    out: list[str] = []

    def walk(obj):
        if isinstance(obj, str):
            out.append(obj)
        elif isinstance(obj, dict):
            for k in sorted(obj, key=lambda k: k != "url"):  # "url" first
                walk(obj[k])
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    stripped = text.strip()
    if ctype == "application/json" or stripped[:1] in ("{", "["):
        try:
            walk(json.loads(stripped))
        except (ValueError, RecursionError, MemoryError, TypeError):
            pass  # not usable JSON (incl. pathologically deep nesting) -> text fallback
    # Form-decode only real forms, or text that starts like "name=..." — never a bare URL, whose
    # percent-encoded ?u=/?q= values must not be unwrapped into standalone candidates.
    if ctype == "application/x-www-form-urlencoded" or (
            not out and " " not in stripped and re.match(r"[A-Za-z_][A-Za-z0-9_.-]{0,40}=", stripped)):
        pairs = parse_qsl(stripped, keep_blank_values=False)
        pairs.sort(key=lambda kv: kv[0] != "url")
        out.extend(v for _, v in pairs)
    out.append(text)  # plain text / caption fallback
    return out


def extract_url(body: bytes, content_type: str = "") -> str | None:
    """Return the first allowed URL found in the request body (JSON, form or text)."""
    for chunk in _candidate_texts(body, content_type):
        for m in _URL_RE.finditer(chunk):
            # The URL must start a token: not "notinstagram.com", not "...?u=instagram.com/...",
            # not "evil@instagram.com", not "ftp://instagram.com".
            start = m.start()
            if start > 0:
                prev = chunk[start - 1]
                if not (prev.isspace() or prev in _URL_PREFIX_OK):
                    continue
            url = clean_url(m.group(0))
            if url:
                return url
    return None


# ---------------------------------------------------------------- queue (sqlite)
class QueueFull(Exception):
    pass


class Queue:
    def __init__(self, db_path: Path, max_queued: int = MAX_QUEUED):
        self.db_path = Path(db_path)
        self.max_queued = max_queued
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                status TEXT NOT NULL,          -- queued | running | done | failed
                created REAL NOT NULL,
                started REAL, finished REAL,
                exit_code INTEGER,
                guide TEXT, verdict TEXT, error TEXT,
                output_tail TEXT)""")
            c.execute("CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, id)")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _exec(self, sql: str, args=()):
        conn = self._conn()
        try:
            with conn:
                return conn.execute(sql, args).fetchall()
        finally:
            conn.close()

    def requeue_stale(self) -> int:
        with self.lock:
            rows = self._exec("SELECT id FROM jobs WHERE status='running'")
            self._exec("UPDATE jobs SET status='queued', started=NULL WHERE status='running'")
        return len(rows)

    def enqueue(self, url: str) -> tuple[int, bool]:
        """Return (id, duplicate)."""
        with self.cond:
            rows = self._exec("SELECT id FROM jobs WHERE url=? AND status IN ('queued','running') "
                              "ORDER BY id LIMIT 1", (url,))
            if rows:
                return rows[0]["id"], True
            waiting = self._exec("SELECT COUNT(*) AS n FROM jobs WHERE status='queued'")[0]["n"]
            if waiting >= self.max_queued:
                raise QueueFull(f"{waiting} jobs already queued")
            conn = self._conn()
            try:
                with conn:
                    cur = conn.execute("INSERT INTO jobs(url,status,created) VALUES (?,?,?)",
                                       (url, "queued", time.time()))
                    job_id = cur.lastrowid
            finally:
                conn.close()
            self.cond.notify_all()
            return job_id, False

    def claim(self, stop: threading.Event, wait: float = 5.0):
        """Mark the oldest queued job running and return it, or None if stopping."""
        with self.cond:
            while not stop.is_set():
                rows = self._exec("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1")
                if rows:
                    job = dict(rows[0])
                    self._exec("UPDATE jobs SET status='running', started=? WHERE id=?",
                               (time.time(), job["id"]))
                    return job
                self.cond.wait(wait)
        return None

    def finish(self, job_id: int, *, ok: bool, exit_code, guide, verdict, error, tail):
        with self.lock:
            self._exec("UPDATE jobs SET status=?, finished=?, exit_code=?, guide=?, verdict=?, "
                       "error=?, output_tail=? WHERE id=?",
                       ("done" if ok else "failed", time.time(), exit_code, guide, verdict,
                        error, tail, job_id))

    def health(self) -> dict:
        with self.lock:
            queued = self._exec("SELECT COUNT(*) AS n FROM jobs WHERE status='queued'")[0]["n"]
            run = self._exec("SELECT id, started FROM jobs WHERE status='running' LIMIT 1")
        running = {"id": run[0]["id"], "since": run[0]["started"]} if run else None
        return {"ok": True, "queued": queued, "running": running}

    def recent(self, n: int = 20) -> list[dict]:
        with self.lock:
            rows = self._exec("SELECT id,url,status,created,started,finished,exit_code,guide,verdict,error "
                              "FROM jobs ORDER BY id DESC LIMIT ?", (n,))
        return [dict(r) for r in rows]

    def get(self, job_id: int) -> dict | None:
        with self.lock:
            rows = self._exec("SELECT * FROM jobs WHERE id=?", (job_id,))
        return dict(rows[0]) if rows else None


# ---------------------------------------------------------------- key
def load_or_create_key(path: Path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        key = path.read_text().strip()
        if not key:
            raise SystemExit(f"key file {path} is empty")
        return key
    key = secrets.token_hex(32)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    log(f"created new key file {path}")
    return key


# ---------------------------------------------------------------- notifications
def _default_notify(title: str, body: str, guide_path: str) -> None:
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import notify  # lazy: optional, never fatal
        notify.send(title, body, guide_path)
    except Exception as e:  # never let notification break the worker
        log(f"failure notify unavailable: {e!r}")


# ---------------------------------------------------------------- app
class App:
    def __init__(self, *, db_path=DEFAULT_DB, key_path=DEFAULT_KEY, worker_cmd=None,
                 binds=DEFAULT_BINDS, port=DEFAULT_PORT, job_timeout=JOB_TIMEOUT,
                 notify=_default_notify, cwd=ROOT, retry_seconds=BIND_RETRY_SECONDS,
                 kill_grace=KILL_GRACE, max_connections=MAX_CONNECTIONS):
        self.queue = Queue(db_path)
        self.kill_grace = kill_grace
        self.conn_slots = threading.BoundedSemaphore(max_connections)
        self.key = load_or_create_key(key_path)
        self.worker_cmd = list(worker_cmd or DEFAULT_WORKER_CMD)
        self.binds = list(binds)
        self.port = port
        self.job_timeout = job_timeout
        self.notify = notify
        self.cwd = str(cwd)
        self.retry_seconds = retry_seconds
        self.stop_event = threading.Event()
        self.servers: list[ThreadingHTTPServer] = []
        self.threads: list[threading.Thread] = []

    # -- lifecycle
    def start(self) -> None:
        n = self.queue.requeue_stale()
        if n:
            log(f"re-queued {n} job(s) left running")
        primary, *others = self.binds
        self._bind(primary)  # must succeed
        for addr in others:
            if not self._try_bind(addr):
                t = threading.Thread(target=self._retry_bind, args=(addr,), daemon=True)
                t.start()
                self.threads.append(t)
        w = threading.Thread(target=self._worker, name="worker", daemon=True)
        w.start()
        self.threads.append(w)

    def stop(self) -> None:
        self.stop_event.set()
        with self.queue.cond:
            self.queue.cond.notify_all()
        for s in self.servers:
            s.shutdown()
            s.server_close()

    def _bind(self, addr: str) -> ThreadingHTTPServer:
        srv = Server((addr, self.port), Handler)
        srv.app = self
        if self.port == 0:  # tests: reuse the ephemeral port for later binds
            self.port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, name=f"http-{addr}", daemon=True)
        t.start()
        self.servers.append(srv)
        self.threads.append(t)
        log(f"listening on http://{addr}:{srv.server_address[1]}")
        return srv

    def _try_bind(self, addr: str) -> bool:
        try:
            self._bind(addr)
            return True
        except OSError as e:
            if e.errno not in (errno.EADDRNOTAVAIL, errno.EADDRINUSE, errno.ENETUNREACH):
                log(f"bind {addr}:{self.port} failed: {e}")
            else:
                log(f"bind {addr}:{self.port} not possible yet ({e.strerror}); retrying every {self.retry_seconds}s")
            return False

    def _retry_bind(self, addr: str) -> None:
        while not self.stop_event.wait(self.retry_seconds):
            if self._try_bind(addr):
                return

    # -- worker
    def _worker(self) -> None:
        while not self.stop_event.is_set():
            job = self.queue.claim(self.stop_event)
            if job is None:
                return
            try:
                self._run_job(job)
            except Exception as e:  # keep the worker alive no matter what
                log(f"job {job['id']} crashed in worker: {e!r}")
                self.queue.finish(job["id"], ok=False, exit_code=None, guide=None, verdict=None,
                                  error=f"worker: {e!r}", tail=None)

    def _kill_group(self, proc: subprocess.Popen) -> tuple[str, str]:
        """SIGTERM the job's whole process group, SIGKILL after kill_grace s; return (out, err)."""
        pgid = proc.pid  # start_new_session=True -> the child leads its own group
        out = err = ""
        for sig, wait in ((signal.SIGTERM, self.kill_grace), (signal.SIGKILL, 5)):
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                pass
            try:
                o, e = proc.communicate(timeout=wait)
                out, err = out + (o or ""), err + (e or "")
            except subprocess.TimeoutExpired:
                continue  # leader or a grandchild still holds the pipes
            # Leader is gone; make sure no grandchild in the group survives it.
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return out, err
        # Pipes still held by something that escaped the group; stop waiting on it.
        for f in (proc.stdout, proc.stderr):
            try:
                f.close()
            except Exception:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return out, err

    def _run_job(self, job: dict) -> None:
        cmd = self.worker_cmd + [job["url"]]
        log(f"job {job['id']} start: {job['url']}")
        env = dict(os.environ)
        local_bin = str(Path.home() / ".local" / "bin")
        if not env.get("PATH", "").startswith(local_bin):
            env["PATH"] = local_bin + os.pathsep + env.get("PATH", "")
        exit_code = None
        timeout = False
        try:
            # Own session/process group so a timeout kills yt-dlp/ffmpeg/claude grandchildren too.
            proc = subprocess.Popen(cmd, cwd=self.cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    errors="replace", start_new_session=True)
        except OSError as e:
            proc, out, err = None, "", f"ERROR: spawn: {e}"
        if proc is not None:
            try:
                out, err = proc.communicate(timeout=self.job_timeout)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                timeout = True
                out, err = self._kill_group(proc)

        guide = verdict = error = None
        for line in (out + "\n" + err).splitlines():
            s = line.strip()
            if s.startswith("GUIDE:"):
                guide = s[6:].strip()
            elif s.startswith("VERDICT:"):
                verdict = s[8:].strip()
            elif s.startswith("ERROR:"):
                error = s[6:].strip()
        ok = (not timeout) and exit_code == 0
        if timeout:
            error = f"timeout after {self.job_timeout}s" + (f" ({error})" if error else "")
        elif not ok and not error:
            last = [l for l in err.splitlines() if l.strip()] or [l for l in out.splitlines() if l.strip()]
            error = (last[-1].strip()[:300] if last else f"exit {exit_code}")
        tail = "\n".join((out.rstrip().splitlines() + err.rstrip().splitlines())[-30:])[-4000:]
        self.queue.finish(job["id"], ok=ok, exit_code=exit_code, guide=guide, verdict=verdict,
                          error=error, tail=tail)
        if ok:
            log(f"job {job['id']} done: {guide}")
        else:
            log(f"job {job['id']} failed: {error}")
            # reel_guide.py sends the success push itself; we only report failures.
            shown = (error or "").replace(str(Path.home()), "~")  # no username in the push
            self.notify("Reel guide failed", f"#{job['id']}: {shown}"[:200], "")


class Server(ThreadingHTTPServer):
    """Threading server with a hard cap on concurrent connections (shared via app.conn_slots).

    When full, new connections get an immediate 503 and are closed instead of spawning a thread."""
    daemon_threads = True
    app: "App"

    def process_request(self, request, client_address):
        if not self.app.conn_slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\n"
                                b"Content-Length: 18\r\nConnection: close\r\n\r\n{\"error\":\"busy\"}\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.app.conn_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.app.conn_slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "reel-guide/1"
    sys_version = ""
    timeout = SOCKET_TIMEOUT  # idle/slow clients are dropped (applies to every socket op)

    @property
    def app(self) -> App:
        return self.server.app

    def log_message(self, fmt, *args):  # quieter, no headers/keys
        log(f"{self.client_address[0]} {fmt % args}")

    def _send(self, code: int, obj) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _authed(self) -> bool:
        got = self.headers.get(KEY_HEADER, "").strip()
        return hmac.compare_digest(got.encode(), self.app.key.encode())

    def _path(self) -> str:
        return urlsplit(self.path).path.rstrip("/") or "/"

    def _read_body(self) -> bytes | None:
        """Read at most MAX_BODY bytes; return None (after replying 413) if too big."""
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            self.close_connection = True  # never reuse a connection after a chunked body
            buf = b""
            while True:
                size_hex = self.rfile.readline(64).split(b";")[0].strip()
                if not re.fullmatch(rb"[0-9A-Fa-f]{1,8}", size_hex):  # rejects "-5", "+5", "0x5", ""
                    self._send(400, {"error": "bad chunked body"})
                    return None
                size = int(size_hex, 16)
                if size == 0:
                    self.rfile.readline(64)
                    return buf
                if len(buf) + size > MAX_BODY:
                    self._send(413, {"error": "body too large"})
                    return None
                data = self.rfile.read(size)
                if len(data) != size or self.rfile.readline(64).strip():
                    self._send(400, {"error": "bad chunked body"})
                    return None
                buf += data
        raw_len = self.headers.get("Content-Length", "0").strip()
        if not re.fullmatch(r"\d{1,12}", raw_len):  # rejects "-1", "+5", " ", "1_0"
            self.close_connection = True
            self._send(400, {"error": "bad Content-Length"})
            return None
        length = int(raw_len)
        if length > MAX_BODY:
            self.close_connection = True
            self._send(413, {"error": "body too large"})
            return None
        data = self.rfile.read(length) if length else b""
        if len(data) != length:
            self.close_connection = True
            self._send(400, {"error": "truncated body"})
            return None
        return data

    def do_GET(self):
        path = self._path()
        if path == "/health":
            return self._send(200, self.app.queue.health())
        if path == "/jobs":
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            return self._send(200, {"jobs": self.app.queue.recent(20)})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if self._path() != "/reel":
            return self._send(404, {"error": "not found"})
        if not self._authed():
            self.close_connection = True
            return self._send(401, {"error": "unauthorized"})
        body = self._read_body()
        if body is None:
            return
        try:
            url = extract_url(body, self.headers.get("Content-Type", ""))
        except Exception as e:  # any parse failure is the client's problem, never a 500/crash
            log(f"extract_url failed: {type(e).__name__}")
            url = None
        if not url:
            return self._send(400, {"error": "no instagram/tiktok/youtube URL found"})
        try:
            job_id, dup = self.app.queue.enqueue(url)
        except QueueFull:
            return self._send(429, {"error": f"queue full ({self.app.queue.max_queued} waiting)"})
        log(f"{'dedup' if dup else 'queued'} job {job_id}")
        resp = {"status": "queued", "id": job_id}
        if dup:
            resp["duplicate"] = True
        return self._send(202, resp)


def _env_binds() -> list[str]:
    return [b.strip() for b in os.environ.get("REEL_GUIDE_BIND", "").split(",") if b.strip()]


def main(argv=None) -> int:
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import reel_guide  # noqa: F401  (loads ~/.config/reel-guide/env into os.environ)
    except Exception as e:
        log(f"could not load reel_guide.py: {e!r}")
    p = argparse.ArgumentParser(description="reel-guide share-sheet server")
    p.add_argument("--port", type=int, default=int(os.environ.get("REEL_GUIDE_PORT") or DEFAULT_PORT))
    p.add_argument("--bind", action="append",
                   help="address to bind (repeatable; first is required). Default 127.0.0.1 "
                        "or REEL_GUIDE_BIND (comma-separated)")
    p.add_argument("--db", type=Path, default=Path(os.environ.get("REEL_GUIDE_DB") or DEFAULT_DB))
    p.add_argument("--key-file", type=Path, default=DEFAULT_KEY)
    a = p.parse_args(argv)
    binds = a.bind or _env_binds() or list(DEFAULT_BINDS)
    for b in binds:
        if b in ("0.0.0.0", "::", ""):
            log(f"WARNING: binding {b!r} exposes the endpoint on every network interface. "
                "Prefer 127.0.0.1 plus a private VPN address (see docs/MOBILE.md).")
    app = App(db_path=a.db, key_path=a.key_file, binds=binds, port=a.port)
    app.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
