"""Unit tests for reel_guide.py. No network, no claude, no real ffmpeg/yt-dlp."""
import datetime as dt
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reel_guide as rg  # noqa: E402

GUIDE = """# Local LLM Notes App — Build Guide
**Source:** https://www.instagram.com/reel/ABC123/ · @someone
**Verdict (one line):** A thin wrapper around Ollama plus a notes UI.

## What it is
Stuff.
"""


# --------------------------------------------------------------------- reel id

@pytest.mark.parametrize("url,expected", [
    ("https://www.instagram.com/reel/C9xYz_Ab-12/", "C9xYz_Ab-12"),
    ("https://instagram.com/reel/C9xYz/?igsh=abc", "C9xYz"),
    ("https://www.instagram.com/reels/DAbc123/", "DAbc123"),
    ("https://www.instagram.com/p/CQq1w2e3r4/", "CQq1w2e3r4"),
    ("https://m.instagram.com/someuser/reel/XyZ987/", "XyZ987"),
    ("https://www.tiktok.com/@user.name/video/7301234567890123456?is_from_webapp=1", "7301234567890123456"),
    ("https://m.tiktok.com/v/7301234567890123456.html", "7301234567890123456"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=xyz", "dQw4w9WgXcQ"),
])
def test_reel_id_platforms(url, expected):
    assert rg.reel_id(url) == expected


@pytest.mark.parametrize("url", [
    "https://vm.tiktok.com/ZMabcdef/",       # short link: no id without resolving
    "https://www.instagram.com/someuser/",   # profile, no code
    "https://www.youtube.com/watch?v=../../etc",  # unsafe id
])
def test_reel_id_fallback_sha1(url):
    assert rg.reel_id(url) == hashlib.sha1(url.encode()).hexdigest()[:12]


def test_reel_id_strips_whitespace():
    assert rg.reel_id("  https://youtu.be/abc_DEF-123 \n") == "abc_DEF-123"


# --------------------------------------------------------------------- allowlist

@pytest.mark.parametrize("url,expected", [
    ("https://www.instagram.com/reel/X/", "https://www.instagram.com/reel/X/"),
    ("https://instagram.com/p/X/", "https://www.instagram.com/p/X/"),
    ("https://m.instagram.com/reel/X/", "https://www.instagram.com/reel/X/"),
    ("https://www.instagram.com/reels/X?igsh=abc", "https://www.instagram.com/reels/X/"),
    ("https://www.instagram.com/tv/X/", "https://www.instagram.com/tv/X/"),
    ("https://www.instagram.com/some.user/reel/X/", "https://www.instagram.com/reel/X/"),
    ("https://www.tiktok.com/@a/video/1", "https://www.tiktok.com/@a/video/1"),
    ("https://m.tiktok.com/@a.b_c/video/123?is_from_webapp=1", "https://www.tiktok.com/@a.b_c/video/123"),
    ("https://tiktok.com/@a/video/1", "https://www.tiktok.com/@a/video/1"),
    ("https://vm.tiktok.com/ZM1/", "https://vm.tiktok.com/ZM1/"),
    ("https://vt.tiktok.com/ZS9abc", "https://vt.tiktok.com/ZS9abc/"),
    ("https://www.youtube.com/shorts/X", "https://www.youtube.com/shorts/X"),
    ("https://m.youtube.com/watch?v=X", "https://www.youtube.com/watch?v=X"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1&t=3", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("https://youtu.be/X", "https://youtu.be/X"),
    ("https://youtu.be/X?si=abc#t=1", "https://youtu.be/X"),
    ("http://youtube.com/shorts/X", "https://www.youtube.com/shorts/X"),
    ("HTTPS://WWW.INSTAGRAM.COM/reel/X/", "https://www.instagram.com/reel/X/"),
    ("  https://youtu.be/X \n", "https://youtu.be/X"),
    ("https://www.youtube.com:443/shorts/X", "https://www.youtube.com/shorts/X"),
])
def test_allowed_urls(url, expected):
    assert rg.allowed_url(url) == expected
    assert rg.is_allowed_url(url)


@pytest.mark.parametrize("url", [
    "https://evil.com/instagram.com/reel/X", "https://instagram.com.evil.com/reel/X",
    "https://notinstagram.com/reel/X", "https://fakeyoutu.be/X", "ftp://youtube.com/x",
    "file:///etc/passwd", "instagram.com/reel/X", "", "javascript:alert(1)",
    "https://user@evil.com/?u=youtube.com",
    # open redirectors / other subdomains
    "https://l.instagram.com/?u=https%3A%2F%2Fevil.com%2F", "https://www.youtube.com/redirect?q=https://evil.com",
    "https://youtube.com/redirect?q=https%3A%2F%2Fevil.com&v=X", "https://music.youtube.com/watch?v=X",
    "https://evil.tiktok.com/@a/video/1", "https://instagram.com./reel/X/",
    # no video path
    "https://www.instagram.com/", "https://www.instagram.com/someuser/", "https://www.instagram.com/reels/",
    "https://www.instagram.com/accounts/login/?next=/reel/X/", "https://www.tiktok.com/@a",
    "https://www.tiktok.com/foryou", "https://www.youtube.com/", "https://www.youtube.com/@chan",
    "https://www.youtube.com/watch?list=PL1", "https://www.youtube.com/watch?v=../../etc",
    "https://www.youtube.com/watch?v=A&v=B", "https://youtu.be/", "https://vm.tiktok.com/",
    "https://www.youtube.com/playlist?list=PL1", "https://www.instagram.com/reel/X/../../x",
    # credentials, odd ports, whitespace inside
    "https://youtube.com@evil.com/shorts/X", "https://a:b@www.youtube.com/shorts/X",
    "https://www.youtube.com:8080/shorts/X", "https://youtu.be/X Y", "https://youtu.be/%2e%2e",
    None, 42,
])
def test_rejected_urls(url):
    assert rg.allowed_url(url) is None
    assert not rg.is_allowed_url(url)


def test_allowlist_module_is_lightweight():
    """server.py imports allowed_url; importing reel_guide must not pull in heavy deps."""
    code = ("import sys; sys.path.insert(0, %r); import reel_guide; "
            "bad = [m for m in ('faster_whisper', 'scenedetect', 'cv2', 'ctranslate2', 'notify') "
            "if m in sys.modules]; print(bad); assert not bad"
            % str(Path(rg.__file__).parent))
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_run_normalizes_url_before_download(fake_env, monkeypatch):
    fr = FakeRun()
    monkeypatch.setattr(subprocess, "run", fr)
    rg.run("https://m.instagram.com/reel/R1/?igsh=zzz", work_root=fake_env / "work",
           out_dir=fake_env / "out", notify=False)
    assert fr.cmds[0][-1] == "https://www.instagram.com/reel/R1/"


def test_run_rejects_bad_url(tmp_path):
    with pytest.raises(rg.StageError) as ei:
        rg.run("https://example.com/x", work_root=tmp_path, out_dir=tmp_path, notify=False)
    assert ei.value.stage == "url"
    assert not any(tmp_path.iterdir())


# --------------------------------------------------------------------- frame sampling

@pytest.mark.parametrize("n", [0, 1, 5, 12])
def test_sample_keeps_all_when_few(n):
    items = [f"f{i}.jpg" for i in range(n)]
    assert rg.sample_evenly(items, 12) == items


@pytest.mark.parametrize("n", [13, 20, 37, 100, 500])
def test_sample_caps_evenly(n):
    items = list(range(n))
    out = rg.sample_evenly(items, 12)
    assert len(out) == 12
    assert out == sorted(set(out))
    assert out[0] == 0 and out[-1] == n - 1
    gaps = [b - a for a, b in zip(out, out[1:])]
    assert max(gaps) - min(gaps) <= 1


def test_frame_times_scenes_and_fallback():
    scenes = [(i * 2.0, i * 2.0 + 2.0) for i in range(30)]
    t = rg.frame_times(scenes, 60.0)
    assert len(t) == 12 and t[0] == 1.0 and t[-1] == 59.0
    # zero cuts (detect returns [] or a single scene) -> 6 evenly spaced
    for no_cuts in ([], [(0.0, 60.0)]):
        t = rg.frame_times(no_cuts, 60.0)
        assert t == [5.0, 15.0, 25.0, 35.0, 45.0, 55.0]
    # few cuts -> scene middles topped up with even samples (>= 6 frames, sorted, no near-dupes)
    t = rg.frame_times([(0.0, 20.0), (20.0, 60.0)], 60.0)
    assert 10.0 in t and 40.0 in t and len(t) >= 6 and t == sorted(t)
    t = rg.frame_times([(0, 1), (1, 2), (2, 3)], 3.0)
    assert t[0] == 0.25 and 0.5 in t and len(t) >= 3


# --------------------------------------------------------------------- title / filename / verdict

def test_parse_title_variants():
    assert rg.parse_title(GUIDE) == "Local LLM Notes App"
    assert rg.parse_title("\n\n# Foo – Build Guide\n") == "Foo"
    assert rg.parse_title("# Foo - Build Guide") == "Foo"
    assert rg.parse_title("# A — B — Build Guide") == "A — B"


@pytest.mark.parametrize("text", ["", "Some preamble\n# Foo — Build Guide", "# Foo", "## Foo — Build Guide",
                                  "# — Build Guide"])
def test_parse_title_invalid(text):
    assert rg.parse_title(text) is None


@pytest.mark.parametrize("title,expected", [
    ("Local LLM Notes App", "Local LLM Notes App"),
    ("AI/ML: Agents?  *Fast*", "AI-ML- Agents- Fast"),
    ('a<b>c|d"e\\f', "a-b-c-d-e-f"),
    ("  ..hidden..  ", "hidden"),
    ("tab\there\nnewline", "tab here newline"),
    ("///", "Untitled"),
    ("", "Untitled"),
])
def test_sanitize_filename(title, expected):
    assert rg.sanitize_filename(title) == expected


def test_sanitize_filename_length():
    out = rg.sanitize_filename("x" * 300)
    assert len(out) == 100


def test_unique_path_collision(tmp_path):
    stem = "2026-11-02 – Foo"
    assert rg.unique_path(tmp_path, stem).name == f"{stem}.md"
    (tmp_path / f"{stem}.md").write_text("one")
    assert rg.unique_path(tmp_path, stem).name == f"{stem} (2).md"
    (tmp_path / f"{stem} (2).md").write_text("two")
    assert rg.unique_path(tmp_path, stem).name == f"{stem} (3).md"
    # identical content is reused rather than duplicated
    assert rg.unique_path(tmp_path, stem, b"two").name == f"{stem} (2).md"


def test_publish(tmp_path):
    g = tmp_path / "guide.md"
    g.write_text(GUIDE, encoding="utf-8")
    out = tmp_path / "out"
    d = dt.date(2026, 11, 2)
    p1, title, verdict = rg.publish(g, out, d)
    assert p1.name == "2026-11-02 – Local LLM Notes App.md"
    assert title == "Local LLM Notes App"
    assert verdict == "A thin wrapper around Ollama plus a notes UI."
    assert p1.read_text(encoding="utf-8") == GUIDE
    assert rg.publish(g, out, d)[0] == p1  # same content: no duplicate
    g.write_text(GUIDE + "\nmore\n", encoding="utf-8")
    assert rg.publish(g, out, d)[0].name == "2026-11-02 – Local LLM Notes App (2).md"
    assert not list(out.glob(".*.tmp"))


@pytest.mark.parametrize("line,expected", [
    ("**Verdict (one line):** A wrapper around X.", "A wrapper around X."),
    ("**Verdict:** Real project.", "Real project."),
    ("**Verdict**: Real project.", "Real project."),
    ("Verdict: plain", "plain"),
    ("- **Verdict (one line):** bullet form", "bullet form"),
])
def test_parse_verdict(line, expected):
    assert rg.parse_verdict(f"# T — Build Guide\n**Source:** x\n{line}\n") == expected


def test_parse_verdict_missing():
    assert rg.parse_verdict("# T — Build Guide\n\n## What it is\nverdicts are hard\n") == ""


# --------------------------------------------------------------------- stage skip logic

@pytest.fixture
def no_subprocess(monkeypatch):
    def boom(*a, **k):
        raise AssertionError(f"subprocess called: {a[0] if a else k}")
    monkeypatch.setattr(subprocess, "run", boom)


def make_done_workdir(wd: Path, guide: str = GUIDE):
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "video.mp4").write_bytes(b"v")
    (wd / "info.json").write_text("{}")
    (wd / "audio.wav").write_bytes(b"a")
    (wd / "transcript.txt").write_text("[  1.2s] hi\n")
    (wd / "frames").mkdir(exist_ok=True)
    (wd / "frames" / "frame_01.jpg").write_bytes(b"j")
    (wd / "guide.md").write_text(guide, encoding="utf-8")


def test_run_all_stages_skipped(tmp_path, no_subprocess, capsys):
    url = "https://www.instagram.com/reel/ABC123/"
    make_done_workdir(tmp_path / "work" / "ABC123")
    res = rg.run(url, work_root=tmp_path / "work", out_dir=tmp_path / "out", notify=False)
    assert res["reel_id"] == "ABC123"
    assert res["title"] == "Local LLM Notes App"
    assert res["verdict"].startswith("A thin wrapper")
    assert Path(res["path"]).read_text(encoding="utf-8") == GUIDE
    assert Path(res["path"]).parent == tmp_path / "out"


def test_notify_called(tmp_path, no_subprocess, monkeypatch):
    calls = []
    fake = type(sys)("notify")
    fake.send = lambda *a: calls.append(a) or True
    monkeypatch.setitem(sys.modules, "notify", fake)
    url = "https://youtu.be/abc123"
    make_done_workdir(tmp_path / "work" / "abc123")
    res = rg.run(url, work_root=tmp_path / "work", out_dir=tmp_path / "out")
    assert calls == [("Local LLM Notes App", res["verdict"], res["path"])]


def test_notify_skipped_with_flag(tmp_path, no_subprocess, monkeypatch):
    calls = []
    fake = type(sys)("notify")
    fake.send = lambda *a: calls.append(a) or True
    monkeypatch.setitem(sys.modules, "notify", fake)
    make_done_workdir(tmp_path / "work" / "abc123")
    rg.run("https://youtu.be/abc123", work_root=tmp_path / "work", out_dir=tmp_path / "out",
           notify=False)
    assert calls == []


def test_notify_failure_does_not_break(tmp_path, no_subprocess, monkeypatch):
    fake = type(sys)("notify")
    def bad(*a):
        raise RuntimeError("nope")
    fake.send = bad
    monkeypatch.setitem(sys.modules, "notify", fake)
    make_done_workdir(tmp_path / "work" / "abc123")
    rg.run("https://youtu.be/abc123", work_root=tmp_path / "work", out_dir=tmp_path / "out")


class FakeRun:
    """Records commands and simulates each tool's side effects."""

    def __init__(self, guide_text=GUIDE, audio=True, claude_rc=0, tamper=None):
        self.cmds = []
        self.guide_text = guide_text
        self.audio = audio
        self.claude_rc = claude_rc
        self.tamper = tamper
        self.skill_seen = None

    def __call__(self, cmd, cwd=None, **kw):
        self.cmds.append(cmd)
        name = Path(cmd[0]).name
        out = ""
        if name == "yt-dlp":
            (Path(cwd) / "video.mp4").write_bytes(b"v")
            (Path(cwd) / "video.info.json").write_text("{}")
        elif name == "ffprobe":
            out = ("0\n" if self.audio else "") if "stream=index" in cmd else "30.0\n"
        elif name == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"x")
        elif "--_transcribe" in cmd:
            Path(cmd[-1]).write_text("[  0.5s] hello\n")
        elif name == "claude":
            assert Path(cwd).name == "R1"
            assert "--add-dir" not in cmd
            self.skill_seen = cmd[cmd.index("--append-system-prompt") + 1]
            if self.tamper:
                self.tamper(Path(cwd))
            if self.guide_text is not None:
                (Path(cwd) / "guide.md").write_text(self.guide_text, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, self.claude_rc, "done", "claude stderr")
        return subprocess.CompletedProcess(cmd, 0, out, "")

    def names(self):
        return ["transcribe" if "--_transcribe" in c else Path(c[0]).name for c in self.cmds]


