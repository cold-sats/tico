# Updates: the server and its computers

A Tico installation is a server plus the computers that run its bots (a Mac, or a Linux box with the
`tico-runner` container). The server updates from Settings ("Update now", see [install.md](install.md#one-click-updates))
or with `docker compose pull && docker compose up -d`. **Computers follow the server**: each one asks its server
which release it runs and moves to that release. GitHub is not consulted by a computer, so a server you have not
updated never drags its computers ahead of it.

## How they relate

- The server knows its release (`GET /api/v2/runners/desired` returns it, and Settings > Devices shows it) and the
  oldest computer release it accepts, `MIN_RUNNER_RELEASE` in `backend/runner_versions.py`. The release that changes
  the contract between runner and server raises that number.
- Every heartbeat carries the computer's release, its kind (`mac`, `linux` or `docker`) and how its update stands.
  **Settings > Health** and **Settings > Devices** show one state per computer:

  | State | Meaning |
  |---|---|
  | Up to date | on the server's release, or newer |
  | Updating | switching now; it takes no new work meanwhile |
  | Needs update | older than the server but still accepted. It updates when no turn is running, or it says why it cannot (pinned, local changes, no updater) next to the last update error |
  | Incompatible (bots paused) | older than the minimum. It takes no work, and says why, instead of failing turns. Its queued work waits and runs after it updates |
  | Version not reported | a computer that predates this, or a development build. It is never paused |

- A server that is a development build (no release) has nothing to compare, so computers keep following `main` as
  before and Settings > Health shows no version line. A computer talking to a server from before this existed does the same.

## A Mac (or Linux checkout)

The runner is a git checkout. When the server's release is newer, the runner:

1. stops taking new work and waits until no turn is running (after 20 minutes it stops claiming so a long turn
   cannot hold the update back for ever; it never interrupts one);
2. starts a separate update process, which fetches the tag `vX.Y.Z` from `origin` (the public repository) and
   checks that it exists and is not a tag that moved, then checks out that commit (detached);
3. re-runs the install step: `pip install -r backend/requirements.txt` when the release changed it;
4. restarts the runner through its supervisor (launchd `KeepAlive`) and waits up to three
   minutes for the new process to report in;
5. if it does not, checks the old commit out again, restores the old dependencies, restarts and reports
   `rolled_back` (or `failed` if the old code does not start either). It does not retry that release for six hours,
   or until the server's release changes.
6. once the runner is healthy on the new release, restarts the helper jobs that are installed on this Mac
   (`connectors`, `close-calls`, `importers`; the same `launchctl kickstart -k` as `scripts/tico restart`), so none keeps
   the old release in memory. A helper that is not installed is left alone. Each helper also checks the checkout's
   revision about once a minute and exits when it changes, so launchd starts it on the new code even after a
   `scripts/tico update` or a pull by hand. Each restart is a line in the job's log
   (`scripts/tico logs connectors`) and in `update.log`. A Docker runner replaces its container, helpers included.

A checkout with uncommitted changes, or on a branch other than `main`, is **refused, never touched**: nothing is
stashed, reset or discarded. Settings > Health and Devices show "the checkout has 2 changed files" until someone commits or
stashes them. The update process logs to `state-<runner id>/update.log`; the outcome is in `update-status.json` next
to it. `scripts/tico update` still works by hand and still follows `main`.

## The server's own updater

The server's `updater` service is pinned to the same release as the server (`TICO_UPDATER_TAG`, which defaults to
`TICO_TAG`). "Update now" first downloads that release's `tico-bundle-vX.Y.Z.tar.gz` and `SHA256SUMS` (the files
`install.sh` uses), checks the checksum, and only then replaces the bundle in the install directory (`compose.yaml`,
`.env.example`, `docker/runner.compose.yaml`, `setup/`, and so on) file by file with atomic renames, so new settings and
services that need a compose change reach existing installs. `.env` is never replaced (only its `TICO_TAG` line moves).
The previous files are kept in `.bundle-previous/`. A download or checksum failure refuses the update before anything
changes; a release that does not turn healthy is rolled back, image and bundle together. Slack and the front door are
recreated from the new file when it changes them.

Before it switches the server image, the updater takes a consistent SQLite snapshot (`sqlite3` backup API, run in the
server container) into `/data/snapshots/pre-update-<version>-<time>.sqlite` and keeps the last three. A new version can
migrate the database and then fail its health check, and the old image cannot read a newer schema, so a rollback also
stops the server (Litestream runs inside it), puts the snapshot back through a temporary file, clears Litestream's tracking directory so it does not take the restored file for a break (the migrated database stays beside it as `hub.sqlite.failed-update`) and starts
the old image. Changes made between the snapshot and the rollback are not in it. The update status says which snapshot
was taken and whether it was restored (`snapshot`, `restored`, and the message). If the snapshot cannot be taken the
update does not go ahead.

After a successful update the updater replaces itself, so updater fixes reach existing installs. It pulls the new updater
image and starts a short-lived helper container (`tico-updater-swap`) from it, which recreates the `updater` service,
checks that the new one stays running, and moves `TICO_UPDATER_TAG` in `.env` if the install pinned it. If the new
updater does not stay up the helper puts the old one back, so the install is never left without an updater; its log is
`docker logs tico-updater-swap`. `TICO_UPDATER_SELF=never` turns this off. The same applies to the runner box's updater
sidecar. The last update's outcome is kept in `.updater-status.json` so the new updater still reports it.

Settings still reach the server through the explicit `environment:` list in `compose.yaml`, not `env_file: .env`, which
would also pass secrets that belong to other services (such as `CLOUDFLARE_TUNNEL_TOKEN`) into the server.

