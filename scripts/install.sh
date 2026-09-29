#!/bin/sh
# Installs Tico on this Linux server: Docker if missing, the compose bundle of one exact release, then the
# `tico setup` wizard. Safe to run again: it upgrades or repairs and never rewrites an existing .env.
#
#   curl -fsSL https://github.com/ticoteam/tico/releases/download/vX.Y.Z/install.sh | sh
#   sh install.sh [--version vX.Y.Z] [--dir /opt/tico] [--yes] [--tunnel] [--docker-only] [-- wizard flags]
#   sh install.sh --runner --url https://tico.example.com --code <code> --label "Build box" [--version vX.Y.Z]
#
# --runner sets up a computer that runs bots for a Tico server instead: Docker, that release's runner.compose.yaml (the
# runner and its updater sidecar, both pinned to the release) in /opt/tico-runner, a .env with the join settings, and
# `docker compose up -d`. The sidecar is what keeps the runner on the server's release.
#
# Everything after `--` goes to `tico setup` (python3 -m setup), so automation can answer its questions with flags
# and environment variables (secrets only ever by environment). Exit codes: 0 done, 2 usage, 3 this machine does not
# qualify, 4 download or checksum failed, 5 Docker or Python setup failed, 6 the wizard or the health check failed.
set -eu

# The release workflow replaces the placeholder with the tag; on main it stays and the newest release is looked up.
TICO_VERSION_BAKED='@TICO_VERSION@'
REPO=ticoteam/tico
# TICO_INSTALL_* variables below exist so tests can run this script against local files and fake hosts.
RELEASES=${TICO_INSTALL_RELEASES_URL:-https://github.com/$REPO/releases}
LATEST_API=${TICO_INSTALL_LATEST_URL:-https://api.github.com/repos/$REPO/releases/latest}
OS_RELEASE=${TICO_INSTALL_OS_RELEASE:-/etc/os-release}
MEMINFO=${TICO_INSTALL_MEMINFO:-/proc/meminfo}
HEALTH_URL=${TICO_INSTALL_HEALTH_URL:-http://127.0.0.1:8765/healthz}
HEALTH_TRIES=${TICO_INSTALL_HEALTH_TRIES:-60}

MIN_MEM_KB=900000   # a 1 GB machine reports a little under 1,000,000 kB
MIN_DISK_KB=1000000
VERSION_RE='^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$'

DIR=${TICO_INSTALL_DIR:-/opt/tico}
VERSION=
FORCED=
YES=
TUNNEL=
DOCKER_ONLY=
RUNNER=
RUNNER_URL=
RUNNER_CODE=
RUNNER_LABEL=
SERVER_NETWORK=
DIR_GIVEN=${TICO_INSTALL_DIR:+1}

say() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() { code=$1; shift; printf 'error: %s\n' "$*" >&2; exit "$code"; }

usage() {
  cat <<'EOF'
Usage: install.sh [options] [-- tico-setup flags]

  --version vX.Y.Z   install this release (default: the release this script came from)
  --dir PATH         install directory (default /opt/tico)
  --yes, -y          do not ask for confirmation
  --tunnel           Cloudflare Tunnel: no public ports needed, so ports 80 and 443 are not checked
  --docker-only      only make sure Docker and Compose are installed (used for runner boxes)
  --runner           set up a computer that runs bots for a Tico server (Docker Compose, with the updater sidecar)
  --url URL          with --runner: the Tico server, such as https://tico.example.com
  --code CODE        with --runner: the one-time code from Settings > Devices > Add computer (15 minutes, single use)
  --label NAME       with --runner: the computer's name in Tico (default: this host's name)
  --server-network N with --runner on the server's own machine: join its Docker network N (usually tico_default) and
                     use --url http://server:8765, so the runner never goes through Cloudflare Access
  --help, -h         this text

Run it again any time: with an existing .env it upgrades to --version or repairs and restarts, and leaves
your settings alone. Flags after -- go to the wizard (python3 -m setup --help).
EOF
}

as_root() {
  if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi
}

while [ $# -gt 0 ]; do
  case $1 in
    --version) [ $# -ge 2 ] || { usage >&2; die 2 "--version needs a value"; }; VERSION=$2; FORCED=1; shift 2 ;;
    --version=*) VERSION=${1#--version=}; FORCED=1; shift ;;
    --dir) [ $# -ge 2 ] || { usage >&2; die 2 "--dir needs a value"; }; DIR=$2; DIR_GIVEN=1; shift 2 ;;
    --dir=*) DIR=${1#--dir=}; DIR_GIVEN=1; shift ;;
    --runner) RUNNER=1; shift ;;
    --url) [ $# -ge 2 ] || { usage >&2; die 2 "--url needs a value"; }; RUNNER_URL=$2; shift 2 ;;
    --url=*) RUNNER_URL=${1#--url=}; shift ;;
    --code) [ $# -ge 2 ] || { usage >&2; die 2 "--code needs a value"; }; RUNNER_CODE=$2; shift 2 ;;
    --code=*) RUNNER_CODE=${1#--code=}; shift ;;
    --label) [ $# -ge 2 ] || { usage >&2; die 2 "--label needs a value"; }; RUNNER_LABEL=$2; shift 2 ;;
    --label=*) RUNNER_LABEL=${1#--label=}; shift ;;
    --server-network) [ $# -ge 2 ] || { usage >&2; die 2 "--server-network needs a value"; }; SERVER_NETWORK=$2; shift 2 ;;
    --server-network=*) SERVER_NETWORK=${1#--server-network=}; shift ;;
    --yes|-y) YES=1; shift ;;
    --tunnel) TUNNEL=1; shift ;;
    --docker-only) DOCKER_ONLY=1; shift ;;
    --help|-h) usage; exit 0 ;;
    --) shift; break ;;
    *) usage >&2; die 2 "unknown option: $1" ;;
  esac
