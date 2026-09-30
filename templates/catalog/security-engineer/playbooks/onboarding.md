# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first security report on the task
from the real repositories, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub team show
    gh pr list -R <repo> --author app/dependabot --state open

Check which repositories this bot can read and whether Dependabot opens pull requests there. If it does
not, that is the first finding, not an empty report. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (rank dependency alerts and advisories by exploitation and reach, write the patch plan, find
committed secrets), that you never dismiss, merge or change a setting, and that unpatched details stay
inside the engineering team.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. Which repositories and deployed services are in scope, and which of them face the internet? Why: reachability starts from exposure.
2. What patch deadlines do you want per tier? (Default: known-exploited or reachable critical in 3 days, high in the current sprint, the rest quarterly.) Why: every alert is measured against it.
3. Who fixes security issues in each area, and who must hear at once about a known-exploited one? Why: every patch plan names an owner.
4. Are Dependabot alerts and secret scanning switched on? Why: if they are off, the first report proposes turning them on.
5. Which day and hour should the weekly report land, and who reads it? (Default: Mondays at 08:00, you.) Why: sets the routine.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/patch-policy.md` (tiers,
deadlines, who agreed) and `knowledge/exposure.md` (repository or service, internet-facing or not, owner).

## 5. Produce the first result now

Follow `playbooks/weekly-security-report.md` on the real repositories. Write
`reports/YYYY-MM-DD-security-report.md`, attach it to the task and label it "First draft, not yet
reviewed". Dismiss nothing and change nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will write this report every Monday at 08:00 and raise a known-exploited flaw
the day I see it. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
