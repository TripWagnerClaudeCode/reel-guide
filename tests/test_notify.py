"""Unit tests for notify.py. No network."""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notify  # noqa: E402




def test_disabled_without_topic(monkeypatch):
    monkeypatch.delenv("REEL_GUIDE_NTFY_TOPIC", raising=False)
    called = []
    monkeypatch.setattr(notify.urllib.request, "urlopen", lambda *a, **k: called.append(a))
    assert notify.send("t", "b", "/p") is False
    assert called == []


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_send_posts_json(monkeypatch):
    monkeypatch.setenv("REEL_GUIDE_NTFY_TOPIC", "my-topic")
    monkeypatch.setenv("REEL_GUIDE_NTFY_SERVER", "https://ntfy.example.org/")
    monkeypatch.setenv("REEL_GUIDE_NTFY_TOKEN", "tk")
    monkeypatch.delenv("REEL_GUIDE_QUIET_HOURS", raising=False)
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["data"], seen["headers"] = req.full_url, req.data, dict(req.headers)
        return _Resp()

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    assert notify.send("Title — x", "Verdict", "/g.md") is True
    assert seen["url"] == "https://ntfy.example.org/"
    body = json.loads(seen["data"])
    assert body["topic"] == "my-topic" and body["title"] == "Title — x"
    assert body["message"] == "Verdict\n/g.md" and "delay" not in body
    assert seen["headers"]["Authorization"] == "Bearer tk"


def test_send_never_raises(monkeypatch):
    monkeypatch.setenv("REEL_GUIDE_NTFY_TOPIC", "t")
    monkeypatch.delenv("REEL_GUIDE_NTFY_SERVER", raising=False)

    def boom(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)
    assert notify.send("t", "b") is False


def test_rejects_non_http_server(monkeypatch):
    monkeypatch.setenv("REEL_GUIDE_NTFY_TOPIC", "t")
    monkeypatch.setenv("REEL_GUIDE_NTFY_SERVER", "file:///etc/passwd")
    assert notify.send("t", "b") is False


def test_quiet_hours_wrapping_midnight():
    now = dt.datetime(2026, 1, 5, 23, 30)  # naive = local time
    until = notify.quiet_until(now, "23-8")
    assert until is not None
    assert until.astimezone().replace(tzinfo=None) == dt.datetime(2026, 1, 6, 8, 0)
    early = notify.quiet_until(dt.datetime(2026, 1, 6, 3, 0), "23-8")
    assert early.astimezone().replace(tzinfo=None) == dt.datetime(2026, 1, 6, 8, 0)
    assert notify.quiet_until(dt.datetime(2026, 1, 5, 12, 0), "23-8") is None


def test_quiet_hours_same_day_window():
    until = notify.quiet_until(dt.datetime(2026, 1, 5, 13, 0), "12-14")
    assert until.astimezone().replace(tzinfo=None) == dt.datetime(2026, 1, 5, 14, 0)


def test_quiet_hours_bad_spec():
    now = dt.datetime(2026, 1, 5, 23, 30)
    for spec in ("", "nope", "25-3", "8-8"):
        assert notify.quiet_until(now, spec) is None


def test_payload_has_delay_in_quiet_hours():
    now = dt.datetime(2026, 1, 5, 2, 0).astimezone()
    p = notify.build_payload("t", "b", "", topic="x", now=now, quiet="23-8")
    assert int(p["delay"]) > now.timestamp()
