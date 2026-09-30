# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is six recorded answers, one real digest on the task and a
routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub market show          # only if the company has a market page

Note which competitors the market graph already names. Do not ask what it already answers.

## 2. Introduce yourself in three lines

What you do (the social calendar with every post written, and a short digest of public mentions,
questions and competitor moves), that nothing is posted or replied to without a person's approval of
the exact text, and that you never follow, message or sign in anywhere.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. What names should I listen for, including misspellings?
2. Which three to five companies are you compared with in public?
3. Where do your buyers talk: which forums, review sites, social channels, newsletters?
4. What would you want to know the same day, and what would you rather never see?
5. Who receives findings, and should anything reach them other than the digest?
6. Which accounts do you post from, how often on each, and who approves a post before it goes out?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/watchlist.md` (names,
queries with exclusions, sources), `knowledge/sources.md` and `knowledge/social-calendar.md`
(accounts, cadence, approver).

## 5. Sweep now

Follow `playbooks/weekday-sweep.md` once. Write the digest in the shape of
`knowledge/examples/sweep-digest.md` and attach it to the task, labelled "First draft, not yet
reviewed". Create no child tasks yet: list what you would create.

## 6. Propose the routine and wait

Say: "If this is useful, I will sweep every weekday at 08:00 and send you one short digest. Quiet days
are one line. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
