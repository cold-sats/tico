# Weekly spec and launch review

Schedule: Tuesdays at 10:00 company time (routine `weekly-spec-review`), once a person has approved the
first review. Budget 30 minutes. The outcome is one page: which specs are blocked, on whom, and which
launch lines are due. Nothing is filed or changed.

---

## 1. Read where things stand

    hub task show <id>

Then `state.md`, every spec in `specs/` not marked shipped, `knowledge/launch-checklist.md` and last
week's review. Check whether last week's blocking questions were answered.

## 2. Check each spec in flight

For each: status (draft, agreed, building, in QA, shipped), open questions and how many days each has been
open, scope changes since last week with who agreed them, and what engineering is doing against it (read
the linked issues and pull requests, read only). A question open more than three working days is blocking.

## 3. Check each launch due in four weeks

Walk `knowledge/launch-checklist.md` for each: QA plan from the QA Engineer, docs gap reported to the
Librarian, support briefed, release notes with the Release Manager, messaging with the Product Marketing
Manager, rollback or flag plan. Mark each line done, due or missing, with its owner.

## 4. Write and hand over

Write `reports/YYYY-MM-DD-spec-review.md` in the shape of `knowledge/examples/spec-review.md`, then
`hub file publish reports/YYYY-MM-DD-spec-review.md`. Commit, and `hub task update <id> --status done
--note`: the headline, the blocking questions and their owners, and what you could not read.
