# Draft a proposal

Triggered by a task that names a deal and asks for a proposal or a quote. Budget 60 minutes. The outcome
is one draft in the house structure, with a gap list on top. Nothing is sent and no price is stated.

---

## 1. Read the request and the deal

    hub task show <id>

Note the buyer, the deadline and who signs off. Read the deal's history: `hub meetings search "<company>"`,
the transcript of the discovery call, the seller's notes. If the CRM is connected, read it only. If you
have no call and no notes, ask once with `hub task ask <id>` for the buyer's three priorities.

## 2. Write down the buyer's problem in their words

Three to five quotes or paraphrases with the call or note and its date. Pick two or three win themes
that answer them, each with the proof it needs from `knowledge/proof.md`.

## 3. Assemble from the library

Follow `knowledge/proposal-structure.md`. Default order: summary, problem, solution, scope in and out,
timeline as phases, options, terms, who we are (proof), next step. Reuse approved text from
`knowledge/library/` and past wins, and adapt it to the buyer's words; note which sections are reused.

## 4. Handle the gaps

Every price, discount, term, date and service level is a marked gap: `[price: seller]`, `[start date:
seller]`. A security or legal answer without an approved entry is `[owner: <name>]`. Put the gap list
at the top with the person and the day each is needed by.

## 5. Write the summary last

One page: the buyer's problem, the answer, the outcome they can check, and the next step with a
gap for the date. Read it once as the buyer: does every sentence serve a win theme?

## 6. Hand over

Write `reports/YYYY-MM-DD-<client>-proposal.md` in the shape of `knowledge/examples/proposal-draft.md`,
`hub files publish` it, and attach it to the task. Commit and `hub task update <id> --status done --note`:
the gap list and who owns each. The seller adds the numbers and sends it. Never send.