done

[ -n "$RUNNER" ] && [ -z "$DIR_GIVEN" ] && DIR=/opt/tico-runner
if [ -n "$RUNNER" ]; then
  # These reach a file and a command line, so only plain values are taken.
  [ -z "$TUNNEL$DOCKER_ONLY" ] || die 2 "--runner cannot be combined with --tunnel or --docker-only."
  printf '%s' "$RUNNER_URL" | grep -Eq '^https?://[A-Za-z0-9.-]+(:[0-9]+)?$' || { usage >&2; die 2 "--runner needs --url https://your-tico-server (no path)."; }
  printf '%s' "$RUNNER_CODE" | grep -Eq '^[A-Za-z0-9_-]+$' || { usage >&2; die 2 "--runner needs --code, the one-time code from Settings > Devices > Add computer."; }
  [ -n "$RUNNER_LABEL" ] || RUNNER_LABEL=$(hostname 2>/dev/null || echo runner)
  printf '%s' "$RUNNER_LABEL" | grep -Eq '^[^"$`\\]{1,80}$' || die 2 "--label is 1 to 80 characters without quotes, dollar signs, backticks or backslashes."
fi
printf '%s' "$DIR" | grep -Eq '^/[A-Za-z0-9._/-]+$' || die 2 "--dir must be an absolute path made of letters, digits and . _ - /"

# ---------------------------------------------------------------------------------------------- preflight

preflight() {
  step "Checking this machine"
  [ "$(uname -s)" = Linux ] || die 3 "Tico installs on Linux servers only (this is $(uname -s))."
  case $(uname -m) in
    x86_64|amd64) arch=amd64 ;;
    aarch64|arm64) arch=arm64 ;;
    *) die 3 "Unsupported CPU $(uname -m): the images are built for x86_64 and arm64." ;;
  esac
  if [ "$(id -u)" != 0 ]; then
    command -v sudo >/dev/null 2>&1 || die 3 "Run this as root, or install sudo: it needs to install Docker and write $DIR."
    if ! sudo -n true 2>/dev/null; then
      say "This needs administrator rights; sudo may ask for your password."
      # A piped script has no stdin, so ask on the terminal.
      # shellcheck disable=SC2024  # the terminal is read by this user's shell on purpose
      if ( : </dev/tty ) 2>/dev/null; then sudo -v </dev/tty || die 3 "sudo did not accept the password."
      else die 3 "sudo needs a password and there is no terminal. Run as root or with passwordless sudo."; fi
    fi
  fi
  mem_kb=$(awk '/^MemTotal:/ {print $2}' "$MEMINFO" 2>/dev/null || true)
  [ -n "${mem_kb:-}" ] || die 3 "Could not read the memory size from $MEMINFO."
  [ "$mem_kb" -ge "$MIN_MEM_KB" ] || die 3 "Needs at least 1 GB of memory (this machine has $((mem_kb / 1024)) MB); 2 GB is comfortable."
  probe=$DIR
  while [ ! -d "$probe" ]; do probe=$(dirname "$probe"); done
  disk_kb=$(df -Pk "$probe" | awk 'NR==2 {print $4}')
  [ "${disk_kb:-0}" -ge "$MIN_DISK_KB" ] || die 3 "Needs at least 1 GB of free disk under $probe (found $((${disk_kb:-0} / 1024)) MB); the images alone are about 0.6 GB."
  if [ -z "$TUNNEL" ] && [ -z "$DOCKER_ONLY" ] && [ -z "$RUNNER" ] && [ ! -f "$DIR/.env" ]; then
    for port in 80 443; do
      if port_busy "$port"; then
        die 3 "Port $port is already in use, and Tico's HTTPS front door needs it. Stop what listens there, or use --tunnel (Cloudflare Tunnel needs no open ports)."
      fi
    done
  fi
  say "ok: Linux $arch, $((mem_kb / 1024)) MB memory, $((disk_kb / 1024)) MB free disk"
}

