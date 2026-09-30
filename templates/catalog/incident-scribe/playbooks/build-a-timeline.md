# Build a timeline

Triggered by a task or message while an incident runs, or after it, naming the incident and where its record
lives. Budget 15 minutes (a first pass, then update on request). The outcome is one timestamped list a
responder can read at a glance. Nothing is posted.

---

## 1. Gather the record

    hub task show <id>

Read the incident channel (if connected, read only) or the export a human attached, the tasks and updates
around it, error spikes in an attached error-tracker export, and merged changes or deploys shortly before it.

## 2. Write one line per event

`HH:MM UTC | what happened | who or what | source`. Include: first sign (an alert, a customer report), first
human response, each hypothesis tried and dropped, each change made (rollback, config, scaling), the moment
impact ended, and the moment it was declared over. Convert time zones to UTC once and say which zone the
source used.

## 3. Mark uncertainty

A time read from a message is exact. A time you worked out is "approx." with how. A gap of more than 30
minutes is marked "no record for this period" and becomes a question for the incident lead.

## 4. Keep to facts

Record actions and observations, not opinions about people. "Deploy of change 412 started" is a fact;
"the bad deploy" is a judgement. Strip tokens, keys and personal details from any pasted log line.

## 5. Save and update

Write `reports/incidents/YYYY-MM-DD-<name>.md` with the timeline, the current status in the first line, and a
list of what is still unknown. During a live incident, update the same file on request rather than starting
another. Post nothing; the incident lead decides what goes to the status page.

## 6. Finish

Commit, then `hub task update <id> --status done --note` (or leave the task open while the incident runs):
the path, the latest event and the open questions.
