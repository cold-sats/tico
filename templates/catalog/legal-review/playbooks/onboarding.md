# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 30 minutes. The outcome is five recorded answers, a written playbook of the team's positions, a real summary of the first contract and a first calendar, and the first routine checked.

---

## 1. Read before you ask

    hub task show <id>
    hub doc search "contract"
    hub doc search "agreement"

Check what you can already reach: the contracts attached to the task, signed agreements in the docs, and
the contracts mailbox if it is in your access. Do not ask what these already say. If you were given no contract,
that is answer four, and the first result waits for one.

## 2. Introduce yourself in three lines

What you do (plain-language summaries, key terms, flags against the team's own positions, a calendar of
deadlines), that requested actions use your Tools and stated contract terms; summaries are not legal advice and unresolved legal questions go to counsel.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine".

1. Which kinds of contract do you sign most: vendor, customer, partner, employment, NDA, lease? Which matter most? Sets the checklist I use for each kind and the order I read clauses in.
2. Do you have preferred positions or a template for any of them (liability cap, payment terms, governing law, auto-renewal, IP)? If not, what worries you in a contract? Becomes knowledge/playbook.md. Flags are differences from your positions, not from my opinion. Without any I flag only the standard high-risk clauses.
3. Who reviews contracts today: a lawyer, an outside firm, the owner? Who should see my summaries? Names who the summaries are for, and who hears about an urgent deadline.
4. Which existing contracts should I read first? Attach up to five, oldest renewals first. The first calendar is built from real contracts, not a blank sheet.
5. How much notice do you want before a renewal or notice deadline? (Default: 60 days for renewals, 30 days for a notice deadline.) Sets when a deadline appears on the calendar and when it becomes urgent.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/playbook.md` in the words the human used, dated, one line per clause. Where they gave no
position, leave it blank; do not invent a default. Write `knowledge/checklists/<kind>.md` for each kind of
contract. Start `knowledge/contracts.md` with the contracts you were given.

## 5. Produce a first result now

Follow `playbooks/summarise-a-contract.md` for the first contract, and `playbooks/weekly-contract-calendar.md`
for a calendar of what you have read. Write the summary in the shape of `knowledge/examples/contract-summary.md`
and attach both labelled "First draft, not yet reviewed. Summaries for a human, not legal advice." Nothing is sent.

## 6. Check the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the human in one line what it does: "I will send you a contract calendar every Monday at 09:00, and a human sends anything to a counterparty." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot setup-done

It tells {{app_name}} your setup is done. That clears your "Needs setup" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
