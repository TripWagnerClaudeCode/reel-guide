<!--
Optional. Copy this file to my_setup.md (git-ignored) and describe your own setup.
When it exists, every guide gets a "Fitting it into my setup" section and build steps
written for your machine. Keep it short. Never put IP addresses, passwords or keys here:
it is sent to Claude with every guide.
-->

- **Machine:** an always-on Ubuntu 24.04 mini PC. 8 CPU cores, 16 GB RAM, **no GPU**, no sudo.
  Python 3.12 with one `.venv` per project. Long-running things are systemd user services.
- **Projects** live in `~/projects/<name>/`. Notes and outputs sync to my laptop with Syncthing.
- **Phone:** iPhone. I trigger things with iOS Shortcuts and get results as ntfy pushes.
- **AI:** I have a Claude subscription and the `claude` CLI, so I prefer `claude -p` with a skill
  over paid APIs.
- **Network:** everything is private on Tailscale. Nothing is exposed to the public internet.
