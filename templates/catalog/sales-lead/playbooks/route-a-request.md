# Route a request

Triggered by a task that names a lead, an account or a request and asks who should take it. Budget 10
minutes. The outcome is one routing proposal with its reason. Nothing is assigned until a human says yes.

---

## 1. Read the request

    hub task show <id>

Find what it is: a net-new lead, an existing account, a data problem, a proposal, a renewal or
something for a human only. Look the account up in `knowledge/pipeline-rules.md`'s pipeline source and
in `hub meeting search "<account>"` so you do not route a customer as a lead.

## 2. Pick the owner

Use `knowledge/routing.md` first. Otherwise: net-new lead to `sdr-research`; open deal, follow-up,
proposal, quote or questionnaire to `sales`; renewal or expansion to `account-manager`; stale or
duplicate data, forecast or routing rules to `sales-ops`; technical question or proof of concept to
`sales-engineer`; partner-sourced deal to `partnerships`; health problem to `customer-success`. If the deal is in a live
negotiation, or the prospect replied or asked about price, it belongs to a human: name them.

## 3. Propose

On the task, in three lines: the owner, the reason, and what the owner should produce and by when. Ask
once with `hub task ask <id>`: "Route this to <owner>?" and stop.

## 4. On a yes

    hub task create --owner <slug> --title "<what and for whom>" --body "<the request, the account, the source>" --parent <id>

Record the routing and who approved it in `knowledge/routing.md`. On a no, record the correction as a
rule in `knowledge/routing.md` so the next proposal is right. `hub task update <id> --status done --note`.
