# Setup

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first weekly partner review on the
task, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub docs search "partner agreement"
    hub meetings search "partner"

Check which agreements are in the team docs, whether a CRM is in your access, and which partners
appear in recent calls. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (the partner register, registration checks, partner-sourced deals, new partners, fees owed),
that every decision, message and payout waits for a human, and that you apply one rule to every partner.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine".

1. Which partners do you have, of which kind, and where are their agreements?
2. Your rules of engagement: what makes a registration valid, how long it protects, who wins a conflict? (Default: first complete registration wins, 90 days' protection, our seller wins if already engaged.)
3. How are referral fees or margins calculated and paid, and who approves a payout?
4. What makes a good new partner? One you would clone.
5. How do registrations arrive, and who works approved partner deals?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write one `knowledge/partners/<partner>.md` per
partner, `knowledge/rules-of-engagement.md`, `knowledge/partner-fit.md`, and start
`knowledge/registrations.md` with any registration still open.

## 5. Produce the first result now

Follow `playbooks/weekly-partner-review.md`. Write `reports/YYYY-MM-DD-partner-review.md`, attach it to the
task and label it "First draft, not yet reviewed". Nothing is decided, sent or paid.

## 6. Propose the routine and wait

Say: "If this is useful, I will review the partner channel every Thursday at 09:00, with a proposed
decision on each registration. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop.
On a yes:

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
