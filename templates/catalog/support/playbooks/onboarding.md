# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 20 minutes. The outcome is six recorded answers, a draft digest of the queue as it is
now, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub task list
    hub org

Note what is already here: tickets as tasks, who the approver could be, who owns product. Do not ask
what this already says. Check whether you can read mail at all (`$HUB_DIR/scripts/mail.sh whoami`); if
you cannot, that is answer one and a task for the owner, not something to work around.

## 2. Introduce yourself in three lines

What you do (triage, drafts, standing answers, product issues), that you never reply to a customer or
change the support tool, and that nothing leaves until a person approves it.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. Where does support arrive: a support mailbox, mail forwarded to you, a Slack channel, a ticket
   tool? It sets the intake, and you can only triage what you can read.
2. Who approves your drafts, and who covers when they are away?
3. What may a customer be told without a person deciding (refund windows, plan limits, response times),
   and where is it written? These become standing answers.
4. What must reach a person immediately (refund, legal threat, outage, security, an angry customer),
   and who?
5. How should replies sound? Ask for two replies they were happy with.
6. Who owns fixing product problems?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write the standing answers to
`knowledge/answers.md` (each with its source and today's date), the immediate list to
`knowledge/escalation.md`, and the voice to `knowledge/voice.md`.

## 5. Triage the queue now

Follow `playbooks/daily-support-triage.md` on what is in the queue, in the shape of
`knowledge/examples/triage-digest.md`. If the queue is empty or unreadable, say which, and use the
three most recent resolved tickets the person points you to as practice. Attach the digest to the
task, labelled "First draft, not yet reviewed". Reply to nobody.

## 6. Propose the routine and wait

Say: "If this is useful, I will send you a triage digest every weekday at 09:00 and never reply to
anyone myself. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.
