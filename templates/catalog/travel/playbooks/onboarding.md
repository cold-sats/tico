# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 20 minutes. The outcome is five recorded answers, the travel policy written down, a
first weekly trips page, and a routine proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub doc search "travel policy"
    hub task list --status open
    hub calendar list

Trips already mentioned in tasks or on calendars are the first rows of `knowledge/trips.md`.

## 2. Introduce yourself in three lines

What you do (trip plans within policy, bookings prepared for approval, itineraries, the trips
calendar), that you never book or pay, and that you never keep passport or card numbers.

## 3. Ask, in one message

Numbered, each with its one-line why and a default.

1. Do you have a travel policy? If not: class of travel, hotel limit per city, how far ahead to book. Every option is checked against it.
2. Who approves a trip, and does the amount change who? (Default: the manager; above 2,000, the Operations Manager.)
3. How do you book today: a tool, an agent, or each person? Sets where an approved booking goes.
4. Which cities and events come up most; any preferred airlines or hotels? Preferred options go first when close.
5. When should the weekly trips page land, and for whom? (Default: the Operations Manager, Mondays 10:00.)

## 4. Record

Answers to `state.md` under `## Answers`, dated. Write `knowledge/policy.md`; with no written policy,
write the answers as the working policy and mark it "working policy, not approved" until the owner
says otherwise. Default advance-booking rule if none is given: 14 days domestic, 21 international.

## 5. Produce the first result now

Follow `playbooks/weekly-trips-page.md`. If a trip is already requested, plan it with
`playbooks/plan-a-trip.md` too. Attach both labelled "First draft, not yet reviewed". Book nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will send this page every Monday at 10:00 and plan each trip as it is
requested. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
