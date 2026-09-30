# Connect a Hermes profile ("connect my Hermes profile", "my Hermes bot isn't reporting")

Triggered when a human wants a Hermes profile to be a bot on the team, or says a Hermes bot has gone quiet. A profile
is one Hermes agent on the human's own computer; it becomes one bot with its own chat, credential and heartbeat
(docs/hermes-agents.md). Budget 5 minutes. The human never copies a token: the profile and Tico pair with a short code.

## 1. Ask two things

- **Which profile?** Its name, as Hermes calls it (`hermes profile list` on their computer).
- **The code.** On that computer they run, in a terminal, the two commands you give them, the second one after the first
  has downloaded the connector (use the runner address from `hub api GET agent-skill`, its `mcp_url` without the path):

      curl -fsSL https://<runner address>/api/v2/agents/setup-script -o hermes_agent.py
      python3 hermes_agent.py pair --profile <name> --url https://<runner address>

  It prints a line ending in a code like `K7QM-4F2P` and waits up to ten minutes. Ask them to paste that line.
  Read the code from their words; never ask for a token, and never expect one.

## 2. Register the bot if it is new

Skip this when the bot exists (`hub api GET bots`). Otherwise ask for a name, one line on what it does and who it reports
to (the human by default), then:

    hub bot create <slug> --record-only --model hermes --name "<Name>" --description "<what it does>" --reports-to <bot or human:id>

`--model hermes` is what makes it a Hermes bot: it gets a credential, not a computer. Turn it on with `hub bot go-live <slug>`;
a bot that is only planned cannot report in.

## 3. Approve the code

    hub agent pair approve <code> --bot <slug>

The answer names the profile and the computer it came from. Say them back in one line ("connected profile scout on Mac-mini").
If they do not match what the human told you, stop and run `hub agent pair decline <code>` instead. The code is single use and lasts ten
minutes: "not valid or expired" means they run `pair` again and read you the new one. The server refuses for their rights
(only the bot's owner or an admin may approve); say who can.

## 4. Confirm it reports in

The connector installs itself when the code is approved and posts a heartbeat every minute. Within two minutes:

    hub api GET bots/<slug>

`agent.last_seen` is recent and `online` is true. Then send one small message and tell the human to expect the answer
on the profile's own schedule, not at once: `hub message send <slug> "Hello from <human>: reply with one line so we know you read this."`
In Tico the message waits until the agent reads it. Say what you saw in one line: connected, last heard from a minute ago.
If it is not online after five minutes, use the troubleshooting below.

## Using it day to day

Nothing pushes to a Hermes profile; it reads its messages when its own schedule says so. The bot only needs a Hermes cron job.
Give the human this, to paste into the profile's own chat (Hermes creates the job itself):

> Every 10 minutes, run `python3 hermes_agent.py status --profile <name>`. If `waiting` shows messages or tasks, list them
> with `hub_message_list`, answer each with `hub_message_send` in the same conversation (or move the task with `hub_task_update`),
> then `hub_message_mark_read`. If nothing is waiting, do nothing.

Say that a faster schedule means faster answers and more model use.

## Troubleshooting: a Hermes bot that is not reporting in

Start with `hub health check` and `hub api GET bots/<slug>`. Then the first row that fits:

| What you see | Cause | You do |
| --- | --- | --- |
| The bot is archived (`state: archived`), or Health says its Hermes agent is still reporting in but the bot is archived | Someone archived it; the profile keeps trying | `hub bot restore <slug>` if they want it back (its routines do not come back; say so). Otherwise revoke the credential: `hub api POST bots/<slug>/agent-credential/revoke` |
| The profile's heartbeat is refused with 401 ("revoked") | The credential was revoked or replaced | Pair again: steps 1 and 3. A new pairing makes a new credential and replaces the old one |
| The bot is planned, paused or quarantined | The server refuses its heartbeat (409) | `hub bot go-live <slug>` for planned; `hub bot resume <slug>` for paused (unless they paused it on purpose); quarantined only after you read why (`playbooks/health-check.md`) |
| Active, credential exists, no recent heartbeat | The timer on their computer is not running, or the computer is off | Ask them to run `python3 hermes_agent.py status --profile <name>` and paste the output; it shows the last reply. If it shows no timer or an old version, `python3 hermes_agent.py update --profile <name>` (it fetches the current connector and reinstalls the timer). If the computer is asleep or off, say so: nothing here can wake it |
| Nothing works and the credential is lost | The token cannot be shown again | `hub api POST bots/<slug>/agent-credential` replaces it; the new token is not shown to you, so pair again (steps 1 and 3) |

Rotating or revoking is yours to do as them, with no card. Archiving a Hermes bot is a card; when you propose it say
the profile will stop, and keep the default that revokes its credential.

## Close

Close any task you filed about this bot once its heartbeat is recent (`hub task close <id> --note "Connected: last heard from a minute ago."`).
