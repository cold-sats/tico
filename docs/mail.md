# Message bots: how a bot reads and files email

In the web app, **Message bots** in the sidebar groups connected mailboxes and Slack channels
by the bot that covers them. Open one to see that bot's instructions and routines on the
left and example messages on the right. Email threads are synced copies; the mail tool still
handles Gmail actions. A messaging icon beside a human in the team chart opens their message bot.
The old `#/mail` route remains available for existing deep links.

Mail is one shared tool, `$HUB_DIR/scripts/mail.sh`. One Google service account acts as every
mailbox; who may act as which one comes from the `access:` block in your `employee.yaml`
(`policies/access.md`), never from a prompt. Every read of a body and every label, archive or
star is written to an audit log with your slug and the task.

**Never call the Gmail or Calendar API directly.** Not with curl, not with a Google SDK, not
from your own `software/`. The access checks, the rules, the audit log and the retry handling
live in the tool; a direct call skips all four and is a policy violation, not a shortcut. The
service-account key is not in your environment, so a direct call would not work anyway.

The dispatcher gives every run `HUB_EMPLOYEE` (your slug) and `HUB_DIR` (the Tico clone), so
`mail.sh` already knows who you are. `--as <slug>` is only for running it by hand.

## What you can do today

Reading:

```bash
$HUB_DIR/scripts/mail.sh inbox --untriaged --format brief   # inbox mail with no hub/* label; the list you work
$HUB_DIR/scripts/mail.sh inbox --untriaged --all-mailboxes --format brief  # own mailbox plus reports
$HUB_DIR/scripts/mail.sh inbox --new --since 24h      # what you have not seen in the last day (marks it seen)
$HUB_DIR/scripts/mail.sh inbox --label hub/needs-owner --format brief
$HUB_DIR/scripts/mail.sh thread 18f2c9a3b4d5e6f7 --format brief   # the conversation, no bodies; md when drafting
$HUB_DIR/scripts/mail.sh search "from:stripe.com newer_than:7d"   # any Gmail query, max 50
```

Output is markdown by default: one block per message with id, thread, from, to, date
(America/Los_Angeles), labels, whether it carries an unsubscribe link, attachments listed by
name and size, and a plain-text body (HTML stripped, cut at 32 KB with a marker). Add
`--format json` when you want to process it, `--json` on the other commands.

Filing, which is visible in Gmail so Ana can see and undo what you did:

```bash
$HUB_DIR/scripts/mail.sh label add 18f2... 18f3... hub/needs-owner
$HUB_DIR/scripts/mail.sh label remove 18f2... hub/needs-owner
$HUB_DIR/scripts/mail.sh archive 18f2...             # removes INBOX, deletes nothing
$HUB_DIR/scripts/mail.sh mark-read 18f2...
$HUB_DIR/scripts/mail.sh star 18f2...
$HUB_DIR/scripts/mail.sh triaged 18f2... 18f3...     # you are done with these
```

Every one of those takes `--dry-run`, which prints what would change and changes nothing.

The rules, which run before you read anything:

```bash
$HUB_DIR/scripts/mail.sh rules run --dry-run          # what the rules would do
$HUB_DIR/scripts/mail.sh rules run                    # do it
$HUB_DIR/scripts/mail.sh rules run --all-mailboxes    # each mailbox's own rules, own plus reports
$HUB_DIR/scripts/mail.sh rules explain 18f2...        # why this message got what it got
```

Rules run before any model. Marketing (unsubscribe links), notification senders, and
`registry/mail-rules.yaml` `skip:` addresses/domains are filed and never opened by the bot.
Each mailbox can add its own rules under that address after `common`. A message bot for a
human also reads everyone who reports to them; use `--all-mailboxes`.

And the record:

```bash
$HUB_DIR/scripts/mail.sh whoami                       # your mailboxes and verbs
$HUB_DIR/scripts/mail.sh policy show                  # what you may send, to whom, how often
$HUB_DIR/scripts/mail.sh audit --since 24h            # everything mail did
$HUB_DIR/scripts/mail.sh sent-log --since 7d          # what actually went out
$HUB_DIR/scripts/mail.sh doctor                       # is mail set up at all
$HUB_DIR/scripts/mail.sh sync --all-roster --backfill 90d   # persist mail locally (Mac)
$HUB_DIR/scripts/mail.sh sync export --json           # unpushed batch; no hub token
$HUB_DIR/scripts/mail.sh sync ack <id> ... --mailbox you@acme.example
```

