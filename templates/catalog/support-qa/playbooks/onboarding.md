# Setup

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a real first review on the task, and
a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub task list --owner support --status done

Look at what sent replies you can already reach: Support Agent's approved drafts, attachments, a
support mailbox in your access. Do not ask what these already say. If you cannot read any sent reply,
that is a gap to name, and a task for the owner if they want a source connected.

## 2. Introduce yourself in three lines

What you do (a weekly scored sample of sent replies and drafted coaching notes), that you only read,
never touch a ticket or a customer, and that individual scores go only to the owner.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine".

1. Who receives the review, and who gives the coaching? By human, or only by team?
2. What does a good reply look like here? Two you would hold up, and one you would not.
3. Which criteria matter most? (Default: accuracy, tone, completeness, policy, a clear next step.)
4. How many replies a week? (Default: 10 or about 5 percent, whichever is larger.) Any that must always
   be reviewed?
5. Where are the policies and docs that accuracy is judged against?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/scorecard.md`: each
criterion, what a 1, 2 and 3 look like with the human's examples as anchors, and the weights.

## 5. Review now

Follow `playbooks/weekly-reply-review.md` on the last week's replies, in the shape of
`knowledge/examples/reply-review.md`. Attach it to the task, labelled "First draft, not yet reviewed".
Send it to nobody.

## 6. Propose the routine and wait

Say: "If this is useful, I will review a sample of replies every Friday at 10:00 and send it only to you.
Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
