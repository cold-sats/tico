# Company Docs reader and source synchronization

## Cloud execution boundary

The legacy all-local Tico service can perform the fast-search/model flow described below in the same process. The EC2 deployment deliberately cannot: it has no model runtime or model/provider credentials.

In cloud mode, catalog browsing and keyword search run deterministically against the validated SQLite snapshot. “Docs chat” and “Ask this doc” first persist a separate personal documentation conversation and COO job. The server chooses only documents the requester may read, bounds the source text, and sends that trusted context to the assigned local COO runner. A closed browser does not lose the question or answer; follow-ups within the dialog use the same conversation, which remains in conversation history. If COO's machine is offline, the question remains visibly queued.

“Refresh sources” similarly creates a normal local Doc Updater job. The worker runs `python3 -m clients.company_docs --publish-cloud`, then uploads the complete snapshot through its short-lived active-attempt credential. EC2 accepts that endpoint only from `bot:doc-updater`, validates counts, sizes, identifiers, HTTPS source links, approved repositories, PR URLs, exact head SHAs and bounded diff metadata, and atomically keeps the prior catalog readable until the replacement is accepted. A normal runner token, browser identity, or stale attempt credential cannot publish.

Proposed Changes loads the current PR metadata and diff from that trusted snapshot. Feedback is bound to the exact displayed 40-character head SHA and queued to local Doc Updater. “Merge reviewed revision” only asks Doc Updater to re-fetch and verify that exact revision and, if still eligible, create a normal explicit `merge` approval. EC2 does not merge, and clicking review does not create or approve an approval by itself.

## Linked repositories and agent edits

The cloud Docs page offers owners **Link repository**. Supply an HTTPS Git URL,
`git@host:org/repo.git`, or GitHub `owner/repo`, a repository-relative folder
(`.` for the root), and an optional branch. Configuration is persisted in cloud
registry metadata through `/api/v2/document-sources`. Linking queues a Doc Updater
refresh; the source remains linked if queuing fails, and Refresh sources retries it.
The worker uses its existing Git credentials. Credentials must not be embedded in URLs.

The importer reads regular Git blobs without checking out files or running repository
hooks, filters, symlinks or submodules. Markdown, MDX, text and reStructuredText files
inside the selected folder become searchable internal snapshots with repository,
branch, folder and revision metadata. It limits each source to 1,000 documents and
1 MB per file. A failed source keeps its prior snapshot and reports an import error.
Linked sources can import even if the original sources are unavailable.
Unlinking removes the library entries and preserves repository files and version history;
a stale in-flight catalog cannot restore an unlinked source.

Docs chat passes the authorized snapshot and linked source configuration to the local
COO agent. Owners can ask it to investigate repository documentation and prepare edits
in an isolated branch, returning an actual diff or PR for review. These instructions do
not authorize merging or deployment. Other accounts retain the existing external-only,
read-only documentation access. Source management and linked internal docs currently
require owner access. Additional repositories' PRs are linked in chat results; the
existing Proposed Changes panel still covers the original three repositories.

The legacy local answer service remains read-only. Local imports can read an optional
`runtime/company-docs/sources.json` array containing `repo`, `folder`, and `branch` objects;
the interactive source manager is available in cloud mode.

## Fast Docs answers

“Ask Docs” searches the current library; “Ask this doc” scopes retrieval to the selected page.
Bot Notes must be opened explicitly and are described as reference rather than policy. The server
filters documents by the authenticated reader's access before ranking or sending any model context.

`clients/docs_qa.py` combines SQLite FTS5 keyword ranking with cached 768-dimensional
`gemini-embedding-2` vectors using reciprocal rank fusion. Explicit Pro questions favor the Pro
audience, and broad software integration questions favor the overview. Six excerpts, with at most
two per document for library searches, feed one streamed `gemini-3.7-flash` call with low thinking.
The agent has no action tools. Answers cite numbered excerpts with links to readable source pages;
expand the source excerpt to inspect the actual retrieved evidence. Missing evidence is stated.

Vectors live outside the static site in `runtime/company-docs/search.sqlite`, keyed by content hash,
embedding model and dimensions. Source refresh warms only changed chunks in the background.
Search works with keyword retrieval if embedding calls fail. Repeated query vectors are cached in
memory. No separate vector database is needed. Gemini credentials come from the
server environment or `secrets/docs-qa.env`, with shared vault-reference resolution supported.
Requests use `store=false`; recent conversation turns remain in the open browser dialog.

September 9 evaluation: all five representative queries retrieved the expected document in the
top three; first searches took 0.48–1.54 seconds and repeated searches 43–65 ms. Full cited answers
in the sample took 1.4–2.3 seconds. These are observed local results, not latency guarantees.
The machine-readable retrieval sample is `runtime/company-docs/search-evaluation.json`.

