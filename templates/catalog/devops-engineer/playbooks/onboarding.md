# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first CI health report on the task
from the last two weeks of runs, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub team show
    gh workflow list -R <repo>
    gh run list -R <repo> --limit 50

Find the workflows that run on pull requests and on the main branch, and whether one is named like a
deploy. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (find flaky tests, slow jobs and red-main streaks and write the fix plan), that you never
rerun, cancel, trigger or edit a workflow or deploy, and that the test's owner decides fix or quarantine.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. Which repositories and workflows matter most, and which one gates merging to main? Why: the report starts with the pipeline that blocks people.
2. How do you deploy today: on merge, on a tag, by hand, and from which workflow? Why: deploy frequency is read from it.
3. What is too slow for the merge check, and how many flips make a test flaky? (Default: over 15 minutes; failed then passed on the same commit twice in two weeks.) Why: becomes knowledge/thresholds.md.
4. Who owns the CI configuration, and who owns each test suite? Why: every fix plan names an owner.
5. Which day and hour should the report land, and who reads it? (Default: Tuesdays at 09:00, you.) Why: sets the routine.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/thresholds.md` and
`knowledge/pipeline.md` (workflow, trigger, jobs, typical duration, owner) as present-tense statements.

## 5. Produce the first result now

Follow `playbooks/weekly-ci-health.md` over the last two weeks. Write `reports/YYYY-MM-DD-ci-health.md`,
attach it to the task and label it "First draft, not yet reviewed". Rerun nothing and change nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will write this report every Tuesday at 09:00. Say yes and I will switch it
on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot setup-done

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
