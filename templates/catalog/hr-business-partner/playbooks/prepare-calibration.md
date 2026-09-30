# Prepare calibration

Triggered by a task from the HR owner once manager ratings are in. Budget 45 minutes. The outcome is a
calibration sheet the facilitator can run a session from, attached to the task for the HR owner only.
You flag inconsistencies; the managers and the HR owner decide.

---

## 1. Read the definitions first

`knowledge/rating-scale.md` and the level expectations (`hub doc ask "What do our level expectations
say for <level>?"`). If the scale has no written meaning per point, say so on the task: calibration
without definitions is an argument.

## 2. Build the grid

From the ratings the HR owner attached: reference, team, level, manager, rating, and whether the review
cites evidence (yes, partly, no). No names beyond references, no pay, no tenure notes, nothing about
leave or health.

## 3. Find what to discuss

- Spread per team and level against the company as a whole; a team far above or below is a question
  for its manager, not a correction.
- Ratings at either end of the scale with no evidence cited.
- Two reviews with the same rating described very differently, or different ratings described alike.
- Wording about personality or style rather than work and its effect.
- People on leave for part of the cycle, marked for the facilitator to handle with the policy.
Five to ten discussion items, most consequential first.

## 4. Write the sheet

A one-page summary (spread, items to discuss, the definitions) and the grid as an appendix. Attach it
with `hub task attach <id> <file>` and delete the local copy. Nothing goes into `knowledge/` or `reports/`.

## 5. After the session

Record in `knowledge/review-cycle.md` only process lessons (which definition caused debate, which phase
ran late), never an outcome about a person. `hub task update <id> --status done --note`.
