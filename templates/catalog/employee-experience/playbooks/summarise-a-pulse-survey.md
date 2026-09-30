# Summarise a pulse survey

Triggered by a task with a survey results export. Budget 40 minutes. The outcome is a two-page readout
for the owner: participation, what changed, themes, and two or three actions with owners. It is
shared further only after approval.

---

## 1. Check the export before reading it

Response count per group. Every group below the threshold in `knowledge/survey.md` (default five) is
merged into the next level up or shown as "not shown". If the export has individual rows, work from it
without saving it to the repository, and never look for who wrote what.

## 2. Participation

Overall and per group above threshold, against last quarter. Low participation in one group is itself
a finding.

## 3. Scores and trends

Per question: this quarter, last quarter, the change. Only identical questions are compared. The two
biggest rises and the two biggest falls go first. Small changes (within a few points) are noise, and say so.

## 4. Themes from comments

Read every comment. Group them into four to seven themes, each with a count and the groups it came from
(above threshold). Quote only comments that identify nobody; paraphrase the rest. A comment about
harassment, safety, discrimination or someone at risk is not a theme: hand it, untouched, to the named
human in `state.md` today.

## 5. Actions

Propose two or three actions, each tied to a finding, with a suggested owner, a date and one line on
what employees will be told. Open with last quarter's actions and whether they happened.

## 6. Hand over

Write `reports/YYYY-MM-DD-pulse-readout.md`, attach it to the task, and ask the owner with
`hub task ask <id>` whether to share it and with whom. Add the approved actions to `knowledge/actions.md`.
Delete the export from the working tree.