port_busy() {
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | awk -v p=":$1" '$1 == "LISTEN" && $4 ~ (p "$") {f = 1} END {exit !f}'
  else
    warn "ss is not installed, so port $1 was not checked."
    return 1
  fi
}

# ---------------------------------------------------------------------------------------------- packages

pkg_install() {
  if command -v apt-get >/dev/null 2>&1; then
    as_root env DEBIAN_FRONTEND=noninteractive apt-get update -qq
    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@"
  elif command -v dnf >/dev/null 2>&1; then
    as_root dnf install -y -q "$@"
  elif command -v yum >/dev/null 2>&1; then
    as_root yum install -y -q "$@"
  else
    return 1
  fi
}

need_tool() {
  command -v "$1" >/dev/null 2>&1 && return 0
  say "Installing $1 ..."
  pkg_install "$2" >/dev/null || die 5 "Could not install $2. Install it and run this again."
}

# shellcheck disable=SC1090
os_field() { ( . "$OS_RELEASE" 2>/dev/null; eval "printf '%s' \"\${$1:-}\"" ); }

compose_ok() {
  command -v docker >/dev/null 2>&1 || return 1
  v=$(as_root docker compose version --short 2>/dev/null) || return 1
  v=${v#v}
  [ "$(printf '%s\n%s\n' 2.20.0 "$v" | sort -V | head -n 1)" = 2.20.0 ]
}

# Docker's documented method for Debian and Ubuntu is its own apt repository; the get.docker.com convenience
# script is their fallback for other distributions.
install_docker() {
  step "Installing Docker"
  id=$(os_field ID)
  like=$(os_field ID_LIKE)
  case " $id $like " in
    *" ubuntu "*) family=ubuntu; codename=$(os_field UBUNTU_CODENAME) ;;
    *" debian "*) family=debian; codename=$(os_field VERSION_CODENAME) ;;
    *) family= ;;
  esac
  [ "$id" = ubuntu ] && family=ubuntu
  [ "$id" = debian ] && family=debian
  [ -n "$family" ] && [ -z "$codename" ] && codename=$(os_field VERSION_CODENAME)
  if [ -n "$family" ] && [ -n "$codename" ] && command -v apt-get >/dev/null 2>&1; then
    need_tool curl curl
    pkg_install ca-certificates >/dev/null || die 5 "Could not install ca-certificates."
    as_root install -m 0755 -d /etc/apt/keyrings
    as_root curl -fsSL "https://download.docker.com/linux/$family/gpg" -o /etc/apt/keyrings/docker.asc \
      || die 5 "Could not download Docker's signing key."
    as_root chmod a+r /etc/apt/keyrings/docker.asc
    printf 'Types: deb\nURIs: https://download.docker.com/linux/%s\nSuites: %s\nComponents: stable\nSigned-By: /etc/apt/keyrings/docker.asc\n' \
      "$family" "$codename" | as_root tee /etc/apt/sources.list.d/docker.sources >/dev/null
    pkg_install docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null \
      || die 5 "Installing Docker from Docker's apt repository failed. See https://docs.docker.com/engine/install/ and run this again."
  else
    warn "No Docker package repository is set up for this distribution ($id); using Docker's convenience script."
    need_tool curl curl
    tmp_docker=$(mktemp)
    curl -fsSL https://get.docker.com -o "$tmp_docker" || { rm -f "$tmp_docker"; die 5 "Could not download get.docker.com."; }
    as_root sh "$tmp_docker" >/dev/null || { rm -f "$tmp_docker"; die 5 "Docker's install script failed. See https://docs.docker.com/engine/install/ and run this again."; }
    rm -f "$tmp_docker"
  fi
}

