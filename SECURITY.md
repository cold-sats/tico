# Security policy

## Reporting a vulnerability

Please report security problems privately. Do not open a public issue or pull request.

Use GitHub's private vulnerability reporting: go to the
[Security tab of ticoteam/tico](https://github.com/ticoteam/tico/security/advisories/new) and
choose **Report a vulnerability**. Include what you found, how to reproduce it, and which
version or commit it affects.

We aim to acknowledge a report within a few business days, and to tell you when a fix is
released. Please give us reasonable time to fix a problem before you disclose it. Never put a real
credential in a report, an issue or a pull request.

## Scope

Tico's server, runner, `hub` CLI, MCP tools and desktop shell in this repository. Problems in a
third-party dependency are best reported to that project, but tell us if Tico's use of it makes the
problem worse.

## Threat model, in plain words

Tico has a small server and one or more computers that run bots. What each one holds decides what
losing it costs you. See [docs/architecture.md](docs/architecture.md) for the picture.

### The server

The server holds the company's data: people, bots, tasks, chats, approvals, schedules, files, meeting
notes, and the shared credential store (encrypted with the key you configure). It runs no bots and
never calls a model, so it holds no model logins and no bots' working files. It does hold the sign-in
secrets (OIDC client secret, session secret) and, if you connect GitHub, the GitHub App's private key.
Someone who takes over the server can read and change company data and can mint GitHub tokens, so
treat it like any internal application server: patch it, keep the data volume private, and restrict
SSH.

### A runner computer

A computer that runs bots holds: the model logins for the harnesses installed on it (Codex, Claude
Code, Gemini CLI and so on), the credentials its bots need (`secrets/` in the workspace), and the bots'
git repositories with their instructions, knowledge and memory. Someone who takes over that computer
has all of that, plus whatever the OS account can reach. A runner's credential lets it claim work for
the bots assigned to it; it does not give it company-wide authority on the server. Revoke a lost
computer in **Settings > Devices**.

### Bots on one computer share a trust boundary, on purpose

Tico does not isolate bots from each other on the same computer. By default they run as the same OS user,
in the same workspace, with the same model logins and the same shared secrets. One bot can read another's
files and credentials on that machine. This is a design choice, not a bug: it keeps setup simple and lets
bots on a team cooperate.

What is separated: the computer's own credential. The runner's registration (`runner.json`) can claim the
work of any bot assigned to that computer, so code a bot runs must not be able to read it.

- **Docker runner** (`docker/runner.compose.yaml`, the installer's default): the supervisor is root, owns
  `runner.json` (mode 0600), its state and the tools directory, and runs every process that executes bot
  code (the model CLI of a turn, `git` in a bot's checkout, sign-in flows) as the unprivileged `bot` user. A
  turn gets its own attempt token and the environment the runner passes it, nothing of the registration.
  Its GitHub token comes from a local socket that answers only "a token for the bot this attempt belongs
  to", given the attempt token; the registration never crosses it.
- **Mac runner:** one user runs the runner and the bots, so the registration sits in the same account the
  bots run as: treat the Mac as one trust group. A second macOS account for the bots is possible by hand but
  not built in.
- **Still shared, by default:** the `bot` user's workspace, secrets and model logins, so one bot can read
  another's repository and credentials, and read the environment of another bot's running turn. Separate OS
  users per bot are not built (a future opt-in); separate computers or separate containers are the boundary
  today.

Practical guidance:

- Keep company-wide credentials (a Google service account with domain-wide delegation, org-wide
  tokens, admin keys) off computers whose bots read untrusted mail, web pages, or documents. Text
  from outside can try to steer a bot (prompt injection), and a steered bot can reach anything on its
  computer.
- Group bots by trust. Put bots that handle untrusted input on their own computer, and bots that
  hold powerful credentials on another that reads nothing untrusted.
- For unrelated trust domains (two companies, or teams that must not see each other's data), use
  separate computers, or at minimum separate OS users, each with its own environment and workspace.
  `docs/environments.md` describes the isolated mode with one OS user per environment.
- Give each bot only the secrets it needs (a per-bot file, not the shared one), and use approvals for
  actions that send, spend or delete.

### Sign-in

People sign in with the built-in Google or Microsoft (OpenID Connect) sign-in by default. The server
verifies the token, then requires the email to be on the people roster; an account that is not on the
roster is refused. You can restrict sign-in to your email domains. Cloudflare Access and AWS ALB with
Cognito are supported as advanced front doors you run yourself: the server verifies the signed JWT
they pass, so the proxy must be the only way to reach the server. Loopback sign-in with an owner token
exists only for a local-only server and is refused on a public URL. The owner controls who has access;
protect the owner's account with your identity provider's MFA.

### GitHub tokens

With a GitHub App connected, Tico stores no long-lived personal token. For each turn the server
requests an installation token that expires within the hour and is limited to that bot's own repository
plus any extra repositories the owner granted it. Installing the app on "All repositories" is the
recommended setup (new bot repositories work without a change) and does not widen a bot's reach, because
the token is scoped per bot. The app is private, has no webhook, and asks for no workflow permission by
default. See [docs/github-app.md](docs/github-app.md).

### The updater and the Docker socket

The optional one-click updater container mounts the Docker socket so it can pull a new image and
restart the server. Access to the Docker socket is equivalent to root on that host. The tradeoff is
convenience against exposure: the updater only listens for an owner-initiated request authenticated by
a token, and you can omit it and update by hand (`docker compose pull && docker compose up -d`). Leave
it out if the server host runs anything else you care about.

### Backups

Litestream replicates the SQLite database continuously to a bucket you choose, and the data volume can
be snapshotted. A backup contains everything the server holds, including the encrypted credential store
and sign-in secrets, so give the bucket a private policy, encrypt it, restrict who can read it, and keep
the credential key separate from the backup. Bot repositories and computer workspaces are not part of the
server backup; they live in Git and on the computers.

Never put a credential in git, in a task, or in bot instructions.
