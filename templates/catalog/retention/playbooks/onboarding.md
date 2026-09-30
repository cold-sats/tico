# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 20 minutes. The outcome is five recorded answers, the save policy written down, a
first retention report from the last four weeks, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub org
    hub task list --status open --status done
    hub docs ask "What is our cancellation and refund policy?"

Collect the cancellation and downgrade requests of the last four weeks from tasks (and the support
mailbox if connected). Whatever policy the Librarian cites is the starting point for question two.

## 2. Introduce yourself in three lines

What you do (work each cancellation request, one save offer from written policy, a weekly report on
why customers leave), that cancelling always stays easy, and that a human approves every reply, offer
and billing change.

## 3. Ask, in one message

Numbered, each with its one-line why, offering the defaults.

1. How do customers cancel today, compared with how they sign up?
2. What may be offered to a customer who wants to leave, to whom, and where is it written?
3. What reasons do customers give? (Default codes: price, not using it, missing feature, switching,
   problem not solved, business closed, other.)
4. Which signals say a customer may leave soon, and which can I read?
5. Who approves replies and offers, and who gets the weekly report? (Default: you, Fridays 10:00.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/save-policy.md`: reason
codes, one offer per code with its limits, the approver. Start `knowledge/reasons.md` from the
requests you collected, coding each one.

## 5. Produce the first result now

Follow `playbooks/weekly-retention-report.md` over the last four weeks. Label the report "First draft,
not yet reviewed". Prepare replies for any open request, send none.

## 6. Propose the routine and wait

Say: "If this is useful, I will write this report every Friday at 10:00. Say yes and I will switch it
on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a human approved your first routine. That clears your "Needs setup"
mark and lets the routine run. Never run it before a yes. If setup began in chat there is no task, so
ask in your reply instead of `hub task ask` and end the run; the human's next message is the answer.
