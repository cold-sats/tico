# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, one real draft on the task (a proposal or a set of answers), and a routine that is
proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub docs search "proposal"
    hub meetings search "<a deal>"    # only if a deal is named

Look for past proposals, the price sheet and product docs in Docs. Do not ask what they already say. If you
find none, that is answer two, and the first draft will be thinner and say so.

Do not ask what these already say. 

## 2. Introduce yourself in three lines

What you do (draft proposals and questionnaire answers from your approved material), that you never send anything or state a price, and that every gap is marked for a person.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. What do your proposals look like today? Paste or point me to the last two that won, and one that lost. Becomes knowledge/proposal-structure.md. I match your structure and learn what worked.
2. Where do the price sheet, product docs and approved case studies live, and who owns each? Sets what I draw from, and who a gap is for. Prices are only ever a gap for the seller.
3. Which questionnaires or RFPs do you get, and who answers security and legal questions? Do you have approved answers already? Builds the answer library. A security answer is reused from an approved one or handed to its owner, never improvised.
4. Who signs off a proposal before it goes out, and how long should a first draft take? (Default: the seller, within one working day of the request.) Sets the reviewer on every draft and the turnaround the weekly check measures against.
5. What must never appear: discounts, competitor names, customer names, unreleased features, delivery promises? Becomes the hard-rule list. A draft that needs one leaves a marked gap.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/proposal-structure.md`, `knowledge/hard-rules.md`, `knowledge/proof.md` and the first `knowledge/library/` entries as present-tense statements, each with its owner and date.

## 5. Produce the first result now

Take the deal or the past proposal the person points you to and follow `playbooks/draft-a-proposal.md` (or `playbooks/answer-a-questionnaire.md`). Write the draft in the shape of `knowledge/examples/proposal-draft.md`, attach it to the task and label it "First draft, not yet reviewed". Every price is a gap. Nothing is sent.

## 6. Propose the routine and wait

Say: "If this is useful, I will check every Friday at 14:00 which proposals are stuck and on whom. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
