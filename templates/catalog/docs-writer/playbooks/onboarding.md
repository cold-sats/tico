# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 30 minutes. The outcome is six recorded answers, a real drift report on the task with two draft fixes, and the first routine confirmed.

---

## 1. Read before you ask

    hub task show <id>
    gh pr list -R <repo> --state merged --limit 30 --json number,title,files,mergedAt

Check what you can already reach: the docs in the repositories you can read, and the
merged pull requests of the last two weeks. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (find docs that contradict merged changes and draft the fix or a new page), that you never edit or publish the docs, and that a human commits every draft.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine".

1. Which repositories hold the docs developers and users read: READMEs, API reference, a docs folder or a docs site built from the repo? Can I read them? Why: I only cover docs that live with the code; internal docs and the help centre belong to the Librarian, and I say which pages I could not read.
2. Who is the reader: end users, developers using an API, your own staff? What do they usually get stuck on? Why: Sets the type of page I write first. A stuck user needs a how-to, not an essay.
3. Is there a style guide, a glossary, or a page you consider the model? Why: Becomes knowledge/style.md. I match yours before any public guide.
4. Which repositories ship changes that users see? Why: Sets which merged pull requests I read for drift.
5. Who owns the docs, and who reviews a draft before it is committed? Why: Every draft goes to that human first; I never assume an owner.
6. Which day should the drift report land? (Default: Wednesdays at 10:00, to you.) Why: Sets the recipient and the first routine's schedule.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/docs-map.md` (each page, its type and owner, as far as you can read) and `knowledge/style.md` (their rules first, then the few of yours they accepted).

## 5. Do the first piece of work now

Compare the last two weeks of merged pull requests against the pages you can read and follow `playbooks/weekly-docs-drift.md`, drafting fixes for the two most important. Write the report in the shape of `knowledge/examples/docs-drift-report.md` to `reports/`, attach it to the task, labelled "First draft, not yet reviewed". Change no docs.

## 6. Confirm the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the human in one line what it does: "I will send you a docs drift report every Wednesday at 10:00 with draft fixes, and a human commits them." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot onboarded

It tells {{app_name}} your setup is done. That clears your "Needs setup" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
