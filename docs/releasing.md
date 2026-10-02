# Releasing

A release is a version tag. Pushing `vX.Y.Z` runs `.github/workflows/release.yml`, which builds the
installer bundle, checks the tag against [CHANGELOG.md](../CHANGELOG.md) and publishes the GitHub
release. Running installations look for that release to show "New version" in the sidebar.

## Before you tag

Tests run on your computer, not in CI: nothing in GitHub Actions runs the suite on a push or a pull request. Before
tagging, run the whole thing from the repository root:

```
python -m pytest -q && npm run test:ui
```

That is the full suite (pytest in parallel, then the browser scripts three at a time) and it has to finish in under
10 minutes; that is a hard budget for any suite that runs on merge or on a schedule. Keep it by keeping few tests, the ones
that guard security and privacy boundaries, data safety and core contracts, and by cutting one when you add one. CI only
builds and publishes: the Docker workflow builds the three images for a `v*` tag, and the Release workflow publishes the
GitHub release. The compose smoke test (Docker workflow) and the screenshots workflow run from the Actions tab
(Run workflow) when you want them. The optional `ci.yml` workflow runs the same tests there on demand.

Before a deploy, run the journey check on a laptop with Docker (it is not part of CI or of the ten-minute suite budget, and takes about ten minutes):

```
scripts/journey-test.sh                  # this checkout is the candidate; starts from the newest release tag
scripts/journey-test.sh --tag vX.Y.Z     # a published candidate (its images and bundle must exist)
```

