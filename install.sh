#!/usr/bin/env bash
# reel-guide installer for Linux, WSL2 and macOS. No sudo needed; safe to re-run.
#   ./install.sh            create .venv, install Python deps, check tools, write config skeleton
#   ./install.sh --service  also install + start the background server (systemd user unit or launchd)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$HOME/.config/reel-guide"
WANT_SERVICE=0
[[ "${1:-}" == "--service" ]] && WANT_SERVICE=1

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mWARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

OS="$(uname -s)"
case "$OS" in
  Linux|Darwin) ;;
  *) die "unsupported OS '$OS'. On Windows, run this inside WSL2 (see README)." ;;
esac

# --- Python 3.10+
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || die "python3 not found. Install Python 3.10+ first."
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "Python 3.10+ required (found $("$PY" -V 2>&1))."
"$PY" -c 'import venv, ensurepip' 2>/dev/null \
  || die "Python venv module missing. Debian/Ubuntu: sudo apt install python3-venv"

# --- virtualenv + deps
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  say "creating .venv"
  "$PY" -m venv "$ROOT/.venv"
fi
say "installing Python packages (a few hundred MB the first time)"
"$ROOT/.venv/bin/python" -m pip install --quiet --upgrade pip
"$ROOT/.venv/bin/python" -m pip install --quiet -r "$ROOT/requirements.txt"

# --- external tools
missing=0
for t in ffmpeg ffprobe; do
  if ! command -v "$t" >/dev/null && [[ ! -x "$HOME/.local/bin/$t" ]]; then
    warn "$t not found."
    missing=1
  fi
done
if (( missing )); then
  if [[ "$OS" == Darwin ]]; then
    warn "  install it with:  brew install ffmpeg"
  else
    warn "  install it with:  sudo apt install ffmpeg"
    warn "  (no sudo? put a static build from https://johnvansickle.com/ffmpeg/ in ~/.local/bin)"
  fi
fi

CLAUDE_BIN="$(command -v claude 2>/dev/null || true)"
[[ -z "$CLAUDE_BIN" && -x "$HOME/.local/bin/claude" ]] && CLAUDE_BIN="$HOME/.local/bin/claude"
if [[ -z "$CLAUDE_BIN" || "$CLAUDE_BIN" == *.exe || "$CLAUDE_BIN" == /mnt/* ]]; then
  warn "Claude Code CLI ('claude') not found for this OS."
  warn "  install it: https://docs.claude.com/en/docs/claude-code/setup"
  warn "  then run 'claude' once to log in."
else
  say "claude CLI: $CLAUDE_BIN"
fi

# --- config skeleton (never overwrites)
mkdir -p "$CONF"
chmod 700 "$CONF"
if [[ ! -f "$CONF/env" ]]; then
  cp "$ROOT/env.example" "$CONF/env"
  chmod 600 "$CONF/env"
  say "wrote $CONF/env (edit it to set the output folder, push notifications, ...)"
fi

# --- optional background service
if (( WANT_SERVICE )); then
  if [[ "$OS" == Darwin ]]; then
    PLIST="$HOME/Library/LaunchAgents/com.reel-guide.server.plist"
    mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
    sed -e "s#__ROOT__#$ROOT#g" -e "s#__HOME__#$HOME#g" "$ROOT/deploy/com.reel-guide.server.plist" > "$PLIST"
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load -w "$PLIST"
    say "launchd agent loaded: $PLIST (logs: ~/Library/Logs/reel-guide.log)"
  else
    command -v systemctl >/dev/null || die "systemctl not found; run 'python server.py' yourself (see README)."
    UNIT_DIR="$HOME/.config/systemd/user"
    mkdir -p "$UNIT_DIR"
    sed -e "s#__ROOT__#$ROOT#g" "$ROOT/deploy/reel-guide.service" > "$UNIT_DIR/reel-guide.service"
    systemctl --user daemon-reload
    systemctl --user enable --now reel-guide.service
    say "systemd user service started: systemctl --user status reel-guide"
    if command -v loginctl >/dev/null && ! loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q yes; then
      warn "to keep it running after you log out / at boot:  sudo loginctl enable-linger $USER"
    fi
  fi
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [[ -f "$CONF/key" ]] && break
    sleep 1
  done
  [[ -f "$CONF/key" ]] && say "server key is in $CONF/key (you'll paste it into the phone shortcut)"
fi

say "done. Try:  $ROOT/.venv/bin/python $ROOT/reel_guide.py 'https://www.youtube.com/shorts/<id>'"
