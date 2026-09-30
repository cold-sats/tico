# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first weekly product summary from
the real roadmap, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub goals --all
    hub org
    hub task list --status open --status doing --status waiting
    hub updates --kind weekly --limit 6

Check which product bots exist and whether GitHub or the roadmap doc is readable. Do not ask what these
already say.

## 2. Introduce yourself in three lines

What you do (a weekly product summary, scored proposals, routing and hiring proposals), that you never
change the roadmap or promise a feature, and that the owner decides.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. What is the product outcome for this quarter, and which goal in Tico does it serve? Every proposal is scored against it.
2. Where does the roadmap live, and what is committed this quarter? Sets what I report on and where I read it.
3. Who decides what gets built, and who is on the product team? Decisions and routing go to the right person.
4. How do you size effort today, and who can estimate? Effort is the one number I ask for rather than find.
5. When should the summary land, and who reads it? (Default: Mondays at 09:00, you.) Sets the routine.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/roadmap.md`,
`knowledge/team.md` and `knowledge/scoring.md` (the impact scale and the effort unit) as present-tense
statements.

## 5. Produce the first result now

Follow `playbooks/weekly-product-summary.md` on the real roadmap and reports. Write
`reports/YYYY-MM-DD-product-summary.md`, attach it to the task and label it "First draft, not yet
reviewed". Change nothing and assign nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will write this every Monday at 09:00. Say yes and I will switch it on." Then
`hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
