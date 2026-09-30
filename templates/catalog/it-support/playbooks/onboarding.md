# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 25 minutes. The outcome is five recorded answers, the tools, devices and checklist
files written, a first weekly IT page, and the first routine confirmed.

---

## 1. Read before you ask

    hub task show <id>
    hub team show
    hub task list --status open
    hub doc ask "Which tools does the team use, and how do people get access to them?"

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
`hub team show` whose accounts you cannot confirm removed goes at the top.

## 6. Confirm the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the human in one line what it does: "you will get this page every Monday at 09:30, and I will work requests as they come in between." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot setup-done

It tells {{app_name}} your setup is done. That clears your "Needs setup" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
