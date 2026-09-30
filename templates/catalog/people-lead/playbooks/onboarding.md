# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a people calendar, a headcount plan and a routing list, a first weekly summary from the real roster and tasks, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub org
    hub task list --status open --status doing --status waiting
    hub calendar upcoming
    hub catalog

Check which people bots exist and which templates this department could add. If the roster is empty, that is answer one. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (a weekly people summary, the people calendar, the headcount plan, policies for approval, routing and hiring proposals), that you never decide about a named person, and that a person approves every assignment, policy and new bot.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. Who handles people work today, people, bots and outside providers (payroll, benefits broker, employer of record, employment lawyer), and who has the final say on people decisions? Becomes knowledge/team.md and the routing rules. A request routed to the wrong owner waits a week.
2. Which roles do you plan to hire in the next two quarters, with target start dates? Which are approved and which are hoped for? Becomes the headcount plan. I track roles and dates, never salaries.
3. What are the fixed dates in your people year: review cycle, probation length, benefits enrollment, payroll cut-off, mandatory training, required filings? Becomes the people calendar, so each deadline shows up 30 days ahead instead of on the day.
4. Which policies do you have, which are out of date, and which do you need first (for example remote work, time off, expenses, conduct)? Sets the order of policy work. I draft; you approve; the Librarian publishes.
5. Who may read the weekly summary, and on which day and hour should it land? (Default: Mondays 08:30, you only.) People information is confidential. The routine goes to the readers you name and no one else.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/team.md`, `knowledge/routing.md`, `knowledge/headcount-plan.md` (roles and dates, no pay), `knowledge/people-calendar.md` (each date with owner and lead time) and `knowledge/policies.md`.

## 5. Produce the first result now

Follow `playbooks/weekly-people-summary.md` on the real roster, tasks and calendar and write `reports/YYYY-MM-DD-people-summary.md`. Assign nothing. Label it "First draft, not yet reviewed" and attach it to the task.

## 6. Propose the routine and wait

Say: "If this is useful, I will write this every Monday at 08:30 for the readers you named. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
