# Chase open actions

Triggered by a person asking "what is still open?", by a project's status meeting, or by a task that
names a project. Budget 20 minutes. The outcome is one status page for the project or the week: what
is done, what is late, what is at risk, and a chase ready for each late owner. Nobody is chased until
a person approves.

---

## 1. Refresh the tracker

    hub task show <id>
    hub task list --status open --status doing --status waiting

Match each row in `knowledge/actions.md` to its task. A task closed since the last run moves the row
to done with the date; a row with no task is still a proposal and says so. Read the meetings since the
last run (`hub meeting search --since <date>`) for anything that changed a date or an owner.

## 2. Sort every open row

**Done** (task closed, or the owner said so in a dated meeting), **late** (past its date), **at risk**
(due within five working days and its task has not moved in a week), **on track**, or **no date**. A
milestone is at risk when any action it depends on is late; name that action.

## 3. Prepare the chases

For each late row, one internal message to its owner: the item, the meeting it came from with the
quote, the date it was due, and one question ("new date?" or "blocked on whom?"). Never more than one
chase per owner per week; a second late week goes to the person who ran the meeting instead.

## 4. Write the page

Answer first: "3 of 14 items late, the launch milestone at risk because of one of them." Then late
items with owner and days late, at-risk milestones, items with no date or no owner, and done since
last time as a count. Write `reports/YYYY-MM-DD-actions.md` and `hub file publish` it.

## 5. Hand over

Put the chases on the task and ask once with `hub task ask <id>`: "Send these three chases?". On a
yes, `hub message send --fyi <person> "<the chase and the link>"` for each. Update `knowledge/actions.md` (last
chased, the date), commit, and `hub task update <id> --status done --note` with the headline.