ensure_docker() {
  step "Docker"
  if ! compose_ok; then install_docker; fi
  if ! as_root docker info >/dev/null 2>&1; then
    if command -v systemctl >/dev/null 2>&1; then as_root systemctl enable --now docker >/dev/null 2>&1 || true; fi
    as_root docker info >/dev/null 2>&1 || die 5 "The Docker daemon is not running. Start it (systemctl start docker) and run this again."
  else
    if command -v systemctl >/dev/null 2>&1; then as_root systemctl enable docker >/dev/null 2>&1 || true; fi
  fi
  compose_ok || die 5 "Docker is installed but the Compose plugin (v2.20 or newer) is not. Install docker-compose-plugin and run this again."
  say "ok: Docker $(as_root docker version --format '{{.Server.Version}}' 2>/dev/null || echo installed), Compose $(as_root docker compose version --short)"
}

ensure_python() {
  py_ok() { command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; }
  py_ok && return 0
  step "Python 3"
  pkg_install python3 >/dev/null || true
  py_ok || die 5 "The setup wizard needs Python 3.10 or newer. Install python3 and run this again."
}

# ---------------------------------------------------------------------------------------------- the release

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}

resolve_version() {
  if [ -z "$VERSION" ]; then
    case $TICO_VERSION_BAKED in
      @*) # Not built by a release: main's copy of this script.
        need_tool curl curl
        VERSION=$(curl -fsSL --retry 3 "$LATEST_API" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1) || true
        [ -n "$VERSION" ] || die 4 "Could not look up the latest release. Pass --version vX.Y.Z."
        warn "This copy of install.sh is not pinned to a release; using the latest, $VERSION." ;;
      *) VERSION=$TICO_VERSION_BAKED ;;
    esac
  fi
  case $VERSION in v*) ;; *) VERSION=v$VERSION ;; esac
  printf '%s' "$VERSION" | grep -Eq "$VERSION_RE" || die 2 "Version must look like v1.2.3, not '$VERSION'."
}

installed_version() { sed -n 's/^TICO_TAG=//p' "$DIR/.env" 2>/dev/null | head -n 1; }

fetch_bundle() {
  step "Downloading Tico $VERSION"
  need_tool curl curl
  work=$(mktemp -d)
  trap 'rm -rf "$work"' EXIT
  trap 'exit 130' INT TERM
  bundle=tico-bundle-$VERSION.tar.gz
  base=$RELEASES/download/$VERSION
  curl -fsSL --retry 3 -o "$work/SHA256SUMS" "$base/SHA256SUMS" || die 4 "Could not download $base/SHA256SUMS. Is $VERSION a published release?"
  curl -fsSL --retry 3 -o "$work/$bundle" "$base/$bundle" || die 4 "Could not download $base/$bundle."
  want=$(awk -v f="$bundle" '{n = $2; sub(/^\*/, "", n)} n == f {print $1; exit}' "$work/SHA256SUMS")
  [ -n "$want" ] || die 4 "SHA256SUMS does not list $bundle; refusing to use it."
  got=$(sha256_of "$work/$bundle")
  [ "$got" = "$want" ] || die 4 "Checksum mismatch for $bundle (expected $want, got $got). Nothing was installed."
  # A bundle is ours, but never let an archive write outside the install directory.
  if tar -tzf "$work/$bundle" | grep -Eq '(^|/)\.\.(/|$)|^/'; then die 4 "The bundle has unsafe paths; refusing to unpack it."; fi
  say "ok: $bundle matches SHA256SUMS"

  as_root install -d -m 0755 "$DIR"
  if [ -n "$RUNNER" ]; then
    # A runner needs the compose file and nothing else; the server's compose.yaml stays out of this directory.
    tar -xzf "$work/$bundle" -C "$work" docker/runner.compose.yaml || die 4 "$bundle has no docker/runner.compose.yaml."
    as_root install -m 0644 "$work/docker/runner.compose.yaml" "$DIR/runner.compose.yaml"
    printf '%s\n' "$VERSION" | as_root tee "$DIR/.bundle-version" >/dev/null
    say "ok: runner.compose.yaml for $VERSION is in $DIR"
    return 0
  fi
  [ -f "$DIR/compose.yaml" ] && as_root cp "$DIR/compose.yaml" "$DIR/compose.yaml.previous"
  as_root rm -rf "$DIR/setup"
  as_root tar -xzf "$work/$bundle" -C "$DIR" --no-same-owner
  printf '%s\n' "$VERSION" | as_root tee "$DIR/.bundle-version" >/dev/null
  say "ok: unpacked into $DIR"
}

