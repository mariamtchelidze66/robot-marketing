#!/usr/bin/env bash
#
# install.sh — one-command, step-by-step installer for robot-marketing.
#
#   curl -fsSL https://raw.githubusercontent.com/mariamtchelidze66/robot-marketing/main/install.sh | bash
#   # or:
#   wget -qO- https://raw.githubusercontent.com/mariamtchelidze66/robot-marketing/main/install.sh | bash
#
# It asks before every step (y/n), auto-detects the OS/package manager, works
# whether piped into bash or run directly, and needs NO GitHub token (the repo
# is expected to be public). No secrets are stored in this repo.
#
set -uo pipefail

# ---------- project settings (change these per repo) ----------
PROJECT="robot-marketing"
REPO_URL="https://github.com/mariamtchelidze66/robot-marketing.git"
RAW_URL="https://raw.githubusercontent.com/mariamtchelidze66/robot-marketing/main/install.sh"
DEST="${ROBOT_MARKETING_DIR:-$HOME/robot-marketing}"
# system packages this project needs:
PKGS_APT="git python3 python3-venv python3-pip"
PKGS_PACMAN="git python python-pip"
PKGS_DNF="git python3 python3-pip"
# python (PyPI) dependencies this project needs:
PIP_PKGS="python-telegram-bot anthropic openai openpyxl pydantic flask"

# ---------- colors / logging ----------
if [[ -t 1 ]]; then
  R="\033[31m"; G="\033[32m"; Y="\033[33m"; C="\033[36m"; B="\033[1m"; N="\033[0m"
else R=""; G=""; Y=""; C=""; B=""; N=""; fi
info(){ echo -e "${C}[*]${N} $*"; }
ok(){   echo -e "${G}[+]${N} $*"; }
warn(){ echo -e "${Y}[!]${N} $*"; }
err(){  echo -e "${R}[x]${N} $*" >&2; }
step(){ echo; echo -e "${B}==== $* ====${N}"; }

# ---------- read from the real terminal even when piped (curl | bash) ----------
# Open the actual controlling terminal on fd 3 so prompts work even when this
# script itself arrives on stdin (curl ... | bash). If there is no terminal
# (CI, plain pipe), we must NOT silently assume "yes" — set ASSUME_YES=1 to
# opt into a fully non-interactive run instead.
HAVE_TTY=0
if { exec 3</dev/tty; } 2>/dev/null; then HAVE_TTY=1; fi
ASSUME_YES="${ASSUME_YES:-0}"
need_tty(){
  [[ $HAVE_TTY -eq 1 || "$ASSUME_YES" == "1" ]] && return 0
  err "No interactive terminal detected."
  err "This installer asks questions, so run it one of these ways:"
  err "   bash <(curl -fsSL $RAW_URL)        # keeps the terminal for prompts"
  err "   curl -fsSL $RAW_URL | ASSUME_YES=1 bash   # non-interactive, accept all"
  exit 1
}
ask(){  # ask "question" [default y|n] -> returns 0 for yes
  local q="$1" def="${2:-y}" ans hint="[Y/n]"
  [[ "$def" == "n" ]] && hint="[y/N]"
  if [[ "$ASSUME_YES" == "1" ]]; then ans="$def"
  else read -rp "$(echo -e "${Y}[?]${N} $q $hint ")" -u 3 ans || ans=""; fi
  ans="${ans:-$def}"
  [[ "$ans" =~ ^[Yy]$ ]]
}
prompt(){  # prompt "question" -> echoes the typed line
  local q="$1" ans
  if [[ "$ASSUME_YES" == "1" ]]; then echo ""; return; fi
  read -rp "$(echo -e "${Y}[?]${N} $q ")" -u 3 ans || ans=""
  echo "$ans"
}

# ---------- detect environment ----------
step "0) Detecting environment"
OS="$(uname -s)"
IS_WSL=0
grep -qiE "microsoft|wsl" /proc/version 2>/dev/null && IS_WSL=1
if   command -v apt    >/dev/null 2>&1; then PM=apt;    PKGS="$PKGS_APT"
elif command -v pacman >/dev/null 2>&1; then PM=pacman; PKGS="$PKGS_PACMAN"
elif command -v dnf    >/dev/null 2>&1; then PM=dnf;    PKGS="$PKGS_DNF"
else PM=""; PKGS="$PKGS_APT"; fi
info "OS: $OS   WSL: $([[ $IS_WSL -eq 1 ]] && echo yes || echo no)   package manager: ${PM:-unknown}"
need_tty   # bail out early if we can't ask questions and ASSUME_YES isn't set
[[ "$OS" != "Linux" ]] && warn "This tool targets Linux; other systems are untested."
if [[ $IS_WSL -eq 1 ]]; then
  warn "You're on WSL. The bot runs fine here, but the systemd service step"
  warn "needs systemd (may be disabled on older WSL). You can still run it manually."
fi

