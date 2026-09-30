# Documentation policy

## Current guidance versus notes

The company Docs library describes how Acme operates today. Public product
documentation keeps its existing structure. Internal documentation covers current company
guidance, responsibilities and operating procedures, including customer support and platform
handling.

Research captures, audits, meeting records, proposals, implementation plans and historical
designs are not current company guidance. Preserve useful material in an organized Bot Notes
collection: Research, Plans and proposals, Historical records, Technical reference,
Marketing working files, Bot operating rules, and Library maintenance. Unclassified shared
files go to Needs review. These collections are excluded from the default documentation search.
When explicitly discussing a note, qualify it as reference rather than presenting it as policy.

`registry/company-docs.json` defines the reviewed Tico documents included in the current library
and explicit exceptions for notes. A file being under `docs/` does not by itself make it current
company guidance. The reader organizes existing source files without breaking bot references;
file deletion or physical relocation is unnecessary for removing clutter from the main library.

Promote useful research into a maintained procedure only after its responsible owner confirms
the operational guidance. Preserve unresolved questions as questions; do not invent policy to
fill gaps. PRs remain proposed changes, separate from merged guidance.

Documentation has three homes. Keep one canonical copy and link to it rather than maintaining
parallel versions.

## Bot-internal documents

A bot may create, rewrite, reorganize, and commit documentation in its own repository with a
self-merged pull request or a direct commit, without human approval. This includes its
`knowledge/`, `reports/`, `memory/`, and `playbooks/`. The bot decides the useful structure and
level of standardization for its own work.

Bot autonomy does not waive privacy, security, evidence, access, or role boundaries. Never put
credentials, customer PII, private message text, or unsupported claims in git. A bot may not use
this rule to edit another employee's repository or change shared company policy.

## Shared internal company documents

Company knowledge that more than one team needs belongs under Tico's `docs/`. Before adding a new
page, search for the canonical existing page and update it when practical.

An authorized employee may create a pull request containing only ordinary internal company
documentation under `docs/` and merge that pull request without the owner's review. The pull request
still provides history and a place for automated checks. This self-merge rule does not include
`policies/`, `registry/`, application or runner code, access controls, credentials, or public
product repositories; their normal review and approval rules still apply.

Authenticated display of these documents on `hub.acme.example` remains internal distribution, not public
publishing. The same repository document should be rendered there rather than copied into a second
wiki.

## External and public documents

External documentation is customer-, partner-, candidate-, or public-facing content, including
documentation that ships from a product repository such as `acme/website`.

An employee may research, edit, validate, and open a pull request for external documentation, but
must not merge or deploy it without explicit approval. The owner may merge it personally or use the
Docs review's “Merge reviewed revision” action to authorize Doc Updater to merge that exact
repository, PR number and head SHA. Ordinary chat feedback does not authorize merging. The bot
must verify the approval, current head, docs-only scope and required checks, consume the approval
once, and use GitHub's matching-head merge guard without bypassing branch protection. A changed
head needs fresh review. This does not authorize deployment commands or unrelated changes.

Before opening a pull request, list the target repository's open pull requests and look for an
existing compatible documentation-update pull request. If one exists, add the new documentation
commit to its branch and update its description instead of creating another pull request. Create a
new pull request only when no compatible one exists or the existing branch cannot safely be
updated; explain that exception in the new pull request.

Keep a reused pull request reviewable: list every changed page, summarize the new addition, and
keep unrelated product code out of it. The task handoff to the owner links the one open pull request
and says what changed; it never claims the documentation shipped before the owner merges it.

Opening or updating this review pull request is not itself public publishing. Any other public
publish, deletion, or live-copy change follows `approvals.md`.
