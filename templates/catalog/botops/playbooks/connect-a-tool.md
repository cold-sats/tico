# Give a bot a login (Jira, GitHub, a mailbox, any tool)

Triggered when a bot you build or repair needs a key, token or password, or a person asks you to
connect a tool. Budget 5 minutes. The person never leaves the chat, and the value never goes through you
unless they pasted it themselves.

## 1. Open the card

    hub credential request <VARIABLE> --for-bot <bot> --label "<your Jira login>" \
        --format "<the exact shape>" --help-url <https page where they make one>

- `VARIABLE` is the name the bot's `employee.yaml` `access:` entry declares in `env:`.
- `--label` finishes the sentence "<Bot> needs ...": "your Jira login", "a GitHub token".
- `--format` is the placeholder: `you@company.com:API token` for basic auth, `ghp_...` for a token.
- `--help-url`, when you know it:

  | Tool | Where they make one |
  | --- | --- |
  | Jira, Confluence | https://id.atlassian.com/manage-profile/security/api-tokens |
  | GitHub | https://github.com/settings/personal-access-tokens |
  | OpenAI | https://platform.openai.com/api-keys |
  | Anthropic | https://console.anthropic.com/settings/keys |
  | Slack | https://api.slack.com/apps |

Then say in one line that a field is open in the chat, and keep working on everything else. Do not ask
for the value in words.

## 2. When they save it, you are woken

You get a message from them that says it was saved. Run the bot's own read-only check of the
connection (read one Jira project, list one repository), then report in plain words what it showed
("Connected to Jira: project HTM loaded."). If it fails, say why in one line and open the card again
(`hub credential request` with the same variable replaces the value).

## 3. If they paste the secret in chat

Store it and go on: `printf '%s' "$VALUE" | hub credential set <VARIABLE> --for-bot <bot>`. That keeps it in
Credentials for that bot only and removes it from the conversation. Say in one line: it is saved and
removed from the chat, and next time the card keeps it off the model entirely. Never repeat the value,
write it in a file, a task or a commit, or copy it to another bot.

## 4. What stops you

- The server says only a credential admin can store it: say who (the message names them). They can fill
  the same card.
- `hub credential list` says credential storage is not set up: use the bot's own secrets file on its
  computer (`secrets/<bot>.env`, `NAME=value`, loaded for that bot only) for a value the person gave
  you for that bot, and say that the company has not set up storage.
- The bot does not need a login at all: do not open a card.
