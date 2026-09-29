#!/usr/bin/env bash
# Entry point of the runner image.
#   join --url https://tico.example.com --code <one-time code> --label "Build box"
#   run
# `join` enrolls this runner the first time and then runs it; every later start of the same volume
# skips the enrollment, so the same command can stay as the container's restart command.
set -euo pipefail

CONFIG="$HOME/runner.json"
# Two users (SECURITY.md, runner/isolation.py): started as root, this script and the supervisor own
# runner.json, the runner's state and the tools directory, and every process that runs bot code is `bot`.
BOT_UID=10003 BOT_GID=10003
LAYOUT="$HOME/.tico-two-user-layout"

die() { printf 'tico-runner: error: %s\n' "$*" >&2; exit 1; }
log() { printf 'tico-runner: %s\n' "$*"; }

as_bot() { setpriv --reuid="$BOT_UID" --regid="$BOT_GID" --clear-groups "$@"; }

have_caps() {  # CHOWN DAC_OVERRIDE KILL SETGID SETUID: what the supervisor keeps (docker/runner.compose.yaml)
  local mask bit
  mask=$((16#$(awk '/^CapEff:/ {print $2}' /proc/self/status)))
  for bit in 0 1 5 6 7; do [ $(( (mask >> bit) & 1 )) -eq 1 ] || return 1; done
}

# One time, and again whenever something new was put where the supervisor's files belong.
separate_users() {
  have_caps || die "started as root without the capabilities the runner needs: use the current runner.compose.yaml (user: \"0\", cap_add CHOWN DAC_OVERRIDE KILL SETGID SETUID)"
  if [ ! -e "$LAYOUT" ]; then
    log "moving this volume to the two-user layout (one time): the runner's login stays out of the bots' reach"
    chown -R -h "$BOT_UID:$BOT_GID" "$HOME"
    find "$HOME" -maxdepth 1 -type d -name 'state-*' -exec chown -R -h 0:0 {} + -exec chmod 0700 {} +
    [ ! -d "$HOME/tools" ] || chown -R -h 0:0 "$HOME/tools"
    : > "$LAYOUT"
  fi
  # The registration and what it opens belong to the supervisor alone. The home directory is sticky, so
  # a turn (group bot, may create files here) cannot delete or replace what root owns.
  chown 0:"$BOT_GID" "$HOME" && chmod 1770 "$HOME"
  local file
  for file in "$HOME"/runner.json "$HOME"/runner.json.*; do
    [ -f "$file" ] && [ ! -L "$file" ] && chown 0:0 "$file" && chmod 0600 "$file"
  done
  # What a turn works in: the workspace, its secrets and the model logins are the bot user's.
  as_bot mkdir -p "$HOME/workspace/secrets"
  as_bot chmod 0700 "$HOME/workspace" "$HOME/workspace/secrets"
  mkdir -p /run/tico-runner && chmod 0755 /run/tico-runner
  export TICO_RUNNER_BOT_UID="$BOT_UID" TICO_RUNNER_BOT_GID="$BOT_GID"
  ISOLATED=1
}

ISOLATED=0
if [ "$(id -u)" = 0 ]; then
  separate_users
elif [ -e "$LAYOUT" ]; then
  die "this volume is set up for two users (bots run apart from the runner's login): start the container as root with the capabilities in the current runner.compose.yaml"
fi

# ok, rejected (the server does not know this token) or unreachable (it may just be restarting)
registration() {
  python - "$CONFIG" <<'PY'
import json, sys
from clients.tico import APIError, Client
config = json.load(open(sys.argv[1]))
try:
    Client(config["url"], config["token"]).get("runners/assignments")
except APIError as exc:
    print("rejected" if exc.status in (401, 403) else "unreachable")
except OSError:
    print("unreachable")
else:
    print("ok")
PY
}

enroll() {  # url code label
  local url="$1" code="$2" label="$3" environment code_file
  environment="$(curl -fsS --max-time 10 "$url/healthz" 2>/dev/null | jq -r '.environment_id // empty' 2>/dev/null || true)"
  code_file="$(mktemp "$HOME/.enroll.XXXXXX")"
  jq -n --arg code "$code" '{code: $code}' > "$code_file"
  local attempt
  for attempt in 1 2 3 4 5 6; do
    if python -m runner --config "$CONFIG" enroll --url "$url" --code-file "$code_file" --label "$label" \
         --projects "$HOME/workspace" ${environment:+--environment "$environment"} >/dev/null; then
      # A container never has a checkout to pull: updating means a new image.
      python - "$CONFIG" <<'PY'
import json, sys
config = json.load(open(sys.argv[1]))
config["self_update"] = False
json.dump(config, open(sys.argv[1], "w"), indent=2)
PY
      rm -f "$code_file"   # single-use, but still not left lying around
      log "enrolled as $label"
      return 0
    fi
    # A code that was already used or has expired will not work on a retry; the server may just be starting.
    if [ -f "$CONFIG" ]; then rm -f "$code_file"; return 0; fi
    sleep $((attempt * 5))
  done
  rm -f "$code_file"
  die "could not enroll: check the URL, and that the code is unused and under 15 minutes old"
}

url="" code="" label="${TICO_RUNNER_LABEL:-$(uname -n)}"
mode="${1:-run}"
[ "$#" -eq 0 ] || shift
case "$mode" in
  join|run) ;;
  *) exec "$mode" "$@" ;;
esac
while [ "$#" -gt 0 ]; do
  case "$1" in
    --url) url="${2-}"; shift 2 ;;
    --code) code="${2-}"; shift 2 ;;
    --label) label="${2:?--label needs a value}"; shift 2 ;;
    *) die "unknown option $1 (join takes --url, --code and --label)" ;;
  esac
done

if [ -f "$CONFIG" ]; then
  case "$(registration)" in
    ok) log "already enrolled" ;;
    unreachable) log "the server is not answering; the runner will keep trying" ;;
    rejected)
      [ -n "$url" ] && [ -n "$code" ] || die "the server no longer knows this runner: join again with a new code"
      log "the server no longer knows this runner; enrolling again"
      mv "$CONFIG" "$CONFIG.stale"
      enroll "$url" "$code" "$label" ;;
  esac
else
  [ -n "$url" ] && [ -n "$code" ] || die "this runner is not enrolled: run it with  join --url <https://your-tico> --code <code> --label <name>"
  enroll "$url" "$code" "$label"
fi

as_user() { if [ "$ISOLATED" = 1 ]; then as_bot "$@"; else "$@"; fi; }
as_user git config --global user.name >/dev/null 2>&1 || as_user git config --global user.name "Tico runner"
as_user git config --global user.email >/dev/null 2>&1 || as_user git config --global user.email "tico-runner@$(uname -n)"
# The mail and calendar connectors have no checkout-sibling layout here: point them at the volume. The venv
# is built into the volume on first use (scripts/mail.sh), so the image stays slim and it survives restarts.
export TICO_PROJECTS_DIR="${TICO_PROJECTS_DIR:-$HOME/workspace}"
export TICO_MAIL_VENV="${TICO_MAIL_VENV:-${TICO_TOOLS_DIR:-$HOME/tools}/mail-venv}"
export TICO_SUPERVISED=1 TICO_RUNNER_SELF_UPDATE=0
# The runner also supervises the meeting-importer and Close jobs the hub assigns here (runner/sidejobs.py).
export TICO_SIDE_JOBS="${TICO_SIDE_JOBS:-1}"
exec python -m runner --config "$CONFIG" run
