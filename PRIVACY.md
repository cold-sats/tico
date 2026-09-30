# Privacy

What a Tico install sends outside your own server, and what the receiving side keeps. Tico is open source, so you can read
the sending code (`backend/`) and the receiving code (`hq/`). Tico HQ itself is described in [docs/tico-hq.md](docs/tico-hq.md).

## Suggestions while you build your org chart

When you set up Tico, the org chart step asks one short question per department ("What kind of sales do you do today?") and
suggests bots for it. Each department card has a toggle, **Suggestions from Tico HQ (sends this answer)**. While it is on, your
Tico server (never your browser) sends that one answer to Tico HQ, which ranks the department's bot templates with a language
model and says why each fits. While it is off, or whenever HQ cannot be reached within 6 seconds, your own server ranks them
locally and nothing is sent.

### What is sent

One request per department you answer, and only while the toggle is on:

```
POST https://hq.tico.team/v1/recruit
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
