# Architecture

Tico is a small server plus any number of computers. The server keeps the company's state. The
computers run the bots. They only ever talk to each other over HTTPS, and the computer always
starts the conversation.

```
   people (browser or desktop app)
        |  HTTPS, Google / Microsoft sign-in
        v
  +---------------------------------------------+
  | SERVER (Docker)                             |
  | Caddy or Cloudflare Tunnel -> Tico server   |
  | SQLite + Litestream backups, files          |
  | tasks, chats, approvals, schedules, people  |
  | optional updater                            |
  | runs NO bots; sends questions to the        |
  | decision provider, when that is on          |
  +---------------------------------------------+
        ^                    ^                   ^
        | HTTPS: claim work, stream results, heartbeat
        |                    |                   |
  +-----------+        +-----------+       +-----------+
  | Mac       |        | Linux box |       | cloud VM  |    each joined with a
  | runner    |        | tico-     |       | tico-     |    one-time code
  | (native)  |        | runner    |       | runner    |
  +-----------+        +-----------+       +-----------+
   harnesses (Codex, Claude Code, Gemini CLI, Grok, catch-all),
   model logins, bot repos, bot credentials
        |                              |
        v                              v
  model providers                 GitHub (per-company App,
  (OpenAI, Anthropic, Google,      token scoped to each bot's repo)
   xAI, others)
```

## What runs where

| Where | What |
|---|---|
| Server | The web app and API, sign-in, the people roster, tasks, chats, approvals, the routine scheduler (the clock), files, the credential store, Litestream backups, and the optional updater. |
| Each computer | The runner, the harnesses installed on it, the workspace with one `emp-<slug>` git repository per bot, the bots' secrets, and the model logins. |
| Model providers | Bots reach them from computers, using that computer's logins. The server reaches only the decision provider, when decisions or Slack routing are on. |
| GitHub | Reached from computers with short-lived tokens the server mints per bot. |

A bot is one git repository plus one row on the server, assigned to one computer. Harnesses are
installed on a computer when a bot there needs one; the server does not need to know how.

## How a bot turn flows

1. Something creates work: a person files a task or sends a message, a routine comes due (the server
   turns it into a task), or another bot hands work off.
2. The server queues it for the bot and the computer that bot is assigned to.
3. That computer's runner, heartbeating every few seconds, claims the work. The claim is a lease, so a
   crashed computer's work is released and never runs twice.
4. The runner checks the bot's repository out of the workspace, asks the server for a scoped GitHub
   token if one is needed, and starts the bot's harness inside that repository.
5. The harness talks to the model provider directly, using the login on that computer, and uses tools
   (`hub` commands, git, shell) to do the work.
6. The runner streams progress and the reply back to the server; approvals pause the turn until a person
   answers. The bot commits what it learned to its repository.
7. The server records the result and notifies the people involved.

If the computer is asleep or offline, the server keeps accepting work and shows the computer as
offline; the work waits and runs when it returns.

## Why the server runs no bots or model CLIs

The server never runs a bot or a model CLI; when decisions (or Slack routing) are on, it sends the text of each question to the decision provider you configured (the optional hosted decisions service, or OpenAI, Anthropic, Gemini, xAI or OpenRouter with a key stored on the server).

- **Bot credentials stay with the company's machines.** Model subscriptions and API keys for bots are signed in on
  computers you control. A compromised server does not hand over those logins. It does hold the decision
  provider's key, if you stored one.
- **The server stays small.** It does bookkeeping, not inference or long-running agent processes, so
  1 to 2 GB of RAM has served a small pilot ([sizing](sizing.md)).
- **Bots run next to their work.** A harness needs a shell, git, build tools and the bot's files, which
  belong on a computer, not in a web server.
- **Any harness, any provider.** Adding one is a runner change; the server only sees turns and results.

## Related

[Install](install.md), [sizing](sizing.md), [security model](../SECURITY.md),
[how it works](how-it-works.md), [GitHub App](github-app.md), [environments](environments.md).