pin_tag() {
  # Only the TICO_TAG line changes; every other setting in .env is kept as it is.
  as_root sh -c "umask 077; { grep -v '^TICO_TAG=' '$DIR/.env' || true; printf 'TICO_TAG=%s\n' '$VERSION'; } > '$DIR/.env.new' && chmod 600 '$DIR/.env.new' && mv '$DIR/.env.new' '$DIR/.env'"
}

start_stack() {
  step "Starting Tico"
  ( cd "$DIR" && as_root docker compose pull --quiet && as_root docker compose up -d ) || die 6 "docker compose failed in $DIR. Run 'docker compose logs' there."
  i=0
  while [ "$i" -lt "$HEALTH_TRIES" ]; do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then say "ok: the server answers on $HEALTH_URL"; return 0; fi
    i=$((i + 1)); sleep 5
  done
  die 6 "The server did not become healthy. Look at: cd $DIR && docker compose logs server"
}

run_wizard() {
  step "Setting up your company"
  ensure_python
  extra=
  [ -n "$TUNNEL" ] && extra="--front-door cloudflared"
  [ -n "$YES" ] && extra="$extra --yes"
  state_dir=$DIR/.setup
  as_root install -d -m 0700 "$state_dir"
  # A wizard that cannot ask (no terminal) needs its answers as flags; say so instead of failing halfway.
  if ( : </dev/tty ) 2>/dev/null; then tty_in=/dev/tty; else tty_in=; fi
  if [ -z "$tty_in" ] && ! printf '%s ' "$@" | grep -q -- '--non-interactive'; then
    set -- --non-interactive "$@"
    warn "No terminal to ask questions on; the wizard runs with flags only (see 'python3 -m setup --help')."
  fi
  # $extra is a fixed list of flags built above, never user text, so splitting it is intended.
  # shellcheck disable=SC2086
  set -- --target local --tico-version "$VERSION" $extra "$@"
  cd "$DIR"
  if [ "$(id -u)" = 0 ]; then
    if [ -n "$tty_in" ]; then TICO_INSTALL_DIR=$DIR TICO_SETUP_HOME=$state_dir python3 -m setup "$@" <"$tty_in"
    else TICO_INSTALL_DIR=$DIR TICO_SETUP_HOME=$state_dir python3 -m setup "$@" </dev/null; fi
  else
    keep=
    for v in TICO_OIDC_CLIENT_SECRET CLOUDFLARE_API_TOKEN CLOUDFLARE_TUNNEL_TOKEN OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY \
             LITESTREAM_ACCESS_KEY_ID LITESTREAM_SECRET_ACCESS_KEY AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN; do
      eval "[ -n \"\${$v:-}\" ]" && keep="$keep,$v"
    done
    # sudo drops the environment, so the secrets the caller set are kept by name; their values never reach a command line.
    # shellcheck disable=SC2024  # same: the terminal is opened by this shell, not by root
    if [ -n "$tty_in" ]; then
      sudo -H "--preserve-env=TICO_INSTALL_DIR,TICO_SETUP_HOME$keep" env TICO_INSTALL_DIR="$DIR" TICO_SETUP_HOME="$state_dir" python3 -m setup "$@" <"$tty_in"
    else
      sudo -H "--preserve-env=TICO_INSTALL_DIR,TICO_SETUP_HOME$keep" env TICO_INSTALL_DIR="$DIR" TICO_SETUP_HOME="$state_dir" python3 -m setup "$@" </dev/null
    fi
  fi
}

# A runner started with a bare `docker run -v tico-runner:/home/runner` keeps its login and repositories in that
# volume. The compose file can use the same volume, so switching to it keeps the enrolled runner instead of making a second.
runner_env() {
  volume_line=
  if as_root docker volume inspect tico-runner >/dev/null 2>&1; then
    volume_line=TICO_RUNNER_HOME_VOLUME=tico-runner
    say "Found the tico-runner volume of an earlier docker run: the runner keeps its login, its repositories and its enrollment."
  fi
  env_tmp=$work_env
  ( umask 077
    { printf 'TICO_URL=%s\n' "$RUNNER_URL"
      printf 'TICO_CODE=%s\n' "$RUNNER_CODE"
      printf 'TICO_RUNNER_LABEL="%s"\n' "$RUNNER_LABEL"
      printf 'TICO_TAG=%s\nTICO_UPDATER_TAG=%s\n' "$VERSION" "$VERSION"
      [ -z "$volume_line" ] || printf '%s\n' "$volume_line"
    } > "$env_tmp" )
  as_root install -m 0600 "$env_tmp" "$DIR/.env"
  rm -f "$env_tmp"
}