Proposed Changes has a per-PR Doc Updater conversation, independent of read-only Q&A. Feedback
and exact-revision merge review are separate actions. In the legacy local flow the latter may
record an explicit Hub approval directly. In the cloud flow it queues Doc Updater to revalidate
the exact revision before requesting that normal approval; it never treats the review click as
approval. Mixed code PRs and draft PRs cannot use this merge action.

Acme's `#/docs` is a reader and search index, not a second editable source of truth.
Company documentation is separate from the Docs tab inside each employee page.

The default reader and search include current company guidance and the existing external
documentation structure. `#/docs?collection=notes` separately browses research, plans,
historical records, technical reference, marketing working files and bot operating rules.
`registry/company-docs.json` records the reviewed Tico documents. Unknown Tico files go to
Needs review; they cannot silently become current guidance during a source refresh.
Source files and document IDs remain intact, so older bot references and deep links still work.
Opening one of those links displays a reference-only label and passes that qualification to chat.

## Working now

- Published PM, Pro and Developer articles come from the rendered Acme website. The article
  extractor retains the entire article, headings, tables, code and images, without navigation,
  scripts or page controls. The client-side API reference is represented by its complete published
  OpenAPI specification. Short placeholder pages remain visible as placeholders.
- Internal operations Markdown comes from the default branch of `acme/internal-docs`.
- Shared company documentation and policies come from this workspace's `docs/` and `policies/`.
  These are explicitly labeled workspace copies, since they may include uncommitted work.
- Open documentation PRs are indexed from all three repositories, with file changes and diff
  previews. Proposed internal Markdown can be read as a full, separately labeled draft. GitHub
  can truncate a patch; each preview links to the full PR and file.
- Search matches complete document text. Stable source/path IDs support document deep links.
- Chat resolves the selected document on the server and attaches its full text, source, status
  and import time to the COO conversation. A request to propose an edit is not permission to merge
  or publish. Proposed revisions use the normal documentation review workflow.

In the legacy all-local service, while the owner's Docs page is open, the server checks source commit hashes, open PR revisions
and workspace modification times at most once a minute. Changed sources trigger a background
import. The client checks for a new snapshot every 30 seconds and preserves reading position.
Published articles are rechecked after 15 minutes even without a new Git commit, so a deployment
that finishes later is eventually picked up. Refresh sources starts the same import manually.
The existing complete snapshot stays readable during refresh. Import errors are visible; an
unavailable source keeps its previous content and original import timestamp.

On EC2 those source and GitHub checks happen only inside the locally assigned Doc Updater job;
the frontend polls the durable cloud snapshot and refresh-job state instead.

The mirror lives under `runtime/company-docs/index.json`, outside git and the static web root.
Owner access includes internal documents and PRs. Other authenticated accounts currently receive
only external documents, until a deliberate company-library access rule is defined.

## Next: exact rendering as your documentation site changes

The current external reader represents a **published snapshot**, not an undeployed Git revision.
Do not label a fetched public page as the rendered output of a particular commit: deployments can
lag source changes.

For immediate, exact commit and PR previews, add a documentation-export step to your documentation site's build:

1. Use the same Next/React documentation renderer to export each article into inert HTML and
   plain searchable text. Preserve headings, links, tables, image URLs and code blocks; represent
   client-only widgets with an explicit static equivalent such as the OpenAPI export.
2. Produce a manifest with repository, commit SHA, source blob SHA, source path, audience, title,
   canonical URL, content hash and artifact URL. A deleted source removes its manifest entry.
3. Store immutable artifacts per commit. PR builds use a separate draft namespace and manifest;
   merge/deployment promotes only the matching successful manifest to current documentation.
4. Send a signed completion webhook to Acme with the repository and exact revision. Verify the
   signature and repository allowlist, then fetch the manifest from the configured artifact
   store. Never fetch arbitrary URLs supplied by a webhook or execute repository code in Acme.
5. Atomically replace changed entries in the library and invalidate only their search records.
   Keep the previous readable revision until the replacement passes validation. Periodic revision
   checks remain the recovery path for missed webhook deliveries.

Internal Markdown does not require a build: a verified GitHub push or PR event can fetch the exact
blob by SHA and render it using the reader's sanitizer. For documentation-site PRs, show **Current**, **Proposed**
and **Diff** from the two immutable manifests. Keep proposed content separate from published policy.

The exporter, artifact publication and signed webhook are follow-on integration work. They are not
part of the current polling importer, and require selecting the artifact destination and wiring
the site's build. No documents need to move repositories to support either approach.
