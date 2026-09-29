# Changelog

All notable changes to Tico are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). Each release is also published on
[GitHub](https://github.com/ticoteam/tico/releases) with its section below as the notes.

## [Unreleased]

### Added
### Changed
- Tico's icon and wordmark now match tico.team; the old robot icon is gone. The favicon, app icon (web, desktop, macOS menu bar, Slack) and the assistant's avatar use the new mark, the first-run setup and sign-in pages show the wordmark (reversed in dark mode, replaced by the app's name when a company has named its app), and the installed web app gains a maskable icon. `scripts/build-brand-icons.sh` regenerates every image from the SVGs in `ui/assets/tico/`.
- Who may use a bot no longer depends on the "Can use" list (`owner_ids`), which now only says who a bot works for and who is in
  its shared room; adding a bot no longer asks for people. Everyone can chat with and give tasks to every bot unless its Write
  says otherwise. A person who writes to a shared-room bot without being one of the people it works for talks to it in a room of
  their own.
- **Every bot starts Open after the upgrade.** `private_owners` and `routing_permissions` in `registry/hub-access.yaml` are no
  longer read: if either was set, the first start logs one warning and the owner finds a note on Settings > Health ("hub-access.yaml
  private/routing lists are no longer used; bots are now Open; set access in Settings > Bots"). Set the access you meant there.
- A bot the caller cannot see is a `404` everywhere (it used to be a `403` "This bot is private" on some routes and invisible on
  others); one they can see but not read or write to is a `403 forbidden` that says which.
- `bot_contact` (Other bots: replies only, tasks only) now also limits notes and comments that wake a bot.
- Hub SQL holds the bots the caller can read, and tasks that involve a bot they cannot read only when the task is theirs.
- `execution.text` puts a blank line (`"\n\n"`) between a run's separate messages; it ran them together
  ("planned.I've filed"). Deltas within one message still join directly, the run's closing message no longer replaces the
  progress notes before it, and a model's thinking is no longer part of the text. Tico's own chat shows each message
  as its own paragraph.

### Fixed
- The Assistant tab says "Assistant" in its own copy ("Ask the Assistant…", "Assistant is thinking…"), not the assistant bot's
  name, which on a company named after its bot read "Ask the Acme…". Settings > Bots still shows the bot's name.
- The Assistant composer empties after a message is sent and keeps focus, so a second Enter no longer resends it. A failed
  send keeps the text and shows the error.
- The Assistant now makes the low-risk writes itself and replies with a link, instead of proposing a Confirm card: a task owned
  by the person with no bot on it (create or update, never done, declined, close or reassign), a comment on such a task, marking
  updates read, and a note to themself. Everything the server would refuse with `confirm_required` is still a proposal.
- A tab left open through an update now notices: when the server's version differs from the one the page loaded with (seen on
  the existing config poll), a small banner offers Reload. It never reloads by itself.


- A runner box's updater (0.2.10 and 0.2.11) stopped on every start after its first: it locked its token to the runner's
  user and then, without the right to change another user's file, failed changing it again ("PermissionError ... updater-token")
  and restarted in a loop, so the box could not update. It now leaves a token that is already locked alone and never stops over
  it. A box whose updater is restarting recovers with, in its directory (`/opt/tico-runner`):
  `sed -i 's/^TICO_UPDATER_TAG=.*/TICO_UPDATER_TAG=v0.2.12/' .env && docker compose -f runner.compose.yaml up -d updater`.

## [0.2.11] - 2026-09-29

- An inbox bot now gets a computer to itself. Its Google Workspace key opens every mailbox in the company, and every bot on a
  computer runs as the same user, so the server refuses (409 `inbox_isolation`, with what to do: add a computer) to place an
  inbox bot beside another bot, or another bot beside an inbox bot. Several inbox bots may share one computer only after the
  operator allows it (`POST /api/v2/runners/{id}/inbox-sharing`). Onboarding leaves such a bot unplaced rather than failing.
  Settings > Health warns about installs that already mix them; nothing running is moved.
- On a Docker runner with the two-user layout, the Google Workspace mail key no longer sits in `workspace/secrets`, where any
  bot could read it. The runner moves it (once, on its own) to its state directory, closed to bots, and an inbox bot's turn asks
  the runner over the credential socket for a one-hour token for its own person's mailbox (and the people below them). Any other
  bot, or another mailbox, is refused. A Mac, or Docker started the old way, keeps reading the key file, and Settings > Health
  warns ("Mail key") that bots there can read it. See docs/mail.md, "Who can read the key".

### Fixed
- Rolling back a failed server update no longer leaves Litestream able to upload the migrated database as the newest copy: the snapshot is written to a temporary file and swapped in only once complete, and Litestream's tracking directory is cleared before the old image starts. Rolling back by choice ([updates](docs/updates.md#rolling-back)) uses the same steps.
- Starting on a database that already had part of a schema change (a column added but the version not recorded) failed
  on every boot. Each schema change now runs in one transaction with its version bump and is safe to run twice.
- A database file that has Tico's tables but no version record is refused with a clear message instead of being
  migrated blind. An empty file still starts.
- The one-time removal of the old routine-manifest tables keeps what they held in `routine_*_retired` tables.
- Idle runners no longer keep the database's write lock busy. Each runner asked for work four times a second and every ask
  was a write transaction, so a fleet of 8 to 12 idle runners made 32 to 48 writes a second and starved the scheduler,
  backups and lease renewals. The server now checks with a read and writes only when there is something to do, and an idle
  runner backs off from 0.25 s to 2 s between asks. The API's database wait is 30 s, as the scheduler's already was.
- Due reminders and the three-day auto-close stopped for every task past the first 500: they read a capped task listing. They
  now query exactly the tasks they need.
- The Assistant tab says "Assistant" in its own copy ("Ask the Assistant…", "Assistant is thinking…"), not the assistant bot's
  name, which on a company named after its bot read "Ask the Acme…". Settings > Bots still shows the bot's name.
- The Assistant composer empties after a message is sent and keeps focus, so a second Enter no longer resends it. A failed
  send keeps the text and shows the error.
- The Assistant now makes the low-risk writes itself and replies with a link, instead of proposing a Confirm card: a task owned
  by the person with no bot on it (create or update, never done, declined, close or reassign), a comment on such a task, marking
  updates read, and a note to themself. Everything the server would refuse with `confirm_required` is still a proposal.
- A tab left open through an update now notices: when the server's version differs from the one the page loaded with (seen on
  the existing config poll), a small banner offers Reload. It never reloads by itself.

### Security
- Bot privacy was decided in a handful of places and left gaps: a task, a note or a comment to a private bot needed only that the
  caller could see it (a comment even woke it), a Slack message reached any bot its sender could name, and a page of tasks, updates
  or files could shrink or count differently for someone who was not allowed some of them. One check now covers every route, the
  MCP tools and personal API tokens, lists and SQL are cut in the query (so counts and pages leak nothing), and Slack routing
  follows the sender's Write. The old file lists could not do any of this per bot and are retired (see Changed).
- A person who may only write to a bot no longer sees, under its replies, the steps it took to answer, or the live output of its runs.

## [0.2.10] - 2026-09-29

### Added
- **Assistant**: every person has one private chat with the company's assistant, a personal operator that knows how Tico is
  organised and acts on their behalf (docs/assistant.md). An **Assistant** tab first on your own person page, and "Ask the
  Assistant…" in search (⌘K) that opens it prefilled; a phone layout; replies link tasks, meetings, docs, files and bots as in-app
  routes. Only you can read or post in your room (owner and administrators included), and the ordinary chat routes still refuse
  the assistant. With no assistant the tab says it is off, and the owner gets **Turn on Assistant** there and at the top of Settings > Bots:
  one click restores the archived assistant (a company that set it aside at setup, v0.2.1) or adds it from the catalog, places it on
  BotOps' computer and activates it, and everyone's tab starts working.
- Fast path, no model: "what's waiting on me", search (tasks, docs, meetings, files, people, bots), "open X", "what did <bot> do
  today" and "how do I …" (from `docs/*.md`) are answered on the server from Tico's own data; a `choice` decision question classifies
  an unclear message when the company has a decisions provider. Everything else is a turn of the assistant bot ("thinking").
- The Assistant acts as you and never more: its turn's `hub` and MCP tools are your own (`Auth.assistant_principal`), every write is
  recorded via assistant (`events`, task history, comments; "<name> (via Assistant)"). Direct writes are limited to what touches the person themself (their own tasks, comments, notes, marking updates read; never a task for a bot or someone else, a message to a bot, or settling a task); approving or
  declining a Needs-you item, anything sent outside the company, spending, changing people, access or settings, archiving, deleting
  and activating a bot are proposed (`hub assistant propose`, `hub_assistant_propose`) as a Confirm / Cancel card and run only on
  your click, as you, once; the bot cannot confirm (`assistant_actions` table). Only allowlisted, plain routes can be proposed, the card shows the server's description and the request body, results keep no answer body, and a message the Assistant wrote never lets BotOps act for the person.
- Stable v2: `GET /api/v2/assistant`, `POST /api/v2/assistant/messages|turn-on|actions`, `GET /api/v2/assistant/actions/{id}`,
  `POST /api/v2/assistant/actions/{id}/confirm|cancel`, in `docs/openapi/v2.json` and `docs/custom-frontend.md`.
- **The assistant and BotOps are built in.** Setup always builds both (the wizard's "skip the assistant" choice from v0.2.1 is gone; both
  are active once a computer is enrolled), and neither can be archived or deleted by anyone, owner included, through the UI, the API,
  `hub` or BotOps: `409 system_bot`. Pausing, renaming and editing instructions stay allowed. Settings > Bots lists them as **Built in**
  with no Archive control. A company whose assistant was archived keeps it archived on update (nothing auto-restores it); the owner
  turns it on with **Turn on Assistant** and it cannot be archived again.
- The assistant template's `AGENT.md` and a new `assistant-chat` playbook teach the Assistant how Tico is organised, how to route
  work to the right bot, to answer briefly with links, never to act beyond the person and to ask before any side effect.

### Changed
- Docs match the code. "The server calls no models" is replaced by what is true: with decisions or Slack routing on, the
  server sends the text of each question to the decision provider you configured, and SECURITY.md says what a compromised
  server exposes then. The bare `docker run` sample follows the release placeholder, the shared secrets file is described as
  readable by every bot on the computer, the removed VM path is gone, the Files page states who removes a file and that the
  owner sees direct chats (not personal Assistant rooms), and sizing says only a small pilot was measured.

### Security
- Files auto-publish and `hub files publish` refuse a regular file with more than one hard link, so a bot cannot hard-link a
  secrets file into `reports/`. Copies cannot be detected and are still published.
- The runner's updater token is now `ticorun`'s alone (10002, mode 0600, fixed on every updater start; the updater sidecar gains `CHOWN`), so a bot can no longer read it, and `POST /update` refuses a release older than the running one (409), so a bot cannot move the box back to a version that predates the separate bot user. Going back on purpose stays manual ([updates](docs/updates.md#rolling-back)).


## [0.2.9] - 2026-09-29

### Fixed
- An updater that replaced itself (0.2.6 to 0.2.8) came back with the helper's settings: a server's updater stopped refreshing
  the compose file and bundle, and a runner box's updater stopped pulling images, so the runner's next update failed with
  "No such image" and went back. The helper no longer passes them on. Updating the server to 0.2.9 repairs its updater. On a
  runner box that shows "No such image" under Settings > Health, run once in its directory:
  `docker compose -f runner.compose.yaml up -d --no-deps --force-recreate updater`.
- docs/custom-frontend.md lists `PATCH` among the CORS methods (Files uses it).

## [0.2.8] - 2026-09-29

### Fixed
- A Docker runner (v0.2.6 and v0.2.7) could not start again after its first bot turn: the turn hands the secrets folder to
  the bot user, and the next start failed changing its mode ("chmod: ... Operation not permitted") and restarted in a loop.
  The start now gives that folder to the bot user and sets its mode as that user. A runner stuck this way recovers with
  `docker run --rm -v tico-runner:/h alpine chown 10002:10002 /h/workspace/secrets`, then updating to 0.2.8.

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

[Unreleased]: https://github.com/ticoteam/tico/compare/v0.2.12...HEAD
[0.2.12]: https://github.com/ticoteam/tico/compare/v0.2.11...v0.2.12
[0.2.11]: https://github.com/ticoteam/tico/compare/v0.2.10...v0.2.11
[0.2.10]: https://github.com/ticoteam/tico/compare/v0.2.9...v0.2.10
[0.2.9]: https://github.com/ticoteam/tico/compare/v0.2.8...v0.2.9
[0.2.8]: https://github.com/ticoteam/tico/compare/v0.2.7...v0.2.8
[0.2.7]: https://github.com/ticoteam/tico/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/ticoteam/tico/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/ticoteam/tico/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/ticoteam/tico/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/ticoteam/tico/releases/tag/v0.2.3
