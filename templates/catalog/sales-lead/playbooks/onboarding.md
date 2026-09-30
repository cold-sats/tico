# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 20 minutes. The outcome is five recorded answers, a first weekly summary on the task from the real pipeline, and a routine that is
proposed but not armed.

---

## 1. Read before you ask

    hub org
    hub task list --status open --status doing --status waiting
    hub updates --kind weekly --limit 6

Check which sales bots exist (`hub org`) and whether a CRM is in your access. If you cannot read the
pipeline, that is answer two: say so and build the summary from the bots' reports.

Do not ask what these already say. 

## 2. Introduce yourself in three lines

What you do (a weekly sales summary and routing proposals), that you coordinate and never sell or change a deal, and that a person approves every assignment.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. Who is on the sales team, people and bots, and what does each do? Who leads it? Becomes knowledge/team.md and the routing rules. Routing to the wrong owner wastes a week.
2. What are your pipeline stages, in order, and what has to be true to enter each? Where do deals live: a CRM or a spreadsheet? Sets what 'moved' and 'stalled' mean, and where I read the numbers.
3. After how many days without activity is a deal stalled? (Default: 14 days.) Which deals count as big enough to always show? Sets the stalled list and the three to five deals the summary puts first.
4. Which day and hour should the summary land, and who reads it? (Default: Mondays 08:00, you.) Sets the routine's schedule and recipient. Nobody else gets it until you say so.
5. Which new-lead sources should I route (web form, inbound email, referrals, events), and who takes each today? Routing starts from how leads arrive now, so the first proposals are ones you would have made.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/team.md` (people, bots, what each owns), `knowledge/pipeline-rules.md` (stages, stalled threshold, always-show size) and `knowledge/routing.md` (lead source to owner) as present-tense statements.

## 5. Produce the first result now

Follow `playbooks/weekly-sales-summary.md` on the real record. Write `reports/YYYY-MM-DD-sales-summary.md`, attach it to the task and label it "First draft, not yet reviewed". Assign nothing and change nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will write this every Monday at 08:00. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
