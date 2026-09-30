# Docs

**Docs** is where a company keeps what its people and its bots should know. It has two kinds of thing,
and search covers both.

| | Internal docs | Linked docs |
|---|---|---|
| What it is | Markdown written, pasted or imported in Tico | A link to a doc that lives somewhere else |
| Where the text is | In Tico, with its full history | At the source; Tico stores no copy and runs no sync |
| Who can read | Everyone in the company, and every bot | Everyone in the company, and every bot |
| Who can change | Everyone; an owner or bot administrator can lock one | Whoever added it, an owner or a bot administrator |
| Opening one | In the page (read, edit, history) | In a new tab, at the source |

## Internal docs

A doc has a **title**, a **path** (`sales/pricing.md`: folders are the parts before the last `/`) and a Markdown
body. The page lists them grouped by folder.

- **Write** one with **New doc**: a title, a path (optional; it defaults to a slug of the title), a Markdown
  textarea with a **Preview** toggle, and an optional "what changed?" note. Save with the button or
  Cmd/Ctrl+S. Text is shown through the same sanitizing Markdown renderer as the rest of the app, so a pasted
  `<script>` or `onerror=` does nothing.
- **Import** a file from the `...` menu: `.md`, `.markdown`, `.txt`, `.html`, `.docx` or `.pdf`, up to 20 MB. It becomes
  a Markdown doc (headings, lists, links, bold and italic, and tables are kept; a PDF gives its text, and a scan with no
  text is refused). The title is the first `#` heading, else the file name.
- **Every change is a version.** **History** lists them (who, when, the note; "by Ops" for a bot), shows any old
  version, and **Restore** saves it as a new version. Nothing is rewritten or lost.
- **Editing together.** Saving sends the version you opened. If someone (or a bot) saved first you get "Ben saved
  version 5 while you were editing. Your text is still here." and choose to keep yours (replacing theirs on the next
  Save) or load theirs.
- **Lock.** An owner or bot administrator can lock a doc. A locked doc is read by everyone and changed only by owners
  and bot administrators (`403 locked` for anyone else, restore included). Locking is not a version.
- **Archive** removes a doc from the list and search and frees its path; its history is kept.

Bots use the same docs through the `hub` CLI and the MCP tools:

| Command | Tool | |
|---|---|---|
| `hub docs list [--prefix sales/]` | `hub_docs_list` | paths, titles, who changed them last |
| `hub docs read <id\|path>` | `hub_docs_read` | one doc in full, with its version |
| `hub docs search "words" [--manual]` | `hub_docs_search` | internal and linked docs, best first, then the Tico manual (`--manual`: only it) |
| `hub docs write <path> --title T (--body-file F \| stdin) [--note N]` | `hub_docs_write` | creates or replaces; on a version conflict it reads again and retries once |
| `hub docs history <id\|path>` | `hub_docs_history` | the versions |
| `hub docs links` | `hub_docs_links` | the linked docs |

A bot's writes show in the history as its own ("by Ops"). A locked doc refuses a bot.

## Linked docs

A linked doc is a title, an address, a **kind** and an optional one-line description, and who added it.
The kind comes from the address: `website`, `google_drive` (Drive folders and Sheets, Slides, Forms), `google_doc`,
`notion`, `github` or `other` (Dropbox, SharePoint, Confluence, Figma and similar). The title defaults to the host
and path. Add one with **Add link** on the page (anyone may); its adder, an owner or a bot administrator can edit or
remove it. Opening one goes to the source in a new tab, so people need access there. Tico never fetches it.

## The Tico manual

Every install carries the manual for its own release: the `docs/*.md` its image ships, as a **read-only** collection kept
apart from the company's docs. It is built in memory when the server starts and rebuilt when the release changes; it is never
stored in the company's docs, so it cannot be edited (`405 read_only`), listed with `hub docs list`, synced or backed up as
company content. `GET /api/v2/docs/search?collection=company|manual|all` (default `company`, which is what the Docs page uses)
and `hub docs search` (all: the company's results first, then the manual's) label each manual result `Tico manual` with its
file (`docs/backups.md`), a link to that page (the GitHub file at the release tag, `main` on a build with no version) and the
section's excerpt. `hub docs read manual:<name>` (`GET /api/v2/docs/manual/{name}`) reads one page; `GET /api/v2/docs/manual`
lists them.

