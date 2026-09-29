# Try Tico in a minute

Demo mode runs Tico on your own computer with a made-up company, Acme, already in it: an org chart
with BotOps and the example bots (Support, Sales, Inbox, Content, Market Analyst), a week of daily
and weekly Updates, tasks in every state, a decision waiting on you, chats, meetings with
transcripts, docs, market notes, a routine and two connected computers. No domain, no DNS, no
sign-in, no model account.

```bash
docker run --rm -p 127.0.0.1:8765:8765 ghcr.io/ticoteam/tico:latest demo
```

Open <http://localhost:8765>. You are signed in as Ana, Acme's owner. Press Ctrl+C and everything is
gone. (Use a version tag instead of `latest` to pin one.) Docker is the simplest way because the image
already holds everything; there is nothing to configure, so no compose file is needed. Without Docker,
from a checkout with `pip install -r backend/requirements.txt`: `python3 -m backend.demo`.

![Updates](images/updates-desktop-light.png)

## It cannot be mistaken for a real install

- A **Demo — sample data** strip stays across the top of every page and cannot be closed.
- Everything is fictional: people are `@acme.example`, and dates are relative to now, so the week
  always ends today.
- Nothing leaves the machine. The update check is off, there is no telemetry, and the process
  refuses every connection to a non-local address.
- Bots do not run. There is no scheduler; **Run now** says so; a message to a bot is answered with one
  line saying it is a demo. Settings > Health shows the two sample computers as online and mostly green.
- It listens on loopback only. Started with `--host 0.0.0.0` it exits with an explanation. In the container it binds
  inside, and answers only requests addressed to `localhost`, so publish the port on `127.0.0.1` as above.
- `--public-demo --url https://demo.example.com` serves other people on purpose. Everyone is Ana, so a public
  demo is read-only.

Poking around is safe: changes go to a temporary database.

## Screenshots that stay current

The pictures in this repository's docs come from demo mode, not from a designer's laptop:

```bash
npm ci && npx playwright install chromium
TICO_BROWSER_CHANNEL= npm run screenshots        # everything, into docs/images
node scripts/screenshots --only updates,settings-health   # some pages
```

`scripts/screenshots` starts a demo, visits Updates, Tasks, Needs you, the org chart, a bot chat, Meetings, a
meeting, Settings > Health, Settings > Devices, Getting started, a tour step, Docs and Market at a desktop and a phone
width, light and dark, and writes `<page>-<desktop|phone>-<light|dark>.png`. It waits for the icon font and
fails, instead of saving a bad picture, on any console error, failed request, error banner, unloaded icon or
page that never finished loading. The `Screenshots` workflow runs it on every release tag and opens a pull
request with the new images.

![Health](images/settings-health-desktop-light.png)
