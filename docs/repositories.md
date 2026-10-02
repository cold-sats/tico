# Repositories

Settings → Repositories lists repositories in the connected GitHub organization. An Owner or admin ticks the repositories the team works on. Every human teammate can read the list. BotOps uses the rights of whoever asked it.

Bot repositories are marked by `bot-<slug>` names or by their use as a bot's own repository. The list reads GitHub on connection, when you refresh, and daily. Apps created since v0.3.1 also refresh on installation webhooks; older Apps may have an inactive webhook. A repository that disappears stays listed as not reachable; its setting is kept. Missing product repositories are omitted from tokens for five minutes before retrying and reported in Health when ticked. A bot’s own repository is always retried; a missing Instructions repository is reported for that bot without turning team GitHub health red. Creating a repository or successfully minting its token clears its missing mark.

A repository's default branch comes from GitHub. Its setup command comes from `tico.json` (`{"setup":"npm ci"}`), then `conductor.json` (`{"scripts":{"setup":"npm ci"}}`). Setup files are read only for ticked repositories; a temporary read failure or malformed file keeps the previous command. Only removing both setup files clears it. A command saved in Settings wins, including an empty command. Phase 1 records this command; task worktrees and running their setup follow in a later release.

## Bot repository access

Each bot has one mode:

- **Own repo only:** its Instructions repository, with write access.
- **All ticked repos:** every reachable product repository ticked now and later (other bots’ Instructions repositories are excluded), with read or write access. Write is the default.
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

Changes are audited as `repositories.changed` or `bot.repos_changed`, with before and after values. The older `GET/PUT /api/v2/bots/{bot}/github-repos` API remains an alias for chosen write repositories; only an Owner or admin may tick new repositories through it. Other bot managers can choose already ticked product repositories. An unchanged legacy save preserves all modes and read grants; changing an own or all mode through this alias asks the caller to use Settings. Only an Owner or admin can explicitly choose another bot’s repository. Existing chosen grants remain available.

## Computers and tokens

`GET /api/v2/runners/me/repositories` returns ticked repositories accessible to active bots assigned to that Computer, including each repository's bots, default branch, setup command and widest access. `POST /api/v2/runners/me/repositories/token` issues a contents-read token for exactly those repositories. An empty list returns no token. Heartbeats may report clone state, fetch time, size and an error per repository; older Computers show unknown. A temporary missing report preserves the last known state. Only the latest report is stored.

GitHub applies permissions to a whole installation token, so mixed bot grants use separate write and read tokens. `POST /api/v2/github/token` keeps the existing `token` field for the write repositories (including the bot's own), and adds `tokens` entries containing `token`, `expires_at`, `repositories`, and `access`. Callers can also send `repository` with `bot` to obtain a token for one effective repository. This never expands access. Computers select the corresponding token for each Git remote through an environment-only credential helper. GitHub CLI commands select it from `--repo`/`-R`, a `gh repo view/clone/fork owner/repo` argument, a GitHub URL, a `repos/owner/repo` API path, `GH_REPO`, or the current checkout’s origin. Commands without a repository use the write token; for a read repository, specify the repository or run from its checkout. Each read and write token is redacted individually, including tokens refreshed through the supervisor’s credential socket during a turn. Tokens stay in memory and are never saved in Git config. Older Computers retain access to the bot's own repository and existing chosen write repositories.

Base-clone Git runs as the runner supervisor with the same filtered environment used for turns. Hooks and fsmonitor are disabled, global and system Git configs are ignored, and only HTTPS transport is allowed. Each command trusts only its base-clone path with `safe.directory`, so upgraded clones with mixed ownership keep working. URL-scoped proxy, TLS and header settings are overridden; config includes are refused with a repair message. Tokens stay in the Git process environment and out of saved config.

Base clones are full clones with a normal working copy of the default branch, owned by the same user as bots on that Computer. Bots on one Computer can read each other’s base clones until per-subscription Unix users exist. Same-user computers, including Macs, also allow inspecting processes owned by that user; repository grants restrict issued tokens, not local files. Full object stores let task worktrees commit offline.

Clone and fetch operations check the free-space floor (5 GB or 10% of the volume, whichever is larger). They have at least 15 minutes to complete, and allow up to two hours based on repository size. Repeated failures retry after 15 minutes, one hour, then six hours; Health includes the reason and retry delay. Broken managed clones are re-cloned. Restarting or stopping a Computer interrupts in-flight base-clone Git and its children within ten seconds.

Existing GitHub Apps refresh daily and on Refresh. To enable installation events for an older App, open its GitHub App settings and enable Webhook → Active. GitHub’s [App webhook API](https://docs.github.com/en/rest/apps/webhooks) allows updating URL and secret with the stored App key, but does not expose the Active setting, so Tico cannot enable that switch automatically.
