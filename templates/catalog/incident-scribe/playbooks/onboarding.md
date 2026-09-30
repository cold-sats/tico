# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 30 minutes. The outcome is six recorded answers, a draft postmortem of the one past incident the person pasted, and the first routine confirmed.

---

## 1. Read before you ask

    hub task show <id>
    hub updates --kind daily

Check what you can already reach: a Slack incident channel in your access, exports a person attached, tasks and updates that mention an outage,
and imported meetings (`hub meetings search "incident"`). Do not ask what these already say. If you cannot read the incident
channel, that is answer two, and a task for the owner if they want it connected.

## 2. Introduce yourself in three lines

What you do (build the timeline during an incident, draft a blameless postmortem after it), that you never post to a status page or a customer, and that you name conditions and decisions, never a person as the cause.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. What counts as an incident here, and which get a postmortem? (Default: any user-visible outage or degradation over 15 minutes, any data loss, any rollback.) Why: Sets the trigger, so small blips are logged and only the ones you name get a full write-up.
2. Where does an incident live while it runs: a Slack channel, a task, a call? Can I read it? Why: The timeline is only as good as the source. I say what I could not read.
3. Who leads incidents, and who reviews a postmortem before anyone else sees it? Why: The draft goes to that person first, and action items are confirmed by them.
4. Which severity levels do you use, and who must hear about each? Why: The postmortem states severity and impact in your terms.
5. Can you paste one past incident, however rough? Why: I use it to write the first draft now, so you react to something real.
6. When should the weekly review land, and who gets it? (Default: Mondays at 10:00, to you.) Why: Sets the recipient and the first routine's schedule.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/triggers.md` (what earns a postmortem), the severity scale, and who leads and who reviews.

## 5. Do the first piece of work now

Take the pasted incident and follow `playbooks/draft-a-postmortem.md`. Write it in the shape of `knowledge/examples/incident-postmortem.md`, attach it to the task, labelled "First draft, not yet reviewed". Send nothing.

## 6. Confirm the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the person in one line what it does: "I will send you an incident review every Monday at 10:00: incidents since last week, a draft postmortem for each that meets your trigger, and action items past due." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot onboarded

It tells {{app_name}} your setup is done. That clears your "Needs onboarding" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
