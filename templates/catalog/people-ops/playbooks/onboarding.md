# Setup

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a base offboarding checklist, the systems and access owners list, a letter template, and a first checklist or records audit, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub org
    hub docs ask "What does our handbook say happens when someone leaves?"

Check the roster, anyone with a last day on the open tasks, and whether exports are attached. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (offboarding checklists and the access check, the records audit, employment letters and verifications), that you never remove access, change a system or sign anything, and that every letter and assignment waits for a human's yes.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine". If the human
answers only some, record those and use the defaults for the rest, saying which you used.

1. What has to happen when someone leaves today: which systems, which equipment, who handles payroll's final pay, is there an exit interview? Becomes the base offboarding checklist with an owner per item.
2. Who removes access (IT, an office manager, a founder), and who holds admin rights to the systems with team data? Access items go to the people who can remove them; privileged access is first.
3. Where do HR records live (an HR system, a spreadsheet) and can you give me an export and a payroll export to compare? Sets the records audit. I read exports; I never edit the system.
4. Which letters do people ask for (employment confirmation, salary letters, references), and who signs them? Paste a template if you have one. Becomes the letter templates and the signer for each.
5. Which day should the weekly records check land, and for whom? (Default: Mondays 10:00, the HR owner.) Sets the routine and its only readers.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/offboarding-base.md`, `knowledge/systems.md` (privileged systems first, with who removes access) and `knowledge/letters/<type>.md` for the first letter type. Start `knowledge/leavers.md` with references only.

## 5. Produce the first result now

Follow `playbooks/offboard-a-leaver.md` for the next leaver, or `playbooks/weekly-records-check.md` on the exports given, and write the result in the shape of `knowledge/examples/records-check.md`. Create no tasks and send nothing. Label it "First draft, not yet reviewed" and attach it to the task.

## 6. Propose the routine and wait

Say: "If this is useful, I will run this check every Monday at 10:00 for the HR owner only. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a human approved your first routine. That clears your "Needs setup"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer humans only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the run; the
human's next message is the answer.
