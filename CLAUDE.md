# Tico

Tico is an open-source operating system for a company's human and AI team (Apache-2.0): a FastAPI
server in `backend/`, the one-page web UI in `ui/index.html`, the runner in `runner/`, the `hub`
CLI and MCP tool table in `clients/`, and a Tauri desktop shell in `app/`. `README.md` says how to
run it and `docs/how-it-works.md` describes the system.

## Work queue
Engineering work on Tico is GitHub issues on ticoteam/tico, worked from a Claude Code session until
none are left: read `skills/tico-tickets/SKILL.md` before filing, picking or merging anything. A
bot's own work is hub tasks, never issues.

## Tests
`python3 -m pytest -q -n auto` runs the Python suite in about ten seconds; `npm run test:ui` runs
the browser scripts in `ui/tests/` (Playwright, needs `npm ci`). CI runs both on every push and
pull request (`.github/workflows/ci.yml`). The suite is deliberately small: add a test only for a
path whose breaking would hurt the company, and delete one that stops earning its place.

## Conventions
- Keep company names, people, domains, buckets and credentials out of the repository. Examples use
  the fictional company Acme (`acme.example`).
- The UI has no build step and loads nothing from the network: vendored libraries live in
  `ui/vendor/` with their licenses.
- Comments say why in the present tense; they do not name who asked or when.
