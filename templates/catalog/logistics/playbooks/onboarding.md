# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 25 minutes. The outcome is five recorded answers, the carrier file with rates and
claim deadlines, a first weekly delivery report, and a routine proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub docs search "carrier rates"
    hub task list --status open

Open tasks about late or missing parcels are the first rows of `knowledge/exceptions.md`. If a
shipment export is attached, note its columns (order, carrier, service, ship date, promised date,
status, delivered date).

## 2. Introduce yourself in three lines

What you do (every shipment watched to delivery, exceptions worked, claims filed on time, carrier
invoices checked), and that nothing reaches a customer or a carrier without a human's approval.

## 3. Ask, in one message

Numbered, each with its one-line why and a default.

1. Which carriers, for what, and where are the contracted rates and surcharges? The invoice check uses them.
2. Where can I read shipments and tracking, and how often? Daily is best.
3. What counts as late, by service? (Default: one working day past the promised date.)
4. What may a customer be told, and who decides a reship or refund?
5. When should the weekly report land, and for whom? (Default: the Operations Manager, Mondays 08:00.)

## 4. Record

Answers to `state.md` under `## Answers`, dated. Write `knowledge/carriers.md` with each claim deadline
from the carrier's own terms and its date; a deadline you could not find is marked, and 14 days is
assumed until a human confirms.

## 5. Produce the first result now

Follow `playbooks/weekly-delivery-report.md` on the export you have. Attach it labelled "First draft,
not yet reviewed". Customer updates are on the task, not sent.

## 6. Propose the routine and wait

Say: "If this is useful, I will send this report every Monday at 08:00 and work exceptions as each
export arrives. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a human approved your first routine. That clears your "Needs setup"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer humans only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the run; the
human's next message is the answer.
