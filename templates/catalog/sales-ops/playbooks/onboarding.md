# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is six recorded answers, the first report on the task from a real read of the CRM, and the first routine confirmed.

---

## 1. Read before you ask

    hub task show <id>

Check that a CRM is in your access and that you can read it. If you cannot, that is answer one: file a task
for the owner to connect it read only, say that no report can be built without it, and stop. Never work
around it, and never ask for a write key.

Do not ask what these already say. 

## 2. Introduce yourself in three lines

What you do (a weekly pipeline report and a list of exceptions with proposed fixes), that you only ever read the CRM, and that a person makes every change.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. Which CRM do you use, and can I have a read-only key? Which pipeline and which stages, in order? Sets what I read and how I group the report. I only ever read the CRM, and I say so when I cannot reach it.
2. What has to be true of an open deal to enter each stage, and what must every open deal carry? (Default: stage, amount, close date, owner and a next step with a date.) Becomes knowledge/stages.md and the hygiene rules. A check is only fair against a written standard.
3. After how many days without activity is an open deal stale, and after how many close-date pushes is it flagged? (Defaults: 14 days, 3 pushes.) Sets the two thresholds the weekly report uses, so it neither nags nor misses.
4. Who owns each fix (each seller for their own deals, one person for duplicates), and who reads the report? (Default: the owner reads it; sellers own their deals.) Every exception needs a named owner. I list them; I do not chase them.
5. Do deals carry a forecast category (commit, best case, pipeline) or probabilities, and what must be true for a deal to be commit? I roll up the categories sellers set and flag the ones without evidence. Without categories the report counts and sums, and says so.
6. How are new leads assigned today: by territory, segment, round robin, or whoever sees it first? Who covers when someone is out? Becomes knowledge/routing-rules.md; I flag leads no rule covers and propose changes.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/stages.md` (stages, entry criteria, typical days) and `knowledge/hygiene-rules.md` (required fields, the two thresholds, what a duplicate is), `knowledge/forecast-rules.md` and `knowledge/routing-rules.md` as present-tense statements.

## 5. Produce the first result now

Follow `playbooks/weekly-crm-report.md` on the real CRM. Write `reports/YYYY-MM-DD-crm-report.md`, attach it to the task and label it "First draft, not yet reviewed". Change nothing.

## 6. Confirm the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the person in one line what it does: "I will send you this report every Monday at 06:30, read only, with the fixes listed for the owners." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot onboarded

It tells {{app_name}} your setup is done. That clears your "Needs onboarding" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
