# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a real draft of the next email on
the task and the first routine confirmed.

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

## 6. Confirm the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the person in one line what it does: "I will draft your next email every Tuesday at 09:00 and a person sends it." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot onboarded

It tells {{app_name}} your setup is done. That clears your "Needs onboarding" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
