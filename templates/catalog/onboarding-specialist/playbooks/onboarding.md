# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 20 minutes. The outcome is six recorded answers, a first onboarding board from the
customers in onboarding today, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub team show
    hub task list --status open --status doing --status waiting
    hub meeting search "kickoff"

Find the customers signed in the last 60 days and any kickoff or training calls. If a CRM is in your
access, read closed-won deals from the same window. Do not ask what these already show.

## 2. Introduce yourself in three lines

What you do (a plan per new customer, kickoff prep, milestone tracking, a weekly board), that nothing
reaches a customer until a person approves it, and that you never change a customer's account.

## 3. Ask, in one message

Numbered, each with its one-line why, offering the defaults so a person can answer "fine".

1. What has to be true for a customer to be live, and what is their first moment of real value?
2. What are the usual onboarding steps, in order, and who does each on both sides?
3. How long should onboarding take for small, mid-size and large customers? (Default: 3, 6, 10 weeks.)
4. How do you learn a deal has closed, and where does sales write what it promised?
5. After how many days without progress is a customer stuck, and who hears? (Default: 7 days; you.)
6. Who approves messages to customers, and who runs the kickoff calls?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/milestones.md`: the
milestones in order, first value, target durations, the stuck rule and the approver.

## 5. Produce the first result now

For each customer in onboarding today, write a short plan in `knowledge/customers/` from what you can
read, marking every gap. Then follow `playbooks/weekly-onboarding-board.md` and write
`reports/YYYY-MM-DD-onboarding-board.md`, labelled "First draft, not yet reviewed". Contact nobody.

## 6. Propose the routine and wait

Say: "If this is useful, I will update this board every Monday at 10:00. Say yes and I will switch it
on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot setup-done

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run. Never run it before a yes. If setup began in chat there is no task, so
ask in your reply instead of `hub task ask` and end the turn; the person's next message is the answer.
