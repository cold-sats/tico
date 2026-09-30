# Privacy

What a Tico install sends outside your own server, and what the receiving side keeps: the anonymous usage count, and the
suggestions while you build your org chart. Each has its own switch. Tico is open source, so you can read the code that
sends them (`backend/census.py`, `backend/releases.py`, `backend/recruit.py`) and the code that receives them (`hq/`).
Tico HQ itself is described in [docs/tico-hq.md](docs/tico-hq.md).

## The anonymous usage count

Tico counts how many installs are in use, so the project can tell whether it is helping anyone. It does this the way
Homebrew, Next.js and Astro do: anonymously, in the open, and with a switch you control.

### What is sent

Your Tico looks for a new release about every six hours. With counting on, it asks Tico HQ instead of GitHub, and the
request carries exactly these four fields and nothing else:

```
GET https://updates.tico.team/v1/latest?install_id=6f1c2a9e-3b7d-4c58-9a10-2d4e8b7f5a63&version=0.2.15&active_people=true&active_bots=false
```

| Field | What it is |
|---|---|
| `install_id` | A random UUID made once and stored in your database. It is not derived from your domain, company, machine or anything else. You can replace it at any time. |
| `version` | The Tico release you run, for example `0.2.15`. |
| `active_people` | `true` if at least one person used Tico in the last 7 days, otherwise `false`. |
| `active_bots` | `true` if at least one bot turn finished in the last 7 days, otherwise `false`. |

That is all. No company name, domain, email address, people, bot names, counts, content, hostnames or file names. Your
IP address is unavoidably seen by any server you connect to (GitHub sees it today), and HQ handles it as described below.

### When

Only while counting is on, only from a real install (never in demo mode, never from a source checkout that reports
`dev`), and only after the owner has been shown the notice. A new install shows it in the installer, in the setup
wizard and once in the web app; an existing install shows it in the web app when it updates to 0.2.15, and nothing is
sent before the owner has seen it.

### What HQ stores

One row per install ID, and nothing else:

| Column | Value |
|---|---|
| `install_id` | the random ID |
| `first_seen` | the UTC day the ID first arrived |
| `last_seen` | the UTC day it last arrived |
| `last_version` | the version in the last request |
| `last_people` | the last UTC day `active_people` was true |
| `last_bots` | the last UTC day `active_bots` was true |

- **No IP addresses are stored or logged.** HQ uses the address in memory only, as a salted hash forgotten when the
  process restarts, to limit each address to 60 requests an hour. Its access log is switched off, so no address and no
  query string reaches a log. There is no ping history, user agent or other column.
- Every field is checked strictly (a UUID, a version number, the words `true` or `false`); a request with anything
  else is refused and stores nothing. Extra fields are ignored and never stored.
- **Retention:** an install not heard from in 13 months is deleted, by a job that runs daily.
- The database is on one server run by the Tico team, separate from any customer's Tico.

### What we publish

`https://updates.tico.team/v1/stats` is public. It shows the number of installs that have tried Tico (a person and a bot
active at some point), that were active in the last 7 days, and that are still running bots 30 or more days after they
first appeared, plus a count by major version. Counts by version under 5 are left out. Those are the numbers behind
Tico's goal of 100 companies trying it and 100 still using it after 30 days.

### Turn it off

Any one of these is enough. When counting is off, the update check still works: it asks GitHub directly, exactly as
before, with no ID and no flags.

1. **In the app:** Settings > Privacy, switch off "Help count active installs" (the owner).
2. **Environment:** `TICO_TELEMETRY=off` in your `.env`.
3. **The standard:** `DO_NOT_TRACK=1` in your environment ([consoledonottrack.com](https://consoledonottrack.com/)).
4. **The command line:** `docker compose exec server python -m backend.manage usage-count /data/hub.sqlite off`.

Other controls: **Reset install ID** in Settings > Privacy (or `... usage-count /data/hub.sqlite reset-id`) makes a new
random ID, so the old one no longer connects to your install; do it when you clone a server. `TICO_UPDATE_CHECK=off`
stops the update check altogether, and with it the count. `TICO_HQ_URL` points the check at your own HQ.

### Check it yourself

- `TICO_TELEMETRY_DEBUG=1` prints the exact request Tico would send to the server log and sends nothing.
- `docker compose exec server python -m backend.manage usage-count /data/hub.sqlite payload` prints the same four fields.
- The sending code is `backend/census.py` and `backend/releases.py`; the collector is `hq/`. A test
  (`backend/tests/test_usage_count.py`) fails if the request carries any field beyond these four.

More on why it is built this way, and how to run HQ yourself: [docs/telemetry.md](docs/telemetry.md).

## Suggestions while you build your org chart

When you set up Tico, the org chart step asks one short question per department ("What kind of sales do you do today?") and
suggests bots for it. Each department card has a toggle, **Suggestions from Tico HQ (sends this answer)**. While it is on, your
Tico server (never your browser) sends that one answer to Tico HQ, which ranks the department's bot templates with a language
model and says why each fits. While it is off, or whenever HQ cannot be reached within 6 seconds, your own server ranks them
locally and nothing is sent.

### What is sent

One request per department you answer, and only while the toggle is on:

```
POST https://updates.tico.team/v1/recruit
{"department": "sales",
 "briefing": "Inbound demos and a few big accounts",
 "about": {"what": "We sell scheduling software to clinics", "sells_to": "businesses", "software": true},
 "catalog_version": "ee9999fd8f2a",
 "install_id": "6f1c2a9e-3b7d-4c58-9a10-2d4e8b7f5a63"}
```

| Field | What it is |
|---|---|
| `department` | Which of the nine departments you are answering for |
| `briefing` | Your answer to that department's question, at most 500 characters |
| `about.what` | "What you do" from About the company, cut to 500 characters |
| `about.sells_to` | `businesses`, `consumers`, `both`, or empty |
| `about.software` | Whether software is your product |
| `catalog_version` | Which release's bot catalog you have, so HQ answers with templates you have |
| `install_id` | Only while the anonymous usage count is on: its random install ID, used for a rate limit and nothing else |

Nothing else: no company name, domain, people, email addresses or bot names. HQ answers with template ids and a one-line
reason for each; your server keeps only ids that are in its own catalog.

### What HQ keeps

**Nothing.** HQ has no table for these requests and writes nothing to disk for them.

- It never logs a request body. If the model call fails, only the kind of error is logged.
- It keeps an answer in memory for an hour, under a one-way hash of the question, so the same question costs nothing twice; the
  question itself is not kept even there. A restart forgets all of it.
- Your address is used in memory, as a salted hash, only to limit how many requests it can make; it is never stored or logged.
- The model is called with storage switched off (OpenAI's `store: false`). It sees the department's template list, your answer and
  the three facts above, and nothing else. HQ calls it at most a fixed number of times a day; past that, HQ ranks locally.

### When it is off

The toggle starts on and you can switch it off on any department. It is off, and cannot be switched on, when any of these holds;
the card says which:

- the anonymous usage count is switched off in Settings;
- `TICO_TELEMETRY=off` is set;
- `DO_NOT_TRACK` is set (to anything but `0`);
- Tico runs in demo mode.

With it off, the suggestions come from `backend/recruit_rank.py` on your own server, and nothing about your answers leaves it.
Your answers are saved in your own database with the rest of onboarding, so the bots you create can read them.

`TICO_HQ_URL` points your server at another HQ, such as one you run yourself.
