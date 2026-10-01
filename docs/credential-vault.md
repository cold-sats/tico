# Shared credentials

How a credential reaches a bot. A bot only ever sees the environment variable named in its own
`tools:` entry; it never reads the vault, 1Password or a credential file itself. The runner masks a run's
granted values (as typed, URL-encoded or base64) with `••••` in everything it posts and logs, in the text
files the run changed in the repository, and holds back a push whose commits contain one (`runner/redact.py`).

## Who can use a credential

Four words, used the same way everywhere:

- A **human** signs in. The owner and the admins are the **credential administrators**: they store credentials and decide who has them
  (`TICO_CREDENTIAL_ADMINS` names a different list; a member is never one).
- A **bot** is a worker. It has the credentials it was given and nothing else. **A bot never uses a credential that was not
  granted to it**, and never another bot's: having one in its own file on its computer does not make it anyone else's.
- A **credential** is a stored secret with a name and, for a bot, the environment variable it arrives in (`JIRA_BASIC_AUTH`). Its value
  is encrypted and is never shown in a message, a log, an event or to a model.
- A **grant** is the explicit yes: "this credential, for this bot" (or for a person). A grant can be taken away (**revoked**) and the
  bot's next run no longer has it.

## Tico's Credentials

Settings → Credentials lists team credentials, usernames and masked previews. The owner and admins administer the vault. Each credential has its own grants. A granted human may reveal/copy it or attach it to bots they manage; a direct bot grant works on its assigned computer during an active run. Revoking the parent grant removes delegated bot access. Changing a bot owner invalidates delegation from its former owner.

Credentials use AES-256-GCM with per-write random nonces and credential-bound authenticated data. Reveal operations are audited; credential values are excluded from audit and idempotency receipts. Restoring a snapshot revokes restored grants to avoid resurrecting permissions.

The bot credential name becomes an environment variable only for a granted bot, during its run (`GET /api/v2/credential-runtime`), on a Mac or Linux computer and in the Docker runner alike. File credentials become mode-0600 temporary files during the run. A bot with a credential of the same name in its own secrets file gets the granted value. A bot cannot be granted two credentials that use one variable name (the second grant is refused until the first is taken away). Computer login entries describe existing CLI/browser sessions and must be connected separately on each computer. A bot's Tools row and Health count a granted credential as present ("granted through the credential vault") even though its computer's secrets file does not hold it: the server knows the grant, the computer cannot. Secrets already in a bot's own file keep working; storing one in Credentials does not erase the file and does not give it to any other bot.

## The key: nothing to set up

The vault works as soon as Tico starts. The AES-256 data key is 32 random bytes made once, the first time a credential is stored,
and kept in `credential.key` (mode 0600, the server's user) in the data volume next to the database (`/data/credential.key` in the
Docker install). The database holds only encrypted values and a fingerprint of the key, so a copy of the database alone cannot read them.
The key is never logged or returned by any route.

**Back `credential.key` up** with the database, to a different place than the database backup (a password manager, a private bucket):
Litestream copies the database, not this file. A database restored without its key file cannot decrypt any credential: Credentials
says the key file is missing, and Tico never makes a new key over an existing vault, so nothing is lost by putting the file back.
Re-enter the credentials only if the key is truly gone.

To use AWS KMS instead, set `TICO_CREDENTIAL_KMS_KEY` (a key id or alias). Then the data key is wrapped by that KMS key and only the wrapped form
is in the database. Setting it on a server that has been using the key file wraps the same key with KMS on the next use, without
re-encrypting anything, and the file can then be deleted. An install that began with KMS is unchanged, and taking the KMS key away
again is refused rather than starting a second key.

## Give a bot a credential another bot has

Say it in the chat with BotOps: "Give Engineering Monitor the Jira access Jira Manager has." BotOps acts as you, so you must be a credential
administrator; anyone else is told who to ask. It runs at once, with no Confirm card, and then tries the connection as the bot:

1. If the credential is only in the first bot's own file (`secrets/<bot>.env` on its computer), BotOps moves it into Credentials first
   (`hub credential import JIRA_BASIC_AUTH --from-bot jira-manager`). The computer that runs that bot reads the variable from
   that one file and sends it to the server itself, over its own signed-in channel. The value is not printed, logged or put in a
   message, and the file is not changed, so the first bot keeps working. Only a credential administrator can ask, and only for a
   variable in that bot's own file (not `_shared.env`, not another bot's).