run_runner() {
  fetch_bundle
  step "Setting up the runner"
  if [ -f "$DIR/.env" ]; then
    say "Keeping the settings in $DIR/.env."
    if [ -n "$FORCED" ]; then
      as_root sh -c "umask 077; { grep -v -e '^TICO_TAG=' -e '^TICO_UPDATER_TAG=' '$DIR/.env' || true; printf 'TICO_TAG=%s\nTICO_UPDATER_TAG=%s\n' '$VERSION' '$VERSION'; } > '$DIR/.env.new' && mv '$DIR/.env.new' '$DIR/.env'"
    fi
  else
    work_env=$(mktemp)
    runner_env
  fi
  # The bare container has the name compose wants; the volume it used stays.
  if as_root docker container inspect tico-runner >/dev/null 2>&1 \
     && [ -z "$(as_root docker container inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' tico-runner 2>/dev/null)" ]; then
    say "Replacing the container from an earlier docker run (its volume is kept)."
    as_root docker rm -f tico-runner >/dev/null
  fi
  if [ -n "$SERVER_NETWORK" ]; then
    printf '%s' "$SERVER_NETWORK" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$' || die 2 "--server-network is a Docker network name."
    as_root docker network inspect "$SERVER_NETWORK" >/dev/null 2>&1 || die 2 "No Docker network $SERVER_NETWORK on this machine (the server's is usually tico_default)."
    # Not part of the bundle, so an update keeps it; the updater adds it to its compose calls.
    printf 'services:\n  runner:\n    networks: [default, server]\nnetworks:\n  server:\n    external: true\n    name: %s\n' "$SERVER_NETWORK" \
      | as_root tee "$DIR/runner.override.yaml" >/dev/null
  fi
  files="-f runner.compose.yaml"
  [ -f "$DIR/runner.override.yaml" ] && files="$files -f runner.override.yaml"
  # shellcheck disable=SC2086  # $files is two or four words on purpose
  ( cd "$DIR" && as_root docker compose $files pull --quiet && as_root docker compose $files up -d ) \
    || die 6 "docker compose failed in $DIR. Run 'docker compose $files logs' there."
  say ""
  say "The runner is starting and joins $RUNNER_URL as \"$RUNNER_LABEL\"; it shows online in Settings > Devices in a minute."
  say "It follows the server's release through its updater; sign the bots in to a model from Settings > Devices."
}

# ---------------------------------------------------------------------------------------------- main

preflight
if [ -n "$RUNNER" ]; then resolve_version; ensure_docker; run_runner; exit 0; fi
if [ -n "$DOCKER_ONLY" ]; then ensure_docker; say "Docker is ready."; exit 0; fi
# A bad version should fail before anything is installed.
resolve_version
ensure_docker
say "Installing Tico $VERSION into $DIR"

if [ -f "$DIR/.env" ]; then
  have=$(installed_version)
  if [ -n "$have" ] && [ "$have" != "$VERSION" ] && [ -z "$FORCED" ] \
     && [ "$(printf '%s\n%s\n' "$have" "$VERSION" | sort -V | tail -n 1)" = "$have" ]; then
    # The one-click updater moves TICO_TAG ahead of a pinned installer; an old installer must not undo that.
    say "Installed $have is newer than this installer ($VERSION): repairing it as it is. Pass --version to change it."
    VERSION=$have
  else
    fetch_bundle
    if [ "$have" != "$VERSION" ]; then
      say "Changing the installed release from ${have:-unknown} to $VERSION; your .env is kept."
      pin_tag
    else
      say "Already at $VERSION: repairing and restarting; your .env is kept."
    fi
  fi
  start_stack
  say ""
  say "Tico $VERSION is running from $DIR."
  exit 0
fi

fetch_bundle
run_wizard "$@" || die 6 "The setup wizard did not finish. Run this again: it resumes where it stopped, and finished steps are skipped."
say ""
say "Next: add the computers that run your bots (Settings > Devices > Add computer in the app)."
say "Later checks: cd $DIR && sudo ./scripts/tico-setup doctor --domain <your domain>"