It installs the previous release into a throwaway directory (auth none), enrolls a computer with a one-time code, runs one
bot run through a fake `codex` (`scripts/journey-fake-codex.py`), restarts the server, upgrades to the candidate with
"Update now", rolls back an update that migrates the database and never turns healthy (checking the pre-update snapshot
is restored, with the server's real entrypoint running Litestream), wipes the data volume and checks the server restores
from its replica without the migration, restarts a runner started as `runner.compose.yaml` starts it after a run and
requires a second run to work, and finishes with `docker/backup-test.sh` (MinIO and a file replica, wipe, restore). It prints a table of
PASS, FAIL or SKIP per step and exits non-zero on a failure. `scripts/install.sh` itself needs Linux and root, so the
script does what the installer does after its preflight (checksummed bundle, `.env`, `docker compose up -d`). For a
release that adds updater or migration behavior, the upgrade step is done by the *previous* updater, so also read the
rollback step: it runs on the candidate's updater.

1. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`, add a fresh empty
   `## [Unreleased]` above it, and update the link references at the bottom.
2. Commit that to `main` once the local suite is green.
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.

The workflow then:

- runs `scripts/build_install_bundle.py`, which attaches the one-line installer: `install.sh` with the tag baked into it,
  `tico-bundle-vX.Y.Z.tar.gz` (`compose.yaml`, `.env.example`, `docker/runner.compose.yaml` and the `setup/` wizard) and
  `SHA256SUMS` over both. `install.sh` checks the bundle against `SHA256SUMS` before it unpacks anything;
- waits until `ghcr.io/ticoteam/{tico,tico-runner,tico-updater}:vX.Y.Z` exist (the Docker workflow builds them from the
  same tag), so no release is published whose installer would fail on `docker compose pull`;
- uses the `[X.Y.Z]` section of the changelog, unchanged, as the release notes, and fails if the
  section is missing or empty. A tag with a suffix such as `v0.2.0-rc.1` is marked a prerelease,
  which the update check ignores.

Docker images are published by a separate workflow (on the same `v*` tag, plus a manual run) and set `TICO_VERSION` in the image, which is how the running app
knows its version (a source checkout reports `dev`). There is no source archive: the server and the runners run from
the images, and a Mac runner is a git checkout that moves to the release's tag.

The desktop app is built for every tag too (`.github/workflows/app.yml`, called from the Release workflow). If any
desktop build fails, the GitHub release is not created and the Release run is red: servers only offer a version that
has a release, so a failed desktop build stops the rollout. The app's version is the release's
(v0.3.6 → app 0.3.6, including any prerelease suffix), stamped from the tag at build time.

Tagged builds are the generic **Tico** app, even when the repository has per-environment deploy
variables. The three build jobs upload their bundles as `app-<target>` artifacts. After those
jobs pass, the Release workflow downloads them and attaches these assets to the GitHub release:

- macOS universal `.dmg`, `.app.tar.gz` and `.app.tar.gz.sig`;
- Windows NSIS `-setup.exe` and `-setup.exe.sig`;
- Linux `.AppImage`, `.AppImage.sig` and `.deb`;
- `latest.json`, the Tauri updater manifest, with both macOS architectures pointing at the
  universal archive and every platform URL pointing at an asset of that GitHub release.

`TAURI_SIGNING_PRIVATE_KEY` (and its optional password) signs the updater artifacts. Keep the
corresponding public key in `app/tauri.conf.json`. Missing signatures or platform bundles stop
publication. Generic apps check
`https://github.com/ticoteam/tico/releases/latest/download/latest.json`; prereleases are not
selected by GitHub's latest-release endpoint. See [Desktop app](desktop.md) for installation.

Generate the public manifest locally from collected bundles without uploading anything:

```bash
python scripts/app_release.py --github --version X.Y.Z --tag vX.Y.Z --output latest.json bundles/
```

The optional S3 publish job remains enabled when `TICO_DEPLOY_ROLE` and `TICO_DEPLOY_BUCKET`
are set. Manual or main-branch builds can still bake in `TICO_HUB_URL` and use `TICO_RUNNER_URL`
(or the hub address) for their updater endpoint. `scripts/app.sh --env <slug>` retains its
per-environment behavior. Hubs prefer a bucket manifest of their running version or newer;
otherwise they offer assets from the GitHub release of their running version, with a ten-minute
cache and no credentials sent to GitHub.

## What installations do

The server asks Tico HQ (`https://updates.tico.team/v1/latest`, which serves the same release from GitHub and counts the install
anonymously, see [PRIVACY.md](../PRIVACY.md)) at most every six hours, in the background, without credentials. With counting
off, when HQ does not answer, or with `TICO_RELEASES_URL` set, it asks `https://api.github.com/repos/ticoteam/tico/releases/latest`
directly and sends no ID.

| Variable | Meaning |
|---|---|
| `TICO_UPDATE_CHECK` | `off` stops the check and hides the notice |
| `TICO_RELEASES_URL` | Replaces the check with a GitHub-shaped URL, for a mirror or a test; nothing is counted |
| `TICO_HQ_URL` | Replaces `https://updates.tico.team` |
| `TICO_TELEMETRY`, `DO_NOT_TRACK` | `off` / `1` stops the count; the check then goes to GitHub |
| `TICO_VERSION` | The running version, set by the image |
| `TICO_UPDATER_URL`, `TICO_UPDATER_TOKEN` | An updater service the owner's "Update now" calls |

The updater contract is `POST {TICO_UPDATER_URL}/update` with `{"version": "X.Y.Z"}` and
`GET {TICO_UPDATER_URL}/status`, which answers `{state, from, to, message}` where `state` is one of
`idle`, `pulling`, `restarting`, `healthy`, `rolled_back` or `failed`. Both carry
`Authorization: Bearer <TICO_UPDATER_TOKEN>`. Without an updater, "Update now" shows the command to
run on the server: `docker compose pull && docker compose up -d`.

## Publish the release docs

The tagged repository is the source for that release's manual. Run `python -m backend.openapi_v2` and
`python scripts/build_api_docs.py` after changing API descriptions; check the spec and API guide together.

Publish the public site's docs from the same tag, including the docs landing page's three reader paths and its **Use Tico** and
**Glossary** links. The website source and publishing process live outside this repository. Check that its install and demo pages
use the latest-release installer and `latest` demo image by default, with version pinning shown separately, and mention Docker Desktop
on Mac. Keep the local install command visible on the home page and continue through model sign-in and a first bot result.

Validate the published copy against this release: server Decision calls and HQ suggestion disclosures, 25 active member bots by default,
Inbox Manager's single disabled weekday 07:30 Routine and assigned-mailbox access, and the complete KPI colour example in
[Goals and KPIs](goals-and-kpis.md#the-colours). Run `npm run screenshots` when local dependencies and browsers are available and publish
images from the same release as the UI. Preserve inbound links when moving pages; the transcript and old docs-sync pages link to their successors.
