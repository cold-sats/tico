# Write up a meeting

Triggered by the `meeting.ready` routine (one task per imported company meeting, its notes and
transcript in the body), or by a person sending you a meeting. Budget 15 minutes. The outcome is
one report and a task note; nobody is told and nothing is assigned until a person approves.

---

## 1. Decide whether to write it up

    hub task show <id>

Read `knowledge/coverage.md`. If the meeting is outside coverage, on the restricted list, or has a
transcript with nothing readable in it, finish the task with one line that says which and stop. A
skipped meeting is a stated decision, never silence.

## 2. Read it properly

The body has the source's own notes and the transcript. If it is cut off, read the rest:

    hub meeting read <id> --offset <next_offset>

Read the whole transcript. The source's summary is a lead, not a fact: check its decisions against
what was actually said.

## 3. Sort what was said

| Kind | Test | Where it goes |
|---|---|---|
| Decision | Someone proposed it and someone with the authority confirmed it | Decisions, with the reason if given |
| Action item | A named person said "I will", or was asked and agreed, to do a specific thing | Action items |
| Open question | Raised and not answered | Open questions |
| Discussion | Everything else | One or two lines at most, or nothing |

Anything you cannot quote is not a decision and not an action item. Two people agreeing "we should
look at that" is a discussion.

## 4. Check what already exists

    hub task list --owner <person>

If the action item is already a task, link it instead of proposing it again. Search
`knowledge/decision-log.md`: a decision that contradicts an earlier one is shown next to it with both
dates, not resolved by you.

## 5. Write the report

`reports/YYYY-MM-DD-<meeting>.md`, in the shape of `knowledge/examples/meeting-summary.md`:
1. **Headline**: what the meeting decided, one sentence.
2. **Decisions**: one line each, with the speaker and timestamp.
3. **Action items**: a table of action, proposed owner, due date (only if said), quote and timestamp.
   "Owner unclear" is a valid owner.
4. **Open questions** and **What I could not tell** (audio gaps, unidentified speakers).
5. **Sources**: the meeting id, its date and its link.

Under 250 words for the summary part. Append each decision to `knowledge/decision-log.md`.

## 6. Ask once

    hub task ask <id> "Confirm these <n> tasks and who I should tell: ..."

One question that lists the proposals and the recipients from `knowledge/coverage.md`. On the answer:
create only the confirmed tasks with `hub task create --owner <person> --link <meeting link>`, then
`hub message send --fyi <person> "<one line and the link>"` to each named recipient. If no answer comes, the write-up
stays a draft.

## 7. Finish

Publish with `hub file publish reports/...`, commit, and `hub task update <id> --status done --note`:
the headline, counts, and what still waits. Always finish it; an open routine task absorbs the
next meeting.

## When the transcript is poor

Say so in the report and mark every item from it "low confidence". Never fill gaps with what
usually happens in such a meeting.
