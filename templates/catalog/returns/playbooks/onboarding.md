# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, the policy turned into checks, the
open requests worked, a first returns report, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub team show
    hub task list --status open --status waiting
    hub doc ask "What is our return and refund policy?"

Collect the open return and refund requests. The policy the Librarian cites, with its date, is the
starting point for question one. Do not ask what these already show.

## 2. Introduce yourself in three lines

What you do (check each return against the policy and the order, prepare the reply and the refund, a
weekly report on why things come back), that a person approves every refund, label and reply, and that
you never refuse what the policy allows.

## 3. Ask, in one message

Numbered, each with its one-line why, offering the defaults.

1. What is the return and refund policy, and where is it written?
2. Where can I read orders?
3. Which returns may I recommend approving without discussion, and which always need a person?
   (Default: over $150, outside the window, or a damage claim need a person.)
4. Who approves refunds and replies, and who issues them in the shop or payment system?
5. When should the weekly report land, and who reads it? (Default: Mondays 09:00, you.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/policy-checks.md`: each
rule as a check, with its source. Start `knowledge/ledger.md` from the open requests.

## 5. Produce the first result now

Run `playbooks/decide-a-return.md` on each open request, then `playbooks/weekly-returns-report.md`.
Label the report "First draft, not yet reviewed". Issue nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will write this report every Monday at 09:00. Say yes and I will switch it
on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot setup-done

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run. Never run it before a yes. If setup began in chat there is no task, so
ask in your reply instead of `hub task ask` and end the turn; the person's next message is the answer.
