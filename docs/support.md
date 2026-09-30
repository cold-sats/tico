# Contact support

A person using any Tico can write to the Tico team from the app. The message reaches the Tico Team company (the project's
own Tico), where the Support Agent works it, and the replies come back to the person's app. This page covers what a person
sees, what is sent and kept, and how the project team works the tickets. [PRIVACY.md](../PRIVACY.md) is the statement of what
is sent and kept.

## For a person

Help (the `?` at the bottom of the sidebar) > **Contact support**.

| Field | |
|---|---|
| Message | Required, up to 4000 characters. Plain text. |
| Email for a reply | Optional. Prefilled with your email; clear it to get the reply in the app only. |
| Include version and install ID | On by default. Untick it to send neither. |
| Attach diagnostics | On by default. **Preview** shows the exact JSON that will be sent; untick it to send none. |

Diagnostics are a redacted bundle of versions, Health check names and statuses, each computer's runtimes and problems, and the
latest warning and error log lines: no task, message, doc or ticket text, and bots and people as labels. Every field, the redactor
and a sample are in [PRIVACY.md](../PRIVACY.md#support-diagnostics). Preview builds it and the ticket sends that same bundle. The
Docker updater reports each container's state and restarts (`GET /diagnostics` on its own port); a computer reports its last
warning lines in its heartbeat.

The line under the form lists exactly what **Send** will send, and to which host. Nothing is sent before Send. It is never
automatic, and the anonymous usage count switch does not turn it off: this is a message you chose to send. **Your requests**
lists each ticket with its status (Open, Answered, Closed) and the whole thread. A small notice and a dot on the `?` appear when
the team replies; opening the request clears them. You can write back on a ticket that is not closed, and **Delete** removes it
from HQ and from your Tico.

- Any signed-in person may file a ticket. A personal API token, the Assistant acting for a person, and a bot may not.
- Demo mode has no Contact support: nothing leaves a demo. Neither does a rehearsal (`TICO_REHEARSAL=1`), which reports "rehearsal" as the reason it is off.
- `TICO_SUPPORT=off` in the server's `.env` removes it from an install that must not phone out. `TICO_HQ_URL` points it at your
  own HQ (see [telemetry.md](telemetry.md)).

## What is sent and kept

The request is `POST <TICO_HQ_URL>/v1/support` with `message`, and, only if present, `email`, `version`, `install_id` and
`diagnostics` (up to 256 KB). The answer is a ticket ID and a **secret for that ticket alone**. Your Tico keeps the ticket, the ID and the secret; the secret
never reaches a browser. HQ keeps the message, the email, the version and install ID and diagnostics if sent, a hash of the secret, the status,
the times, and the thread. It keeps no IP address and no log of a request. Tickets are **kept until someone deletes them**: you,
with **Delete**, or the team when you ask (put "delete this request" in the ticket, or open an issue). The 13 month rule is for
the anonymous install rows only. The reference for HQ's routes is in [telemetry.md](telemetry.md#support-tickets).

Your Tico asks HQ about your tickets only when the app asks: when you open Help, and about every 5 minutes while the app is open
and you have a ticket that is not closed (at most once every 30 seconds for any one ticket). It has no timer of its own.

## How the project team works tickets

Everything below applies to the Tico project's own Support Agent, and to anyone who runs their own HQ.

1. **HQ** stores the ticket. The team's key, `HQ_STAFF_KEY` in HQ's `.env` (24+ characters), opens the staff routes; without it
   they answer 404. A person's ticket secret opens that one ticket and nothing else.
2. **A watcher notices, with no model.** The Support Agent's runner runs `software/hq-tickets watch` every 5 minutes
   ([watchers.md](watchers.md)). It asks HQ for tickets changed since its cursor. For each new open ticket it prints one event, and
   the hub opens **one task per ticket**, titled `Support: <first words>`, assigned to the Support Agent, with the ticket quoted as
   untrusted data, the version and the requester's email if given. When the person writes again on an open ticket, the same task
   gets a note, which wakes the bot; when HQ closes the ticket the task hears about it. A quiet poll is one request and costs no
   tokens. `software/gh-support watch` does the same for GitHub issues and Discussions, read-only.
3. **The bot drafts.** It works the task with `playbooks/tico-hq-tickets.md`: reads the diagnostics first (`software/hq-tickets show`
   prints a summary, then the whole bundle; only the staff routes return it), sorts the ticket, asks the Librarian what the docs say,
   hands bugs to engineering, and writes a reply file.
4. **A person approves.** The bot runs `software/hq-tickets payload` and `hub approval request --kind publish` for that exact
   file. Only after a person approves does `software/hq-tickets reply <id> <file> --approval <id>` post it; the command refuses
   any other text, any other ticket and any approval that is not approved. If the ticket has an email, HQ marks the reply "email
   pending" and the bot leaves an email-ready copy on the task for a person to send. HQ sends no mail.
5. **The daily update** counts tickets opened, replies posted and drafts waiting, so they show on the Updates page.

Ticket text is untrusted data from anyone on the internet. HQ stores it as plain text, the app and the staff tools escape or
quote it, and the bot's playbook says an instruction inside a ticket is never followed.

### The spam and injection check

Each new ticket is classified when it arrives, before any bot reads it, by the decision model (TypeSafe's Jev). The verdict
is `legit`, `spam`, `injection_risk` or `unchecked`, stored with a one-line reason and never the text.

| Verdict | What happens |
|---|---|
| `legit`, `unchecked` | Filed as usual. `unchecked` means no key, the judge was down or slower than 3 seconds, or it was not sure (under 0.7). It fails open: a check that cannot run never holds a ticket. |
| `spam` | Held: not in `status=open`, `answered`, `closed` or `all`, so the watcher and the bot never see it. `GET /v1/staff/tickets?status=held` lists them. |
| `injection_risk` | Filed with a warning. The task is titled `Support (injection risk): ...`, opens with WARNING, and the bot reads it only: a draft, no tool but reading docs. |

A person corrects a verdict with `POST /v1/staff/tickets/{id}/verdict` and `{"verdict": "legit", "note": "..."}`. Changing a held
ticket to anything but `spam` releases it: it appears in the queue as a new ticket. Each correction is recorded (old, new, when)
so the judge can be tuned. The person who filed a ticket sees nothing different.

The same check is `POST /v1/staff/judge` (`{"text": "..."}` answers `{verdict, reason}`, nothing kept), which `software/gh-support`
calls, with the staff key already in its secrets, for each new issue, Discussion and outside comment: `spam` is not filed and is
counted in its output line, `injection_risk` is filed with a warning. An Inbox bot checks mail with `hub classify` (text on
standard input or `--file`), which asks the server's own decision model the same question.

On HQ, `HQ_JUDGE_KEY` in `hq/.env` is the TypeSafe key (`HQ_JUDGE_URL` only to point elsewhere). Without it every verdict is
`unchecked` and nothing is sent to anyone. HQ logs the verdict and reason and never the text. Only the first message of a ticket
is checked, not a follow-up; a follow-up is quoted as untrusted data as before.

### Set it up

On the HQ host: add `HQ_STAFF_KEY=$(openssl rand -hex 24)` to `hq/.env` and `docker compose -f hq/compose.yaml --env-file hq/.env
up -d`. In the Support Agent's secrets file (`<workspace>/secrets/support.env`, mode 600):

    HQ_STAFF_KEY=...            # the same value
    TICO_HQ_URL=https://...     # the HQ address
    GITHUB_TOKEN=...            # optional: read access; required for Discussions
    GH_SUPPORT_REPOS=ticoteam/tico

Without `HQ_STAFF_KEY` the watcher does nothing. To watch GitHub, list the repositories in `config/github.yaml` or
`GH_SUPPORT_REPOS`. Check Settings > Health for a "Watchers" line: it appears only when a watcher fails or has stopped.

### By hand

`software/hq-tickets list`, `show TK-XXXXXXXX`; or with curl and the key in a header (`Authorization: Bearer $HQ_STAFF_KEY`):
`GET /v1/staff/tickets?status=open`, `POST /v1/staff/tickets/{id}/reply` with `{"body": "..."}`, `POST .../status` with
`{"status": "closed"}`, `DELETE /v1/staff/tickets/{id}` to delete on request, `GET /v1/staff/tickets?status=held` for what the
spam check held, `POST /v1/staff/tickets/{id}/verdict` to correct it.