# sudo helper (root runs commands directly)
SUDO=""
if [[ $EUID -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then SUDO="sudo"; else warn "Not root and no sudo; package install may fail."; fi
fi

echo
info "About to install '${PROJECT}':"
info "  1. install system packages:  $PKGS"
info "  2. clone the repo into:       $DEST"
info "  3. create a python venv + install: $PIP_PKGS"
info "  4. create a .env config file (you fill in the secrets)"
info "  5. optionally install the systemd service"
info "  6. optionally run/test the bot"
ask "Continue?" y || { err "Aborted by user."; exit 1; }

# ---------- 1) system packages ----------
step "1) System packages"
if [[ -z "$PM" ]]; then
  err "No known package manager (apt/pacman/dnf). Install manually: $PKGS"
elif ask "Install/verify packages ($PKGS)?" y; then
  case "$PM" in
    apt)    $SUDO apt-get update -y && $SUDO apt-get install -y $PKGS ;;
    pacman) $SUDO pacman -Sy --noconfirm $PKGS ;;
    dnf)    $SUDO dnf install -y $PKGS ;;
  esac && ok "Packages ready." || err "Package install had errors (continuing)."
else
  warn "Skipped package install."
fi

# ---------- 2) clone / update the repo ----------
step "2) Get the code"
if [[ -d "$DEST/.git" ]]; then
  info "$DEST already exists."
  if ask "Update it (git pull)?" y; then git -C "$DEST" pull --ff-only || warn "pull failed."; fi
else
  if ask "Clone $REPO_URL into $DEST?" y; then
    git clone "$REPO_URL" "$DEST" && ok "Cloned into $DEST" || { err "Clone failed."; exit 1; }
  else
    warn "Skipped clone — nothing to run."; exit 0
  fi
fi

# ---------- 3) python venv + dependencies ----------
step "3) Python venv + dependencies"
VENV="$DEST/venv"
if ask "Create venv at $VENV and install python deps?" y; then
  if [[ ! -d "$VENV" ]]; then
    python3 -m venv "$VENV" && ok "venv created at $VENV" || { err "venv creation failed."; exit 1; }
  else
    info "venv already exists at $VENV"
  fi
  "$VENV/bin/pip" install --upgrade pip >/dev/null 2>&1 || warn "pip upgrade skipped."
  if [[ -f "$DEST/requirements.txt" ]]; then
    "$VENV/bin/pip" install -r "$DEST/requirements.txt" && ok "Deps installed from requirements.txt." \
      || err "pip install had errors (continuing)."
  else
    "$VENV/bin/pip" install $PIP_PKGS && ok "Deps installed: $PIP_PKGS." \
      || err "pip install had errors (continuing)."
  fi
else
  warn "Skipped venv/deps."
fi

# ---------- 4) config (.env) + connection test ----------
step "4) Configuration (.env) & connection test"
# Secrets the bot reads (see config.py):
#   TELEGRAM_BOT_TOKEN (required) — @BotFather
#   ANTHROPIC_API_KEY  (required) — console.anthropic.com  (text parsing)
#   OPENAI_API_KEY     (required for voice) — platform.openai.com (speech-to-text)
# This step ASKS for each and TESTS the connection before saving.
ENV_FILE="$DEST/.env"

ask_secret(){  # ask_secret "prompt" -> echoes typed value (hidden input, fd 3)
  local q="$1" ans=""
  if [[ "$ASSUME_YES" == "1" ]]; then echo ""; return; fi
  read -rsp "$(echo -e "${Y}[?]${N} $q ")" -u 3 ans || ans=""
  echo >&2
  echo "$ans"
}
test_telegram(){  # $1=token
  local out
  out=$(curl -fsS --max-time 15 "https://api.telegram.org/bot$1/getMe" 2>/dev/null) || return 1
  echo "$out" | grep -q '"ok":true'
}
test_anthropic(){ # $1=key
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 \
    https://api.anthropic.com/v1/models \
    -H "x-api-key: $1" -H "anthropic-version: 2023-06-01" 2>/dev/null)
  [[ "$code" == "200" ]]
}
test_openai(){    # $1=key
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 \
    https://api.openai.com/v1/models -H "Authorization: Bearer $1" 2>/dev/null)
  [[ "$code" == "200" ]]
}

TELEGRAM_BOT_TOKEN=""; ANTHROPIC_API_KEY=""; OPENAI_API_KEY=""

if [[ -f "$ENV_FILE" ]] && ! ask ".env already exists at $ENV_FILE — overwrite it?" n; then
  info "Keeping existing .env; loading it to re-test the connections."
  set -a; . "$ENV_FILE"; set +a