`mail sync` copies normalized messages into `<projects>/runtime/mail/mail.db` (`messages` plus a
per-mailbox `sync_state` cursor). First run backfills `--backfill 90d`; later runs use Gmail
history and, if that cursor has expired, `after:<last_run − 2d>`. `--all-roster` is every
address on `registry/people.yaml`. The same rows are also written whenever `inbox`, `thread` or
`search` already fetches a message. Export/ack print and acknowledge a batch only — this
command does not hold a Tico token or push to the server.

## Writing: draft, reply, send

Every write goes through the same five gates, in order: **policy**, **lint**, **a second model**,
execution, audit. A gate that says no never throws the words away - it leaves a draft in Gmail
with the reason. Read the reason. Do not retry the same text, and do not look for another route.

### Draft

```bash
$HUB_DIR/scripts/mail.sh draft --to ava@creator.example \
  --subject "Ava, 6 months of Acme on us" --body-file out/ava.txt --issue 128 [--dry-run]
$HUB_DIR/scripts/mail.sh draft --reply-to 18f2c9a3b4d5e6f7 --body-file out/reply.txt --issue 128
```

`--reply-to <thread>` fills in the recipient and the subject from the thread and keeps
`In-Reply-To` and `References`, so the message lands in the conversation instead of starting a
new one. `--cc` takes internal addresses only. `--dry-run` lints and reviews and writes nothing.

The draft is keyed on (you, the task, the recipient, the subject, the body): running the same
command twice **updates the same Gmail draft** instead of leaving two. Change a word and it is a
new draft. The thread gets `hub/drafted`, so Ana can see it in Gmail.

```json
{ "ok": true, "draft": "r-882...", "thread": "18f2c9a3b4d5e6f7", "to": ["ava@creator.example"],
  "subject": "Ava, 6 months of Acme on us", "created": true, "updated": false,
  "lint": { "ok": true, "findings": [], "summary": "clean" },
  "review": "ok", "label": "hub/drafted" }
```

### Send

```bash
$HUB_DIR/scripts/mail.sh send --draft r-882... --issue 128 [--approval-issue 131] [--dry-run]
```

