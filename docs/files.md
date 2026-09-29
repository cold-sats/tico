# Files

A bot's page lists **Files**: the useful things it created, revised or delivered, newest activity
first, as a plain list of an icon and a name. Three rows show by default; "Show all" opens the rest in
place. A stored file opens in the app's viewer (a CSV as a table, its first 1,000 rows, with Download);
a linked document opens at its provider in a new tab.

## What gets listed

A file is something the bot makes and hands over: a report, a draft, a spreadsheet, an export, a
Google Doc it wrote. Attachments people send a bot are its inputs and are **not** listed unless the
bot itself publishes or changes them. A git checkout is a workspace, not a file store: only what the
bot publishes appears.

One row is one file. Editing it does not add rows: the row keeps its title, gains a version and an
activity entry, and moves to the top. A row is identified by the bot, where it came from (its task,
its conversation, or bot-wide) and a canonical identity:

| Identity | Meaning |
|---|---|
| `blob-series:<id>` | bytes published from a path, one series per path |
| `google-drive:<file id>` | a Google Doc, Sheet, Slides or Drive file, whatever its URL form |
| `url:<address>` | any other https document, without fragment or tracking parameters |
| `s3:<bucket>/<key>` | an S3 object the bot's computer copied |

## The three kinds

1. **Stored files.** The bytes are in Tico's private blob store (content-addressed, backed up,
   never overwritten). They open through Tico only: `GET /api/v2/files/{id}` for the latest version
   and `/api/v2/files/{id}/versions/{n}` for an older one, in the same safe viewer or download as
   any attachment. No storage address (`s3://`, a presigned URL) is ever shown.
2. **Cloud documents.** A Google Doc, Sheet or Slides, a Notion page, a Figma file or any https
   document. `hub files add-link <url> --title "..."` registers the address (http, `javascript:`,
   credentials in the URL and private-network hosts are refused). Open goes to the provider, which
   decides who may read it; the row says "Link opens in Google (requires access)". Tico never
   fetches, proxies or copies the document and never holds a provider token. Each time the bot says
   it edited the document (`hub files touch <id|url>`, or add-link again) the row moves to the top.
3. **S3 objects.** `hub files import s3://bucket/key [--title ...] [--task ...]` runs on the bot's
   computer. It copies the object with the credentials that computer already has (the bot's secrets
   or its AWS environment; boto3, or the aws CLI when boto3 is missing), refuses a type or size
   outside the limits, and uploads the bytes to Tico's store. The object's ETag (and version id) is
   recorded; importing again after the object changed adds a version, importing the same ETag adds
   only an activity entry. The hub never reads a company bucket with its own credentials.

## Publishing

**Explicitly**, from a turn (the same tools exist over MCP as `hub_files_*`):

```
hub files publish reports/2026-09-29-pipeline.md [--title T] [--task ID] [--scope task|bot]
hub files add-link https://docs.google.com/document/d/... --title "Q4 plan"
hub files touch <file id or link>
hub files import s3://bucket/key
hub files list
```

A bot can write only its own files: the authenticated bot decides, never a parameter.

**Automatically**, at the end of a completed turn, the runner uploads new or changed files under
the bot checkout's `reports/` and `artifacts/`, comparing against what it published before. Choose
other folders (or none) per bot in `employee.yaml`:

```yaml
files:
  publish: [reports/, artifacts/, deliverables/]   # publish: [] turns it off
```

Only documents, images, csv, tsv, json, yaml, md, html, pdf and office files go, at most 25 MB each.
A `.env`, anything with a credential-like name, a symbolic link, a file with more than one hard link, and any path that resolves outside
the checkout is refused. Uploads go through a durable outbox in the runner's own state with an
idempotency key per file and content, so a restart or a lost reply retries safely and lands once. A
file that could not be uploaded is not linked and never opens nothing.

When the bot's repository is on GitHub and the file is committed and pushed, the version records
the commit and the row offers **View on GitHub** at that exact commit.

A bot's deliverable attached to a task (`hub task attach`) is listed as a file for that task too.

## Visibility

A file inherits the visibility of where it came from:

- made for a **task**: whoever can see the task;
- made in a **conversation**: whoever can see the conversation. A direct chat's files are visible
  to its participants and to the company owner, who can open direct chats. Personal Assistant rooms are the exception:
  only their person sees them, the owner included. In a shared bot room, only its members do. Anyone else does not learn a file name, a count, a version or an
  activity entry from it, on the bot's page or anywhere else;
- **bot-wide**: anyone who can see the bot.

The check applies to every list row, the total, metadata, activity, versions and every download.

A bot cannot make a chat's file bot-wide. The owner or a bot administrator **promotes** a task or
conversation file to bot-wide, explicitly and never automatically (`PATCH /api/v2/files/{id}` with `promote: true`); the move is
recorded in the file's activity. Archiving (`archived: true`) takes a file off the list; its bytes stay, and it returns when
the bot publishes a changed version.

## API

Stable v2 (`docs/openapi/v2.json`): `GET /api/v2/bots/{bot}/files?limit=&cursor=` (ordered by last
activity, with the visible `total`), `POST /api/v2/files/uploads`, `/links`, `/imports`,
`PATCH /api/v2/files/{id}` (title, task, archive, promote), `GET /api/v2/files/{id}/activity` and
`/versions`. Display names come as `actor_name` and in `actors`, as everywhere in v2.
`docs/custom-frontend.md` and `examples/custom-frontend` show a bot's Files in a frontend of your own.

## Retention

Every version is kept: versions are immutable and nothing prunes them. The owner or a bot administrator
removes a file from the bot's page (`PATCH /api/v2/files/{id}` with `archived: true`). That hides the row
and keeps the bytes; the file returns when the bot publishes a changed version. A bot cannot remove a file.
