# Phone setup: share a reel, get a build guide

You'll end up tapping **Share → Reel → Guide** on any Instagram, TikTok or YouTube video. Your computer writes the guide, and a push tells you when it's ready.

```
Phone share sheet ──private link (Tailscale)──▶ server.py :8765 on your computer
                                                             │ queue (SQLite), one job at a time
                                                             ▼
                                                   reel_guide.py → guide.md → ntfy push ──▶ phone
```

Setup takes about 20 minutes:

1. Run the server on the computer.
2. Make the computer reachable from the phone (Tailscale).
3. Make the share shortcut (iPhone **or** Android).
4. Optional: get a push when the guide is ready.

Finish the main [install](../README.md#install) first, and check that the CLI works on one link.

---

## 1. Run the server

The server should run on a machine that stays on: a desktop, a mini PC, a home server, or a Mac that doesn't sleep.

```bash
cd ~/reel-guide
./install.sh --service
```

- **Linux / WSL2:** this installs a **systemd user service** (`reel-guide`). It needs no sudo. To keep it running after you log out and start it at boot, run `sudo loginctl enable-linger $USER` once.
  - On **WSL2**, systemd must be enabled. It's on by default in recent Ubuntu images. If not, add `[boot]` + `systemd=true` to `/etc/wsl.conf` and run `wsl --shutdown`. WSL also has to be running, so open the Ubuntu terminal once after Windows starts, or add a Task Scheduler task that runs `wsl.exe -d Ubuntu-24.04 --exec true` at logon.
- **macOS:** this installs a **launchd agent** (`com.reel-guide.server`), with logs in `~/Library/Logs/reel-guide.log`.

Check it:

```bash
curl -s http://127.0.0.1:8765/health          # {"ok": true, "queued": 0, "running": null}
cat ~/.config/reel-guide/key                   # the key your phone will send
```

Treat the key like a password: don't paste it into chats, docs or commits. To change it, delete the file and restart the server (`systemctl --user restart reel-guide`, or `launchctl kickstart -k gui/$(id -u)/com.reel-guide.server` on macOS), then update the shortcut on the phone.

Without the service, you can run it in a terminal instead: `.venv/bin/python server.py --bind 127.0.0.1 --bind <tailscale-ip>`.

## 2. Make it reachable from your phone (Tailscale)

By default the server only listens on `127.0.0.1`, so nothing else can reach it. **Don't open it to the internet or bind `0.0.0.0`.** Use a private network instead. [Tailscale](https://tailscale.com) is free for personal use and works on cellular data too.

1. Install Tailscale on the **computer** and on the **phone** ([iOS](https://apps.apple.com/app/tailscale/id1470499037) / [Android](https://play.google.com/store/apps/details?id=com.tailscale.ipn)), and sign in with the same account on both.
2. On the computer, get its Tailscale IPv4: `tailscale ip -4` (it looks like `100.x.y.z`).
3. Add it to `~/.config/reel-guide/env`:
   ```
   REEL_GUIDE_BIND=127.0.0.1,100.x.y.z
   ```
   Then restart the server. If Tailscale isn't up yet when the server starts, it keeps retrying that address every 30 s.
4. From the phone (Tailscale on), open `http://100.x.y.z:8765/health` in the browser. You should see `{"ok": true, ...}`.

**WSL2 notes.** Pick one:

- **Tailscale inside WSL** (simplest): `curl -fsSL https://tailscale.com/install.sh | sh`, then `sudo tailscale up`. Use the IP that `tailscale ip -4` shows **inside WSL**.
- **Tailscale on Windows:** WSL2 can't bind the Windows Tailscale IP by default. Turn on mirrored networking by putting `[wsl2]` + `networkingMode=mirrored` in `%UserProfile%\.wslconfig`, run `wsl --shutdown`, and use the Windows Tailscale IP. You may also need to allow port 8765 in Windows Firewall for the Tailscale interface.

Plain HTTP is fine here because Tailscale already encrypts the traffic end to end. You can use the MagicDNS name (`http://<computer-name>:8765`) instead of the IP.

---

## 3a. iPhone: Shortcuts

1. Open **Shortcuts**, tap **+**, and name the shortcut **Reel → Guide**.
2. Tap **ⓘ** (details) → turn on **Show in Share Sheet**. Under share sheet types, keep only **URLs**, **Text** and **Safari web pages**.
   The first block should read *Receive URLs, Text and Safari web pages from Share Sheet*. Set **If there's no input** to **Get Clipboard**, so the shortcut also works after Instagram's *Copy link*.
3. Add the **Get Contents of URL** action:
   - URL: `http://100.x.y.z:8765/reel`
   - Tap **Show More**. Method: **POST**.
   - **Headers:** add one. Key `X-Reel-Key`, value = the contents of `~/.config/reel-guide/key`.
   - **Request Body:** **JSON**. Add one **Text** field: key `url`, value = the **Shortcut Input** variable.
4. Add **Get Dictionary Value**: get the value for `status` in *Contents of URL*.
5. Add **Show Notification**: `Reel guide: ` + *Dictionary Value*.

To use it: in Instagram tap **Share** (paper plane) → **More**/**Share to…** → **Reel → Guide**. You'll see *Reel guide: queued*. In TikTok, it's **Share → More**. In YouTube, **Share → More**. You can also *Copy link* and run the shortcut from a widget or with Siri.

If the notification shows an empty status, the key is wrong (HTTP 401) or there was no supported link in what you shared (HTTP 400). The response's `error` field has the reason. To see it, add a **Show Result** action with *Contents of URL* while testing.

**Optional "Reel jobs" shortcut** to check progress: **Get Contents of URL** `http://100.x.y.z:8765/jobs` (method GET, same `X-Reel-Key` header) → **Show Result**.

## 3b. Android: HTTP Shortcuts

Android has no built-in Shortcuts app. The free, open-source **HTTP Shortcuts** app ([Play Store](https://play.google.com/store/apps/details?id=ch.rmy.android.http_shortcuts) / [F-Droid](https://f-droid.org/packages/ch.rmy.android.http_shortcuts/)) does the same job. Menu names can differ slightly between app versions.

1. **Make a variable for the shared link:** ☰ → **Variables** → **+** → type **Static/Constant** (or **Text Input**). Name it `shared_url`. In its settings, turn on **Allow 'Share Into'** (*Allow receiving value from share dialog*) and choose **Text**.
2. **Make the shortcut:** **+** → **Regular Shortcut**, named **Reel → Guide**.
   - **Basic Request Settings:** method **POST**, URL `http://100.x.y.z:8765/reel`.
   - **Request Headers:** add `X-Reel-Key` = the contents of `~/.config/reel-guide/key`.
   - **Request Body / Parameters:** type **Custom Text**, content type `application/json`, body:
     ```json
     {"url": "{{shared_url}}"}
     ```
     Insert the variable with the **{ }** button rather than typing it. The app stores it with an internal id.
   - **Response Handling:** show the response as a **Toast** (or a dialog while testing).
3. Save. Because the variable allows *Share Into*, **HTTP Shortcuts** now appears in Android's share sheet.

To use it: in Instagram, TikTok or YouTube tap **Share** → **HTTP Shortcuts** (pick **Reel → Guide** if it asks). The toast shows `{"status": "queued", "id": N}`.

The link doesn't have to be clean. If the share includes caption text with the link somewhere inside it, the server finds the first supported link and strips tracking parameters such as `igsh` and `utm_*`.

**Alternatives:** Tasker or Automate (an *HTTP Request* action triggered by a share intent) work too. You can also test from Termux:
`curl -X POST -H "X-Reel-Key: $KEY" -H 'Content-Type: application/json' -d '{"url":"<link>"}' http://100.x.y.z:8765/reel`

---

## 4. Get a push when it's done (optional)

The share shortcut only tells you the link was **queued**. To hear back when the guide is written (title, verdict and path) or when a job fails:

1. Install **ntfy** ([iOS](https://apps.apple.com/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)) and subscribe to a long random topic. Make one with `openssl rand -hex 12` and prefix it, e.g. `reel-guide-<hex>`.
2. On the computer, set `REEL_GUIDE_NTFY_TOPIC=reel-guide-<hex>` in `~/.config/reel-guide/env`. Optionally add `REEL_GUIDE_QUIET_HOURS=23-8` to hold night-time pushes.
3. Restart the server and test it: `.venv/bin/python notify.py`.

On iOS, set **ntfy → Settings → Default server** to match `REEL_GUIDE_NTFY_SERVER` if you self-host.

## Reading the guides on your phone

Guides are plain Markdown files in `REEL_GUIDE_OUT_DIR`. Some ways to get them onto the phone:

- Point `REEL_GUIDE_OUT_DIR` at a folder you already sync: iCloud Drive (macOS), Dropbox, Google Drive, OneDrive, or Syncthing (Android: [Syncthing-Fork](https://f-droid.org/packages/com.github.catfriend1.syncthingandroid/), iOS: Möbius Sync).
- Open them in any Markdown app (Obsidian, iA Writer, 1Writer, Markor on Android).

## Server reference

| Request | Key? | Result |
|---|---|---|
| `POST /reel` with JSON `{"url": ...}`, form `url=...`, or plain text containing a link | yes | `202 {"status":"queued","id":N}` (`"duplicate": true` if that link is already queued or running); `400` no supported link; `401` bad key; `413` body > 16 KB |
| `GET /health` | no | `{"ok":true,"queued":N,"running":{"id":..,"since":..} or null}` (never shows URLs) |
| `GET /jobs` | yes | the last 20 jobs: status, exit code, guide path, verdict, error |

- The key goes in the `X-Reel-Key` header. It lives in `~/.config/reel-guide/key`: 64 hex characters, mode 0600, created on first start.
- The queue is in `queue.db` (`REEL_GUIDE_DB`). A job left running when the server stopped is queued again on the next start.
- Logs: `journalctl --user -u reel-guide -f` (Linux/WSL) or `tail -f ~/Library/Logs/reel-guide.log` (macOS).
- The server only accepts connections on the addresses you bind. It caps concurrent connections, and drops clients that are slow or send too much.
