"""Optional phone push through ntfy (https://ntfy.sh or a self-hosted ntfy server).

Stdlib only. send() never raises: on any failure it logs one line to stderr and returns False.
It does nothing (returns False) unless REEL_GUIDE_NTFY_TOPIC is set.

Settings (environment variables, or KEY=VALUE lines in ~/.config/reel-guide/env):
  REEL_GUIDE_NTFY_TOPIC        topic name. On the public ntfy.sh anyone who knows the name can read
                               it, so use a long random one (e.g. reel-guide-<32 random chars>).
  REEL_GUIDE_NTFY_SERVER       server base URL (default https://ntfy.sh)
  REEL_GUIDE_NTFY_TOKEN        optional access token (self-hosted servers with auth)
  REEL_GUIDE_QUIET_HOURS       optional "23-8": pushes in that window are held by ntfy until the
                               end hour (local time). Needs a server with a message cache
                               (ntfy.sh has one).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
import urllib.error
import urllib.request

TIMEOUT = 10.0
DEFAULT_SERVER = "https://ntfy.sh"
TAGS = ["clapper"]


def _log(msg: str) -> None:
    try:
        print(f"notify: {msg}", file=sys.stderr)
    except Exception:
        pass


def quiet_until(now: _dt.datetime, spec: str) -> _dt.datetime | None:
    """If `now` falls inside quiet hours "FROM-UNTIL" (24h clock, may wrap midnight), return the
    next UNTIL:00 as an aware datetime; otherwise None. A bad spec means no quiet hours."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*-\s*(\d{1,2})\s*", spec or "")
    if not m:
        return None
    start, end = int(m.group(1)), int(m.group(2))
    if not (0 <= start <= 23 and 0 <= end <= 23) or start == end:
        return None
    # Work in naive local wall-clock time, then let astimezone() pick the right UTC offset for
    # the target (so a DST change overnight is honored).
    local = now.astimezone().replace(tzinfo=None) if now.tzinfo else now
    h = local.hour
    inside = (start <= h < end) if start < end else (h >= start or h < end)
    if not inside:
        return None
    target = local.replace(hour=end, minute=0, second=0, microsecond=0)
    if target <= local:
        target += _dt.timedelta(days=1)
    return target.astimezone()


def build_payload(title: str, body: str, guide_path: str, *, topic: str,
                  now: _dt.datetime | None = None, quiet: str = "") -> dict:
    msg = body.strip() or "Build guide ready"
    if guide_path:
        msg += f"\n{guide_path}"
    payload = {"topic": topic, "title": title[:200], "message": msg[:3500],
               "tags": TAGS, "priority": 3}
    until = quiet_until(now or _dt.datetime.now().astimezone(), quiet)
    if until is not None:
        payload["delay"] = str(int(until.timestamp()))
    return payload


def send(title: str, body: str, guide_path: str = "") -> bool:
    topic = os.environ.get("REEL_GUIDE_NTFY_TOPIC", "").strip()
    if not topic:
        return False
    server = (os.environ.get("REEL_GUIDE_NTFY_SERVER", "").strip() or DEFAULT_SERVER).rstrip("/")
    if not server.startswith(("https://", "http://")):
        _log(f"REEL_GUIDE_NTFY_SERVER must start with https:// (got {server!r})")
        return False
    token = os.environ.get("REEL_GUIDE_NTFY_TOKEN", "").strip()
    try:
        payload = build_payload(title, body, guide_path, topic=topic,
                                quiet=os.environ.get("REEL_GUIDE_QUIET_HOURS", ""))
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(server + "/", data=json.dumps(payload).encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            if 200 <= r.status < 300:
                return True
            _log(f"ntfy returned HTTP {r.status}")
    except urllib.error.HTTPError as e:
        _log(f"ntfy returned HTTP {e.code}")
    except Exception as e:  # noqa: BLE001 - never let a push break a job
        _log(f"push failed: {type(e).__name__}: {e}")
    return False


if __name__ == "__main__":
    # Quick check: python notify.py  -> sends a test push
    import reel_guide  # noqa: F401  (loads ~/.config/reel-guide/env)
    ok = send("reel-guide test", "If you see this, pushes work.", "")
    print("sent" if ok else "not sent (is REEL_GUIDE_NTFY_TOPIC set? see stderr)")
    sys.exit(0 if ok else 1)