@pytest.fixture
def fake_env(monkeypatch, tmp_path):
    monkeypatch.setattr(rg, "detect_scenes", lambda v: [])
    monkeypatch.setattr(rg, "COOKIES", tmp_path / "no-cookies.txt")
    return tmp_path


URL = "https://www.instagram.com/reel/R1/"


def test_full_pipeline_then_skips(fake_env, monkeypatch):
    fr = FakeRun()
    monkeypatch.setattr(subprocess, "run", fr)
    work, out = fake_env / "work", fake_env / "out"
    res = rg.run(URL, work_root=work, out_dir=out, notify=False)
    wd = work / "R1"
    assert fr.names()[:3] == ["yt-dlp", "ffprobe", "ffmpeg"]
    assert "transcribe" in fr.names() and fr.names()[-1] == "claude"
    assert (wd / "info.json").exists() and (wd / "video.mp4").exists()
    assert not (wd / ".download.tmp").exists() and not (wd / ".frames.tmp").exists()
    assert len(list((wd / "frames").glob("*.jpg"))) == 6
    assert "claude stderr" in (wd / "claude.log").read_text()
    assert Path(res["path"]).exists()
    # second run: everything skipped
    fr.cmds.clear()
    rg.run(URL, work_root=work, out_dir=out, notify=False)
    assert fr.cmds == []
    # --force re-runs everything
    rg.run(URL, work_root=work, out_dir=out, notify=False, force=True)
    assert "yt-dlp" in fr.names() and "claude" in fr.names()


