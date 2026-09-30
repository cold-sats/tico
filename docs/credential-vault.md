# Shared credentials

How a credential reaches a bot. A bot only ever sees the environment variable named in its own
`tools:` entry; it never reads the vault, 1Password or a credential file itself. The runner masks a run's
granted values (as typed, URL-encoded or base64) with `••••` in everything it posts and logs, in the text
files the run changed in the repository, and holds back a push whose commits contain one (`runner/redact.py`).

## Tico's Credentials

Settings → Credentials lists team credentials, usernames and masked previews. The owner and admins administer the vault. Each credential has its own grants. A granted human may reveal/copy it or attach it to bots they manage; a direct bot grant works on its assigned computer during an active run. Revoking the parent grant removes delegated bot access. Changing a bot owner invalidates delegation from its former owner.

Credentials use AES-256-GCM with per-write random nonces and credential-bound authenticated data. The data key is wrapped by the dedicated rotating AWS KMS key. SQLite and backups contain ciphertext, not the plaintext data key. Reveal operations are audited; credential values are excluded from audit and idempotency receipts. Restoring a snapshot revokes restored grants to avoid resurrecting permissions.

The bot credential name becomes an environment variable only for a granted bot, during its run (`GET /api/v2/credential-runtime`). File credentials become mode-0600 temporary files during the run. Computer login entries describe existing CLI/browser sessions and must be connected separately on each computer. Existing runner-local credentials continue to work during migration; moving a credential to this list does not erase local copies or implicitly grant it to every bot.

The initial migration inventories the existing bot credentials directory and resolves its configured 1Password references. Values are encrypted locally before upload. It adds no grants, preserves existing local files, and imports computer-login metadata without exporting browser sessions. All raw migration evidence remains outside Git.

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

`<workspace>/secrets/_shared.env` (every run on that computer inherits it) and
`secrets/<slug>.env` (one bot; it wins), mode 600, never in git. The runner loads both at the
start of a run. `credential_profile` on an `tools:` entry loads one named variable from
`secrets/<profile>.env`, not the whole file.

## 1Password references

A value in a credential file may be `op://vault/item/field` instead of the credential. The runner
resolves it at run start with a read-only 1Password service account (`OP_SERVICE_ACCOUNT_TOKEN`
in `secrets/_shared.env`, `runner/op.py`) and strips that token, `OPENROUTER_API_KEY` and
`HUB_INGEST_TOKEN` from the run's environment. A reference that does not resolve becomes an
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
  name the variable on the task and stop. `$HUB_DIR/scripts/preflight.sh <slug>` shows every declared credential as present or missing.
- Saving a credential is not permission to use it. Only an `tools:` entry (and, for the Tico
  vault, a grant) connects a bot to a credential. Changing `tools:` is a task for the owner.
- A granted value exists only for that run; do not copy it anywhere that outlives the run.
- A shared read credential and a narrower write credential can carry the same variable name: the bot's own
  file wins over `_shared.env`, and its `tools:` entry must say `write` before it may write.
- The launchd job on a Mac does not see a shell export; a credential must be in a credential file.
