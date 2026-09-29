---
service: github
title: GitHub
kind: cli
summary: The company's repositories and each bot's own emp-<slug> repository, reached with a per-bot token from the company's GitHub App, or with the computer's own git access when no app is connected.
access: "`gh` and `git` in a turn; the runner's git credential helper supplies the bot's app token when the GitHub App is connected, otherwise the computer's own login is used"
credentials:
  - none of the bot's own to manage — with the GitHub App, the runner fetches a short-lived token scoped to the bot's repository (`POST /api/v2/github/token`) and never stores it; without it, the computer's inherited `gh` and `git` login
declared_as: |
  # Access to a bot's own emp-<slug> repository is implicit; no entry is needed.
  - service: github
    identity: <org>/<repo>              # one entry per repository or group of repositories
    can: [read]                         # read | draft (branches and review PRs) | write
    note: review PRs only; a person merges; never push to main
writes: approval
owner: owner
---

## What it is

GitHub as the bots reach it: the `gh` CLI and `git` on the computer that runs them. When the
owner has connected the company's GitHub App (Settings, Cloud services; `docs/github-app.md`),
each bot gets a short-lived token for its own repository only, and commits and PRs are made
by the app on that bot's behalf. With no app connected, the computer's own git access is used,
and everything shows as whoever is signed in on that computer. Work does not live in GitHub
Issues; it lives in the hub (`hub task ...`).

## What data it has

| Repository | What | Who, how |
|---|---|---|
| `<org>/emp-<slug>` | each bot's own repository | the owning bot may commit directly or open and merge a tested PR; the runner pushes commits from its checkout after each turn |
| product and docs repositories | whatever the company keeps there | as the bot's `access:` entry says; review PRs unless it says `write` |
| `ticoteam/tico` | this hub: backend, runner, clients, docs, policies | authorized maintainers may merge after required checks |

Extra repositories a bot may read are granted by the owner (Settings, the bot's GitHub
repositories); they must be in the connected organization.

## How a bot uses it

```bash
gh api repos/<org>/<repo>/contents/<path> --jq .content | base64 -d
gh pr list -R <org>/<repo> --state open
gh pr view 123 -R <org>/<repo> --json title,body,files
gh pr create -R <org>/<repo> --draft --base main --head <branch> --title "..." --body "..."
git -C ~/tico-work/emp-<slug> add -A && git commit -m "..."   # your own repo, at the end of a turn
gh pr create -R <org>/emp-<slug> --base main --head <branch> --title "..." --body "..."
gh pr merge -R <org>/emp-<slug> <number> --merge --delete-branch  # your own repo, checks passed
```

For a repository whose merge still needs human review, request that exact action:
`hub approval request --kind merge --payload '{"repo": "<org>/<repo>", "pr": 123,
"head_sha": "..."}'`.

## Rules

- GitHub Issues are disabled for work. Never `gh issue`; tasks, asks and approvals go through
  `hub`.
- A bot may merge a PR into its own `emp-<slug>` repository after relevant tests and required
  checks pass, without human approval. Other repositories follow their scoped review and approval
  rules; never bypass branch protection. Deleting, archiving or changing repository visibility
  remains gated.
- Never push to another repository's default branch. Changes go on a branch as a draft or review
  PR, unless the bot's `access:` entry says `write`.
- Ordinary shared-internal docs PRs that change only `docs/` in `ticoteam/tico` may be
  self-merged by their authorized author (`policies/documentation.md`); authorized maintainers
  may also merge other Tico PRs after checks (`policies/approvals.md`).
- Your own `emp-<slug>` repository: commit directly to `main` for small internal changes, or use
  a PR and merge it yourself. The runner pushes its current checkout after a turn and fast-forwards
  that checkout before the next one. Use a separate worktree for a PR branch, or return the runner
  checkout to an up-to-date `main` before ending the turn. Do not clone another bot's repository
  into your own. Ask its owner to improve it with a Hub task (`policies/handoffs.md`).
- Creating a bot repository (BotOps, or the owner): `hub github create-bot-repo <slug>` from a
  template, or `--empty` for a bot whose repository already exists on a computer
  (`docs/github-app.md`). It needs the app's administration permission, and the name is always
  `emp-<slug>` in the connected organization, private.

## Recipes

- Read one file without a clone: `gh api repos/<owner>/<repo>/contents/<path> --jq .content |
  base64 -d`.
- A review PR for a repository that still needs human review: branch from the default branch,
  commit, `gh pr create --draft`, put the PR URL on the Hub task, and stop for review.
- A bot built locally with no repository on GitHub yet: `hub github create-bot-repo <slug>
  --empty`, then set the bot's repository to `<org>/emp-<slug>` (`docs/github-app.md`). Do not push
  it yourself: the bot's next turn publishes its history with its own token.

## Gotchas

- With the app connected, the bot's token reaches only its own repository (plus any extras the
  owner granted); a 403 or 404 on another repository is the scope, not an outage. With no app,
  everything shows as the computer's login, so say which bot and which task in the PR body.
- A bot repository that diverged from `origin/main` is not force-pushed by the runner; it logs one
  line an hour. Check for another writer's commits, then reconcile without discarding their work.
- `GH_TOKEN` is not in a turn; if `gh auth status` fails on a computer without the app, that
  machine's login is the operator's to fix.
- Company docs are Tico's Docs page (internal docs, and links to where the rest live); do not
  edit `docs/` in a product repo for that ([docs/docs.md](../docs/docs.md)).

## Learnings

What bots and people learn about this integration is added with `hub learn github "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