def test_failed_guide_rerun_skips_earlier_stages(fake_env, monkeypatch):
    work = fake_env / "work"
    fr = FakeRun(guide_text=None)
    monkeypatch.setattr(subprocess, "run", fr)
    with pytest.raises(rg.StageError) as ei:
        rg.run(URL, work_root=work, out_dir=fake_env / "out", notify=False)
    assert ei.value.stage == "guide" and "not written" in ei.value.reason
    fr2 = FakeRun()
    monkeypatch.setattr(subprocess, "run", fr2)
    rg.run(URL, work_root=work, out_dir=fake_env / "out", notify=False)
    assert fr2.names() == ["claude"]


def test_invalid_guide_is_error_and_not_skipped(fake_env, monkeypatch):
    work = fake_env / "work"
    fr = FakeRun(guide_text="Here is your guide!\n# Foo — Build Guide\n")
    monkeypatch.setattr(subprocess, "run", fr)
    with pytest.raises(rg.StageError) as ei:
        rg.run(URL, work_root=work, out_dir=fake_env / "out", notify=False)
    assert ei.value.stage == "guide" and "first line" in ei.value.reason
    fr.cmds.clear()
    with pytest.raises(rg.StageError):
        rg.run(URL, work_root=work, out_dir=fake_env / "out", notify=False)
    assert fr.names() == ["claude"]  # invalid guide.md doesn't count as done


