# Answer a policy question

Triggered by a task or message that asks what a policy says. Budget 10 minutes. The outcome is one drafted
answer that quotes the handbook and cites its page, or a hand-off to a person. Nothing is sent.

---

## 1. Decide whether you may answer at all

Read `knowledge/hand-offs.md`. If the question is about pay, leave entitlements, discipline, performance,
health, a complaint, harassment, immigration or a termination, or about what a specific person is owed or
allowed, do not answer. Create a task for the person listed with the question copied untouched, tell the
requester it has gone there, and stop. Also stop when the person seems distressed.

## 2. Find the page

    hub docs search "<topic>"
    hub docs read <path>

Read the page itself, not only the index in `knowledge/handbook-index.md`. Note its date. If the search
finds two pages that disagree, keep both.

## 3. Draft the answer

1. Line one: what the handbook says, in one sentence, in the handbook's own words where you can.
2. The quoted sentence, the page title and its date.
3. What it does not cover, in one line, and who to ask (`knowledge/hand-offs.md`).
Never fill a gap with "usually", "most companies" or a legal rule. If the handbook is silent, the first
line is "The handbook does not answer this" and the question goes on `knowledge/unanswered.md` with a
count of how often it has been asked.

## 4. Hand over

Attach the draft to the task. A person sends it, or approves that exact text and recipient with
`hub approval request --kind send`.

## 5. Finish

Update the index if a page was out of date (say which in the note). `hub task update <id> --status done
--note`: the answer's page, or the hand-off and its owner.

## When a source fails

If the handbook cannot be read, say so and answer nothing. An answer from memory is never acceptable here.
