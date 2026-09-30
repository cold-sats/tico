# Screen an application

Triggered by a task that attaches an application, or by the mailbox if connected. Budget 8 minutes each.
The outcome is a summary under 150 words for the hiring manager. It says how the application matches the
stated criteria. It does not say whether to advance the person.

---

## 1. Read the role file first

`knowledge/roles/<role>.md`. If it has no written criteria, stop and ask the manager one question with
`hub task ask <id>`; screening against your own idea of a good candidate is the failure this playbook prevents.

## 2. Read the application

Only what a human handed you or the connected mailbox holds. Do not search for the person online, do not
look at photos, social profiles, names for an origin, or age signals such as graduation years. Note but do
not use anything in the application that is not a stated criterion.

## 3. Match, item by item

For each required criterion write one of: **shown** (with the line from the application), **partly shown**,
or **not shown in the application**. "Not shown" never means "no". Then the preferred ones the same way.
Add up to two facts the manager may want to ask about, framed as questions, not judgements.

## 4. Write the summary

Three lines and a table: a reference (initials and a number), the role, the criteria match, questions to ask.
No score, rank or recommendation. If the application mentions a disability, an accommodation, pregnancy,
religion or family, leave it out of the summary and tell the manager to look at the original.

## 5. Record

Add one line to `knowledge/pipeline.md` (reference, role, stage a human set, date). Do not copy contact
details into a file.

## 6. Finish

Attach the summary to the task and `hub task update <id> --status done --note`: how many summarised, which
could not be read (a broken attachment is named), and who is waiting past the agreed wait. A reply to the
candidate is a draft on the task, and a human sends it.

## When a source fails

An unreadable attachment is "not read", and the summary says so at the top. It is never a weaker match.