def test_claude_nonzero_exit(fake_env, monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRun(claude_rc=1))
    with pytest.raises(rg.StageError) as ei:
        rg.run(URL, work_root=fake_env / "work", out_dir=fake_env / "out", notify=False)
    assert ei.value.stage == "guide" and "exited 1" in ei.value.reason


def test_no_audio_stream_gives_empty_transcript(fake_env, monkeypatch):
    fr = FakeRun(audio=False)
    monkeypatch.setattr(subprocess, "run", fr)
    rg.run(URL, work_root=fake_env / "work", out_dir=fake_env / "out", notify=False)
    wd = fake_env / "work" / "R1"
    assert (wd / "transcript.txt").read_text() == ""
    assert not (wd / "audio.wav").exists()
    assert "transcribe" not in fr.names()


def test_partial_download_not_skipped(fake_env, monkeypatch):
    wd = fake_env / "work" / "R1"
    wd.mkdir(parents=True)
    (wd / "video.mp4.part").write_bytes(b"half")
    fr = FakeRun()
    monkeypatch.setattr(subprocess, "run", fr)
    rg.run(URL, work_root=fake_env / "work", out_dir=fake_env / "out", notify=False)
    assert fr.names()[0] == "yt-dlp"


def test_cookies_used_when_present(fake_env, monkeypatch):
    cookies = fake_env / "cookies.txt"
    cookies.write_text("# Netscape")
    monkeypatch.setattr(rg, "COOKIES", cookies)
    fr = FakeRun()
    monkeypatch.setattr(subprocess, "run", fr)
    wd = fake_env / "w"
    wd.mkdir()
    rg.stage_download(URL, wd)
    cmd = fr.cmds[0]
    assert cmd[cmd.index("--cookies") + 1] == str(cookies)
    assert cmd[-1] == URL and cmd[-2] == "--"


