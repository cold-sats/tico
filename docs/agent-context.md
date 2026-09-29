# Company context and meeting search

The `hub` CLI and MCP expose the same read-only functions, and one that files a meeting:

| CLI | MCP | Purpose |
| --- | --- | --- |
| `hub context search "pricing"` | `hub_context_search` | Search full company document text and market entities/evidence. |
| `hub context show <document-id>` | `hub_context_show` | Read a complete document found by search. |
| `hub meetings search "pricing"` | `hub_meetings_search` | Search meeting titles, notes, and transcripts; omit the query for recent history. |
| `hub meetings transcript <meeting-id>` | `hub_meetings_transcript` | Read the full transcript in bounded pages. |
| `hub meetings import call.vtt --source zoom` | `hub_meetings_import` | File a transcript from another tool as a meeting of yours (people only; [Meetings](meetings.md)). |

Context search accepts `--source all|docs|market` and `--limit` (1–50). Results
include source IDs, links, and matching excerpts. Use the existing `hub market show`
to inspect a market entity. Search is keyword-based, not a generated answer.

Meeting search accepts `--person`, `--since YYYY-MM-DD`, `--until YYYY-MM-DD`,
`--limit` (1–50), and `--offset`. Dates are inclusive and use the meeting start
when present, otherwise its creation date. Results include up to five matching
speaker passages with timestamps when the source provides them. Follow `next_offset`
for additional results. Transcript reads accept `--offset` and `--limit` in characters
(default 20,000, maximum 50,000); follow `next_offset` until it is null.

Document reads preserve the document library's existing visibility: owners see all
documents and other identities see external documents. Market knowledge follows the
existing market access rules. Bots may read explicitly non-private company meetings;
they do not inherit their operator's access to private meetings or personal notes.
Human access follows the existing owner/attendee rules. Deleted meetings are excluded.
The read tools do not expose audio, attachments, or credentials.
