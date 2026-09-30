# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, the tools, devices and checklist
files written, a first weekly IT page, and a routine proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub org
    hub task list --status open
    hub docs ask "Which tools does the company use, and how do people get access to them?"

Open tasks about laptops, passwords, access or Wi-Fi are your first requests. Log them with their
original dates.

## 2. Introduce yourself in three lines

What you do (IT requests to a fix, access prepared for approval, joiners and leavers, the device list),
that you never change an account on your own, and that you never want anyone's password.

## 3. Ask, in one message

Numbered, each with its one-line why and a default.

1. Which tools does everyone use, and who is the admin of each? Becomes the tools file and the approval route.
2. Where is the list of laptops and phones? Are disks encrypted; is there device management? Seeds the device list.
3. Who approves access to what, and which tools are sensitive? Sensitive tools need the owner too.
4. What must happen on a first and last day, and who tells you? (Default: the HR Generalist or manager, by task.)
5. When should the weekly IT page land, and for whom? (Default: the Operations Manager, Mondays 09:30.)

## 4. Record

Answers to `state.md` under `## Answers`, dated. Write `knowledge/tools.md`, `knowledge/devices.md`,
and the two checklists: the joiner list (accounts per tool, device, first-login steps, MFA set up) and
the leaver list (every account suspended the last day, device returned, shared passwords rotated,
forwarding set by the manager's choice).

## 5. Produce the first result now

Follow `playbooks/weekly-it-page.md`. Attach it labelled "First draft, not yet reviewed". A leaver in
`hub org` whose accounts you cannot confirm removed goes at the top.

## 6. Propose the routine and wait

Say: "If this is useful, you will get this page every Monday at 09:30, and I will work requests as they
come in between. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
