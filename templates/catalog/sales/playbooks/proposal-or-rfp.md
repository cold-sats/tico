# Proposal, RFP or questionnaire

Triggered by a task that names a deal and asks for a proposal, a quote, an RFP response or a security
questionnaire. Budget 60 minutes for a proposal, 90 for fifty questions. The outcome is a finished document
with a gap list on top. Prices, terms and unapproved answers are gaps with an owner; nothing leaves unapproved.

---

## 1. Read the request and the deal

    hub task show <id>

Read `knowledge/deals/<deal>.md` and the discovery call. Note the deadline, the required format and who
signs off internally. If there is no call and no note, ask once with `hub task ask <id>` for the buyer's
three priorities.

## 2. A proposal

Pick two or three win themes that answer the buyer's quoted problem, each with its proof from
`knowledge/proof.md`. Follow `knowledge/proposal-structure.md`; the default order is summary, problem,
solution, scope in and out, timeline as phases, options (three where pricing allows), terms, proof, next
step. Reuse approved text from `knowledge/library/`, adapted to the buyer's words. Write the summary last:
one page, every sentence serving a win theme.

## 3. An RFP or questionnaire

Sort the questions (product, commercial, security, legal, compliance, references). For each, search
`knowledge/library/` and `hub doc ask`. A match under twelve months old is **reused**; one needing change is
**adapted**; no match is **new**, and a new security, legal or compliance answer is not drafted: it is
`[owner: <name>]`. Technical depth goes to `sales-engineer` as a sub-task if the team has one.

## 4. Gaps

Every price, discount, term, date and service level is `[price: <owner>]`, `[start date: <owner>]`. Put the
gap list at the top: the gap, the human, the day it is needed by.

## 5. Hand over

Write `reports/YYYY-MM-DD-<deal>-proposal.md` (or `-rfp.md`), `hub file publish` it and attach it. Once the
owner fills the gaps and approves, request `hub approval request --kind send` with the final file and
recipient. Add each newly approved answer to `knowledge/library/` with its owner and date.
`hub task update <id> --status done --note`: counts reused, adapted, new; open gaps and owners.
