# Contributing to Tico

Thanks for helping. Tico is released under the license in [LICENSE](LICENSE); your contribution is
under that same license. There is no contributor license agreement (CLA): you sign off each commit
instead (see below). Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Before you start

- Open an issue on [ticoteam/tico](https://github.com/ticoteam/tico/issues) that states the
  current behavior, the wanted outcome and how you will check it. Small fixes can go straight
  to a pull request.
- Report security problems privately, as described in `SECURITY.md`.

## Running the tests

```bash
pip install -r backend/requirements-dev.txt
python -m pytest -q                            # the Python suite, in parallel

npm ci
npx playwright install chromium
npm run test:ui                                # the browser scripts in ui/tests/
```

Run both locally before you open a pull request: CI does not run the tests unless started by hand
(`.github/workflows/ci.yml`). A full run (pytest, then the browser scripts) takes a few minutes and has
to stay under 10. To run less while you work: `python -m pytest -q backend/tests/test_x.py` for one
file, `node scripts/ui-tests.cjs <name>` for one browser script. If you touch `app/`, also run
`cargo check` there.

## Developer Certificate of Origin

Every commit in a pull request must be signed off, which says you wrote it or have the right to
submit it under the project's license, as set out in the
[Developer Certificate of Origin](https://developercertificate.org/). Add the sign-off with `-s`:

```bash
git commit -s -m "Fix the thing"
```

That appends `Signed-off-by: Your Name <you@example.com>`, using your git `user.name` and
`user.email`, which must be your real name and an address you use. To add it to commits you
have already made: `git rebase --signoff main` (then `git push --force-with-lease`). A pull request
with unsigned commits will be asked to sign them before it is merged.

## Pull requests

- Make the smallest change that fixes the problem, against `main`.
- Few, high-value tests. Write tests while you build if they help, then keep only the ones that guard a
  security or privacy boundary, data safety (migrations, backup, restore) or a core contract (the
  updater and release path, job claim and lease, task writes, the API schema), plus at most one happy
  path per feature. Delete the rest before you open the pull request; the whole suite has to run in
  under 10 minutes, so a new test that would push it over means cutting another.
- Added or changed an icon in `ui/`? Run `python3 scripts/build-icon-font.py` to rebuild the icon font subset (a test fails until you do).
- Keep the tests green, and do not add a dependency, a network call in the UI or a build step
  without saying why.
- Comments explain why, in the present tense. They do not name who asked or when.
- Keep real company names, people, domains and credentials out of the repository. Examples use
  the fictional company Acme (`acme.example`).
- Describe the behavior change and how you checked it in the pull request.

## Releases

A release is a version tag. Maintainers move the `[Unreleased]` notes in [CHANGELOG.md](CHANGELOG.md)
under the new version, run the full suite locally, then push a tag `vX.Y.Z` on `main`. The tag builds
the Docker images and publishes the GitHub release, with that CHANGELOG section as its notes, and
running installs then offer the update. Contributors do not tag; add your change to `[Unreleased]` in
the CHANGELOG instead. The steps are in [docs/releasing.md](docs/releasing.md).
