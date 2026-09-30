# On-call handoff

Triggered by a task at a rotation change ("handoff from Omar to Lena") or by a human asking for one. Budget
20 minutes. The outcome is one page the incoming person reads before their first page arrives. You page,
silence and change nothing.

---

## 1. Read the shift

    hub task show <id>
    hub task list --status open --status doing --status waiting

Then `knowledge/actions.md`, this week's incident files in `reports/incidents/`, and any alert or error
source named in `knowledge/triggers.md` that you can read (a channel, an attached export). Note the shift's dates.

## 2. Write the handoff

- **Open now:** incidents not resolved, with severity, status and the next step.
- **Watch:** alerts that fired more than twice without action (noise to tune, a proposal for the owner), and
  anything degraded but not paging.
- **Changes landing this week:** releases and migrations from the Release Manager's readiness checklist, with
  their rollback note.
- **Action items due** during the shift, with owners.
- **Could not read:** any source you lacked.

One line each, with the link and the date. Blameless: describe systems and events, never a person's fault.

## 3. Hand over

Write `reports/oncall/YYYY-MM-DD-handoff.md`, attach it, `hub files publish` it, commit, and
`hub task update <id> --status done --note` with the count of open incidents in the first line.
