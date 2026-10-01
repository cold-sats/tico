# Write a policy

Triggered by a task asking for a new policy or a change to one (remote work, time off, expenses, conduct,
equipment). Budget 40 minutes. The outcome is a policy the team can use with one edit, the reasons
for each choice, and a note of what counsel should check. Nothing is published.

---

## 1. Read what exists

    hub task show <id>
    hub doc ask "What do our current policies say about <topic>?"

Open every page the Librarian cites (`hub doc read <path>`) and read it whole. Note contradictions
between pages and how people actually work today (ask the requester if unclear, one question).

## 2. Settle the decisions first

List the three to six choices the policy makes (for example: who approves time off, how far ahead,
carry-over, what happens on leaving). For each, give the current practice and one or two options.
Where a law or regulation may set a minimum (leave, pay, working time, privacy), write "check with
counsel: <question>" instead of stating the law. You are not a lawyer.

## 3. Write it

Purpose in one sentence, who it covers, the rules as short numbered statements, the stated terms, where
to ask, the effective date and the review date (default: one year). Plain words, second person, under
two pages. No rule the team cannot enforce the same way for everyone.

## 4. Check it

Read it as a new hire, as a manager applying it and as someone it could disadvantage (a part-timer, a
remote worker, someone on leave). Fix any rule that treats them differently without a reason.

## 5. Hand over

Attach the policy, the decisions list and the counsel questions to the task and ask only about unresolved facts with `hub task ask <id>`. Record requested policy changes in `knowledge/policies.md` and send them to the Librarian: `hub task create --owner librarian --title "Publish policy: <topic>" --body "<text, effective date, owner>"`. Announce requested changes to the intended teammates with your Tools.
