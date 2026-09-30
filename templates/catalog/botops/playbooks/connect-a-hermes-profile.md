# Connect a Hermes or OpenClaw profile ("connect my Hermes profile", "connect my OpenClaw profile", "my Hermes bot isn't reporting")

Triggered when a human wants a Hermes or OpenClaw profile to be a bot on the team, or says such a bot has gone quiet. A
profile is one agent on the human's own computer; it becomes one bot with its own chat, credential and heartbeat
(docs/hermes-agents.md, docs/openclaw-agents.md). Budget 5 minutes. The human never copies a token: the profile and Tico
pair with a short code. Everything below is for Hermes; for OpenClaw it is the same with `--harness openclaw` on the
connector's commands, `--model openclaw` when you register the bot, and `--profile` optional (no `--profile` is the
default profile in `~/.openclaw`). OpenClaw has no MCP client; its skill calls Tico through the connector, and that is
already set up by `pair`.

## 1. Ask three things

- **Which profile?** Its name, as Hermes calls it (`hermes profile list` on their computer; `openclaw --profile <name>`
  for OpenClaw, or none for its default).
- **How often should it check Tico for messages and tasks?** Offer `15m`, `1h` (the default, say it if they have no
  preference), `daily`, or `off` if they will prompt it themselves. It is the profile's own schedule: Tico never starts
  it, and a faster schedule means faster answers and more model use. They give it to the connector as `--sync <interval>`.
- **The code.** On that computer they run, in a terminal, the two commands you give them, the second one after the first
  has downloaded the connector (use the runner address from `hub api GET agent-skill`, its `mcp_url` without the path):

      curl -fsSL https://<runner address>/api/v2/agents/setup-script -o hermes_agent.py
      python3 hermes_agent.py pair --profile <name> --url https://<runner address> --sync <interval>

  (OpenClaw: `pair --harness openclaw [--profile <name>] --url ... --sync <interval>`.) It prints a line ending in a code like `K7QM-4F2P` and waits up to ten minutes. Ask them to paste that line.
  Read the code from their words; never ask for a token, and never expect one.

## 2. Register the bot if it is new

Skip this when the bot exists (`hub api GET bots`). Otherwise ask for a name, one line on what it does and who it reports
to (the human by default), then:

    hub bot create <slug> --record-only --model hermes --name "<Name>" --description "<what it does>" --reports-to <bot or human:id>

`--model hermes` (`--model openclaw` for an OpenClaw profile) is what makes it an external bot: it gets a credential, not a computer. Turn it on with `hub bot go-live <slug> --no-setup` (no computer, no setup chat);
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

Nothing pushes to the profile; it reads its messages when its own schedule says so, and `pair` already set that up: the
`tico-sync` skill and one cron job at the interval they chose (on the profile's own computer, in Hermes's or OpenClaw's
scheduler). Nothing for the human to paste. Hermes runs cron only while the profile's gateway runs, and OpenClaw's
job lives in its Gateway; if they say it never answers, ask them to run `doctor --profile <name>` (add `--harness openclaw`
for OpenClaw): it says whether the job exists and when it last ran.

To change the interval later they run, on that computer, `python3 ~/.config/tico/agents/hermes_agent.py reinstall --profile <name> --sync <interval>`
(`--sync off` removes the job). Once a week the skill also updates the connector by itself.

## Troubleshooting: a Hermes bot that is not reporting in

Start with `hub health check` and `hub api GET bots/<slug>`. Then the first row that fits:

| What you see | Cause | You do |
| --- | --- | --- |
| The bot is archived (`state: archived`), or Health says its Hermes agent is still reporting in but the bot is archived | Someone archived it; the profile keeps trying | `hub bot restore <slug>` if they want it back (its routines do not come back; say so). If its answer shows `agent.credential: false` the credential was revoked: pair again (steps 1 and 3). Otherwise revoke the credential: `hub api POST bots/<slug>/agent-credential/revoke` |
| The profile's heartbeat is refused with 401 ("revoked") | The credential was revoked or replaced | Pair again: steps 1 and 3. A new pairing makes a new credential and replaces the old one |
| The bot is planned, paused or quarantined | The server refuses its heartbeat (409) | `hub bot go-live <slug> --no-setup` for planned; `hub bot resume <slug>` for paused (unless they paused it on purpose); quarantined only after you read why (`playbooks/health-check.md`) |
| Active, credential exists, no recent heartbeat | The timer on their computer is not running, or the computer is off | Ask them to run `python3 ~/.config/tico/agents/hermes_agent.py status --profile <name>` and paste the output; it shows the last reply. `doctor --profile <name>` (same file) says what is wrong. If it shows no timer or an old version, `update --profile <name>` (it fetches the current connector and reinstalls the timer). If the computer is asleep or off, say so: nothing here can wake it |
| Nothing works and the credential is lost | The token cannot be shown again | `hub api POST bots/<slug>/agent-credential` replaces it; the new token is not shown to you, so pair again (steps 1 and 3) |

Rotating or revoking is yours to do as them, with no card. Archiving a Hermes bot is a card; when you propose it say
the profile will stop, and keep the default that revokes its credential.

## Close

Close any task you filed about this bot once its heartbeat is recent (`hub task close <id> --note "Connected: last heard from a minute ago."`).
