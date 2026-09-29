#!/usr/bin/env bash
# The install-to-rollback journey, on demand: a maintainer runs this before a deploy, on a laptop with Docker.
# It is not part of CI. It takes about ten minutes and prints a pass/fail table.
#
#   scripts/journey-test.sh                     # build this checkout as the candidate (v9.9.9), start from the newest release
#   scripts/journey-test.sh --tag v0.3.0        # a published candidate release (its images and bundle must exist)
#   scripts/journey-test.sh --tag v0.3.0 --previous v0.2.5
#   scripts/journey-test.sh --keep              # leave the stack running afterwards
#
# What it does, in one throwaway install directory and Docker project (tico-journey), auth none:
#   1 install     the PREVIOUS release: its checksummed bundle unpacked, a .env, `docker compose up -d`
#   2 enroll      a runner container joins with a one-time code
#   3 bot turn    one BotOps turn answered by a fake `codex` (scripts/journey-fake-codex.py), through the real runner
#   4 restart     the server restarts; data, environment id and the runner survive
#   5 upgrade     "Update now" (POST /api/v2/system/update) moves the server to the candidate
#   6 rollback    the updater follows (docker compose up -d), then an update to an image that migrates the database and
#                 never turns healthy is rolled back, and the pre-update snapshot brings the database back
#   7 backup      docker/backup-test.sh on the candidate: MinIO and a file replica, wipe the volume, restore
#
# scripts/install.sh is Linux-and-root only (it installs Docker and writes /opt/tico), so this does what it does
# after the preflight, the same way: download the bundle and SHA256SUMS, check the checksum, unpack, write .env. The
# images are used from the local Docker cache (`docker pull` for a published tag), so the updater runs with
# TICO_UPDATER_PULL=never; the bundle download and replacement is real for --tag and skipped for the local build.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

CAND="" PREV="" KEEP=0 LOCAL=1
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) CAND="$2"; LOCAL=0; shift 2 ;;
    --previous) PREV="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    -h|--help) sed -n 2,26p "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
[ "$LOCAL" = 1 ] && CAND=v9.9.9
BROKEN=v9.9.8
RELEASES="${TICO_JOURNEY_RELEASES_URL:-https://github.com/ticoteam/tico/releases}"
SERVER_IMAGE=ghcr.io/ticoteam/tico RUNNER_IMAGE=ghcr.io/ticoteam/tico-runner UPDATER_IMAGE=ghcr.io/ticoteam/tico-updater
PROJECT=tico-journey NET=tico-journey_default RUNNER=journey-runner

for tool in docker curl python3; do command -v "$tool" >/dev/null || { echo "journey: $tool is required" >&2; exit 2; }; done
docker info >/dev/null 2>&1 || { echo "journey: the Docker daemon is not running" >&2; exit 2; }
if [ -z "$PREV" ]; then
  PREV="$(git tag -l 'v[0-9]*' --sort=-v:refname | grep -v -- - | grep -vx "$CAND" | head -n 1)"
  [ -n "$PREV" ] || { echo "journey: no previous release tag found; pass --previous" >&2; exit 2; }
fi

WORK="$(mktemp -d)"
DIR="$WORK/install"
mkdir -p "$DIR"
RESULTS=() STATE_ID="" FAILED=0

