# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers and a first readout (or a tracking gap list) on the task, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub db list
    hub goal list --all
    hub task list --status open --status doing

Run `hub db doctor <name>` on each database you can see, and look for a tracking plan with
`hub doc search "tracking"`. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (a weekly usage readout, answers to product questions, experiment readouts), that you never write to data or set KPIs, and that numbers leave the product team only with a person's yes.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. Where does product usage data live, and can I read it? Sets the source, or makes the first result a gap list.
2. What counts as active and as activated here? Every funnel and cohort is built on these.
3. Which recent launches should I track, and when did each ship? The first readout covers what people ask about.
4. Are experiments running now, and what metric was each meant to move? Results are judged against the plan.
5. When should the readout land, and who reads it? (Default: Wednesdays at 09:00, the Head of Product.) Sets the routine.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/definitions.md` (each definition as a rule and its query) and `knowledge/launches.md` as present-tense statements.

## 5. Produce the first result now

Follow `playbooks/weekly-usage-readout.md` on the real data. Attach the readout to the task, labelled "First draft, not yet reviewed". With no readable data, attach `knowledge/tracking-gaps.md` instead.

## 6. Propose the routine and wait

Say: "If this is useful, I will write this readout every Wednesday at 09:00. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
