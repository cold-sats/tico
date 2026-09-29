# Changelog

All notable changes to Tico are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). Each release is also published on
[GitHub](https://github.com/ticoteam/tico/releases) with its section below as the notes.

## [Unreleased]

## [0.2.7] - 2026-09-29

### Added
- **Files**: a bot's page lists what it created, revised or delivered, newest activity first (three rows and the total, "Show all"
  inline), in the main view beside its tasks. Three kinds: stored files (Tico's private blob store, opened through an authenticated
  route, every version kept), linked cloud documents (Google Docs, Sheets and Slides, Notion, Figma, any https document; Tico keeps the
  address only), and S3 objects copied by the bot's own computer with its own credentials. Tables `bot_files`, `bot_file_versions`
  and an append-only `bot_file_activity`. See `docs/files.md`.
- `hub files publish|add-link|touch|import|list` and the matching `hub_files_*` MCP tools. After a completed turn the runner
  uploads new or changed files under `reports/` and `artifacts/` (per bot: `files: {publish: [...]}` in `employee.yaml`) through a
  durable outbox with idempotency keys; credential-like names, symbolic links, paths outside the checkout, other types and files over
  25 MB are refused. A pushed commit adds "View on GitHub" at that exact commit.
- Files inherit the visibility of their task or conversation (a private chat leaks no name, count, version or download);
  the owner or a bot administrator can promote one to bot-wide or remove it from the list.
- Stable v2: `GET /api/v2/bots/{bot}/files`, `POST /api/v2/files/uploads|links|imports`, `PATCH /api/v2/files/{id}`,
  `GET /api/v2/files/{id}/activity|versions`, in `docs/openapi/v2.json`; CORS allows `PATCH`. The custom-frontend example shows a bot's Files.
- The bot templates' `AGENT.md` and the BotOps playbooks tell bots to publish their deliverables.

### Changed
- The bot page's old storage card (More) is gone, with `GET /api/employees/{bot}/storage`; task and chat attachments stay where they were.

## [0.2.6] - 2026-09-29

### Added
- `scripts/journey-test.sh`: an on-demand install-to-rollback check to run against Docker before a deploy (docs/releasing.md).

### Fixed
- A server started on an empty data volume no longer becomes a blank company when its backup cannot be restored. It records an
  environment marker outside the database (`.tico-environment` in the volume, `environment.json` beside the backup) and refuses
  to start, with a clear message, when a company exists (or may exist) and the restore failed. Starting a new company over an
  existing backup needs `TICO_INITIALIZE_EMPTY=1` or `server --initialize-empty`; a genuinely fresh install starts as before.
- "Check for updates" waits (up to 10 seconds) for the fresh answer instead of returning the cached one, bypasses the cache
  for it, and says "still checking" when GitHub is slow.
- Updates snapshot the database (`/data/snapshots`, last three kept) before switching the server image and restore it when the
  new version fails its health check and is rolled back; the update status reports the snapshot and whether it was restored.
- The server's updater and the runner box's updater replace themselves after a successful update (a short-lived helper
  recreates the service and puts the old updater back if the new one does not stay up), so updater fixes reach existing installs.