2. It grants the stored credential to the second bot: `hub credential grant "JIRA_BASIC_AUTH" --to engineering-monitor`. (`--to` takes the
   bot's name or slug; the credential is named by its name or its variable.) The second bot has it, as that variable, from its next run.
3. To take it away: `hub credential revoke "JIRA_BASIC_AUTH" --from engineering-monitor`.

The same three steps are the tools `hub_credential_import`, `hub_credential_grant` and `hub_credential_revoke`, and Settings → Credentials
does the grant and revoke by hand. A grant to a person, or to every computer, still asks for the person's own click when it comes through BotOps.

## The local credential key and backups

Without `TICO_CREDENTIAL_KMS_KEY`, the data key is 32 random bytes in `/data/credential.key` (mode 0600) on the server's data
volume. The database holds ciphertext only, so **a database restored without that file cannot decrypt a credential**. Litestream
copies the database and not the file, so the backup loop copies the key to the same backup destination: the bucket and prefix in
`TICO_BACKUP_URL` (object `credential-key/credential.key`), else the `tico-backups` volume. It copies it when the key first
appears and whenever it changes, and never logs it or sends it anywhere else. The object is encrypted at rest as the bucket is;
because the database backup is in the same bucket, keep it private, limit its access key to it, and turn on versioning.

Health shows **Backups** as a warning while a local key exists, backups are set up, and the key has not been copied yet; with
backups only on this server the note says the key is lost with the server too.

To restore: `docker compose run --rm --no-deps server restore` brings back the database, attachments and the key (see
[Backups and restore](install.md#backups-and-restore)). By hand, copy `credential-key/credential.key` from the backup
location to `/data/credential.key` (32 bytes, mode 0600, owned by the server's user) before the server starts. Tico never makes a
new key over an existing vault, so putting the file back loses nothing. Setting `TICO_CREDENTIAL_KMS_KEY` replaces the file
as the thing to protect: the data key is then wrapped by KMS in the database.

## Credentials asked for in the chat

A bot that needs a credential opens a **credential card** in the conversation where it asked (`hub credential request <VARIABLE> --for-bot <bot> --label
"your Jira credential" --format "you@example.com:API token" --help-url https://...`): the title says what it is for, the input shows the exact format,
"Get one" opens the page where the token is made, and Save sends the value from the browser to `POST /api/v2/credential-requests/{id}/save`.
The server checks its shape (a `:` where the format has one; never echoing the value), stores it in this vault under the variable's name
(a credential already holding that name for that bot is replaced, one shared with other bots is left alone), grants it to that one bot, and wakes the
asking bot with "Saved". The value is in no message, event, receipt or log, and never reaches the model. Only the human who was asked, or a
credential admin, can fill a card, and only a credential admin can store (the vault's rule: the owner and the Admins, unless
the owner limits it to the owner in Settings > Humans); anyone else sees who to ask.

If a human pastes a credential into the chat instead, BotOps stores it with `hub credential set <VARIABLE> --for-bot <bot>` (the value on standard input,
never on the command line) as that human, and the server takes the pasted words out of their messages, the run's recorded events and the answers kept
for retries, replacing them with `•••• saved as <VARIABLE>`; later events of the same run are scrubbed as they arrive. The runner masks granted values in
what it posts and logs. `hub message redact <id>` does the same for one message.

## Credential files on the computer

Bots receive only their granted Credentials. A run does not inherit the runner's process credentials, `_shared.env`,
its old bot file, or a profile file. Revoking a grant takes the value out of the next run, even when an old file still has it.

On upgrade, each existing bot automatically gets grants for everything it could read before: its own file's variables,
every key in its computer's `_shared.env` (except the Codex sign-in key), the variables its Tools name, and the key used
by its model runtime. The Computer encrypts those values into Credentials through its own signed-in
channel. A bot created after the upgrade inherits no shared tool credentials. Migration is once per existing bot, and
never restores a revoked grant. Legacy files stay available to operator tools, but are no longer a source for run environments.
On isolated Computers, the supervisor owns these files. A Computer without process isolation still has the shared
filesystem trust boundary described in [SECURITY.md](../SECURITY.md); environment filtering does not isolate its shell.
Use Credentials or its chat card for new values; grant them to the bot that needs them.

## 1Password references

A stored Credential may be `op://vault/item/field` instead of the credential. The runner
resolves it at run start with a read-only 1Password service account (`OP_SERVICE_ACCOUNT_TOKEN`
on the Computer, `runner/op.py`). The service account token stays with the runner; only the resolved granted value reaches the bot. A reference that does not resolve becomes an
empty value, so preflight shows it as missing instead of a run failing halfway. Rotating an item
in 1Password reaches a reference on the next run.

`scripts/vault-sync.sh` is the by-hand complement: it copies plain values from 1Password into
the credential files, for tools and checks that run outside a run. Its map
(`secrets/vault-map.txt`, or the file `VAULT_SYNC_MAP` names) has one line per variable,
`ENV_VAR | op://<vault>/<item>/<field> | target env file`; the target defaults to
`_shared.env`. Keep the map private; it names your vault items. An item whose name contains `@`
breaks the `op://` form; reference it by its item id.

## Rules for bots

- Credentials never go in tasks, git, logs, updates or prompts. A key-shaped string in a
  draft fails lint for this reason. A bot that needs one opens a card in the chat; BotOps stores what a human
  pastes and removes it from the conversation.
- A missing credential is not yours to work around: open the card (`hub credential request`), or for a task no human is in,
  name the variable on the task and stop. The bot's Tools row shows every declared Credential as present or missing.
- Saving a credential is not permission to use it. Only a `tools:` entry and a grant connects a bot to a credential. Changing `tools:` is a task for the owner.
- A granted value exists only for that run; do not copy it anywhere that outlives the run.
- Each bot can have only one active granted Credential for a variable. Revoke its previous grant before replacing it.
- Store new values in Credentials and grant them to the bot; a shell export does not grant access.

## Delete a Credential

A Credential administrator can choose **Delete** in Credentials, use `hub credential delete <name>`, or call
`DELETE /api/v2/credentials/<id>`. Deletion erases the encrypted value and all grants together. History records names and
variable names only. Revocation removes access while keeping the stored value; deletion removes the Credential itself.

**Every computer (signs models in)** is available only for stored model API keys and tokens, with the variable name set to
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` or `CURSOR_API_KEY`. Naming a Credential after a variable alone
does not set that field. This signs the model software in; tool Credentials still need a grant per bot.
`hub_credential_grant` targets one bot; use Credentials to grant a model key to Every computer.