else
  # --- Telegram bot token (required) ---
  while :; do
    TELEGRAM_BOT_TOKEN="$(ask_secret 'Telegram bot token (from @BotFather):')"
    if [[ -z "$TELEGRAM_BOT_TOKEN" ]]; then
      warn "Empty token — the bot cannot run without it."
      ask "Skip for now and fill .env manually?" n && break || continue
    fi
    info "Testing the Telegram token…"
    if test_telegram "$TELEGRAM_BOT_TOKEN"; then ok "Telegram token works — connected ✅"; break
    else err "Telegram rejected that token."; ask "Try a different token?" y || break; fi
  done
  # --- Anthropic API key (required) ---
  while :; do
    ANTHROPIC_API_KEY="$(ask_secret 'Anthropic API key (from console.anthropic.com):')"
    if [[ -z "$ANTHROPIC_API_KEY" ]]; then
      warn "Empty key — text parsing needs it."
      ask "Skip for now and fill .env manually?" n && break || continue
    fi
    info "Testing the Anthropic key…"
    if test_anthropic "$ANTHROPIC_API_KEY"; then ok "Anthropic key works — connected ✅"; break
    else err "Anthropic rejected that key (or no network)."; ask "Try a different key?" y || break; fi
  done
  # --- OpenAI API key (required for voice) ---
  while :; do
    OPENAI_API_KEY="$(ask_secret 'OpenAI API key (voice/speech-to-text, from platform.openai.com):')"
    if [[ -z "$OPENAI_API_KEY" ]]; then
      warn "Empty — voice features will be disabled (text still works)."
      ask "Skip the OpenAI key?" y && break || continue
    fi
    info "Testing the OpenAI key…"
    if test_openai "$OPENAI_API_KEY"; then ok "OpenAI key works — connected ✅"; break
    else err "OpenAI rejected that key (or no network)."; ask "Try a different key?" y || break; fi
  done
  # write .env
  umask 077
  cat > "$ENV_FILE" <<EOF
# robot-marketing secrets — do NOT commit this file.
OPENAI_API_KEY=${OPENAI_API_KEY}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}

# ---- Optional overrides (defaults shown) ----
# WEB_HOST=0.0.0.0
# WEB_PORT=8080
# WEB_PASSWORD=robot1234     # web dashboard password — CHANGE THIS
# MAX_EMPLOYEES=3
EOF
  chmod 600 "$ENV_FILE" 2>/dev/null || true
  ok "Saved $ENV_FILE (chmod 600)."
fi

# --- final connectivity summary ---
step "4b) Connection summary"
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && test_telegram "$TELEGRAM_BOT_TOKEN"; then
  ok "Telegram: connected ✅"
else warn "Telegram: NOT verified — check TELEGRAM_BOT_TOKEN in $ENV_FILE"; fi
if [[ -n "${ANTHROPIC_API_KEY:-}" ]] && test_anthropic "$ANTHROPIC_API_KEY"; then
  ok "Anthropic: connected ✅"
else warn "Anthropic: NOT verified — check ANTHROPIC_API_KEY in $ENV_FILE"; fi
if [[ -n "${OPENAI_API_KEY:-}" ]] && test_openai "$OPENAI_API_KEY"; then
  ok "OpenAI: connected ✅"
else warn "OpenAI: not set/verified — voice disabled (text still works)"; fi

# ---------- 5) systemd service (optional) ----------
step "5) systemd service (optional)"
UNIT_SRC="$DEST/robot-marketing.service"
if [[ ! -f "$UNIT_SRC" ]]; then
  warn "No robot-marketing.service found in repo — skipping."
elif ! command -v systemctl >/dev/null 2>&1; then
  warn "systemctl not available — skipping service install (run the bot manually instead)."
elif ask "Install & enable the systemd service (auto-start on boot)?" n; then
  # The shipped unit is hard-coded to /root/robot-marketing; rewrite paths to $DEST.
  TMP_UNIT="$(mktemp)"
  sed -e "s#/root/robot-marketing#$DEST#g" "$UNIT_SRC" > "$TMP_UNIT"
  $SUDO cp "$TMP_UNIT" /etc/systemd/system/robot-marketing.service && rm -f "$TMP_UNIT"
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now robot-marketing.service \
    && ok "Service installed & started (systemctl status robot-marketing)." \
    || err "Service enable/start had errors — check: journalctl -u robot-marketing"
else
  warn "Skipped systemd service."
fi

# ---------- 6) run / test ----------
step "6) Run / test"
ok "Installed. To run the bot manually:  $VENV/bin/python $DEST/bot.py"
info "  (web dashboard listens on WEB_PORT, default 8080)"
if ask "Run the bot now in the foreground for a quick test (Ctrl-C to stop)?" n; then
  if [[ ! -f "$DEST/.env" ]]; then
    warn "No .env found — fill in your secrets first. Skipping test run."
  else
    info "Starting bot… press Ctrl-C to stop."
    "$VENV/bin/python" "$DEST/bot.py" <&3
  fi
else
  info "You can run it anytime with:  $VENV/bin/python $DEST/bot.py"
fi

echo
ok "Done."
