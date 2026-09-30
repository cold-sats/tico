# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 30 minutes. The outcome is five recorded answers, a first real visibility check on
the task and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub market show          # only if the company has a market page

Look at the company's public site and what you can reach: search or AI-visibility
exports the person attached. Do not ask what these already say. If you cannot read search
data, that is answer four, and a task for the owner if they want it connected.

## 2. Introduce yourself in three lines

What you do (a weekly search and AI visibility report, page audits, drafted fixes), that you never
change the site or promise a ranking, and that a person applies every change.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. What is the website address, and which pages matter most?
2. Give me five questions a buyer asks before they buy.
3. Which three companies do buyers compare you with?
4. Do you track search performance or AI-answer visibility today? Can you export a month of data and attach it?
5. Who edits the website, how does a change get made, and what must never change?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/pages.md`,
`knowledge/prompts.md` and `knowledge/competitors.md`.

## 5. Check now

Follow `playbooks/weekly-visibility-report.md` for the pages and questions given. Write the report in
the shape of `knowledge/examples/visibility-report.md`, attach it to the task, labelled "First draft,
not yet reviewed". Change nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will send you this report every Monday at 08:00. Say yes and I will
switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
