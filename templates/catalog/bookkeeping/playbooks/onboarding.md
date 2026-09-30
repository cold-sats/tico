# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 25 minutes. The outcome is six recorded answers, a real close status drafted from an
export, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>

Check what you already have: an export attached to the task, files in a docs folder the human
named, receipts in a mailbox in your access. Do not ask for what these already show. If you cannot
read any transactions, that is answer two.

## 2. Introduce yourself in three lines

What you do (propose categories, keep the close checklist, draft the monthly status), that you only
read the books and never post, reconcile, pay or give tax advice, and that a human approves every
message and entry.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine".

1. Which accounting system are the books in, and who keeps them?
2. How will you get me the transactions (weekly export, bank and card CSVs, read-only access)? Can you
   attach last month now?
3. Please paste the chart of accounts and any category rules you already use.
4. On which day should the close checklist start, and when should the status reach you? (Default: the
   1st, status by the 5th.)
5. Above what amount, or for which kinds of item, must I always ask first?
6. Where do receipts live, and how many days does the owner need to answer a question? (Default: two.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/categories.md` from the chart
and rules, and `knowledge/close-checklist.md` from `playbooks/monthly-close-checklist.md`, marking who
does each line. Never write an account number or credential into either file.

## 5. Work the export now

Follow `playbooks/categorize-transactions.md` on the export, then draft the status in the shape of
`knowledge/examples/close-status.md`, labelled "First draft, not yet reviewed". Attach it to the task.
Nothing is posted and nobody but the requester sees it.

## 6. Propose the routine and wait

Say: "If this is useful, I will draft the close status on the 1st of every month, and a human makes every
entry. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a human approved your first routine. That clears your "Needs setup"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer humans only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the run; the
human's next message is the answer.
