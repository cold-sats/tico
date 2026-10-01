# OpenClaw agents

An [OpenClaw](https://openclaw.ai/) profile can be a bot in Tico, the same way a
[Hermes profile](hermes-agents.md) can: Tico knows it is there, shows whether it is alive, and gives it a
credential to use when it chooses. Tico never starts a run for it. It uses the same `hermes_agent.py` Tool,
with `--harness openclaw`.

## Connect an OpenClaw profile in 2 minutes

You need the OpenClaw profile set up already (`openclaw --profile <name> setup`, or the default profile in
`~/.openclaw`), and the runner address of your Tico: the hostname in **Settings → Computers → Add computer**,
for example `runner.acme.example`. Use the runner address, not the public one.

1. On the computer that runs OpenClaw:

   ```bash
   curl -fsSL https://<runner host>/api/v2/agents/setup-script -o hermes_agent.py \
     && python3 hermes_agent.py pair --harness openclaw --profile <name> --url https://<runner host>
   ```

   Leave out `--profile <name>` for the default profile. The command prints a code like `K7QM-4F2P` and waits
   up to 10 minutes. No token to copy.
2. In Tico, tell BotOps: **"Connect my OpenClaw profile `<name>`, code K7QM-4F2P."** BotOps adds the bot if it
   does not exist yet, then approves the code as you. Or approve it yourself: **Settings → Bots**, **Pair** in
   the bot's Computer column, type the code. Only a bot's owner or an admin can approve.
3. Start a new OpenClaw session (new skills load when a session starts). Test it: message the bot in Tico, and
   within the sync interval it answers in the same chat.

`pair` saves the credential on the computer (mode 600), installs the `tico-sync` skill in the profile's
`skills` folder, schedules the sync job, and starts a heartbeat timer, then prints what it did. It never prints
the credential.

## What is different from Hermes

- **No MCP client.** OpenClaw 2026.3 cannot connect to an MCP server, so nothing is added to its config. The
  credential is in `tico.env` in the profile's state folder (mode 600) and in
  `~/.config/tico/agents/openclaw-<name>.json`. The skill calls the Tico tools this bot may use through `hermes_agent.py`:
  `python3 ~/.config/tico/agents/hermes_agent.py call --harness openclaw --profile <name> hub_message_list`
  (one HTTPS call to Tico's MCP endpoint with the bot's token; the agent never sees the token).
- **Profiles.** `--profile <name>` is OpenClaw's own `--profile`: state in `~/.openclaw-<name>`. Leave it out
  for `~/.openclaw`. The saved files are named `openclaw-<name>`, so a Hermes profile and an OpenClaw profile can
  share a name.
- **The job is an OpenClaw cron job**, created with `openclaw cron add`. It lives in the profile's Gateway, so the
  Gateway must be running for it to fire. OpenClaw has no pre-check step, so each run starts the agent, whose
  first step is a one-line check that ends the run at once when nothing is waiting (a small, cheap model call).

## Keep it in sync

`--sync <interval>` works as it does for Hermes: `15m`, `1h` (the default), `daily`, a cron expression in
quotes, or `off`. It is the agent's own schedule, and Tico never starts it.

- **Change it:** `python3 ~/.config/tico/agents/hermes_agent.py reinstall --harness openclaw --profile <name> --sync 30m`.
  This replaces the one `tico-sync` job and leaves your other jobs alone.
- **What each run does:** the same skill as Hermes ([what it does](hermes-agents.md#keep-it-in-sync)): read
  what is waiting, answer each person in their conversation, move its tasks, stop. Once a week it runs the
  `update` command in `hermes_agent.py`.
- **Check it:** `python3 hermes_agent.py doctor --harness openclaw --profile <name>` says whether the job
  exists, when it last ran, and whether the Gateway is up. `openclaw [--profile <name>] cron list` is OpenClaw's
  own view.
- **If the Gateway was down when you paired,** the pairing still works and the command says the job is not in
  place. Start the Gateway, then run `reinstall --harness openclaw --profile <name>`.

## Keep it working and remove it

The commands are Hermes's (see [Keep it working](hermes-agents.md#keep-it-working)) with `--harness openclaw`:
`update`, `reinstall`, `status`, `doctor`, `heartbeat` and `uninstall`. `uninstall` removes the heartbeat
timer, the `tico-sync` job, the skill, `tico.env` and the credential file; it leaves OpenClaw's own config alone
and does not revoke the credential in Tico (Settings → Bots, or ask BotOps).

## In Tico

An OpenClaw bot is an external bot like a Hermes one: model **OpenClaw/its own model** (`hub bot create <slug>
--record-only --model openclaw`), harness `openclaw`, no computer, one standing credential, a heartbeat every
minute (offline after 180 s), and no runs or usage, because nothing is dispatched. A message to it waits until
the agent reads it. Everything else, including the troubleshooting table and the credential rules, is as in
[Hermes agents](hermes-agents.md).