dc() { docker compose -p "$PROJECT" --project-directory "$DIR" "$@"; }
say() { printf '  %s\n' "$*"; }
retry() { local end=$((SECONDS + $1)); shift; until "$@" >/dev/null 2>&1; do [ "$SECONDS" -lt "$end" ] || return 1; sleep 2; done; }
api() {  # curl arguments; the owner token never leaves the server container
  dc exec -T server sh -c 'curl -fsS -H "Authorization: Bearer $(cat /data/local-owner.token)" -H "Content-Type: application/json" "$@"' sh "$@"
}
post() { local path=$1 body=$2; api -X POST -H "Idempotency-Key: j-$RANDOM$RANDOM$SECONDS" -d "$body" "http://127.0.0.1:8765/api/v2/$path"; }
get() { api "http://127.0.0.1:8765/api/v2/$1"; }
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
healthy() { dc exec -T server curl -fsS --max-time 3 http://127.0.0.1:8765/healthz; }
environment_id() { healthy | json 'd["environment_id"]'; }
server_tag() { dc ps -q server | xargs docker inspect --format '{{.Config.Image}}' | sed 's/.*://'; }
updater_on_candidate() { [ "$(dc ps -q updater | xargs docker inspect --format '{{.Config.Image}}' | sed 's/.*://')" = "$CAND" ]; }
sql() {  # a read-only query in the server's database; prints the first column of each row
  dc exec -T server python -c 'import sqlite3,sys
for row in sqlite3.connect("file:/data/hub.sqlite?mode=ro", uri=True).execute(sys.argv[1]): print(row[0])' "$1"
}

cleanup() {
  [ "$KEEP" = 1 ] && { echo "journey: kept the stack (docker compose -p $PROJECT --project-directory $DIR ...) and $RUNNER"; return; }
  dc down -v >/dev/null 2>&1
  docker rm -f "$RUNNER" tico-updater-swap >/dev/null 2>&1
  docker volume rm journey-runner >/dev/null 2>&1
  for v in v9.9.9 "$BROKEN"; do docker rmi "$SERVER_IMAGE:$v" "$RUNNER_IMAGE:$v" "$UPDATER_IMAGE:$v" >/dev/null 2>&1; done
  rm -rf "$WORK"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------------------------- steps

sha256_of() { if command -v sha256sum >/dev/null; then sha256sum "$1" | awk '{print $1}'; else shasum -a 256 "$1" | awk '{print $1}'; fi; }

step_install() {
  local bundle="tico-bundle-$PREV.tar.gz" want got
  curl -fsSL -o "$WORK/SHA256SUMS" "$RELEASES/download/$PREV/SHA256SUMS" && curl -fsSL -o "$WORK/$bundle" "$RELEASES/download/$PREV/$bundle" \
    || { say "could not download the $PREV bundle"; return 1; }
  want="$(awk -v f="$bundle" '{n=$2; sub(/^\*/,"",n)} n==f {print $1; exit}' "$WORK/SHA256SUMS")"
  got="$(sha256_of "$WORK/$bundle")"
  [ -n "$want" ] && [ "$got" = "$want" ] || { say "checksum mismatch for $bundle"; return 1; }
  tar -xzf "$WORK/$bundle" -C "$DIR" && printf '%s\n' "$PREV" > "$DIR/.bundle-version"
  cat > "$DIR/.env" <<EOF
TICO_COMPANY_NAME=Journey
TICO_OWNER_EMAIL=owner@example.com
TICO_AUTH_PROXY=none
COMPOSE_PROFILES=updater
TICO_UPDATER_URL=http://updater:8080
TICO_TAG=$PREV
EOF
  [ "$LOCAL" = 0 ] || echo "TICO_UPDATER_BUNDLE=never" >> "$DIR/.env"   # the candidate is a local build: no release to download
  # Kept out of the bundle's files, so the updater never replaces it: a private project, no host port, quick health limit.
  cat > "$DIR/compose.override.yaml" <<EOF
name: $PROJECT
services:
  server:
    ports: !override []
  updater:
    environment:
      TICO_UPDATER_PULL: never
      TICO_HEALTH_SECONDS: "60"
EOF
  say "pulling $PREV images"
  docker pull -q "$SERVER_IMAGE:$PREV" >/dev/null && docker pull -q "$UPDATER_IMAGE:$PREV" >/dev/null && docker pull -q "$RUNNER_IMAGE:$PREV" >/dev/null \
    || { say "the $PREV images are not available"; return 1; }
  dc up -d >/dev/null 2>&1 || { say "docker compose up failed"; return 1; }
  retry 180 healthy || { say "the server did not become healthy"; return 1; }
  STATE_ID="$(environment_id)"
  [ -n "$STATE_ID" ] && [ "$(server_tag)" = "$PREV" ]
}

step_enroll() {
  local operator code
  operator="$(get me | json 'd["actor"].split(":",1)[1]')"
  code="$(post enrollments "{\"operator\": \"$operator\"}" | json 'd["code"]')" || return 1
  docker rm -f "$RUNNER" >/dev/null 2>&1
  docker run -d --name "$RUNNER" --network "$NET" -e OPENAI_API_KEY=journey-fake -v journey-runner:/home/runner \
    "$RUNNER_IMAGE:$PREV" join --url http://server:8765 --code "$code" --label "Journey runner" >/dev/null || return 1
  retry 120 runner_online || { say "the runner did not come online"; return 1; }
}
runner_online() { get getting-started | json 'sys.exit(0 if any(i["id"]=="computer" and i["done"] for i in d["items"]) else 1)'; }
runner_id() { get operations | json 'd["machines"][0]["id"]'; }
last_seen() { sql "SELECT coalesce(max(last_seen),'') FROM runners WHERE revoked_at IS NULL"; }

step_turn() {
  local rid revision cid
  # The fake harness: a `codex` on the runner's PATH that speaks the app-server protocol. The runner finds it, the
  # OPENAI_API_KEY given above satisfies its sign-in check, and no model or network is involved.
  docker cp scripts/journey-fake-codex.py "$RUNNER:/usr/local/bin/codex" && docker exec -u root "$RUNNER" chmod 755 /usr/local/bin/codex || return 1
  revision="$(get providers | json 'd["revision"]')"
  api -X PUT -H "Idempotency-Key: j-$RANDOM$SECONDS" -d "{\"enabled\": [\"openai\"], \"runtime\": \"\", \"model\": \"\", \"expected_revision\": $revision}" \
    http://127.0.0.1:8765/api/v2/providers >/dev/null || { say "could not enable OpenAI"; return 1; }
  rid="$(runner_id)"
  post bots/botops/assignment "{\"runner_id\": \"$rid\", \"expected_generation\": 0}" >/dev/null || return 1
  revision="$(get bots | json '[b for b in d if b["slug"] == "botops"][0]["revision"]')" || return 1
  post bots/botops/definition "{\"status\": \"active\", \"expected_revision\": $revision}" >/dev/null || return 1
  retry 180 botops_ready || { say "BotOps never became ready on the runner"; return 1; }
  cid="$(post chat/botops '{"text": "journey ping"}' | json 'd["conversation"]["id"]')" || return 1
  echo "$cid" > "$WORK/conversation"
  retry 120 replied || { say "no reply from the fake harness"; return 1; }
}
botops_ready() { get operations | json 'sys.exit(0 if d["machines"][0]["readiness"]["bots"]["botops"]["ready"] else 1)'; }
replied() { get "conversations/$(cat "$WORK/conversation")/messages" | json 'sys.exit(0 if any(m["body"].startswith("journey-reply:") for m in d["messages"]) else 1)'; }
conversation_intact() { replied && [ "$(environment_id)" = "$STATE_ID" ]; }

step_restart() {
  local before
  before="$(last_seen)"
  dc restart server >/dev/null 2>&1 || return 1
  retry 120 healthy || { say "the server did not come back"; return 1; }
  conversation_intact || { say "the conversation or environment id changed"; return 1; }
  retry 120 seen_since "$before" || { say "the runner did not reconnect"; return 1; }
}
seen_since() { [[ "$(last_seen)" > "$1" ]]; }

update_state() { get system/update | json 'd["state"]'; }
run_update() {  # version -> waits for a final state; prints it
  local state end=$((SECONDS + 400))
  post system/update "{\"version\": \"$1\"}" >/dev/null || { echo request_failed; return; }
  sleep 3
  while [ "$SECONDS" -lt "$end" ]; do
    state="$(update_state 2>/dev/null || true)"
    case "$state" in healthy|rolled_back|failed) echo "$state"; return ;; esac
    sleep 3
  done
  echo timeout
}

step_upgrade() {
  local state
  if [ "$LOCAL" = 1 ]; then
    say "building the candidate images from this checkout"
    for target in "server:$SERVER_IMAGE" "runner:$RUNNER_IMAGE" "updater:$UPDATER_IMAGE"; do
      docker build -q --target "${target%%:*}" --build-arg "TICO_VERSION=$CAND" -t "${target#*:}:$CAND" . >/dev/null || { say "build failed"; return 1; }
    done
  else
    say "pulling the $CAND images"
    for image in "$SERVER_IMAGE" "$UPDATER_IMAGE" "$RUNNER_IMAGE"; do docker pull -q "$image:$CAND" >/dev/null || { say "$image:$CAND is not published"; return 1; }; done
  fi
  state="$(run_update "${CAND#v}")"
  [ "$state" = healthy ] || { say "the update ended in state $state: $(get system/update | json 'd["message"]')"; return 1; }
  retry 60 healthy && [ "$(server_tag)" = "$CAND" ] || { say "the server is not on $CAND"; return 1; }
  conversation_intact || { say "data did not survive the update"; return 1; }
  grep -q "^TICO_TAG=$CAND\$" "$DIR/.env" || { say ".env does not record $CAND"; return 1; }
}

step_rollback() {
  local state snapshot
  # What a host does after an update: the updater is only replaced by `docker compose up -d` (or, from this release on,
  # by itself after an update). Its new code is what has to do the rollback below.
  dc up -d >/dev/null 2>&1 || return 1
  retry 60 updater_on_candidate || { say "the updater is not on $CAND"; return 1; }
  retry 120 healthy || { say "the server is not healthy after docker compose up"; return 1; }
  # A "release" that migrates the database and then never serves: the case the snapshot exists for.
  printf 'FROM %s:%s\nENTRYPOINT ["python", "-c", "import sqlite3, time; c = sqlite3.connect(\\"/data/hub.sqlite\\"); c.execute(\\"CREATE TABLE journey_migrated(x)\\"); c.commit(); time.sleep(3600)"]\n' \
    "$SERVER_IMAGE" "$CAND" | docker build -q -t "$SERVER_IMAGE:$BROKEN" - >/dev/null || return 1
  state="$(run_update "${BROKEN#v}")"
  [ "$state" = rolled_back ] || { say "expected rolled_back, got $state"; return 1; }
  snapshot="$(get system/update | json 'd.get("snapshot","") + " " + str(d.get("restored"))')"
  [ "${snapshot##* }" = True ] || { say "the snapshot was not restored ($snapshot)"; return 1; }
  retry 90 healthy && [ "$(server_tag)" = "$CAND" ] || { say "the server is not back on $CAND"; return 1; }
  [ -z "$(sql "SELECT name FROM sqlite_master WHERE name='journey_migrated'")" ] || { say "the migration is still in the database"; return 1; }
  conversation_intact || { say "data did not survive the rollback"; return 1; }
  dc exec -T server sh -c 'ls /data/snapshots/pre-update-*.sqlite >/dev/null' || { say "no snapshot file in /data/snapshots"; return 1; }
}

step_backup() {
  [ -x docker/backup-test.sh ] || return 1
  # Its own project, network and MinIO; the candidate images are in the local cache by now.
  TICO_IMAGE="$SERVER_IMAGE" TICO_TAG="$CAND" docker/backup-test.sh > "$WORK/backup.log" 2>&1 || { tail -n 15 "$WORK/backup.log" | sed 's/^/    /'; return 1; }
}

# ---------------------------------------------------------------------------------------------- run

run_step() {  # label function; after a failure the rest are skipped
  local label=$1 fn=$2 start=$SECONDS
  printf '==> %s\n' "$label"
  if [ "$FAILED" = 1 ]; then RESULTS+=("$label|SKIP|0"); return; fi
  if "$fn"; then RESULTS+=("$label|PASS|$((SECONDS - start))")
  else RESULTS+=("$label|FAIL|$((SECONDS - start))"); FAILED=1; fi
}

printf 'journey: previous %s -> candidate %s (%s)\n' "$PREV" "$CAND" "$([ "$LOCAL" = 1 ] && echo "built from this checkout" || echo "published release")"
run_step "install $PREV (bundle, auth none)" step_install
run_step "enroll a runner with a one-time code" step_enroll
run_step "one bot turn through a fake harness" step_turn
run_step "restart the server" step_restart
run_step "upgrade $PREV -> $CAND" step_upgrade
run_step "roll back a bad update (snapshot restored)" step_rollback
FAILED=0   # the backup rehearsal builds its own stack; it does not depend on the steps above
run_step "backup, wipe and restore (MinIO + file replica)" step_backup

printf '\n%-52s %-6s %s\n' STEP RESULT SECONDS
status=0
for row in "${RESULTS[@]}"; do
  IFS='|' read -r label result secs <<<"$row"
  printf '%-52s %-6s %s\n' "$label" "$result" "$secs"
  [ "$result" = FAIL ] && status=1
done
exit "$status"
