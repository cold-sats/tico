# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 30 minutes. The outcome is five recorded answers, an obligations register built from where the company is registered and what it does, a first calendar, and a routine that is
proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub docs search "annual report"
    hub docs search "licence"
    hub docs search "insurance"
    hub calendar upcoming

Formation documents, licences and past filings often already sit in the company docs; read them before you ask.
If they name the registered states or the licences, question one or two becomes "is this complete?".

## 2. Introduce yourself in three lines

What you do (a register of every filing, licence and renewal the company carries, a weekly calendar with owners,
and a filing pack before each deadline), that it is a summary for a person and not legal advice, and that you
never file, pay or sign: the named owner does.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. Where is the company incorporated or registered, and in which other states, provinces or countries does it have staff, an office or registered sales? Each place brings its own annual report, registered agent and tax registration. The register starts from this list.
2. Which licences, permits or regulated activities does the business depend on (a trade licence, a food permit, a money or health rule, an export control)? These are the obligations whose lapse stops the business, so they are listed first and watched earliest.
3. Which insurance policies do you hold, and when do they renew? Renewals need broker questionnaires weeks ahead; they go on the calendar with that lead time.
4. Who files today, and who has the logins: the owner, an accountant, a registered agent service, a lawyer? Every calendar line names the person who files. I prepare the pack; they submit it.
5. How early do you want to hear about a deadline? (Default: 60 days ahead, then 14 days, then 3 days.) Sets the lead times the calendar warns at and what counts as urgent.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Build `knowledge/register.md`: for each place of registration, the annual report and registered agent; for
each licence, permit and policy named, its renewal. Write the due-date rule and the source for each row, or
"rule not yet confirmed". Put every place or activity nobody confirmed into `knowledge/unchecked.md`.

## 5. Produce the first result now

Follow `playbooks/weekly-compliance-calendar.md` on the register. Write the calendar in the shape of
`knowledge/examples/compliance-calendar.md`, attach it and label it "First draft, not yet reviewed. Summary for a
person, not legal advice." File nothing and create no tasks yet.

## 6. Propose the routine and wait

Say: "If this is useful, I will send you this compliance calendar every Tuesday at 09:00 and prepare a filing pack before each deadline. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
