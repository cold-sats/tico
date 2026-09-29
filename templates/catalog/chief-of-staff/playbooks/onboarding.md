# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 15 minutes. The outcome is six recorded answers, one real draft brief on the task,
and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub goals --all
    hub org
    hub task list --status open --status doing --status waiting

Do not ask what these already say. If there are no goals at all, say so, and in step 4 propose three
drawn from the open tasks and updates instead of asking the person to invent them.

## 2. Introduce yourself in three lines

What you do (a weekly brief, stalled-goal follow-up, Monday's agenda), that you only read what is
in {{app_name}}, and that nothing reaches anyone but the person until they approve it.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer the default so a person can answer "fine".

1. Who is the brief for, and which day and hour? (Default: the owner, Fridays 15:00.) It sets the
   recipient and the schedule.
2. Which three goals matter most this quarter? (Or: "they are under Goals".) The brief measures
   progress against them.
3. After how many days without a change is a goal or task stalled? (Default 10 and 7.) It sets the
   stalled list.
4. Who may you nudge about a stalled item, and should each nudge come to the person first?
   Nudges are messages to people, so each stays a draft until approved.
5. Which meeting is Monday's agenda for, who attends, how long? It sets how many items fit.
6. Is anything off limits for the brief: people matters, pay, legal? It becomes the exclusion list.

If the person answers only some, record those and proceed with the defaults for the rest, saying
which defaults you used.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Put the recipient, threshold and
exclusions in `knowledge/rhythm.md` as present-tense rules.

## 5. Produce the first brief now

Follow `playbooks/weekly-company-brief.md` on the real data, write `reports/YYYY-MM-DD-weekly-brief.md`,
and attach it to the task. It is a draft: label it "First draft, not yet reviewed". A first result
the person can correct is the point of this session.

## 6. Propose the routine and wait

Say: "If this is useful, I will send you this every Friday at 15:00. Say yes and I will switch it
on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a change,
adjust `knowledge/rhythm.md` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
