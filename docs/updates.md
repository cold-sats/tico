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

The updater cannot replace itself while it is running the update, so it stays on its old image, which keeps working,
until the next `docker compose up -d` on the host, which reads the `TICO_TAG` the update wrote to `.env` and moves it.
The bundle logic that runs is therefore the one from the updater's release, one update behind.

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
release, and nothing else. The Add computer command sets this up: `install.sh --runner` writes the compose file and a
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

- **Server:** `docker compose pull` after setting `TICO_TAG=vX.Y.Z` in `.env`, then `docker compose up -d`. Computers newer
  than the server are left as they are (they still work, as long as they are at or above the minimum).
- **Mac:** `git -C <checkout> checkout vX.Y.Z`, `scripts/tico restart`, and pin it (above) or the next heartbeat moves it
  back to the server's release.
- **Docker runner:** set `TICO_TAG=vX.Y.Z` and `TICO_RUNNER_PINNED=1` in `.env`, then `docker compose -f runner.compose.yaml up -d`.

## For maintainers

Bump `MIN_RUNNER_RELEASE` in the release that changes the runner/server contract, and say so in the changelog.
Ship the server and runner image for that release together, and expect computers to move within a few minutes of
the server's restart.
