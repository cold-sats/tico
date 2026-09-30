# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 20 minutes. The outcome is five recorded answers, the first convention and handoff
rules, a first check on the task, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub goal list --all
    hub team show

Check whether CRM read access is in your `employee.yaml` and whether an export is attached. Note the
funnel goals the Goal Manager keeps; you measure against them, not beside them.

## 2. Introduce yourself in three lines

What you do (the tracking convention, tagged links for each campaign, the lead handoff rules and a
weekly data check), that you change no system, and that a person applies every fix.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. Where do leads land, and which field says where each came from?
2. Is there a naming convention for campaign links today? May I propose one?
3. What makes a lead ready for sales, who receives it, and how fast should they touch it?
4. Which campaigns are running now, and who owns each?
5. How will analytics and lead exports reach me until read access is connected?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/tracking.md` (propose the
default convention if there is none, marked "proposed"), `knowledge/handoff.md` and
`knowledge/campaigns.md`.

## 5. Produce the first result now

Follow `playbooks/weekly-marketing-data-check.md` on what you can read. Write
`reports/YYYY-MM-DD-marketing-data.md`, attach it to the task and label it "First draft, not yet
reviewed". Put the proposed convention up for the owner's yes in the same message.

## 6. Propose the routine and wait

Say: "If this is useful, I will run this check every Monday at 10:00. Say yes and I will switch it
on." Then `hub task ask <id>` once, and stop. On a yes:

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
