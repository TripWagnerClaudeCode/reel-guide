# reel-guide

Send it an Instagram reel, TikTok or YouTube Short and it writes a Markdown **build guide** for whatever the video shows how to make. The guide comes with an honest verdict: what was actually shown working, what was only claimed, and what was left out.

```
yt-dlp → ffmpeg (16 kHz wav) → faster-whisper "small" (CPU) → PySceneDetect keyframes (≤ 12)
      → claude -p + the reel-guide skill → "<date> – <title>.md" → optional phone push (ntfy)
```

There are two ways to use it:

- **CLI:** `python reel_guide.py <url>` on your computer.
- **Phone:** a small server that your phone's share sheet posts links to. It queues them and runs them one at a time. See **[docs/MOBILE.md](docs/MOBILE.md)**.

It runs on CPU (no GPU), needs no sudo for itself, and uses your Claude subscription through the `claude` CLI, so there's no separate API bill.

---

## Requirements

| | |
|---|---|
| OS | Linux, macOS, or **Windows via WSL2** (native Windows isn't supported) |
| Python | 3.10+ with `venv` |
| ffmpeg | `ffmpeg` and `ffprobe` on `PATH` (or in `~/.local/bin`) |
| Claude Code | the `claude` CLI, logged in (`claude` once interactively). A Claude Pro/Max plan or API key |
| Disk / RAM | ~1 GB for packages + the whisper model; ~2 GB free RAM while transcribing |

## Install

### Linux / WSL2 / macOS

```bash
git clone https://github.com/<you>/reel-guide.git
cd reel-guide
./install.sh
```

`install.sh` creates `.venv`, installs the pinned Python packages, checks for `ffmpeg` and `claude`, and writes a settings file at `~/.config/reel-guide/env`. It never uses sudo and is safe to re-run.

If something is missing it tells you what to run:

- **ffmpeg:** `sudo apt install ffmpeg` (Debian/Ubuntu) or `brew install ffmpeg` (macOS). With no sudo, put a static build in `~/.local/bin`.
- **Claude Code:** follow <https://docs.claude.com/en/docs/claude-code/setup>, then run `claude` once to log in.

### Windows (WSL2)

1. In PowerShell (as admin, once): `wsl --install -d Ubuntu-24.04`, then reboot and create your Linux user.
2. Open the **Ubuntu** terminal and run everything else there:
   ```bash
   sudo apt update && sudo apt install -y python3-venv ffmpeg git
   curl -fsSL https://claude.ai/install.sh | bash   # Claude Code for Linux; then run: claude
   git clone https://github.com/<you>/reel-guide.git ~/reel-guide
   cd ~/reel-guide && ./install.sh
   ```
3. Use the **Linux** `claude`, not the Windows `claude.exe`. reel-guide skips `.exe` files on PATH on its own. If it still can't find `claude`, set `REEL_GUIDE_CLAUDE=$HOME/.local/bin/claude` in `~/.config/reel-guide/env`.
4. Your guides appear in `~/Reel Guides` inside WSL. From Windows Explorer that's `\\wsl.localhost\Ubuntu-24.04\home\<user>\Reel Guides`. To save them straight to a Windows folder instead, set `REEL_GUIDE_OUT_DIR=/mnt/c/Users/<you>/Documents/Reel Guides`.

### Check it works

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q          # no network, no claude calls
.venv/bin/python reel_guide.py 'https://www.youtube.com/shorts/<id>'
```

## Use it (CLI)

```bash
cd reel-guide
.venv/bin/python reel_guide.py 'https://www.instagram.com/reel/XXXX/' [--no-notify] [--force] [--out DIR]
```

- **Allowed links:** Instagram reels/posts, TikTok videos (incl. `vm.`/`vt.` short links), YouTube Shorts / `watch?v=` / `youtu.be`. Anything else is rejected, and yt-dlp is never pointed at other sites.
- **Output:** `~/Reel Guides/YYYY-MM-DD – <title>.md` (change with `--out` or `REEL_GUIDE_OUT_DIR`). If the name is taken, ` (2)` is added.
- **Re-runs are free:** each stage is skipped when its output already exists in `work/<reel_id>/`. `--force` redoes everything.
- **Script-friendly:** the last two lines are `GUIDE: <path>` and `VERDICT: <line>`. Failures print one line `ERROR: <stage>: <reason>` and exit non-zero.
- **Clean up:** `rm -rf work/*` (finished guides are not touched).

A run takes roughly **1.5–2 minutes** for a short reel: under 20 s for download, transcription and frames, then 70–100 s for the Claude step.

## Settings

All settings are optional. They go in `~/.config/reel-guide/env` (created by `install.sh`, see [`env.example`](env.example)) or in environment variables, which win. Only `REEL_GUIDE_*` names are read from that file. Anything else is ignored.

| Variable | Default | What |
|---|---|---|
| `REEL_GUIDE_OUT_DIR` | `~/Reel Guides` | where guides are saved |
| `REEL_GUIDE_WORK_DIR` | `<repo>/work` | scratch files per reel |
| `REEL_GUIDE_COOKIES` | `<repo>/cookies.txt` | Instagram cookies (see below) |
| `REEL_GUIDE_CLAUDE` | found on `PATH` | path to the `claude` CLI |
| `REEL_GUIDE_CONTEXT` | `<repo>/my_setup.md` | optional description of your setup |
| `REEL_GUIDE_BIND` / `REEL_GUIDE_PORT` | `127.0.0.1` / `8765` | server addresses (comma-separated) and port |
| `REEL_GUIDE_NTFY_TOPIC` | *(off)* | ntfy topic for pushes |
| `REEL_GUIDE_NTFY_SERVER` | `https://ntfy.sh` | ntfy server |
| `REEL_GUIDE_NTFY_TOKEN` | | ntfy access token (self-hosted with auth) |
| `REEL_GUIDE_QUIET_HOURS` | | e.g. `23-8`: pushes are held until the end hour |

### Make guides fit *your* setup (optional)

Copy [`my_setup.example.md`](my_setup.example.md) to `my_setup.md` (git-ignored) and describe your machine, phone and the tools you already run. Every guide then gets a **"Fitting it into my setup"** section, and its build steps are written for your machine. The file is sent to Claude with each guide, so leave out IPs, passwords and keys.

### Push notifications (optional)

1. Install the **ntfy** app ([iOS](https://apps.apple.com/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)) and subscribe to a long random topic, e.g. `reel-guide-7f3c9a1e5b...` (`openssl rand -hex 12` makes one).
2. Set `REEL_GUIDE_NTFY_TOPIC=<that topic>` in `~/.config/reel-guide/env`.
3. Test it: `.venv/bin/python notify.py`.

On public ntfy.sh, anyone who guesses the topic can read the pushes. They contain the guide title, the verdict and the file path. For full privacy, self-host ntfy and set `REEL_GUIDE_NTFY_SERVER` and `REEL_GUIDE_NTFY_TOKEN`.

## Instagram cookies

Many public reels download fine while logged out. Instagram rate-limits logged-out access, though, and private or age-gated posts need a login. When that happens you'll see:

```
ERROR: download: Instagram needs login — add cookies.txt (see README)
```

Fix:

1. Use a **throwaway Instagram account. Never your main one.** reel-guide never asks for a password; it only reads a cookies file.
2. Log in to instagram.com in a browser and export the cookies (Netscape format) with an extension such as **"Get cookies.txt LOCALLY"**.
3. Save the file as `cookies.txt` in the repo folder, or point `REEL_GUIDE_COOKIES` at it. Windows line endings and a BOM are fine: the file is rewritten to LF with mode 0600 before use. `cookies.txt` is git-ignored.

When the cookies expire, the same error comes back. Export them again.

## Troubleshooting

| Error line | Fix |
|---|---|
| `ERROR: url: not an allowed reel URL ...` | Share the reel's own link (not a profile or a redirect link) |
| `ERROR: download: Instagram needs login ...` | Add or refresh `cookies.txt` (above) |
| `ERROR: download: yt-dlp exited 1: ... Unexpected response from webpage request` | TikTok needs `curl_cffi`: `.venv/bin/pip install -r requirements.txt` |
| `ERROR: download: yt-dlp exited N: ...` (other) | Site changed: `.venv/bin/pip install -U yt-dlp`. Age-gated YouTube needs cookies too |
| `ERROR: download: ... timed out` / `no video file` | Network hiccup: rerun with `--force` |
| `ERROR: transcribe: ...` | `.venv/bin/pip install -r requirements.txt` (keeps `av==18.1.0` pinned) |
| `ERROR: frames: ...` | `ffmpeg -version` works? Then `rm -rf work/<id>` and rerun |
| `ERROR: guide: ... not found (install Claude Code ...)` | Install Claude Code, or set `REEL_GUIDE_CLAUDE` |
| `ERROR: guide: claude exited N: ...` / `timed out` | Not logged in (`claude`), or usage limit hit: wait and rerun |
| `ERROR: guide: guide.md first line is not ...` | Claude didn't follow the skill. Rerun with `--force` |
| `ERROR: busy: ...` | That reel is already running in another process |

## How the Claude step is locked down

The video's speech, caption and on-screen text are treated as **untrusted**: a reel could contain "ignore your instructions…" text. So `claude -p` runs:

- with only `Read`, `Write` (limited to `guide.md`), `WebSearch` and `WebFetch`: no shell, no MCP servers, and no settings files loaded (`--restricted`);
- inside `work/<reel_id>/` only, so the repo, `.venv` and `cookies.txt` are out of reach;
- with every other permission request denied without prompting.

If Claude changes any file other than `guide.md`, the run fails and the guide is thrown away.

Before Claude runs, `info.json` is cut down to a few fields (title, caption, uploader, URL, tags, duration). yt-dlp also records the cookies it used there, which would include your Instagram login from `cookies.txt`, so those never reach Claude.

**Web access is open on purpose.** Claude needs `WebSearch`/`WebFetch` to check the repos and tools a reel mentions, and they aren't limited to certain domains. A reel could try to talk Claude into fetching a URL with data in it. What Claude can see is the reel's own public transcript, caption and frames, plus your `my_setup.md` if you made one. So **never put secrets, IPs or private details in `my_setup.md`**. If you want it stricter, change `CLAUDE_ALLOWED` in `reel_guide.py` to domain rules such as `WebFetch(domain:github.com)`.

## Costs, limits and fair use

- Each guide is **one `claude -p` run** on your plan, about 70–100 s.
- **One job at a time** on the server, with at most 20 waiting. More get HTTP 429. Whisper loads once per job, and a global lock keeps two whisper models out of RAM.
- Downloading from Instagram/TikTok may break their Terms of Service. Keep volume low and use it for personal reference only.
- Don't share your server or its key with other people. That would put their usage on your Claude plan.

## Files

```
reel_guide.py                     CLI + pipeline (stdlib at import; heavy deps loaded lazily)
server.py                         share-sheet HTTP endpoint + SQLite job queue (stdlib only)
notify.py                         optional ntfy push (stdlib only)
.claude/skills/reel-guide/SKILL.md  instructions Claude follows to write the guide
install.sh                        installer (Linux/WSL/macOS)
deploy/reel-guide.service         systemd user unit (Linux/WSL)
deploy/com.reel-guide.server.plist  launchd agent (macOS)
env.example, my_setup.example.md  settings templates
docs/MOBILE.md                    phone setup (iPhone + Android)
tests/                            pytest, no network
```

## License

MIT, see [LICENSE](LICENSE).