## Search

The search box (and `GET /api/v2/docs/search`) looks through both kinds at once. Internal docs are ranked with
SQLite FTS5 (bm25; a title counts most, then the path, then the body) and show an excerpt; a question written as a
sentence still finds what answers it. Linked docs are matched on title, description and address. Each result says
which it is: **Internal** or **Linked**. Where SQLite has no FTS5, search falls back to a plain match.

## Ask AI

**Ask AI** asks the Librarian, the built-in bot for the company's docs, which answers with citations (`docs/librarian.md`). Bots and the Assistant ask it with `hub docs ask`.

## Upgrading

The old document mirror (a worker importing linked repositories, the "Current docs" view, Bot Notes, Proposed
changes and Doc Updater's link-repository setting) is gone. On the first start of a version with Docs, each linked
documentation source and each approved documentation repository becomes a linked doc, added by "Tico"; this runs
once. The old `documents` tables stay in the database, unused. Bot reference material stays in each bot's repository,
reachable from the bot's page.

## API

All of it is in the stable v2 contract ([openapi/v2.json](openapi/v2.json), tag **Docs**); every write needs an
`Idempotency-Key`. Reads are open to every signed-in person and bot.

| | |
|---|---|
| `GET /api/v2/docs?path_prefix=&limit=&cursor=` | `{"docs": [{"id", "path", "title", "updated", "updated_by", "updated_by_name", "locked", "version"}], "next_cursor"}` |
| `POST /api/v2/docs` `{"path"?, "title", "body", "note"?}` | `{"doc"}`; `409 path_taken` for a path in use |
| `GET /api/v2/docs/{id}` | `{"doc": {..., "body", "created_by", "created_by_name", "archived"}}` |
| `PATCH /api/v2/docs/{id}` `{"version", "title"?, "body"?, "path"?, "locked"?, "archived"?, "note"?}` | `{"doc"}`; `409 version_conflict` (with the current `version`, `updated_by_name`), `403 locked`, `403 forbidden` for `locked` by anyone but an owner or bot administrator |
| `GET /api/v2/docs/{id}/versions` | `{"versions": [{"version", "current", "title", "path", "actor", "actor_name", "created", "note", "size"}]}` |
| `GET /api/v2/docs/{id}/versions/{n}` | `{"version": {..., "body"}}` |
| `POST /api/v2/docs/{id}/restore` `{"version"}` | `{"doc"}`: the old version saved as a new one |
| `POST /api/v2/docs/import` (multipart `file`, `title`?, `path`?) | `{"doc"}` |
| `GET /api/v2/docs/search?q=&limit=` | `{"results": [{"type": "internal", "id", "path", "title", "excerpt", "score"} \| {"type": "linked", "id", "title", "url", "kind", "description", "score"}]}` |
| `GET /api/v2/linked-docs` | `{"linked": [{"id", "title", "url", "kind", "host", "description", "added_by", "added_by_name", "created", "updated"}]}` |
| `POST /api/v2/linked-docs` `{"url", "title"?, "description"?}` | `{"linked"}`; `409 already_linked` |
| `PATCH /api/v2/linked-docs/{id}` `{"title"?, "description"?, "url"?, "archived"?}` | `{"linked"}` |

Writes are recorded in the activity log with the actor (`docs.created`, `docs.updated`, `docs.restored`,
`docs.locked`, `docs.imported`, `docs.linked`, ...). The Assistant's fast-path lookup (`GET /api/v2/context/search?source=docs`)
covers internal and linked docs too.

The code is `backend/docs.py` (with `backend/docs_import.py` for file conversion) and `ui/docs-page.js`,
`ui/docs-editor.js`, `ui/docs-search.js`. Tests: `backend/tests/test_docs.py` and `ui/tests/docs.cjs`.
