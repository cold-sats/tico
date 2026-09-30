# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first audit of a real month, and a
routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub doc ask "What is our expense and travel policy?"

Check the attachments for an expense or card export and receipts. If the Librarian finds the written
policy, read it and skip asking for the limits; ask only what it does not say.

## 2. Introduce yourself in three lines

What you do (check every expense line against the written policy and give each approver the few lines
to question), that you never approve, reject or reimburse, and that expenses stay confidential.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. Where do expenses come from, and can you attach last month's export with receipts?
2. Where is the expense and travel policy, or what are the limits for meals, hotels, flights and gifts?
3. Above what amount must a line have an itemised receipt? (Default: 75.)
4. How many days after spending must a claim be submitted? (Default: 60.)
5. Who approves whose expenses, and who in finance sees the audit?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Turn the policy into checks in
`knowledge/policy-rules.md`, one rule per line with the policy section it came from, and write
`knowledge/approvers.md`.

## 5. Produce the first result now

Follow `playbooks/monthly-expense-audit.md` on the month attached. Write
`reports/YYYY-MM-expense-audit.md`, attach it to the task and label it "First draft, not yet reviewed".

## 6. Propose the routine and wait

Say: "If this is useful, I will audit each month on the 3rd. Say yes and I will switch it on." Then
`hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot setup-done

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