def test_download_failure_message(fake_env, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(
        cmd, 1, "", "ERROR: [Instagram] R1: login required\n"))
    with pytest.raises(rg.StageError) as ei:
        rg.run(URL, work_root=fake_env / "work", out_dir=fake_env / "out", notify=False)
    assert ei.value.stage == "download"
    assert ei.value.reason == "Instagram needs login — add cookies.txt (see README)"


def test_download_failure_non_instagram_passthrough(fake_env, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(
        cmd, 1, "", "ERROR: [youtube] x: Video unavailable\n"))
    with pytest.raises(rg.StageError) as ei:
        rg.run("https://youtu.be/abc", work_root=fake_env / "work", out_dir=fake_env / "out",
               notify=False)
    assert ei.value.stage == "download" and "Video unavailable" in ei.value.reason


def test_download_prefers_h264_720(fake_env, monkeypatch):
    fr = FakeRun()
    monkeypatch.setattr(subprocess, "run", fr)
    wd = fake_env / "w"
    wd.mkdir()
    rg.stage_download(URL, wd)
    cmd = fr.cmds[0]
    assert cmd[cmd.index("-S") + 1] == "vcodec:h264,res:720"


def test_crlf_cookies_normalized(fake_env, monkeypatch):
    cookies = fake_env / "cookies.txt"
    cookies.write_bytes(b"\xef\xbb\xbf# Netscape HTTP Cookie File\r\n"
                        b".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tx\r\n")
    monkeypatch.setattr(rg, "COOKIES", cookies)
    monkeypatch.setattr(subprocess, "run", FakeRun())
    wd = fake_env / "w"
    wd.mkdir()
    rg.stage_download(URL, wd)
    data = cookies.read_bytes()
    assert b"\r" not in data and data.startswith(b"# Netscape")
    assert data.count(b"\n") == 2


def test_scenedetect_failure_falls_back_to_even_frames(fake_env, monkeypatch):
    def boom(v):
        raise rg.StageError("frames", "scene detection failed: av1 not supported")
    monkeypatch.setattr(rg, "detect_scenes", boom)
    monkeypatch.setattr(subprocess, "run", FakeRun())
    rg.run(URL, work_root=fake_env / "work", out_dir=fake_env / "out", notify=False)
    assert len(list((fake_env / "work" / "R1" / "frames").glob("*.jpg"))) == 6


# --------------------------------------------------------------------- claude sandbox

