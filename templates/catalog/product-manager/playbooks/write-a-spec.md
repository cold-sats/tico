# Write a spec

Triggered by a task that names a problem the Head of Product or the owner has chosen. Budget 45 minutes
for a first version. The outcome is `specs/<slug>.md` that an engineer can estimate from, with every open
question assigned. Nothing is filed in GitHub.

---

## 1. Confirm it was chosen

    hub task show <id>

Check `hub goals` and the Head of Product's decision log for the decision. If nobody decided it, say so on
the task and ask who did; a spec is not a way to decide by stealth.

## 2. Gather the evidence

Read the latest `feedback-analyst` report for the theme and its count, the `product-researcher`
snapshots and opportunity map, `product-analyst`'s numbers for the area, and `hub meetings search
"<feature>"` for what customers and the team said. Quote sparingly, with source and date.

## 3. Write the core page

In the order of `knowledge/spec-format.md`:
- **Problem**: who, trying to do what, what it costs them today. Two or three sentences.
- **Evidence**: three to five lines, each with its source and count.
- **Goal**: the goal in Tico it moves, and what we would expect to see if it works.
- **Scope** and **Non-goals**: bullets. Every non-goal is something someone might reasonably assume.
- **Acceptance criteria**: Given/When/Then, one behaviour each, including the edge cases (empty, full,
  permission denied, offline, time zones).
- **Open questions**: each with the person who owes the answer and a date.
- **Risks**: what could make this the wrong bet, and the cheapest check.

## 4. Check it with the builders' eyes

Read it as the engineer: can each criterion be tested? Is anything ambiguous ("quickly", "simple")? Is
there a dependency on another team? Fix those before handing over.

## 5. Hand over

Publish with `hub files publish specs/<slug>.md --task <id>`. List the issues you would file (title and
body) on the task for a person, and the questions for the owners. `hub task update <id> --status done
--note`: the problem in one line, the path, open questions and who owes them.
