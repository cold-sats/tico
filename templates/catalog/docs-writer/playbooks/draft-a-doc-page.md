# Draft a doc page

Triggered by a task asking for a page or a fix, and used for each draft in `playbooks/weekly-docs-drift.md`.
Budget 30 minutes. The outcome is one draft file in `reports/drafts/`, one reader, one type, one job, for the
docs owner to commit with one edit.

---

## 1. Decide who and what

    hub task show <id>

Write down the reader (from `state.md`) and the job in one sentence: "A new admin invites a teammate."
Choose exactly one type:
- **Tutorial**: teaches by doing something safe, start to finish.
- **How-to**: solves one task for someone who knows the basics.
- **Reference**: complete, dry facts in a fixed structure (options, fields, errors).
- **Explanation**: why it works this way, and the context.
If the request mixes two, draft the main one and link to a stub for the other.

## 2. Gather the facts

Read the pull request, the diff and the current page. Run through the steps in your head against the code; if a
step depends on a screen or behaviour you cannot confirm, mark it `[to verify: who can confirm]`. Use the exact
names in `knowledge/glossary.md`.

## 3. Write, in the team's style

Follow `knowledge/style.md` first; where it is silent: second person, present tense, active voice, sentence-case
headings, one action per numbered step, the expected result after the step, no "simply".
- **How-to**: title as a goal ("Invite a teammate"), when to use it, prerequisites, numbered steps, what you
  see when it worked, what to do if it did not, and links to related pages.
- **Reference**: a table or list in a fixed order, every option with type, default and an example.
- **Tutorial**: a small working goal, checkpoints after each step.
- **Explanation**: the concept, the reasoning and the trade-offs, without steps.

## 4. Show the change

For a fix, put the old text, the new text and the reason (pull request link, date) at the top of the draft; for a
new page, the reader, the type and the sources. Keep the draft in the format of the docs repository.

## 5. Check

Every command, path and name is spelled as it is in the product. Every link points at a page that exists or is
marked new. No secret or customer detail. Under the length a reader can finish in one sitting.

## 6. Finish

Save the draft, attach it to the task, commit, then `hub task update <id> --status done --note`: the path,
the type, the items marked to verify, and who should review. A person commits it; you never do.

## When you cannot verify

Ask once with `hub task ask <id>`, naming the sentence and the person who knows. Ship the draft with the gap marked.
