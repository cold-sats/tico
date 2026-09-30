# Propose a hire

Triggered when the weekly summary finds recurring finance work with no owner, or when the owner asks
"should we add a bot for this?". Budget 15 minutes. The outcome is one proposal on the task, and a
BotOps request only after the owner says yes. You never create a bot.

---

## 1. Establish the gap

List the evidence: the requests or tasks of the same kind in the last 30 days with their dates, how
long each waited, and what slipped because of it (a close day, a late invoice, a missed receipt).
Fewer than three occurrences, or one late week, is not a gap; note it in `memory/learnings.md` and stop.

## 2. Pick the role

    hub template list
    hub team show

Choose the one template in `team_templates` whose card owns that work, and check it is not already in
the company. Examples: invoices issued late or wrong goes to `billing`; bills paid twice or late to
`accounts-payable`; expense reports sitting unreviewed to `expense-auditor`; payroll corrections after
the run to `payroll`; a filing missed or nearly missed to `tax`; deferred revenue done by hand at close
to `revenue-accountant`. Work outside finance goes to that department's head as a note, not a proposal.

## 3. Write the proposal

On the task, five lines:
- **Work**: what recurs, how often.
- **Evidence**: the dated tasks or reports.
- **Role**: the template's name and id.
- **First routine**: its card's `first_routine` title and cadence, and what it would have produced last month.
- **Reports to**: finance-lead.

`hub task ask <id> "Set up the <role>? Its first routine stays off until someone approves its first draft."`

## 4. On the owner's yes

    hub task create --owner botops --title "Set up <template> from the catalog" --body "<the five lines>" --parent <id>

Record the decision in `memory/decisions.md`, add the role to `knowledge/team.md` as "requested", and
route its work to it once it appears in `hub team show`. On a no, record the reason and do not propose the
same role for 60 days unless the evidence doubles.
