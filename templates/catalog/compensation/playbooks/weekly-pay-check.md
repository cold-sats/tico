# Weekly offer and pay change check

Schedule: Wednesdays at 11:00 team time (routine `weekly-pay-check`), after setup. Budget 30 minutes. The outcome is a counts-only page and a person-level attachment for the owners: every proposed offer and pay change placed in its band, and open roles missing a range.

---

## 1. Read where things stand

    hub task show <id>
    hub task list --status open --status doing --status waiting

Then `knowledge/bands.md`, `knowledge/philosophy.md` and last week's page. Collect this week's proposed
offers and pay changes from the tasks and their attachments.

## 2. Place each one

For each proposal: role family, level, location rule, the band (minimum, midpoint, maximum), the proposed
figure, the compa-ratio, and where the nearest peers in the same role and level sit (references only).
Mark: in band, below minimum, above maximum, or no band.

## 3. Open roles

Every open role with a job post due or published: does it have a band, and has a sourced range gone
into the post? A post due without a sourced range is flagged for the Recruiter and the owners.

## 4. Write the attachment

Person-level detail (references, figures, compa-ratios) goes into one file attached with
`hub task attach <id> <file>` for the owners named in `state.md`. Delete the local file.

## 5. Write the page and hand over

Write `reports/YYYY-MM-DD-pay-check.md` with counts only, in the shape of `knowledge/examples/pay-check.md`,
then `hub file publish reports/YYYY-MM-DD-pay-check.md --scope task --task <id>`. Delete the exports,
commit, and `hub task update <id> --status done --note`.

## When a source fails

A proposal without a level or location is "cannot place" with the missing field; never guess the level.