**A send needs an approval task unless a standing allowance covers the recipient.** Internal
addresses (`@acme.example`) need neither. Everyone else needs one of: an allowance in
`registry/mail-policy.yaml` that lists the recipient (Influencer's creator table is one), or
`--approval-issue N` where N is a **closed** task in Tico with `owner:ana` and
`type:decision` whose title or body names that address or the thread. `mail policy show` says
which of those you have.

`send` always answers in JSON and always exits 0 for a policy refusal. A refusal is a
**downgrade**, not an error:

```json
{ "ok": true, "sent": false, "downgraded": "draft", "gate": "outbound_send",
  "reason": "outbound_send is false in emp-influencer/employee.yaml",
  "draft": "r-882...", "to": ["ava@creator.example"],
  "note": "the draft is still in ana@acme.example Drafts; Ana can send it, or close the gate
           that refused it." }
```

A successful send looks like `{"ok": true, "sent": true, "message": "18f3...",
"label": "hub/handled/<slug>"}` and writes a row to `sent-log`. Sending the same draft twice
sends nothing the second time.

### Reply

```bash
$HUB_DIR/scripts/mail.sh reply --thread 18f2c9a3b4d5e6f7 --body-file out/reply.txt --issue 128
```

Drafts, then sends if every gate allows it. If not, you get the draft and the reason in one
JSON object with `"sent": false`. This is the command to use on a thread; `draft` plus `send` is
the same thing in two steps.

## Lint and the reviewer, on their own

```bash
$HUB_DIR/scripts/mail.sh lint --body-file out/ava.txt --subject "Ava, ..." [--to addr] \
  [--reply-to <thread>] [--check-calendar] [--slot 2026-09-08T13:00:00-07:00]
$HUB_DIR/scripts/mail.sh review --body-file out/reply.txt --thread 18f2c9a3b4d5e6f7
```

`lint` exits 0 when clean and 2 when a rule blocks. Every finding has a stable id, a severity
and a fix, and the ids are stable enough to quote on a task:

```json
{ "ok": false, "summary": "1 error(s), 0 warning(s)",
  "findings": [ { "id": "L001", "severity": "error",
                  "message": "forbidden phrase: 'we guarantee'",
                  "fix": "Team writing rules: do not promise outcomes. Say
                          'we will look into it', ..." } ] }
```

The rules, in short: no forbidden phrases (for example `we guarantee`, `AI Agent`,
`outsource`, `is locked`, `our crew`; the list is yours to set in the policy); acme.example links only, and if you have a
required CTA every link must be it; no placeholders, key-shaped strings, `s3://`, `emp-` or Tico
task numbers; a subject under 120 characters, a body of 20-2500, at most three exclamation
marks, a signature naming Ana, one external recipient; and for times offered: at least two, in
order, in the future, on a weekday, in business hours, with the zone spelled out. Confirmation
language without `--slot` is an error - **never confirm a time before the invite exists.**

`review` asks a second model (Grok, a different vendor from the one that wrote the draft) to
check the draft against the incoming thread. Any commitment - money, a date, a discount, a legal
position, a guarantee - fails it. If the reviewer is unreachable, a draft still goes through
flagged `"review": "unavailable"`, and a send is downgraded to a draft.

## Calendar

Every bot can read and schedule appointments through the Tico MCP, without a Gmail grant in its
manifest:

```text
hub_calendar_list(calendar="ana@acme.example")
hub_calendar_schedule(title="Murphy hold", start="2026-09-22T09:00:00-07:00",
                      end="2026-09-22T09:30:00-07:00", attendees=["person@example.com"])
hub_calendar_status(id="<action id>")
```

The schedule call queues one idempotent action for the private Mac calendar tool. Only a status of
`succeeded` means the Google event and invitations exist. `pending` and `running` are unfinished;
`unknown` must be inspected before retrying. This standing calendar grant does not enable Gmail
reading, drafting or sending. The equivalent shell commands are `hub calendar list`,
`hub calendar schedule` and `hub calendar status`.

The mail-local calendar commands use the same team-wide grant. Every bot can read or create an
event on any address in `registry/people.yaml`; Gmail permissions, including `read_only`, do not
change that calendar access:

```bash
$HUB_DIR/scripts/mail.sh slots --for ana@acme.example --n 2 --minutes 20 [--days 7]
$HUB_DIR/scripts/mail.sh calendar list --for teammate@acme.example --hours 48 --json
$HUB_DIR/scripts/mail.sh calendar add --for teammate@acme.example \
  --start 2026-09-22T09:00:00-07:00 --minutes 30 --summary "Customer follow-up" \
  [--attendee another-teammate@acme.example] [--description "Internal context"]
$HUB_DIR/scripts/mail.sh calendar get --for teammate@acme.example --event <id> --json
$HUB_DIR/scripts/mail.sh schedule --thread 18f2... --slot 2026-09-08T13:00:00-07:00 \
  --minutes 20 --attendee ava@creator.example --body-file out/confirm.txt --issue 128
```

`calendar add` is audited and deterministic: the same exact request retrieves the existing event
instead of making a duplicate. It accepts only roster attendees. External invitations
stay in the guarded `schedule` flow.

`slots` reads **every** calendar the mailbox can see, treats all of them as busy, keeps a
30-minute buffer both sides, and only offers weekdays 09:00-17:00 America/Los_Angeles. It prints
lines you can paste straight into a draft - `Tue Sep 8, 1:00–1:20pm PT` - and
`{"slots": [{"start": "...", "end": "...", "human": "Tue Sep 8, 1:00–1:20pm PT"}]}` with `--json`.

`schedule` creates the event and sends the confirmation, or does neither: if the send fails the
event is deleted again. While your `outbound_send` is false it puts **nothing** on the calendar
and answers with the draft plus `"would_schedule": {...}` so Ana can do it in one click.

## Verbs, and the one thing that is implied

Your `access:` entry lists verbs: `read`, `draft`, `send`.

`read` also allows `label`, `archive`, `mark-read`, `star` and `triaged` **on your own
mailbox**. Moving a message between folders is not a send: nothing leaves the team, the
change is visible in Gmail, and Ana undoes it by relabelling.

`draft` is needed for `draft`, `reply` and `schedule`. `send` is needed on top of that for
anything to leave, and `send` also needs `outbound_send: true` in your `employee.yaml`. With the
flag false, every send is a draft, whatever an older instruction says.

Anything you are not granted is refused with exit code 2 and a line telling you what to ask
for. Do not work around a refusal: open a task with `owner:ana` and `type:decision` naming
the mailbox and why, per `policies/access.md`.

## The rules do the boring half

`registry/mail-rules.yaml` files the obvious mail before a model sees it: legal risk words
(`legal-risk-words`) and money-owed words like past due or final notice (`payment-risk-words`)
get `hub/needs-owner` and are never archived; receipts and a short list of exact senders Ana
has settled (Clio bills, Postiz digests, and so on) are archived and marked read; anything with
an unsubscribe link is marketing and gets archived; machine senders get `hub/notification`.
Rules cost no tokens, so everything they settle is free.

Run `rules run` first, then `inbox --untriaged --format brief --decisions`. What is left is the part that
needs judgement. `--format brief` is id, date, from, subject, labels and a snippet; `md` prints
whole bodies, so use it on one thread you are about to act on, never on a list.

`--decisions` asks the decision model (an optional decision model, `skills/decisions/SKILL.md`) about every listed
message before any thread is opened, from the listing's fields alone, and prints one more line
under each:

```text
  decision: reply  (reply 0.81; ask 0.90, money 0.05, legal 0.02, urgency 1.4)
```

The word after `decision:` is what the thresholds in `questions/mail-triage.json` say to do:
`archive`, `needs-owner`, `route`, `reply`, or `read`. Legal protects first, at a low
threshold, because a wrong needs-owner costs one look; money protects only when someone is
also asking, because payroll runs and receipts score money high with nobody asking anything;
filings need high confidence, because a wrong archive costs a missed email. `read` means the model was not sure enough: open the thread
and decide the way you always did. It changes nothing in Gmail; the JSON carries the same under
`judgment`, and one `judge` audit line (the audit name is unchanged) keeps the counts and the suggestion per id. Inside a bot
run the call goes through Tico with your credential; outside one it needs
the decision model API key (`skills/decisions/SKILL.md`), and `MAIL_DECISIONS=none` switches it off (`MAIL_JUDGE` and `--judge` are the deprecated old names and still work).

`draft` runs the same model as a gate before the second reviewer: six yes/no questions
(`questions/mail-draft-gate.json`) about money, dates, a confirmed time, unsupported claims, a
legal position and tone, printed as `gate: ok` or `gate: flagged commitment_money 0.81`. The
gate is advisory: a flagged draft is still written, the reviewer still decides, and the audit
keeps both so the thresholds can be tuned from what actually happened. Rewrite a flagged draft
once before you try again.

Three rules under `ana@acme.example` (`judge-legal-risk`, `judge-needs-owner`, `judge-noise`) ask the decision model
instead of matching words: a `decision` condition (`judge` is the old spelling and is still read) reads what the model said about the message
from the same listing fields as `--decisions` (`registry/mail-rules.yaml` explains the shape). They
sit under the mailbox on purpose: they run after every common rule, so a word protection still
blocks the model's archive, and only that mailbox's mail is sent to the model. Inside a bot run
the call goes through Tico; with no decision model available those rules simply do not fire and the
report says so. `mail rules explain <id>` prints the answer a message got.

If you keep triaging the same kind of message by hand, that is a rule. Write it in the file's
own shape - id, `when`, `do` - for `common`, above the protections, with `to_matches` on your
mailbox and `stop: true` (a mailbox-section rule runs after `common` and can never archive what a
`never_archive` rule protected). Prove it with `rules backtest --since 14d --rules <file>` and one
fixture, then open a PR against ticoteam/tico; a human merges it. Do not edit
`registry/mail-rules.yaml` in place.

## Labels Tico owns

`hub/triaged/<slug>`, `hub/handled/<slug>`, `hub/drafted`, `hub/needs-owner`, `hub/marketing`,
`hub/notification`, `hub/noise`. The tool refuses to touch any label outside `hub/` (and
Gmail's own INBOX, UNREAD, STARRED), because everything else is Ana's own filing.

## What to put in the task closing comment

Per `policies/handoffs.md`, three sections and under 200 words. For a mail run, **what was
done** is counts and not a transcript:

```text
What was done: 41 new messages in ana@acme.example. Rules filed 33 (26 marketing archived,
7 notifications). I triaged 6 and left 2 for Ana.
Deliverable: labels in Gmail; 2 messages carry hub/needs-owner:
  18f2c9a3b4d5e6f7  Acme renewal quote, they want an answer by Friday
  18f2c9a3b4d5e6f8  Invoice 4471 past due, $2,140
What the requester should know: the renewal needs a number I do not have.
Audit: scripts/mail.sh audit --since 24h --employee <slug>
```

Never paste a full message body into a task, and never paste an address list. Message ids and
one line of context are enough for Ana to open the thread herself. Nothing from a mailbox
goes into Slack.

## When something is wrong

`doctor` prints one line per problem with the exact fix. If it says the key is missing or
delegation is not granted, that is Ana's twenty minutes, not yours: open a task with
`owner:ana` and `needs-human` quoting the failing line, and stop. Exit codes: 0 fine,
1 something broke, 2 a Tico policy refused you.

Details of the plan and the reasoning behind every gate: `docs/mail-service.md`. The rule ids,
the policy schema and the reviewer backends: `connectors/mail/README.md`.

## Works on Linux runners

The mail and calendar sync (the `connectors` job) runs on a Docker runner, so a team whose bots all live
on cloud Linux can sync mail and calendar with no Mac. It is the same code and behavior as on a Mac; only the places it
looks are named instead of guessed.

1. Create the Google service account with domain-wide delegation once (`connectors/mail/README.md`, Setup), and download its JSON key.
2. Put the key on **one** runner, in the runner's own state directory, where only the runner can read it (owner `ticorun`, mode 0600):
   `docker exec -i -u ticorun tico-runner sh -c 'umask 077; cat > "$(ls -d /home/runner/state-* | head -1)/google-sa.json"' < google-sa.json`.
   A key left in `workspace/secrets/google-sa.json` (an older install, or an older version of this page) is moved there within
   a minute. Bots cannot read that place: a message bot's run asks the runner for a short-lived token for one mailbox instead
   (below).
3. Wait a minute. `docker logs tico-runner` says `Tico side jobs: started connectors (mail, calendar)`. The first start builds
   the Python environment into the runner's volume (`/home/runner/tools/mail-venv`, or `/var/lib/tico-runner/tools/mail-venv`),
   about a minute, needing outbound access to PyPI once. It is not in the image, so the image stays slim for runners that never sync mail;
   it is rebuilt when `connectors/mail/requirements.txt` changes.
4. Check: `python -m runner --config <runner.json> connectors-doctor`, then Settings shows the mail and calendar
   tool health.

### Who can read the key

The key can act as any mailbox in the team, so bots must not be able to read it.

- **Docker runner with the two-user layout** (the current `runner.compose.yaml`): the key is in the runner's state directory,
  closed to the bots' user. The `connectors` job reads it there. A message bot's run gets, from the runner over its credential
  socket, a Gmail or Calendar access token that lasts an hour for one mailbox: its human's, and the humans below them in the
  team chart. Any other bot, and any other mailbox, is refused.
- **A Mac, or Docker started the old way**: bots run as the same user as the runner and can read the key file, and Settings >
  Health says so ("Mail key"). Keep such a computer for the message bot alone.
- A message bot and any other bot are never placed on the same computer (the server answers 409 `inbox_isolation`: add a computer
  for the message bot). Several message bots may share one only if the owner allows it with
  `POST /api/v2/computers/<id>/inbox-sharing {"allowed": true}`, since they would hold the same key anyway. Where one owner runs every
  computer and bot, the refusal offers this and BotOps turns it on as the human who asked; anywhere else an owner or an admin does it
  (a message bot still never shares a computer with another kind of bot).
- Bots that are not message bots but declare `gmail` access do not get mail on an isolated runner.

Instead of the key, the owner can set `TICO_PROCESSING_OPERATORS=<operator>` on the server: that owner's runners run
the job (and show a sign-in problem in Settings until the key is there).

| Setting | Default (Mac) | Linux runner |
| --- | --- | --- |
| `TICO_PROJECTS_DIR` bot repos, `secrets/` | folder above the checkout | `<home>/workspace` |
| `TICO_MAIL_VENV` | `<projects>/runtime/mail/venv` | `<tools>/mail-venv` for the connectors job; a bot's run is given `TICO_PROJECTS_DIR`, so its first `mail.sh` builds `<home>/workspace/runtime/mail/venv` (the bot user can write it) |
| `TICO_MAIL_RUNTIME_DIR` mail.db, audit log | `<projects>/runtime/mail` | same, under `workspace/runtime/mail` |
| `GOOGLE_SA_KEY` | `<projects>/secrets/google-sa.json` | the runner's state directory (`~/state-<id>/google-sa.json`) |
| `TICO_REGISTRY_DIR` | `<checkout>/registry` | unset: the sync needs no registry; per-bot mailbox rules do |

Nothing in the connectors job is Mac-only: the key is a file on both (no Keychain), and there is no browser automation
in it. What stays Mac-only is launchd (`scripts/tico install`; Linux uses the runner's own supervisor) and
`connectors/browser.py`, the signed-in browser tool bots use, which needs a desktop browser.

## Unsubscribe before model triage

`rules run` now attempts RFC 8058 one-click unsubscribe for eligible subscription mail before
archiving it. It never calls a model. Earlier `never_archive` protection also blocks unsubscribe.
The acting bot needs the separate Gmail `unsubscribe` verb; read/draft/send do not imply it.
This grant cancels email-list subscriptions only, without enabling general emails or invites.

```
scripts/mail.sh unsubscribe <message-id> --as inbox --dry-run --json
scripts/mail.sh unsubscribe <message-id> --as inbox --archive --json
scripts/mail.sh rules run --as inbox --json
```

The command verifies DKIM over the raw message and both unsubscribe headers, then POSTs the
standard one-click body to HTTPS. No cookies, authorization, redirects, email requests or body
links are used. Connections are pinned to validated public IPs. Audit/state contains endpoint
hosts and token hashes, never full unsubscribe URLs. Duplicate endpoint requests are suppressed,
including uncertain outcomes after timeouts. A sender's 2xx means `accepted`, not proof it will
never send again. Unsupported methods return `manual_required`; uncertain requests return
`unknown`. The rules pass still archives unwanted mail and exposes the unsubscribe result;
standalone `--archive` archives only after acceptance. No request is made in a dry run.

Keep the processing order: scripts and filing rules, then model analysis of unresolved mail.
Unsubscribe requires choosing unwanted subscription mail; it does not cancel a paid service.

## Scoped automatic scheduling (Ana approved September 8)

The message bot uses `mail scheduling offer|book`, not generic `reply`, `send` or `schedule`.
It has `scheduling_send: true` and separate Gmail/Calendar `schedule` verbs; general
`outbound_send` stays false. `policy show` reports both. Scope is influencers and BD-confirmed
non-investor contacts only. An independent reviewer checks relationship and explicit acceptance;
only fixed scheduling text can be sent. BD confirmation must be an actual Tico message authored
by that bot with exact `Scheduling approval: <email>` and `Thread: <thread>` lines.

Offers use two 30-minute slots, 20 hours notice, weekdays excluding nationwide federal/observed
holidays, 08:00-16:00 Pacific, and 30-minute buffers across every calendar. Unavailable freebusy
falls back to paginated event reads; unreadable calendars block scheduling. Thread and calendars
are rechecked immediately before a send. Bookings send a single invite with Google Meet creation,
not an invite followed by a separately fallible email. Per-mailbox locking and action records
suppress duplicates; uncertain delivery is recorded for reconciliation, never automatically
retried or falsely described as rolled back. `--dry-run` performs no outbound action.

Ana's `mail slots` uses the same time rules and defaults to 30 minutes. The older generic
scheduler is not the message bot's standing-authorized workflow.
