# Access: what each employee may touch

Every employee declares its access in `employee.yaml` under `access:`. The hub app shows this
list on the bot's page, so the owner can see at a glance whether a bot can read Slack, send email as
owner@acme.example, spend on Google Ads, and so on. **Not listed means not allowed.**

```yaml
access:
  - service: gmail                # short name, lower-case
    identity: owner@acme.example  # the account it acts as; omit when not an identity
    can: [read, draft]            # verbs, see below
    env: GMAIL_CREDENTIALS        # secret that connects it; the app shows connected / not connected
    note: "send needs outbound_send: true"
```

Verbs: `read`, `draft` (prepare but never send or publish), `send`, `post`, `write`, `spend`, `use`
(a tool with no account of its own, like a web search or an AI model API).

Rules:
- Every employee implicitly has Tico Hub tasks, its own prefix in the S3 bucket, and read/write
  access to its own `emp-<slug>` GitHub repository, including its branches and pull requests.
  Do not list them. Access to another bot's or a product repository still needs a declaration.
- `send`, `post`, `publish`, or any `spend` verb is only honoured while `outbound_send: true` and
  within `approvals.md`. Listing the verb records intent; the flag turns it on. For email only,
  an exact-message Hub approval (`approvals.md`) turns `send` on for the one message it names.
- The secret named in `env` lives in `~/tico-work/secrets/<slug>.env` on the machine that runs
  the company. If it is missing, the app shows "not connected" and the bot should ask via
  `needs-human` rather than improvise.
- A value in that file may be a 1Password reference instead of the secret itself:
  `UPFLUENCE_PASSWORD=op://vault/item/field`. The runner reads it from
  the **Acme Bots** vault at the start of the turn with a read-only service account
  (`OP_SERVICE_ACCOUNT_TOKEN` in `_shared.env`, never handed to a run) and `scripts/preflight.sh`
  checks that the reference resolves. Prefer this for every new secret; the owner adds the item in
  1Password and only the reference lands on disk.
- Email is special. A bot may only send from an address that appears as an `identity` on a
  `gmail` entry with `send` in `can`. No entry means the bot cannot email anyone from any address.
- Calendar appointments are a company-wide capability for every bot, separate from Gmail access.
  Every address in `registry/people.yaml` may be read or scheduled through the guarded Hub tools
  or mail CLI; a Gmail `read_only: true` entry does not restrict calendar use:
  `hub_calendar_list` reads the connector's bounded snapshot and `hub_calendar_schedule`
  queues an audited provider action. `hub_calendar_status` must say `succeeded` before the bot
  claims the event exists. `mail calendar add|list|get` is the direct audited path on the runner.
  Invitations may include guests outside the company (the owner can turn that off with
  `TICO_BLOCK_EXTERNAL_INVITES=1`, which limits bots to roster attendees). This standing grant does
  not add Gmail read, draft or send authority.
- Mailbox `read` access includes listing and downloading attachments from that mailbox for
  every employee. There is no separate incoming-attachment permission; outbound attachment
  restrictions remain unchanged.
- A Gmail entry may set `read_only: true` to restrict `read` to reading messages and downloading
  attachments. This refuses labels, archive, mark-read, star, rules, drafts, and sends even if
  another verb is accidentally listed. Without this flag, existing `read` permissions retain
  their mailbox-filing behavior. An optional top-level `default_mailbox` selects one declared
  mailbox when a CLI command omits `--mailbox`; it grants no additional access. Without it, a
  command with no `--mailbox` acts as the one gmail identity the manifest declares; org-tree
  reads (below) never become the default, and two declared identities make `--mailbox` required.
- A person's `inbox_bot` in `registry/people.yaml` may read that person's mailbox plus everyone
  who reports to them (`reports_to`). A gmail entry may set `org_read: true` for the same
  expansion from that identity. Draft and send stay on the declared mailbox. Each mailbox has
  its own rules in `registry/mail-rules.yaml`. `mail inbox --all-mailboxes` and
  `mail rules run --all-mailboxes` walk the tree. Marketing, skip-list, and notification rules
  file noise before a model reads anything.
- The browser is one service, `aside`, with two extra fields: `sites:` (the hosts the bot may open;
  subdomains count) and `can: [read]` or `[read, act]`. `read` is looking: snapshots, titles,
  screenshots. `act` is clicking, typing, and handing a task to Aside's agent. Logins are never a
  bot's job: The owner signs in once in Aside, and a login page means stop and say so.
- A Slack entry may set `channels: [channel-name, ...]`. When present, `history --as <slug>` (or a
  hosted run carrying `HUB_EMPLOYEE`) refuses reads outside that allow-list before calling Slack.
  Omit it only for existing roles that intentionally need every registered readable channel. A
  channel in this list still needs to exist in `registry/slack-channels.yaml` and the hub app must
  be a member. Set `dms: false` when the role must not read the shared app's DM inbox; `inbox`
  enforces it from `--as <slug>` or `HUB_EMPLOYEE`.
- Changing `access:` is a Tico-level decision: create a task for the owner rather than editing
  your own manifest.
