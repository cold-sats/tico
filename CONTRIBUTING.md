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
python -m pytest -q -n auto -p no:warnings     # the Python suite, about ten seconds

npm ci
npx playwright install chromium
npm run test:ui                                # the browser scripts in ui/tests/
```

CI (`.github/workflows/ci.yml`) runs both on every pull request. If you touch `app/`, also run
`cargo check` there.

## Pull requests

- Make the smallest change that fixes the problem, against `main`.
- Add a test only for a path whose breaking would hurt users; the suite is kept small on purpose.
- Added or changed an icon in `ui/`? Run `python3 scripts/build-icon-font.py` to rebuild the icon font subset (a test fails until you do).
- Keep the tests green, and do not add a dependency, a network call in the UI or a build step
  without saying why.
- Comments explain why, in the present tense. They do not name who asked or when.
- Keep real company names, people, domains and credentials out of the repository. Examples use
  the fictional company Acme (`acme.example`).
- Describe the behavior change and how you checked it in the pull request.
