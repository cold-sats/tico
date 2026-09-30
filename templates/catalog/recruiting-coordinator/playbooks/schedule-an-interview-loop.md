# Schedule an interview loop

Triggered by a task from `recruiting` or a hiring manager moving a candidate to interview. Budget 15
minutes. The outcome is one message to the candidate offering real times, ready for approval, and
held slots for the panel. Nothing is booked or sent before a yes.

---

## 1. Read the loop

    hub task show <id>

The role's `knowledge/loops/<role>.md`: rounds, panel, length, format. If the task changes the loop for
this candidate, use the task and note why. Missing panel names: one question to the manager.

## 2. Find three options

Read each panel member's calendar for the window in `state.md` (default five working days):
`hub calendar upcoming --calendar <email>`. Apply `knowledge/interviewer-rules.md`. For a loop with
several rounds, prefer back-to-back rounds on one day with a 10 minute break, or at most two days.
Three options, each with every round's time in the candidate's zone and the company's.

## 3. Write the message

Under 120 words: the role, the rounds and who the candidate meets (first name and role), length and
format, the three options, what to prepare (if anything), and one line on how to ask for a different
time or an accommodation. Put it up with `hub approval request --kind send --task <id>`.

## 4. On the candidate's choice

Book the roster interviewers once a person confirms: `hub calendar schedule --title "<role> interview:
<reference>" --start <iso> --end <iso>` per round, and check it with `hub calendar status <action-id>`.
The candidate's invitation with the join link goes up for approval as a message. Update
`knowledge/schedule.md`.

## 5. Kits

The day before, send each panel member the role's questions, the scoring guide and the resume on the
interview task (`hub task attach`) and one `hub say` line pointing at it.