### Security
- The Docker runner keeps its own credential away from bot code. The supervisor stays the runner's own user (`ticorun`, 10002, as in every earlier image) and owns `runner.json` (0600), holding
  five ambient capabilities (`CHOWN`, `DAC_OVERRIDE`, `KILL`, `SETGID`, `SETUID`); each turn's model CLI, `git` in a
  bot's checkout and the sign-in flows run as an unprivileged `bot` user (uid 10003). A turn's git credential helper gets
  the bot's GitHub token from a supervisor socket with its attempt token, never from the registration. The current
  `runner.compose.yaml` sets `user: "0"` and the capabilities; an older compose file, or a bare `docker run` without them,
  keeps running as one user, and so does the previous image if an update is rolled back on a migrated volume. Bots still share the `bot` user with each other. SECURITY.md says what is and is not separated.
  On the first start of an existing volume the entrypoint changes its ownership once (logins and dotfiles to `bot`, group-writable; the workspace keeps its owner and
  the supervisor's files stay with `ticorun`); use `docker exec -u bot` to sign a model in.

### Tests
- `POST /api/v2/sql` and the JSON API are checked against each other for tasks, private rooms, messages and meetings, for the
  owner, a member, a person with a private room, a bot and a bot whose turn was reassigned.
- A Docker test starts the runner image on a volume from an older release and shows a turn cannot read the registration but can
  still run its harness and push through the credential helper.


## [0.2.5] - 2026-09-29

### Fixed
- The in-app update now updates the compose bundle too. The updater downloads the target release's `tico-bundle-vX.Y.Z.tar.gz` and
  `SHA256SUMS`, refuses a checksum mismatch or unsafe archive before changing anything, replaces `compose.yaml`, `.env.example`,
  `docker/runner.compose.yaml` and the rest of the bundle atomically (never `.env`), and keeps the old files in `.bundle-previous/`.
  A release that does not turn healthy is rolled back, image and bundle together. Slack and the front door are recreated from the
  new file. A runner box's updater does the same for `runner.compose.yaml`. The updater itself still moves to the new release at
  the next `docker compose up -d` (it cannot recreate itself mid-run), so it applies bundles from the update after its own.
  New settings therefore reach existing installs without re-running `install.sh`. The server keeps its explicit `environment:` list
  rather than `env_file: .env`, which would pass secrets meant for other services (such as the tunnel token) into it.
- `GET /api/v2/bots` no longer lists archived bots (`?include_archived=1` for admin views that need them), so a custom frontend's
  chat picker does not offer them.

### Added
- Display names in the stable v2 API, beside the ids and never instead of them: `owner_name`, `requester_name`, `from_name`,
  `to_name` and so on, an `actors` map (`{"human:ana": "Ana Alvarez"}`) on read answers, and notices the hub wrote ("New task from
  bot:x: ...") shown to people with names in `body` (the stored text is in `body_raw`). The example app shows task owners by name.

### Changed
- The demo company is now a neutral fictional software company (project-tracking software for small studios) instead of
  property management. Screenshots in `docs/images` are unchanged until `npm run screenshots` is run again.

## [0.2.4] - 2026-09-29

### Added
- Build your own web frontend on Tico: `docs/custom-frontend.md` (start here) and `docs/api.md`, with a no-build example app in
  `examples/custom-frontend/` (org chart, chat with streamed replies, tasks, Needs you) that a browser test runs against a real server.
- `TICO_CORS_ORIGINS` (also in `compose.yaml` and `.env.example`): exact origins, never `*`, that may call the API from a browser
  with credentials. Unset, the server adds no CORS behavior. A browser write from a listed origin passes the origin check.
- Sign-in for a frontend on another origin (built-in sign-in, `TICO_AUTH_PROXY=oidc`): `/auth/login?next=<listed origin>&code_challenge=<S256>`
  returns a one-time code in the URL fragment, `POST /auth/token` exchanges it (PKCE, and the same origin) for a bearer session
  (`Authorization: Bearer tico_st_...`, same 12-hour idle and 7-day lifetimes), and `POST /auth/token/revoke` ends it. Only listed
  origins are ever redirected to; any other `next` keeps falling back to `/`.
- `GET /api/v2/openapi.json` is now the stable v2 contract: the operations a frontend builds on, with tags, operation ids and the shapes of
  their answers, still for signed-in callers only. The committed copy is `docs/openapi/v2.json`; `python -m backend.openapi_v2` regenerates it
  and a test fails when it is stale. Before, the route returned every route of the server, internal ones included.
- A bot built on a computer publishes its history itself. After `hub github create-bot-repo <slug> --empty` and setting
  the bot's repository link, the runner, in the bot's own turn, sets `origin` to the resolved GitHub URL and runs
  `git push -u origin <branch>` with that bot's own token when the checkout has commits and no upstream. It never
  forces; different history on the remote, or an `origin` that points elsewhere, stops it and shows under Health, "Bot
  history". BotOps no longer pushes other bots' repositories (playbook step 5b).

### Changed
- "Judge" is now "decisions" in everything people read: docs, the UI, the setup prompts, the hub CLI and MCP tools, the
  mail flags and the bot skill. A decision question is a yes/no (`noul`), a `choice` or a `score`, answered with
  probabilities and acted on with thresholds, the same format as OpenRouter's Decisions API; the provider setup is unchanged. New names: `hub decisions` / `hub_decisions`, `hub listen decide` / `hub_listen_decide`,
  `skills/decisions`, `--decisions-provider`, `MAIL_DECISIONS`, `mail inbox --decisions`, and a `decision:` condition in
  `registry/mail-rules.yaml`. The old names (`hub judge`, `hub_judge`, `--judge-provider`, `MAIL_JUDGE`, `--judge`,
  `judge:` rules) still work and are deprecated. Internals are unchanged: `backend/judge.py`, `/api/v2/judge`,
  `judge.call` audit events, `routed_by: "judge"` and rule ids.
- Listening's inboxes are the company's own: `registry/listening.yaml` lists the destinations (category, threshold,
  receiver bot, optional readers and `unless`), and a company with none routes nowhere. The hub no longer ships
  company-specific destinations. The example question sets (`questions/listening-*.json`) describe a
  fictional software company; `listening-item` is version 5 with categories `lead` and `partner`. Companies that had those destinations copy them into `registry/listening.yaml` and keep their
  own questions.
- The UI no longer special-cases the `human-ops` and `success` teams: team names read from the data.
- The Version line in Health writes releases as `v0.2.3` everywhere.
- The writing check accepts far more imperative verbs ("Connect", "Authorize", "Configure", "Rotate", ...) and refuses
  only a title that clearly does not start with one: a label such as "Needs-you:", a noun phrase, a gerund or a
  third-person form.

### Fixed
- Health said "GitHub refused a token" and "give it access" when the bot's repository simply did not exist yet. It now
  says the repository does not exist yet and how to create it (`hub github create-bot-repo <slug>`, or `--empty`); a
  403, or a repository outside the installation, keeps the access message.
- "Check for updates" showed its answer twice, once as `0.2.3` and once as `v0.2.3`. It shows it once.
- `npm run screenshots` failed on the Devices capture because Settings remembers its last tab. Each Settings capture
  now picks its tab, and the Health capture is `settings-health-*`.


### Removed
- The older install stacks. Docker is now the only way to install and run the Tico server (`install.sh`, `tico setup`
  or the cloud-init files). Gone: `infra/aws` (the ALB + Cognito CloudFormation stack), `infra/ec2` (the EC2
  reference stack and its `deploy.py`, `install.py`, `deploy_from_ci.py`), and `infra/linux` (`install-vm.sh`,
  `install-runner.sh` and the systemd units). A Linux computer that runs bots uses the Docker runner
  (`install.sh --runner`); the Mac runner is unchanged. `scripts/tico` no longer drives a `tico-runner.service`
  unit on Linux, and `INVOCATION_ID` no longer marks a runner as supervised (set `TICO_SUPERVISED=1` under your own
  supervisor). Sign-in with an AWS ALB and Cognito (`TICO_AUTH_PROXY=aws-alb`) still works behind a load balancer you
  run yourself; see `docs/install-advanced.md`.
- `tico-release.tar.gz` and its checksum are no longer attached to releases. Releases publish `install.sh`, the
  compose bundle and `SHA256SUMS`; the images carry the version.
- If you run one of the removed stacks: nothing changes on your running server, but new releases will not update
  it. Move to Docker by installing with `install.sh` on a new server, restoring a backup bundle into it (see
  Backups and restore in `docs/install.md`), and pointing your DNS at it; the old stacks stay available in the v0.2.3 tag.

## [0.2.3] - 2026-09-29

### Added
- `hub github create-bot-repo --empty` (API `empty: true`) creates an empty private `<org>/emp-<slug>` for a bot whose
  repository already exists on a computer; BotOps' playbook and `docs/github-app.md` describe pushing its history in.

### Changed
- Health moved from the main navigation into Settings > Health. `#/health` still works and opens it; a red dot on
  the account button, Settings and the Health tab shows when something needs attention. Getting started, once done,
  just leaves the rail.
- The BotOps bot may create bot repositories (`emp-<slug>`, private, for a planned or active bot, in the connected
  organization) when the app has administration permission, audited with the acting bot; anyone else is refused with a reason.
- A bot repository link that is a bare `emp-<slug>` resolves to the connected GitHub organization for its token.
- Integration pages name the `owner` role instead of a person, served as the company owner's name; `integrations/github.md`
  describes the GitHub App model, and the shipped pages and templates no longer state fixture people or companies as facts.

### Fixed
- Health's Update button opens the update popup instead of closing it again on the same click.

## 0.2.2 - 2026-09-29

### Added
- Health > Version has an owner-only "Check for updates" that asks the server to look for a release now (at most once
  a minute; `POST /api/v2/system/update/check`) and shows the answer beside the line.
- The "What should your bot do?" dialog offers "Build another" after sending, and Done in place of Cancel.

### Fixed
- Settings > Bots and a bot's Setup show "company default (model · effort)" for a bot that follows the default, not "not set".
- "Build one with BotOps" creates the bot's planned record (on your computer, under you, on the default model) before
  filing the task, so the bot shows on the org chart and BotOps can attach routines instead of finding it unknown.
- Health and the sidebar's "New version" notice fetch fresh data on every visit and on the app's poll, so a release
  the server just learned of no longer waits for a page reload.
- Health > Computers and Settings > Devices list only the models the company's providers or an assigned bot use (plus
  any installed); a missing one is red only when something needs it.
- A GitHub connection that is not set up is shown as optional info on Health, not a green check.
- A Docker runner without an updater is told to move onto the compose file with `install.sh --runner` (pinned to the
  server's release); a compose runner keeps the `docker compose pull && docker compose up -d` hint.
- The first-run wizard no longer assumes a Mac: computers can be Macs or Linux or cloud boxes, models a subscription or
  an API key, and Review lists every online computer.
- The "What should your bot do?" dialog closes when you navigate elsewhere.
- Notices such as "New task from human:sam" show the person's or bot's name, not the raw id.
- A key or sign-in the provider refuses (401, "Incorrect API key", "not logged in") now marks that model on that
  computer "rejected" with the time and a redacted reason, instead of showing "signed in" while every turn fails.
  The computer takes no work that needs it until the key or sign-in changes (or one retry after five minutes), and
  the job waits in the queue rather than starting a new attempt every 15 seconds.

### Changed
- The server's updater is pinned to the release (`TICO_UPDATER_TAG`, default `TICO_TAG`) instead of `:latest`. An update
  leaves the updater running, since it cannot replace itself; it moves at the next `docker compose up -d` on the host.
- `python3 -m setup runner` and `infra/cloud-init/tico-runner.yaml` set the runner up with the release's
  `install.sh --runner`, so every documented path gets the updater sidecar instead of a bare `docker run`.

## 0.2.1 - 2026-09-29

### Added
- `python3 -m setup backup-storage --domain ... --aws-region ...` creates the AWS backup bucket and its scoped key from a
  laptop, for a server that has no AWS credentials; the installer then takes it as an `existing` bucket.
- `install.sh --runner --url ... --code ... --label ...` sets up a computer that runs bots: Docker, the release's
  `runner.compose.yaml` with its updater sidecar, a `.env` pinned to the release, and `docker compose up -d`. Settings >
  Devices > Add computer and the first-run wizard show this line for a Linux or cloud server, pinned to the server's own
  release; the bare `docker run` stays as a documented alternative that does not update itself. Re-running it on a
  machine with a bare-run runner reuses the `tico-runner` volume, so the enrollment carries over.
- The company assistant is optional in the first-run wizard: ticked to start with, with a line on when you want it (Slack,
  meetings sent to bots); BotOps stays required. Without an assistant, Slack routing asks through BotOps, meetings and
  work nobody was named for go to BotOps, refused-write reviews of BotOps go to the owner, and BotOps and new bots
  report to the owner. It can be added later from Settings > Bots > Add from catalog.

### Fixed
- The catalog card's Owns and Never lists no longer show a raw object for an entry written as `- Name: description`;
  the server serves every entry as one sentence.
- Provider descriptions say what the runner accepts: Codex works with a ChatGPT subscription or `OPENAI_API_KEY`, Claude
  Code with a Claude subscription or `ANTHROPIC_API_KEY`.
- The setup wizard's final checks retry the HTTPS certificate, `/healthz` and sign-in redirect for up to 3 minutes
  while Caddy is still getting its certificate, instead of failing right after `docker compose up`. `setup doctor`
  stays single-shot.
- The TLS "internal error" hint now says the certificate is probably still being issued and points to
  `docker compose logs caddy`; the "Nothing answers on 443" hint names the private-subnet (NAT gateway) case.
- `--cloud aws` launches an internet-facing server only in a subnet routed to an internet gateway, and stops with a
  clear error when there is none.

### Changed
- `docs/install.md`: the AWS server needs a public subnet (the bot box may be private), and "When something fails"
  covers the private-subnet case.

## 0.2.0 - 2026-09-29

The server runs in Docker and runs no bots; bots run on computers that join it. One command installs it.

### Added
- **Install:** `curl -fsSL https://github.com/ticoteam/tico/releases/download/v0.2.0/install.sh | sh` on
  any Linux server. It pins the release, verifies checksums, installs Docker if needed and runs
  `tico setup`, which covers DNS, sign-in, backups and health checks. Re-running it upgrades or repairs
  without touching `.env`. See [docs/install.md](docs/install.md).
- **Docker:** server, runner and updater images; a compose file with Caddy or a Cloudflare Tunnel in
  front; one-click updates with automatic rollback.
- **Where to run it:** `tico setup --cloud hetzner|digitalocean` creates the server with `hcloud` or
  `doctl`, and cloud-init files cover any Ubuntu cloud. The AWS load balancer + Cognito stack and the
  older Linux VM installer are in [docs/install-advanced.md](docs/install-advanced.md).
- **Computers:** a computer joins with one command and a one-time code (Settings > Devices > Add
  computer), as a Mac or a Linux box.
  - Computers follow the server's release, update at a quiet moment and roll back if they don't come
    back. See [docs/updates.md](docs/updates.md).
  - Linux computers also run mail and calendar sync, meeting importers and Close call sync.
- **Harnesses:** the runner installs only the model CLIs your providers need, keeps them updated
  between turns and honours pins (Settings > Devices). New providers: DeepSeek, Kimi, Meta Llama and
  Mistral (through pi and OpenRouter), and Cursor. See [docs/harnesses.md](docs/harnesses.md).
- **Sign-in:** built-in "Sign in with Google or Microsoft". Cloudflare Access and AWS Cognito remain
  supported.
- **Model sign-in from the browser:** the real Codex or Claude Code login link and code, relayed from
  the computer, so a company's own subscription signs in without SSH.
- **People:** people, access and ownership are managed in Settings > People. Directory sync from Google
  Workspace or Microsoft Entra ID (with a preview) and SCIM 2.0 for Okta, Entra and JumpCloud. Leavers
  are marked left, never deleted.
- **Backups on by default:** continuous copies to a separate volume, or to S3/R2 buckets that
  `tico setup` can create. `docker compose run --rm server restore` rebuilds a server.
- **Health page:** version, computers, models, queue, GitHub, backups, Slack, sign-in and failed runs,
  each with a fix.
- **"New version" notice** in the sidebar with the changelog and, for the owner, Update now.
- **Meetings:** importers for Fireflies, Zoom, Google Meet and Granola (Settings > Cloud services), and
  hand-written meeting notes.
- **Company databases:** `hub db` gives bots read-only access to PostgreSQL, MySQL, SQLite and MongoDB
  (including Atlas), with per-bot grants, row caps, timeouts and an audit trail. Companies can layer
  their own integration pages and query catalogs from private config. See
  [docs/databases.md](docs/databases.md).
- **Slack** in the Docker install: create the app from the manifest and paste two tokens in Settings.
- **GitHub:** per-bot extra repositories, and guidance to install the app on All repositories.
- **Demo:** `docker run --rm -p 127.0.0.1:8765:8765 ghcr.io/ticoteam/tico:v0.2.0 demo` shows a fictional company on
  localhost with no setup and no outbound calls. See [docs/demo.md](docs/demo.md). The docs' screenshots are generated
  from it (`npm run screenshots`).
- Docs: [architecture](docs/architecture.md), [sizing](docs/sizing.md), and a plain-words threat model
  in [SECURITY.md](SECURITY.md).

### Changed
- Luna 6 at max effort is the recommended Codex model. Companies still choose their providers at setup.
- A computer older than the server's minimum runner release takes no work and says why.

### Fixed
- Settings no longer jumps back to the Devices tab or loses what you were typing.
- On a phone, the closed navigation drawer no longer casts a shadow on the page edge.

## 0.1.0 - 2026-09-29

First public release.

### Added
- Server: one company per environment, holding people, bots, tasks, chats, approvals, routines,
  meetings, files and an audit trail in SQLite, with the routine scheduler built in.
- Runner: executes AI employee bots one leased attempt at a time on a company machine, through the
  model CLIs the company is already signed in to, so credentials never leave that machine.
- Web interface and desktop app (macOS, Windows, Linux): the org chart, Updates (the bots' daily
  and weekly reports), Tasks, chat with bots, Needs you approvals, Integrations, Settings and help.
- Bots: created from templates in their own git repositories, with a first-run onboarding wizard
  and BotOps, the bot that sets the others up.
- Shared hub over MCP and the `hub` CLI, so any agent can use the same tasks, messages and
  company context as people.
- Connectors for mail and calendar, meetings, Slack and GitHub, plus a credential vault.
- Sign-in through an identity-aware proxy (Cloudflare Access or AWS ALB with Cognito), or loopback
  sign-in for a local install.
- Hosting: local only on a Mac, or self-hosted, including a reference AWS stack under `infra/ec2/`
  with Litestream backups.

[Unreleased]: https://github.com/ticoteam/tico/compare/v0.2.7...HEAD
[0.2.7]: https://github.com/ticoteam/tico/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/ticoteam/tico/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/ticoteam/tico/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/ticoteam/tico/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/ticoteam/tico/releases/tag/v0.2.3
