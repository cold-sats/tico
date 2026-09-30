# Hermes agents

A bot that is run by a [Hermes](https://hermes-agent.nousresearch.com/) profile instead of by
a registered computer. Tico knows it is there, knows whether it is alive, and gives it a
credential it can use against Tico when it chooses to. Tico never starts a run for it.

## What it is

One Hermes profile is one bot. A profile is a separate Hermes home directory with its own
`config.yaml`, `SOUL.md`, memory, skills, sessions and cron; five profiles on one computer are five
independent agents that share a binary, and to Tico they are five bots. Each has its own slug,
display name, place on the team tree, Chat page, repository, credential and heartbeat. The computer
itself is not a thing Tico tracks, because nothing is dispatched to it: if the computer goes down,
all its bots go offline at once, which is the honest thing to show.

What is the same as every other bot: the record (name, description, reporting line, status,
owners), the Chat page, tasks, routines, the rules in the write layer. A Hermes bot
acts only as itself, may message only active bots and humans, and is linted and capped like
any bot when it writes to a human.

What is different:

| | A bot on a computer | A Hermes bot |
|---|---|---|
| Harness | `openai`, `claude`, `gemini`, `antigravity`, `grok`, `pi` | `hermes` |
| Model and effort | chosen in Settings | the profile's own; the heartbeat reports what it is |
| Where it runs | a registered computer, chosen in Settings | wherever the profile lives; not tracked |
| Credential | a 90 s lease per run, minted by the runner's claim | one standing credential per bot, minted in Settings and revocable there |
| A message to it | queues a job the runner claims | waits until the agent reads it |
| Liveness | runner heartbeat every 15 s; offline after 60 s | a plain heartbeat every minute; offline after 180 s |
| Runs, tokens, usage limits, fallback, interrupted review | yes | no: nothing is dispatched, so there is nothing to lease or review |
| Repository | `bot-<slug>`, pushed by the runner after each run | `bot-<slug>` for backup; the profile directory minus credentials and sessions, pushed by the computer |

## Register one

1. **Settings → Bots → Add bot.** Pick the model `hermes/profile's own model`. The computer
   field goes grey: an external harness has no computer. Save. The bot appears planned or
   active like any other, and until it has a credential **Needs attention** says so.
2. **Create credential** in the bot's Computer column. The token is shown once. The dialog
   gives one command for the computer that runs the profile:

   ```bash
   curl -fsSL -H "Authorization: Bearer <token>" https://<hub>/api/v2/agents/setup-script -o hermes_agent.py \
     && python3 hermes_agent.py install --profile <name> --url https://<hub> --bot <slug> --token <token>
   ```

   The Tico address in that command is the runner hostname (`TICO_RUNNER_URL`, for Acme
   `runner.acme.example`), where a bearer token is accepted without the human sign-in. The
   public address answers a bare bearer with the login page.

   The installer (`clients/hermes_agent.py`, standard library only) checks the token against
   `GET /api/v2/me`, writes `mcp_servers.tico` into the profile's `config.yaml` with the token
   in the profile's `.env` as `TICO_AGENT_TOKEN`, saves the credential under
   `~/.config/tico/agents/<profile>.json` (mode 600), posts one heartbeat, and installs a timer
   that posts one every minute: a launchd job on macOS, a systemd user timer on Linux. It
   prints what it did. `python3 hermes_agent.py status --profile <name>` shows the last reply;
   `uninstall` removes the timer, the env line and the MCP entry.
3. **Reload the profile's MCP servers**: `/reload-mcp` in a running chat, or restart its
   gateway. From then on the profile has every `hub_*` tool: `hub_message_list`, `hub_message_send`,
   `hub_task_*`, `hub_approval_*`, `hub_bot_status_set`, `hub_sql`, `hub_message_mark_read`, and the rest, the
   same tool table (`clients/hubtools.py`) every bot has. With a Tico checkout on the computer the
   `hub` CLI works with the same token in `HUB_API_URL` and `HUB_TOKEN`.

The Settings **Computers** card lists every external agent under the computers: harness,
profile, version, platform, model, provider, and when it last reported in.

## What the pages say

- **Chat.** A message to the bot saves and appears; no job is queued. One line above the
  composer says the bot is a Hermes agent that reads its messages on its own schedule and is
  reporting in, or that it has not reported in since a time, or that it has no credential
  yet. There is no *Saved — queued* or *Working*: nothing here promises a reply.
- **Needs attention.** *X has no agent credential* until one is minted; *X's hermes agent has
  not reported in* with the last heartbeat and how many unread messages wait for it
  once it is three minutes silent.
- **The bot page, More → Setup.** *Run by: hermes agent · profile <name> · version · platform*,
  and whether it is reporting in. Model is what the last heartbeat reported.
- **Runs** stays empty for these bots. Tico records what the agent does through the API
  (tasks touched, messages sent, status set) exactly as it does for every bot.

## How the agent works its messages

Nothing pushes to Hermes. The profile's own cron, a human talking to it on its gateway, or
its own habit decides when it looks. When it does:

1. `hub_message_list` lists the messages and notices waiting and the open tasks it owns.
2. It reads the conversation (`hub_task_show` for a task; the message carries
   `conversation_id`) and answers with `hub_message_send` in that conversation, or moves the task with
   `hub_task_update`, or asks with `hub_task_ask`, or requests an approval.
3. `hub_message_mark_read` marks a message read so it stops showing as unread. A runner does this for other
   bots; a Hermes bot is its own delivery.

The heartbeat reply carries `waiting: {messages, tasks}`, so a Hermes cron job can run
`python3 hermes_agent.py status --profile <name>` and decide whether a run is worth starting.

## The credential

- It acts as `bot:<slug>` under the same authorization every run token gets, with one
  difference: a run sees the conversations it was handed for one run, the agent sees
  every conversation the bot is in. One credential is the whole bot.
- It stops working when the bot is paused or quarantined (`409`), and when it is revoked or
  rotated in Settings (`401`). Rotating replaces the token at once; install the new one on the
  computer.
- It cannot heartbeat as a runner, claim jobs, or act as a human. A runner credential cannot
  heartbeat as an agent.
- It is a standing credential on another computer, which is a departure from the per-run lease
  every other bot has. Keep the profile's `.env` and `~/.config/tico/agents/` at mode 600, and
  revoke from Settings if the computer is lost.

## The repository

Keep `bot-<slug>` for backup: the profile directory's `config.yaml`, `SOUL.md`, `memories/`,
`skills/` and cron definitions, with `.env` and the sessions database ignored. Hermes's own
profile distributions deliberately leave memories out, so a plain repository is the right shape.
A commit-and-push from the same timer, or a Hermes cron job, keeps it current. The bot record's
repository field points at it; nothing in Tico reads or writes it for a Hermes bot.

## Decisions taken

- **No runner on the Hermes computer.** Hermes is not recreated on top of Hermes; its loop, memory,
  skills and gateway stay its own. Tico is the record, the credential and the presence.
- **The profile is the unit.** One profile, one bot, one credential, one heartbeat.
- **The heartbeat is not an agent run.** A timer and a plain HTTP call prove the computer and the
  profile, cheaply and reliably. Whether the model works shows in what the bot does.
- **A message to a Hermes bot never queues a job.** The queue trigger skips external harnesses;
  the chat line says the message waits for it.
- **The profile keeps its own gateway if the owner wants it.** Traffic on Slack or Telegram
  through Hermes bypasses Tico's human-facing lint and message limits; the bot page does
  not pretend otherwise. Turn the gateway off for a bot that should only speak through Tico.
