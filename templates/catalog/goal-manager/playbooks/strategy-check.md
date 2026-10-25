# Strategy check

**Not yet on.** This is the playbook for the `strategy-check` routine, declared in `bot.yaml` with `enabled: false`.
It stays off until the owner turns it on (`hub routine update <id> --enable`, or Resume on the Routines card); the
server never arms it, and you never do. If it fires while off, or the owner runs it by hand before they mean to, end
with one line saying the strategy check is not on yet and nothing was filed.

When it is on: monthly, on the first, after the KPI pass. One pass over the active choices against the evidence
that has come in since the last check, then one short report. Nothing here edits the strategy or a goal: a
contradiction is a proposal the owner confirms. Budget 20 minutes.

**Never invent a number.** Evidence is a market page, a market delta row or a KPI reading you read this run, cited.
A feeling that a choice is wrong is not evidence; leave it out.

---

## 1. Read the record

- `hub strategy show`: the current version and its choices with status `active`, each with its `why`, `rules_out`
  and `goals_by_choice`. No published version: end with one line saying so; there is nothing to check a draft
  against.
- `hub market delta`: what changed in the market since the last check (new competitors, a price move, a segment
  that grew or shrank, a rule), grouped by entity. Read the Theses page too (`hub doc search --market theses`).
- `hub goal list --all`: every live goal, its colour, its reason line and its `choice_id`.
- The latest readings on the KPIs those goals carry: `hub kpi show <id>` for each KPI on a goal that serves a choice.
- `hub proposal list`: a pending `strategy_draft` proposal about a choice means you already said this; do not say it
  again.

## 2. Compare each active choice with the evidence

For each choice, in the version's order, answer three questions from the record and write one line each:

1. **Does the market still support it?** A delta row or a thesis that contradicts the choice's `why` (the segment it
   bets on is shrinking by a cited figure; the price point it bets on is now matched by a core competitor) is a
   contradiction. A row that merely mentions the same topic is not.
2. **Is it paying off?** The colours of its goals: all green or no data is "no signal"; a red goal whose KPI measures
   the choice itself (not a side effect) for two periods is a contradiction.
3. **Does anything serve it?** A choice with no live goal has no way to show whether it is paying off.

A choice with no contradiction and at least one goal is fine; say so in one line and move on.

## 3. File proposals, not edits

One proposal per finding, each with the evidence in its reason, and never a second about the same choice while one
is pending:

- **Evidence contradicts a choice**: a `strategy_draft` proposal that rewords, re-justifies or retires the choice,
  payload `{"choices": [{"id": "<choice id>", "status": "retired"}]}` or `{"choices": [{"id": "...", "why": "..."}]}`,
  reason: the delta row or reading, with its date, and what it contradicts. You do not retire or reword the choice
  yourself at any level: a check is a proposal, and the owner decides.
- **A choice has no goal**: one line in the report naming the choice and the goal you would propose (title, owner,
  the KPI that would measure it). Above Passive, also one card to the owner with that goal for them to accept,
  `choice_id` set (`playbooks/goals-make-sense.md`, "Choices"). Never create a team goal yourself.
- **A goal serves a retired choice**: one line in the report; its owner decides what to do with it.

Read `asked_today` in `hub goal ceo-bot` first: the proposals count toward the owner's 5 a day, so the most
consequential contradiction goes first and the rest wait for next month.

## 4. Report

One message to the owner, in their chat, under 150 words, facts first:

1. **Contradicted**: each choice with evidence against it, the evidence in one line, and the proposal you filed.
2. **No goal**: each active choice nothing serves.
3. **Fine**: how many choices had no contradiction and at least one goal.
4. One line: that each proposal waits in Needs you, and that the strategy changes only when they publish a version.

Say plainly when nothing needs attention. Rewrite `state.md` with the date of this check and the delta you read up
to, so next month starts there, and commit this repository.