## A Docker runner

The runner box's `docker/runner.compose.yaml` has an `updater` sidecar, the same image and code as the server's
updater (`docker/updater.py`) in runner mode (`TICO_UPDATER_MODE=runner`). When no turn is running, the runner
asks it for the release its server names; it pulls `ghcr.io/ticoteam/tico-runner:vX.Y.Z`, replaces `runner.compose.yaml` with the release's copy (same checksum check, rolled back with the image), recreates the runner
container, waits up to three minutes for the container's health check, and puts the old image back if it does not
turn healthy. The runner then reports the outcome (`rolled_back`, `failed`) from the sidecar's `/status`, and does not
ask for that release again. The login and the bots' repositories are in the `runner-home` volume and are kept.

The Docker socket is mounted into the `updater` service only, never into the runner. The two share a `runner-control`
volume that holds a token the updater writes and the runner reads; the sidecar answers on the compose network and
accepts only `vX.Y.Z` tags of one image. A bot on the runner can therefore ask its own runner for another
release, and nothing else: the token is readable by the runner supervisor only (bots run as another user), and the sidecar refuses a release older than the one running. The Add computer command sets this up: `install.sh --runner` writes the compose file and a
`.env` with the image and updater tags pinned to the server's release ([install](install.md#linux-or-cloud-server-docker)).

A runner started with a plain `docker run` has no sidecar: it says so in Settings > Health, and you update it as before
(`docker pull`, then start it again). To move one onto the compose setup, run the `install.sh --runner` line from Add
computer on the same machine: it reuses the `tico-runner` volume (`TICO_RUNNER_HOME_VOLUME` in `.env`), so the login,
the repositories and the enrollment stay, and the runner then follows the server.

## Pinning

Pinning keeps a computer where it is. It then shows "Needs update (pinned)" when the server moves on, and once it
falls below the minimum it is paused, so pin only while you plan to update by hand.

- Mac or Linux checkout: `"pinned": true` in the runner's config (`runner.json`), or `TICO_RUNNER_PINNED=1` in its
  environment. `"self_update": false` and `TICO_RUNNER_SELF_UPDATE=0` also stop it.
- Docker runner: `TICO_RUNNER_PINNED=1` in the runner box's `.env`, then `docker compose -f runner.compose.yaml up -d`.
  To remove the sidecar's socket access altogether, delete the `updater` service.
- The server: leave `updater` out of `COMPOSE_PROFILES`, or set `TICO_TAG` to a tag in `.env`.

## Rolling back

Automatic rollback covers a release that does not come up. To go back by choice:

- **Server:** if the release you are leaving changed the database, the older one cannot read it, so put back a snapshot
  from before that update (`/data/snapshots`, above) with the server stopped and Litestream's record of the file cleared,
  or the next start can upload the restored file as if it were newer than the migrated one:

  ```
  docker compose stop server
  docker compose run --rm --no-deps --entrypoint sh server -c '
    ls /data/snapshots    # pick one, then:
    cp /data/snapshots/pre-update-....sqlite /data/hub.sqlite.restoring && sync &&
    rm -rf /data/.hub.sqlite-litestream /data/hub.sqlite-wal /data/hub.sqlite-shm &&
    mv /data/hub.sqlite /data/hub.sqlite.failed-update && mv /data/hub.sqlite.restoring /data/hub.sqlite'
  ```

  Then set `TICO_TAG=vX.Y.Z` in `.env`, `docker compose pull` and `docker compose up -d`. Without a database change,
  skip the middle step. Computers newer than the server are left as they are (they still work, as long as they are at or above the minimum).
- **Mac:** `git -C <checkout> checkout vX.Y.Z`, `scripts/tico restart`, and pin it (above) or the next heartbeat moves it
  back to the server's release.
- **Docker runner:** set `TICO_TAG=vX.Y.Z` and `TICO_RUNNER_PINNED=1` in `.env`, then `docker compose -f runner.compose.yaml up -d`.

## Coming from an older version

- **v0.2.5 or older:** the updaters of these versions cannot replace themselves or install new configuration files, so
  run the release's install command once more on each machine (server, then each runner box). From then on, Update
  in the app does everything.
- **v0.2.6 to v0.2.8:** Update in the app to v0.2.9 or later. An updater that replaced itself in these versions stopped
  pulling images, so a Linux runner box may then show "No such image" under Settings > Health and stay on its old
  version. Run this once in its directory (`/opt/tico-runner`):

  ```
  docker compose -f runner.compose.yaml up -d --no-deps --force-recreate updater
  ```

  Its next update follows the server as usual. The server's updater repairs itself when the server updates.
- **v0.2.10 or v0.2.11 runner box whose updater keeps restarting** (`docker ps` shows `tico-runner-updater-1 Restarting`):
  run once in `/opt/tico-runner`:

  ```
  sed -i 's/^TICO_UPDATER_TAG=.*/TICO_UPDATER_TAG=v0.2.12/' .env && docker compose -f runner.compose.yaml up -d updater
  ```

- **v0.2.16 to v0.2.18:** the update is in the app, with no manual steps. Browser tabs left open show "New version · Reload".
  A Mac runner's helper jobs now restart on their own after an update; on v0.2.17 or older, run `scripts/tico restart all` once
  after updating. If you run your own HQ, its `backup` service in `hq/compose.yaml` must run as uid 10005 (fixed in v0.2.18).

## For maintainers

Bump `MIN_RUNNER_RELEASE` in the release that changes the runner/server contract, and say so in the changelog.
Ship the server and runner image for that release together, and expect computers to move within a few minutes of
the server's restart.
