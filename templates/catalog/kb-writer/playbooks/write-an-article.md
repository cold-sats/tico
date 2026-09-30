# Write an article

Triggered by a task that names a question or a resolved ticket, and used in
`playbooks/weekly-article-drafts.md`. Budget 15 minutes per article. The outcome is one draft in
`knowledge/drafts/` a reviewer can publish with one edit.

---

## 1. Check for what exists

Search `knowledge/drafts/` and the linked help centre for the same problem. If an article exists, this
run updates it and the draft says "update to: <title>". Do not start a near duplicate.

## 2. Gather the facts

Read the resolved tickets and the standing answer. Note the customer's own words for the problem: those
are the title and the search terms. Write down the exact button and menu labels, the plan or version it
applies to, and any error message quoted exactly. A fact you cannot source becomes `[confirm: who]`.

## 3. One problem, one cause

If the tickets show two causes, write two articles or pick the one with the higher count and note the
other in the backlog.

## 4. Write, in this shape

- **Title**: the customer's question, in their words.
- **Short answer**: one or two sentences that solve it for most readers.
- **Steps**: numbered, one action each, with `[screenshot: ...]` where a picture helps.
- **If it did not work**: the one or two next things to check, and how to reach support.
- **Related**: two article titles.
- **Last reviewed: YYYY-MM-DD** and, for the reviewer only, a block "Source tickets and dates".

Under 250 words unless the task is genuinely long. No names, emails or account details from a ticket.

## 5. Finish

Set the draft's status to `draft, not reviewed`, update `knowledge/backlog.md`, and put the draft on the
task. Never publish. When the reviewer wants it live, they publish it themselves.