def _arg(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def test_claude_cmd_is_sandboxed(tmp_path):
    (tmp_path / "frames").mkdir()
    for n in ("frame_02_0003.00s.jpg", "frame_01_0001.00s.jpg"):
        (tmp_path / "frames" / n).write_bytes(b"j")
    cmd = rg.claude_cmd(tmp_path)
    assert cmd[0] == rg.CLAUDE and cmd[1] == "-p"
    assert "--add-dir" not in cmd and "--dangerously-skip-permissions" not in cmd
    assert str(rg.PROJECT_ROOT) not in " ".join(cmd)
    assert "--restricted" in cmd and "--strict-mcp-config" in cmd
    assert set(_arg(cmd, "--tools").split(",")) == {"Read", "Write", "WebSearch", "WebFetch"}
    allowed = _arg(cmd, "--allowedTools").split(",")
    assert "Edit(./guide.md)" in allowed  # the rule claude 2.1.x applies to Write
    assert not {"Write", "Edit", "Bash"} & set(allowed)
    assert set(_arg(cmd, "--disallowedTools").split(",")) >= {"Bash", "NotebookEdit"}
    assert _arg(cmd, "--permission-mode") == "dontAsk"
    assert _arg(cmd, "--permission-prompts") == "none"
    prompt = _arg(cmd, "-p")
    assert "untrusted" in prompt and "never instructions" in prompt
    assert "frames/frame_01_0001.00s.jpg, frames/frame_02_0003.00s.jpg" in prompt


def test_skill_passed_inline_without_front_matter():
    text = rg.skill_text()
    assert not text.startswith("---") and "name: reel-guide" not in text
    assert "guide.md" in text and text in rg.SKILL_SRC.read_text(encoding="utf-8")


def test_guide_stage_passes_skill_and_leaves_no_extra_files(fake_env, monkeypatch):
    fr = FakeRun()
    monkeypatch.setattr(subprocess, "run", fr)
    rg.run(URL, work_root=fake_env / "work", out_dir=fake_env / "out", notify=False)
    assert fr.skill_seen == rg.skill_text()
    assert not (fake_env / "work" / "R1" / ".claude").exists()


@pytest.mark.parametrize("tamper", [
    lambda wd: (wd / "transcript.txt").write_text("rewritten"),
    lambda wd: (wd / "evil.sh").write_text("rm -rf ~"),
    lambda wd: [p.unlink() for p in (wd / "frames").glob("*.jpg")],
    lambda wd: (wd / "frames" / "x.jpg").write_bytes(b"new"),
    lambda wd: os.chmod(wd / "info.json", 0o777),
])
def test_guide_stage_fails_if_claude_touches_other_files(fake_env, monkeypatch, tamper):
    monkeypatch.setattr(subprocess, "run", FakeRun(tamper=tamper))
    with pytest.raises(rg.StageError) as ei:
        rg.run(URL, work_root=fake_env / "work", out_dir=fake_env / "out", notify=False)
    assert ei.value.stage == "guide" and "other than guide.md" in ei.value.reason
    wd = fake_env / "work" / "R1"
    assert not (wd / "guide.md").exists()  # never published
    assert not (fake_env / "out").exists() or not any((fake_env / "out").iterdir())


# --------------------------------------------------------------------- yt-dlp extractors

def test_download_restricts_extractors(fake_env, monkeypatch):
    fr = FakeRun()
    monkeypatch.setattr(subprocess, "run", fr)
    wd = fake_env / "w"
    wd.mkdir()
    rg.stage_download(URL, wd)
    cmd = fr.cmds[0]
    assert _arg(cmd, "--use-extractors") == "instagram,tiktok,vm.tiktok,youtube"
    assert cmd.index("--use-extractors") < cmd.index("--")


# --------------------------------------------------------------------- temp-file permissions

def test_atomic_write_modes(tmp_path, monkeypatch):
    modes = []
    real_open = rg.os.open

    def spy(path, flags, mode=0o777, *a, **k):
        if str(path).endswith(".tmp"):
            modes.append((flags, mode))
        return real_open(path, flags, mode, *a, **k)
    monkeypatch.setattr(rg.os, "open", spy)
    rg.atomic_write(tmp_path / "secret", b"x", mode=0o600)
    rg.atomic_write(tmp_path / "plain", "y")
    assert modes[0][1] == 0o600 and modes[1][1] == 0o644
    assert all(f & os.O_EXCL and f & os.O_CREAT for f, _ in modes)
    assert (tmp_path / "secret").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "secret").read_bytes() == b"x" and (tmp_path / "plain").read_text() == "y"
    assert not list(tmp_path.glob(".*.tmp"))


def test_atomic_write_cleans_temp_on_error(tmp_path, monkeypatch):
    def boom(a, b):
        raise OSError("disk full")
    monkeypatch.setattr(rg.os, "replace", boom)
    with pytest.raises(OSError):
        rg.atomic_write(tmp_path / "f", b"x")
    assert list(tmp_path.iterdir()) == []


