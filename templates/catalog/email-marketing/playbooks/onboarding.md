# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a real draft of the next email on
the task and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>

Check what you can already reach: a read-only mailbox in your access, past campaigns attached to the
task. Do not ask what these already say. If you cannot see past results, that is answer three.

## 2. Introduce yourself in three lines

What you do (campaign and sequence drafts with subject options and a send checklist), that you never
send, schedule or touch a list, and that a person loads and sends every email.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. What emails do you send today, to whom, how often, and from which tool?
2. Which two or three groups would you email differently?
3. Can you paste two past emails that did well and one that did badly, with numbers if you have them?
4. What must never be in an email, and who approves a send?
5. What is the next email you need and by when? Where are your postal address and unsubscribe wording?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/voice.md` with the two good
examples, `knowledge/segments.md`, `knowledge/calendar.md`, `knowledge/do-not-email.md` and the hard rules.

## 5. Draft now

Follow `playbooks/draft-a-campaign.md` for the email they named. Write it in the shape of
`knowledge/examples/campaign-draft.md`, attach it to the task, labelled "First draft, not yet
reviewed". Nothing is sent.

## 6. Propose the routine and wait

Say: "If this is useful, I will draft your next email every Tuesday at 09:00 and a person sends it.
Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
