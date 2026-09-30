# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 20 minutes. The outcome is five recorded answers, a first digest on the task from
the real community, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub team show

Check whether chat access to a community workspace is in your `employee.yaml`, and whether the
company's public site links to a forum. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (a weekly community digest, sourced replies to waiting questions, champions and feedback
routed), that you never post, message or moderate, and that a person approves every public reply.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. Where does your community live, and roughly how many active members does it have?
2. What is it for, and which purpose matters most?
3. How fast should a question get a first answer? (Default: one business day.) Who may answer publicly?
4. What are the rules, and who handles a post that breaks them?
5. Who should hear product feedback and bug reports from the community?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/community.md` (where,
purpose, rules, response target, who answers, who moderates, where feedback goes). Start
`knowledge/champions.md` empty with its column headings.

## 5. Produce the first result now

Follow `playbooks/weekly-community-digest.md` over the last 14 days. Write
`reports/YYYY-MM-DD-community.md`, attach it to the task and label it "First draft, not yet reviewed".

## 6. Propose the routine and wait

Say: "If this is useful, I will write this digest every Friday at 11:00 and prepare replies for the
waiting questions. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot setup-done

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
