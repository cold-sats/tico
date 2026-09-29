# Contributing to Tico

Thanks for helping. Tico is licensed under Apache-2.0; by contributing you agree your work is
released under the same license.

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
(`.github/workflows/ci.yml`). A full run has to stay under 10 minutes. If you touch `app/`, also run
`cargo check` there.

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
