# Repositories

Settings → Repositories lists repositories in the connected GitHub organization. An Owner or admin ticks the repositories the team works on. Every human teammate can read the list. BotOps uses the rights of whoever asked it.

Bot repositories are marked by `bot-<slug>` names or by their use as a bot's own repository. The list reads GitHub on connection, when the installation changes, when you refresh, and daily. A repository that disappears stays listed as not reachable; its setting is kept.

A repository's default branch comes from GitHub. Its setup command comes from `tico.json` (`{"setup":"npm ci"}`), then `conductor.json` (`{"scripts":{"setup":"npm ci"}}`). A command saved in Settings wins, including an empty command. Phase 1 records this command; task worktrees and running their setup follow in a later release.

## Bot repository access

Each bot has one mode:

- **Own repo only:** its Instructions repository, with write access.
- **All ticked repos:** every repository ticked now and later, with read or write access. Write is the default.
- **Chosen repos:** chosen ticked repositories, with read or write access for each.

The bot always keeps write access to its own repository. Read grants allow reading contents. Write grants also allow changing contents, issues and pull requests. Repositories must belong to the connected organization. Unticking a repository removes it from all and chosen effective access; its stored chosen grant stays available if it is ticked again. Bot settings can save these unticked choices without removing them. Tokens already issued expire within an hour.

Settings → Repositories also sets **New bots get**: own only (the default), or all ticked repositories. This applies when a bot is created; existing bots keep their access. Existing extra repositories migrate once to chosen write access and are ticked automatically, including archived bots' grants.

## Tools and commands

MCP tools: `hub_repo_list`, `hub_repo_update`, `hub_bot_repos_get`, `hub_bot_repos_set`.

```sh
hub repo list
hub repo tick example/product
hub repo untick example/product
hub bot repos sales
hub bot repos sales --all
hub bot repos sales --chosen example/product example/docs:read
hub bot repos sales --own
```

## API

- `GET /api/v2/repositories`: repositories, `new_bot_default`, `github_connected`.
- `POST /api/v2/repositories/refresh`: refresh GitHub and return the same answer.
- `PUT /api/v2/repositories/{owner}/{repo}`: `enabled` and/or `setup_command`.
- `PUT /api/v2/repositories/settings`: `new_bot_default` (`own` or `all`).
- `GET /api/v2/bots/{bot}/repositories`: `mode`, `all_access`, `chosen`, `effective`.
- `PUT /api/v2/bots/{bot}/repositories`: `mode`, optional `all_access`, optional `chosen` entries with `full_name` and `access`.

Changes are audited as `repositories.changed` or `bot.repos_changed`, with before and after values. The older `GET/PUT /api/v2/bots/{bot}/github-repos` API remains an alias for chosen write repositories; a PUT also ticks them. Existing bot managers retain use of that alias.

## Computers and tokens

`GET /api/v2/runners/me/repositories` returns ticked repositories accessible to active bots assigned to that Computer, including each repository's bots, default branch, setup command and widest access. `POST /api/v2/runners/me/repositories/token` issues a contents-read token for exactly those repositories. An empty list returns no token. Heartbeats may report clone state, fetch time, size and an error per repository; older Computers show unknown. Only the latest report is stored.

GitHub applies permissions to a whole installation token, so mixed bot grants use separate write and read tokens. `POST /api/v2/github/token` keeps the existing `token` field for the write repositories (including the bot's own), and adds `tokens` entries containing `token`, `expires_at`, `repositories`, and `access`. Callers can also send `repository` with `bot` to obtain a token for one effective repository. This never expands access. Computers select the corresponding token for each Git remote through an environment-only credential helper. GitHub CLI commands select it from `--repo`/`-R`, a `gh repo view/clone/fork owner/repo` argument, a GitHub URL, a `repos/owner/repo` API path, `GH_REPO`, or the current checkout’s origin. Commands without a repository use the write token; for a read repository, specify the repository or run from its checkout. Tokens stay in memory and are never saved in Git config. Older Computers retain access to the bot's own repository and existing chosen write repositories.

After an upgrade, the server starts a repository refresh immediately and retries on its next
scheduler tick if the GitHub installation is not ready. A temporary installation lookup failure
preserves reachability and does not consume the daily sync backoff. Disconnecting the App marks
repositories unreachable.

Computer answers (`GET /api/v2/computers`, Operations and `hub_computer_list`) include `release`
for the installed Tico release. The legacy `version` field is the runner software version.
A Computer that does not report its release returns an empty `release`.
