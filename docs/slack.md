# Slack

Talk to your bots in Slack. DM Tico, or `@Tico` in a channel it has been invited to, and the message
reaches the bot it is for; the reply comes back in the same thread under that bot's name.
How messages are routed and stored is in [slack-gateway.md](slack-gateway.md).

## Set it up (about five minutes)

1. In `.env` add `slack` to `COMPOSE_PROFILES` (for example `caddy,updater,slack`), then `docker compose up -d`.
   This starts one extra container from the same image. It only makes an outbound connection to Slack
   (Socket Mode): no port to open and no public URL.
2. At <https://api.slack.com/apps> choose **Create New App > From a manifest**, pick your workspace, and paste
   `connectors/slack-app-manifest.json` (or use **Copy the manifest** in Tico under Tools > Slack).
3. **Install App** to the workspace and copy the **Bot User OAuth Token** (`xoxb-`).
4. **Basic Information > App-Level Tokens > Generate**, scope `connections:write`, and copy it (`xapp-`).
5. In Tico, Tools > Slack, paste both tokens. They are stored encrypted in Tico's database
   and never shown again. Do not put them in `.env`.

Within a minute the Slack card on Tools and Settings > Health say **Connected**. The first connection pins the workspace
the tokens belong to; to pin it in advance, set `SLACK_TEAM_ID` in `.env`. To change workspace, disconnect and
paste the new tokens. Invite Tico to a channel with `/invite @Tico`.

## What humans can do

- DM Tico to ask for anything; the router picks the right bot, or asks one clarifying question.
- `@Tico` in a channel; mention it again in the thread to continue.
- Reply in a thread a bot already talks in; no mention needed.
- Only humans on the roster (Humans) whose Slack email matches can wake a bot. Guests and Slack Connect
  channels are refused.

## Troubleshooting

| Tools card or Settings > Health says | Do this |
|---|---|
| Tokens saved, waiting | The service is not running: `slack` is missing from `COMPOSE_PROFILES`, or run `docker compose logs slack`. |
| `invalid_auth` | The bot token is wrong or was revoked; reinstall the app and paste the new token. |
| Socket Mode did not connect | The app-level token is wrong or lacks `connections:write`, or Socket Mode is off (the manifest turns it on). |
| Missing scopes in `docker compose logs slack` | Paste the current manifest over the app's, then reinstall it. |
| No reply in a channel | Tico must be invited to it, and the sender must be on the roster. |
| Replies show as "Tico", not the bot | The `chat:write.customize` scope is missing; update the manifest and reinstall. |

Kill switch: remove `slack` from `COMPOSE_PROFILES` and run `docker compose up -d --remove-orphans`.
The server, its data and the saved tokens are untouched.
