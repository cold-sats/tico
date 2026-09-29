---
service: credential-vault
title: Credentials (1Password and the hub vault)
kind: cli
summary: How a secret reaches a bot — the secrets files on the runner computer, op:// references into a 1Password vault, and the hub's encrypted Credentials with per-bot grants.
access: "a bot only ever sees the environment variable named in its `access:` entry; it never reads 1Password or the hub vault itself"
credentials:
  - OP_SERVICE_ACCOUNT_TOKEN — the read-only 1Password service account scoped to the vault "Company Bots", in secrets/_shared.env on the runner computer; consumed by the runner and stripped from every turn
  - the per-service variables listed under "What data it has", each named by the bot's own `env:` field
declared_as: |
  - service: <name>
    can: [read]
    env: THE_VARIABLE          # what the bot's code reads; its value comes from one of the paths below
    credential_profile: docs-qa   # optional: also load THE_VARIABLE from secrets/<profile>.env
writes: never
owner: owner
aliases: [1password, vault, secrets]
---

## What it is

Four pieces, all on the runner side, none of them in a bot's hands:

1. **The secrets files.** `~/tico-work/secrets/_shared.env` (every turn inherits it) and
   `secrets/<slug>.env` (one bot; it wins), mode 600, never in git. The runner loads both at
   the start of a turn (`runner/service.py`).
2. **1Password references.** A value in those files may be `op://vault/item/field`
   instead of the secret. The runner resolves it at turn start with the read-only service
   account (`runner/op.py`) and strips `OP_SERVICE_ACCOUNT_TOKEN`, `OPENROUTER_API_KEY` and
   `HUB_INGEST_TOKEN` from the turn's environment; those are the runner computer's own keys. A reference
   that does not resolve becomes an empty value, so preflight shows it as missing instead of a
   run failing halfway. Prefer this for every new secret: the owner adds the item in 1Password and
   only the reference lands on disk.
3. **`scripts/vault-sync.sh`.** The by-hand complement: copies plain values from the vault
   into the env files for connectors and checks that run outside a turn. Its `MAP` says which
   variable comes from which item and lands in which file.
4. **The hub's Credentials** (Settings → Credentials, `docs/credential-vault.md`,
   `backend/credentials.py`). Encrypted with AES-256-GCM under a KMS-wrapped data key. The owner
   and admins administer it; each credential has its own grants. A granted bot receives the
   value as the named environment variable only during its run, through
   `GET /api/v2/credential-runtime`; file credentials become mode-0600 temporary files. Reveals
   are audited. Restoring a snapshot revokes restored grants. Moving a credential here does not
   erase local copies or grant it to every bot.

## What data it has

The map is a file (`secrets/vault-map.txt`, or the path in `VAULT_SYNC_MAP`), one line per
variable, `|`-separated: `ENV_VAR | op://<vault>/<item>/<field> | target env file (optional)`.
The target defaults to `_shared.env`; name a bot's file to reach only that bot. An example
map for a company that uses a few of the services documented here:

```text
POSTHOG_API_KEY | op://Company Bots/PostHog Read Only/credential | _shared.env
STRIPE_API_KEY  | op://Company Bots/Stripe Read Only/credential  | finance.env
CLOSE_API_KEY   | op://Company Bots/Close API/credential         | sales-ops.env
SENTRY_TOKEN    | op://Company Bots/Sentry/credential            | engineering.env
```

Keep the map itself private; it names your vault items. Not in the map, in `_shared.env` by
hand: `SLACK_BOT_TOKEN`, `AWS_PROFILE`, `HUB_BUCKET`, `OP_SERVICE_ACCOUNT_TOKEN`; a Google
service-account key is a file, `secrets/google-sa.json`.

## How a bot uses it

A bot does not use the vault. It reads the variable named in its own `access:` entry from the
environment and never prints, logs or writes the value. What it can do:

```bash
$HUB_DIR/scripts/preflight.sh            # every declared secret: present, resolves, or missing
hub task create --owner PERSON --title "Add the X key to my secrets file" --body "..."   # when one is missing
```

What the owner does on the runner computer:

```bash
scripts/vault-sync.sh                    # sync everything in MAP
scripts/vault-sync.sh CLOSE_API_KEY      # one variable
```

## Rules

- Secrets never go in chat, hub tasks, git, logs, reports or prompts. A key-shaped string in a
  draft fails mail lint for this reason.
- A missing key is not yours to improvise around: the app shows "not connected"; file a task
  for the owner naming the variable and stop.
- Saving a credential is not permission to use it. Only an `access:` entry (and, for the hub
  vault, a grant) connects a bot to a secret. Changing `access:` is a task for the owner, not an
  edit to your own manifest.
- A granted bot's value exists only for that run; do not copy it anywhere that outlives the turn.
- Nothing here writes to 1Password. The owner adds and rotates items; a bot never asks for a
  service to be bought or a credential created merely to try something.

## Recipes

- Check what is connected before a task that needs a key: `scripts/preflight.sh`; a referenced
  item that is empty or absent shows as missing with the variable name.
- Add a new secret the preferred way: the owner creates the item in "Company Bots", then writes
  `VAR=op://vault/item/field` into `secrets/<slug>.env`; the runner resolves it next turn.
- An item whose name contains `@` breaks the `op://vault/name/field` form; reference it by its
  item id instead (the Bright Data line in `vault-sync.sh` does this).
- A shared read key and a narrower write key can carry the same variable name: the bot's own
  file wins over `_shared.env`, and its `employee.yaml` must say `write` before it may use it
  (PostHog for the CRO).

## Gotchas

- The launchd job does not see a shell export; a key must be in the env files, not your shell.
- Existing runner-local files keep working during the move to the hub vault; the two do not
  replace each other automatically.
- Rotating an item in 1Password changes nothing on disk until `vault-sync.sh` runs (plain
  values) — references pick it up on the next turn.
- `credential_profile` on an `access:` entry loads one named variable from
  `secrets/<profile>.env`; it does not load the whole profile.

## Learnings

What bots and people learn about this integration is added with `hub learn credential-vault
"…"` and shown under this page; a person folds it into the page over time. The page is the rule.
