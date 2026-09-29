# Releasing

A release is a version tag. Pushing `vX.Y.Z` runs `.github/workflows/release.yml`, which builds the
installer bundle, checks the tag against [CHANGELOG.md](../CHANGELOG.md) and publishes the GitHub
release. Running installations look for that release to show "New version" in the sidebar.

1. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`, add a fresh empty
   `## [Unreleased]` above it, and update the link references at the bottom.
2. Commit that to `main` once CI is green.
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

Docker images are published by a separate workflow and set `TICO_VERSION` in the image, which is how the running app
knows its version (a source checkout reports `dev`). There is no source archive: the server and the runners run from
the images, and a Mac runner is a git checkout that moves to the release's tag.

## What installations do

The server asks `https://api.github.com/repos/ticoteam/tico/releases/latest` at most every six
hours, in the background, without credentials.

| Variable | Meaning |
|---|---|
| `TICO_UPDATE_CHECK` | `off` stops the check and hides the notice |
| `TICO_RELEASES_URL` | Replaces the GitHub URL, for a mirror or a test |
| `TICO_VERSION` | The running version, set by the image |
| `TICO_UPDATER_URL`, `TICO_UPDATER_TOKEN` | An updater service the owner's "Update now" calls |

The updater contract is `POST {TICO_UPDATER_URL}/update` with `{"version": "X.Y.Z"}` and
`GET {TICO_UPDATER_URL}/status`, which answers `{state, from, to, message}` where `state` is one of
`idle`, `pulling`, `restarting`, `healthy`, `rolled_back` or `failed`. Both carry
`Authorization: Bearer <TICO_UPDATER_TOKEN>`. Without an updater, "Update now" shows the command to
run on the server: `docker compose pull && docker compose up -d`.