def test_cookies_normalized_with_0600_temp(fake_env, monkeypatch):
    cookies = fake_env / "cookies.txt"
    cookies.write_bytes(b"# Netscape\r\nx\r\n")
    os.chmod(cookies, 0o644)
    monkeypatch.setattr(rg, "COOKIES", cookies)
    seen = []
    real = rg.atomic_write
    monkeypatch.setattr(rg, "atomic_write", lambda p, d, mode=0o644: seen.append(mode) or real(p, d, mode))
    rg.normalize_cookies(cookies)
    assert seen == [0o600]
    assert cookies.stat().st_mode & 0o777 == 0o600


# --------------------------------------------------------------------- locks

def _hold_lock(path):
    """Hold an flock on `path` from a separate process (flock is per open file description,
    so a second fd in this process would also conflict, but a child is the realistic case)."""
    code = ("import fcntl, os, sys, time; fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT); "
            "fcntl.flock(fd, fcntl.LOCK_EX); print('locked', flush=True); time.sleep(30)")
    p = subprocess.Popen([sys.executable, "-I", "-c", code, str(path)], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "locked"
    return p


def test_reel_lock_busy(fake_env, monkeypatch, capsys):
    wd = fake_env / "work" / "R1"
    wd.mkdir(parents=True)
    holder = _hold_lock(wd / ".lock")
    try:
        monkeypatch.setattr(subprocess, "run", FakeRun())
        with pytest.raises(rg.StageError) as ei:
            rg.run(URL, work_root=fake_env / "work", out_dir=fake_env / "out", notify=False)
        assert (ei.value.stage, ei.value.reason) == ("busy", "this reel is already being processed")
        monkeypatch.setattr(rg, "WORK_ROOT", fake_env / "work")
        monkeypatch.setattr(rg, "run", lambda url, **k: (_ for _ in ()).throw(
            rg.StageError("busy", "this reel is already being processed")))
        assert rg.main([URL]) == 1
        assert capsys.readouterr().out.strip() == "ERROR: busy: this reel is already being processed"
    finally:
        holder.kill()
        holder.wait()


def test_reel_lock_released_after_run(fake_env, monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRun(guide_text=None))
    with pytest.raises(rg.StageError):
        rg.run(URL, work_root=fake_env / "work", out_dir=fake_env / "out", notify=False)
    with rg.FileLock(fake_env / "work" / "R1" / ".lock"):  # free again after a failure
        pass


def test_whisper_lock_waits_then_runs(fake_env, monkeypatch):
    work = fake_env / "work"
    work.mkdir()
    holder = _hold_lock(work / ".whisper.lock")
    msgs = []
    monkeypatch.setattr(rg, "log", msgs.append)
    fr = FakeRun()
    monkeypatch.setattr(subprocess, "run", fr)
    import threading
    t = threading.Timer(0.5, holder.kill)
    t.start()
    try:
        wd = work / "R1"
        wd.mkdir()
        (wd / "audio.wav").write_bytes(b"a")
        rg.stage_transcribe(wd / "audio.wav", wd, lock_path=work / ".whisper.lock")
    finally:
        t.cancel()
        holder.kill()
        holder.wait()
    assert any("waiting" in m for m in msgs)
    assert fr.names() == ["transcribe"]


def test_whisper_lock_is_held_during_transcribe(fake_env, monkeypatch):
    work = fake_env / "work"
    wd = work / "R1"
    wd.mkdir(parents=True)
    (wd / "audio.wav").write_bytes(b"a")
    state = {}

    def fake(cmd, **k):
        try:
            with rg.FileLock(work / ".whisper.lock"):
                state["free"] = True
        except rg.LockBusy:
            state["free"] = False
        Path(cmd[-1]).write_text("")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake)
    rg.stage_transcribe(wd / "audio.wav", wd, lock_path=work / ".whisper.lock")
    assert state["free"] is False


# --------------------------------------------------------------------- CLI output

