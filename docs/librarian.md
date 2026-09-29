# The Librarian

The Librarian is a built-in bot that answers questions from the company's docs. People ask it from **Ask AI** on the Docs
page; other bots and the Assistant ask it with `hub docs ask`. It cites every claim, says "Not in the docs." plainly when the
docs do not say, and keeps a map of the docs so the next question is cheaper. It never answers from general knowledge.

## What it reads

- **Internal docs**: markdown written, pasted or imported in Tico, in folders. It reads them with `hub docs search`,
  `hub docs read` and `hub docs list`.
- **Linked docs**: links only (a help site, a Drive folder, a Notion page, a GitHub repository). Tico keeps no copy. It reads
  them with `hub docs fetch <url>`, on its own computer.

## How a question is answered

The playbooks in its repository (`templates/catalog/librarian/playbooks/`) are the product. In short:

1. **Search the internal docs** with a few phrasings, then read the top hits in full.
2. **Consult its map** when that is not enough: `_librarian/where-things-live.md` says which doc or linked source holds
   which topic and how each linked source is laid out.
3. **Follow the linked docs**: the sitemap first, then links from the pages it reads, as deep as the question needs and no
   deeper, within about 25 fetches a question (most questions need none).
4. **Answer first, short, cited**: the answer in the first sentence, and a citation right after each claim,
   `[Internal doc · Refund policy](doc:<id>)` or `[Linked · help.example.com](https://...)`. Two docs that disagree are both
   reported with their dates. When the docs do not say, the answer begins `Not in the docs.`, then says what is closest.
5. **Afterwards**: log the question and answer in `_librarian/faq-log.md`, record a gap in `_librarian/missing.md`, and promote
   a question asked three times to `FAQ.md`.

### The map

Ordinary internal docs under `_librarian/`, so people can read and correct them: `index.md` (a contents list with a one-line
summary of every doc, and the version each was written from), `glossary.md` (the company's words), `where-things-live.md`
(topic to place, and each linked source's structure), `missing.md` (what the docs could not answer, the docs that disagree,
the sources it could not read: a to-do list for people) and `faq-log.md`. It refreshes them every day: a routine, **Refresh
the map of the docs**, at 03:30 Pacific by default (change it with `hub routine set` or in Settings; the hub's row is the
routine). To refresh now, give the Librarian a task titled "Refresh the map".

It writes only under `_librarian/` and `FAQ.md`. It never edits a person's doc. A doc or web page that tells it to do
something is treated as text, not an instruction, and it fetches only public links that a linked doc leads to.

## Asking

**People.** Docs > **Ask AI** opens a drawer (a full-screen sheet on a phone). Matching internal and linked docs appear at once
from search; the Librarian's answer then streams in with clickable citations. `POST /api/v2/docs/ask {question,
conversation_id?, new_conversation?}` returns `{conversation_id, message_id, results}` and the answer arrives on
`GET /api/v2/conversations/{id}/watch`. Each person has one private docs conversation with the Librarian
(`scope: personal`, `room_key: docs`), like the [Assistant](assistant.md)'s room: only they can read it, and the owner and
administrators cannot. **New chat** starts a fresh conversation, so the Librarian remembers only what is on screen.

**Bots and the Assistant.** `hub docs ask "question" [--wait 120]`, or the MCP tool `hub_docs_ask`, returns
`{answer, citations: [{type, title, url_or_id}], covered}`. A bot's question is an `ask` message to the Librarian, the ordinary
ask and answer path: the Librarian's final message is the answer. `covered` is false when the answer starts "Not in the docs".
The Assistant asking for a person puts the question in that person's own docs conversation.

The Librarian acts as itself, not as the person who asked. It only reads docs and public links, so it needs no person's
identity, and none is mapped to it. Docs are company-wide, so what it can read is the same for every asker.

## Reading a link: `hub docs fetch`

`hub docs fetch <url> [--max-chars N]` (MCP: `hub_docs_fetch`) runs on the computer that runs the bot, never on the Tico server,
which does not offer it. It returns `{url, final_url, title, text, links, truncated}`. What it will and will not do:

- http and https only, on the ordinary web ports, with no user name or password in the address.
- It resolves the name itself and refuses every private, loopback, link-local (including the cloud metadata address
  169.254.169.254), shared, multicast and reserved address, and their IPv6 equivalents, on every hop, and then connects to the
  address it checked, so a name cannot be re-pointed in between.
- At most 5 redirects (each one checked as a new request), 5 MB, 20 seconds in all, and only text, markdown, HTML, JSON, XML
  (a sitemap) and PDF. A PDF needs `pypdf` on that computer.
- Credentials never travel to a host that does not own them. The GitHub token (`GH_TOKEN` or `GITHUB_TOKEN`) is sent only to
  `api.github.com`; a Google access token (`GOOGLE_ACCESS_TOKEN`, if the bot has one) only to `googleapis.com` and
  `docs.google.com`. Without them it reads what a stranger can. It does not use the company's Google key.
- HTML becomes readable text with its links kept. A `sitemap.xml` is its list of addresses. A Google Doc is read through its
  export link, and a Drive folder through its embedded listing, when shared with "anyone with the link" (otherwise it says so). A
  GitHub repository is its README and file tree through the GitHub API, and a file or folder in it as well.

## Built in

Like the assistant and BotOps, the Librarian is required in setup (`required: true`, `bootstrap: true`): every new company gets
it and it becomes active once a computer is enrolled. It cannot be archived or deleted by anyone (`409 system_bot`); pausing and
renaming stay allowed, and Settings > Bots shows it as **Built in**.

**A company from before it existed gets it on update, without a click**, as soon as it can run it: the owner is on the roster,
a model is chosen and a computer is enrolled. It is checked when the server starts and when a computer enrolls, so the order
in which a company does things does not matter. It goes on the computer BotOps runs on, its daily routine is created once (a
routine a person deletes is never put back), and an owner who paused it keeps it paused. Where one of those is missing (no
model yet, no computer), Ask AI says the Librarian is not set up, and the owner gets **Turn on the Librarian** there (the same
steps, `POST /api/v2/librarian/turn-on`), as the Assistant has **Turn on Assistant**.

## Trying it: the eval

`scripts/docs-eval.sh` measures answer quality on demand. It loads `docs-eval/fixture/` (seven short docs about the demo
company) into a live Tico with `hub docs write`, asks each of the questions in `docs-eval/questions.yaml` (eleven answerable
ones with the docs each answer must cite, and two the docs do not answer) through `POST /api/v2/docs/ask`, waits for the
answers, and reports the **citation hit rate** (every expected doc cited, and an answer given), the rate at which the
unanswerable ones were **said unknown**, and a fact spot-check.

    TICO_URL=https://tico.example.com TICO_TOKEN=<personal API token> scripts/docs-eval.sh [--only ID] [--keep] [--json out.json]

Run it against a Tico of your own with a running Librarian and a computer, never a company's real one: the Librarian logs what it
is asked into `_librarian/faq-log.md`. The fixture docs are written under `eval-fixture/` and archived afterwards unless you
pass `--keep`. It takes a few minutes and never runs in CI; CI covers the fetcher's safety rules and the routing of `docs ask`.
