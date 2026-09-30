# GitHub App

Your team gets GitHub access through a GitHub App that the owner creates in the team's own
GitHub organization. Tico holds no shared token: for every run Tico asks GitHub for a token that
works on that one bot's repository (and any extra ones the owner allowed) and expires within the hour. Without a connected app nothing
changes; bots keep using whatever git access their computer already has.

## Permissions and why

| Permission | Level | Why |
|---|---|---|
| Contents | write | a bot pulls and pushes its own repository |
| Pull requests | write | a bot opens pull requests for its work |
| Issues | write | a bot files and comments on issues |
| Metadata | read | required by GitHub for every app |
| Administration | write, optional | only to create bot repositories from a template; omit it by leaving the box unchecked |

The app is private, has no webhook (nothing here needs GitHub to call Tico), and requests no
workflow permission, so a bot cannot change `.github/workflows` files. Add Workflows: write on the
app's GitHub settings page if a bot's repository needs that.

Run tokens ask for exactly the four non-administration permissions and only the bot's own repository
plus the extra repositories the owner listed for it.
The runner cannot pick the repository: Tico reads it from the bot's configuration, and refuses a
bot the caller does not run or a repository outside the connected organization.

## Set up

1. As the owner, open Tools, GitHub. Enter the organization, optionally rename
   the app, and choose whether Tico may create bot repositories. Select Connect GitHub.
2. GitHub shows the app to create. Confirm it. GitHub returns to Tico, which stores the app's
   credentials and sends you to install the app on the organization.
3. On the install page, choose **All repositories** (recommended). Bots then get new repositories
   automatically, with nothing to add each time a bot is created. This does not widen what a bot can
   touch: each bot's token names its own repository plus any extra repositories you allow (below), and
   nothing else. Choosing selected repositories works too, but every new bot repository, and every
   extra repository, must be added to the installation by hand. Settings then shows the app as installed.

If the organization also holds sensitive code, create a separate GitHub organization just for bot
repositories and connect that one. "All repositories" then covers only what bots should reach, and a
mistake in a token's scope cannot expose the rest. The app itself can reach whatever it is installed on;
the per-bot limit is enforced by Tico when it asks GitHub for a token.

Bots' repositories must live in the connected organization. A bare repository name is completed by
`TICO_GITHUB_OWNER`, then by the connected organization.

## Extra repositories for one bot

A bot sometimes needs a second repository, such as shared documentation or a design system. Whoever manages the
bot (the owner, an admin, its owners, the people it reports up to) adds it in Settings, Bots, the bot's settings, Extra GitHub
repositories (one per line, in the connected organization), or asks BotOps to. From then on that bot's token covers its own
repository and those, with the same four permissions. Other bots are unaffected, and each change is an audit
event (`github.bot_repos_changed`, with the list before and after). The API is
`GET` and `PUT /api/v2/bots/{bot}/github-repos`. A repository outside the connected organization is
refused. Remove a repository from the list to take it back out; tokens already issued expire within the hour.

## Creating bot repositories

With administration allowed, the owner can create `<org>/bot-<slug>` privately from a template:

    hub bot repo-create botops            # from ticoteam/botops
    hub bot repo-create sales --template <org>/bot-template

The BotOps bot (`bot:botops`) may make the same call, because the owner allowed repository creation
when connecting the app. It is limited to the name `bot-<slug>` for a bot that exists (planned or
active, not archived), always private, in the connected organization, from the default template or
one in that organization. Every creation is audited (`github.repo_created`) with the acting bot.
Anyone else gets 403 with the reason. Without the administration permission the command says so and
how to create the repository by hand. If the app is installed on selected repositories only, add the
new repository to the installation.

### A bot whose repository already exists on a computer

A bot BotOps built locally (no GitHub yet) has history to keep, so it needs an empty repository, not
a template copy. `--empty` (API `{"slug": ..., "empty": true}`, no template) creates a private
`<org>/bot-<slug>` with nothing in it (`POST /orgs/<org>/repos`, `auto_init` false). Then, from the
bot's checkout:

    hub bot repo-create <slug> --empty

Then set the bot's repository (Settings, Bots) to `<org>/bot-<slug>`; a bare `bot-<slug>` there also
works and means the connected organization (an existing `emp-<slug>` repository keeps its name). Nobody pushes by hand: a run's token
(`POST /api/v2/github/token {"bot": "<slug>"}`) is scoped to that bot's own repository, so BotOps
cannot push another bot's history. Instead the runner does it in the bot's own run, at the start
and again after a completed run: when the checkout has commits but no upstream, it sets `origin` to
the resolved https URL and runs `git push -u origin <branch>` with that bot's token. It never forces.
If the repository already has history the checkout does not contain, or `origin` points somewhere
else, nothing is pushed and Health shows "Bot history" with the reason (the bot's warning in
Settings, Bots says the same); fix the cause and the next run publishes.

## Where the key lives

The app's private key, client secret and webhook secret are encrypted (AES-GCM) in the Tico database.
With `TICO_CREDENTIAL_KMS_KEY` set the key is the credential vault's KMS-wrapped data key; otherwise
it is a random `github-app.key` (mode 0600) beside the database, so a database copy alone does not
carry the app's key. No API returns the key and it is never logged. Installation tokens are cached in
server memory only, until five minutes before they expire. The runner holds the run's token in the
run's process environment (`GH_TOKEN`, and an inline git credential helper); nothing is written to disk.
A token is fixed for its run, and a run may outlast it only after about fifty minutes of the hour.

## Rotating the key

On the app's GitHub settings page (Settings, Developer settings, GitHub Apps, your app), generate a
new private key and delete the old one. Then disconnect in Tico and connect again, or delete the
app and reconnect, so Tico stores a key GitHub still accepts. Cached tokens keep working until they expire.

## Disconnect and uninstall

Disconnect in Tico only forgets the app locally; bots fall back to their computers' git access. To
revoke access on GitHub, uninstall the app from the organization's installed apps page, or delete the
app from its settings page.
