# Page audit

Triggered by a task naming a page or a question ("why don't we show up for X?"). Budget 25 minutes.
The outcome is one note on the task: what is wrong with the page for a buyer and for search, and the
drafted change.

---

## 1. Read the request and the page

    hub task show <id>

Load the public page. If it does not load, say so and stop: that is the finding.

## 2. Check the fundamentals

Indexable (no noindex, allowed in robots, in the sitemap); a unique title and a description that
match the page; one clear heading structure; descriptive internal links to and from it; alt text on
images that carry meaning; structured data valid if present; mobile view usable.

## 3. Check the content against the question

Which buyer question is this page for (`knowledge/pages.md`)? Does it answer it fully, with original
value, clear sourcing and a named author or owner? Compare with the two pages that rank or are cited
above it: what do they answer that this one does not? Read them, and cite them.

## 4. Draft the change

The exact new title (under about 60 characters), description (a sentence or two), heading or
paragraph, in `knowledge/voice.md` terms if a voice file exists. Facts come from
`knowledge/company.md` only; a claim you cannot source is marked as a gap for the owner.

## 5. Finish

Save the draft in `knowledge/drafts/`, update the page's line in `knowledge/pages.md`, commit, then
`hub task update <id> --status done --note`: the finding in one line, the draft path, and what you
could not check. Never edit the live page.