def test_main_success_output(monkeypatch, capsys):
    monkeypatch.setattr(rg, "run", lambda url, **k: {"path": "/x/g.md", "title": "T", "verdict": "V", "reel_id": "r"})
    assert rg.main(["https://youtu.be/x", "--no-notify"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[-2:] == ["GUIDE: /x/g.md", "VERDICT: V"]


def test_main_flags(monkeypatch):
    seen = {}
    monkeypatch.setattr(rg, "run", lambda url, **k: seen.update(k) or {"path": "p", "title": "t", "verdict": "v", "reel_id": "r"})
    rg.main(["https://youtu.be/x", "--force"])
    assert seen == {"notify": True, "force": True}


def test_main_out_flag(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(rg, "run", lambda url, **k: seen.update(k) or {"path": "p", "title": "t", "verdict": "v", "reel_id": "r"})
    rg.main(["https://youtu.be/x", "--out", str(tmp_path)])
    assert seen["out_dir"] == tmp_path


# --------------------------------------------------------------------- config

def test_load_env_file(tmp_path, monkeypatch):
    f = tmp_path / "env"
    f.write_text("# comment\nREEL_GUIDE_T1=a b\nexport REEL_GUIDE_T2=\"q\"\nREEL_GUIDE_T3=keep\nnoequals\n")
    monkeypatch.delenv("REEL_GUIDE_T1", raising=False)
    monkeypatch.delenv("REEL_GUIDE_T2", raising=False)
    monkeypatch.setenv("REEL_GUIDE_T3", "already")
    rg.load_env_file(f)
    assert os.environ["REEL_GUIDE_T1"] == "a b"
    assert os.environ["REEL_GUIDE_T2"] == "q"
    assert os.environ["REEL_GUIDE_T3"] == "already"
    for k in ("REEL_GUIDE_T1", "REEL_GUIDE_T2"):
        monkeypatch.delenv(k)


def test_load_env_file_ignores_foreign_keys(tmp_path, monkeypatch):
    f = tmp_path / "env"
    f.write_text("PATH=/evil\nLD_PRELOAD=/evil.so\nREEL_GUIDE_T4=ok\n")
    old_path = os.environ.get("PATH")
    monkeypatch.delenv("LD_PRELOAD", raising=False)
    monkeypatch.delenv("REEL_GUIDE_T4", raising=False)
    rg.load_env_file(f)
    assert os.environ.get("PATH") == old_path
    assert "LD_PRELOAD" not in os.environ
    assert os.environ["REEL_GUIDE_T4"] == "ok"
    monkeypatch.delenv("REEL_GUIDE_T4")


def test_sanitize_info_json_drops_cookies(tmp_path):
    import json
    p = tmp_path / "info.json"
    p.write_text(json.dumps({"title": "T", "description": "cap", "webpage_url": "u", "tags": ["a"],
                             "cookies": "sessionid=SENTINEL", "http_headers": {"Cookie": "SENTINEL"},
                             "formats": [{"url": "x", "cookies": "SENTINEL"}]}))
    rg.sanitize_info_json(p)
    text = p.read_text()
    assert "SENTINEL" not in text
    assert json.loads(text) == {"title": "T", "description": "cap", "webpage_url": "u", "tags": ["a"]}


def test_sanitize_info_json_bad_input_becomes_empty(tmp_path):
    p = tmp_path / "info.json"
    p.write_text("not json SENTINEL")
    rg.sanitize_info_json(p)
    assert p.read_text().strip() == "{}"
    p.write_text("[1, 2]")
    rg.sanitize_info_json(p)
    assert p.read_text().strip() == "{}"


def test_guide_stage_sanitizes_old_info_json(tmp_path, monkeypatch):
    """Work dirs from older runs may hold a raw info.json; it is cleaned before claude runs."""
    import json
    wd = tmp_path / "w"
    (wd / "frames").mkdir(parents=True)
    (wd / ".download.tmp").mkdir()
    (wd / ".download.tmp" / "video.info.json").write_text('{"cookies": "SENTINEL"}')
    (wd / "info.json").write_text(json.dumps({"title": "T", "cookies": "SENTINEL"}))
    seen = {}

    def fake(cmd, **k):
        seen["info"] = (wd / "info.json").read_text()
        seen["tmp_exists"] = (wd / ".download.tmp").exists()
        (wd / "guide.md").write_text(GUIDE, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake)
    rg.stage_guide(wd)
    assert "SENTINEL" not in seen["info"] and seen["tmp_exists"] is False


def test_load_env_file_missing_is_fine(tmp_path):
    rg.load_env_file(tmp_path / "nope")


def test_skill_text_appends_context(tmp_path, monkeypatch):
    ctx = tmp_path / "my_setup.md"
    monkeypatch.setattr(rg, "CONTEXT_FILE", ctx)
    base = rg.skill_text()
    assert "(provided by the reader)" not in base
    ctx.write_text("- A Raspberry Pi 5, no GPU.\n")
    with_ctx = rg.skill_text()
    assert with_ctx.startswith(base)
    assert "## The reader's setup (provided by the reader)" in with_ctx
    assert "Raspberry Pi 5" in with_ctx


def test_no_personal_paths_in_source():
    src = Path(rg.__file__).read_text(encoding="utf-8")
    assert "/home/" not in src and "Dash" not in src


def test_main_error_output(capsys):
    assert rg.main(["https://example.com/x"]) != 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].startswith("ERROR: url: ")
