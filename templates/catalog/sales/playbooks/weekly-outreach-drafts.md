# Weekly outreach drafts

Schedule: Mondays at 09:00 company time (routine `weekly-outreach-drafts`), once a person has approved
the first pack. Also run by hand on request. Budget 40 minutes. The outcome is one pack for the sender:
research and a first-touch draft for new leads, follow-up drafts for quiet ones, and current pipeline
notes. Nothing is sent, and nothing in the CRM changes.

---

## 1. Read where things stand

    hub task show <id>

Then `knowledge/pipeline.md`, `knowledge/icp.md`, `knowledge/voice.md` and `knowledge/do-not-contact.md`.
Get the current list of leads from the source the onboarding named (the task, or a read of the CRM). A lead
on the do-not-contact list is skipped and named as skipped.

## 2. Choose at most ten

1. **Follow-ups due first**: leads whose last touch is older than the agreed cadence with no reply, and
   who have not had all their touches.
2. **New leads next**, fittest to `knowledge/icp.md` first.
3. Skip anyone who replied, booked or opted out: a person takes over. Note them in the pack.

## 3. Research each new lead

Follow `playbooks/research-an-account.md` steps 1 to 4, at a lead's depth: 10 minutes, two sources
read well. If there is call or mail history, read it first (`hub meetings search "<company>"`, the sender's
last thread) so a follow-up does not repeat what was said.

## 4. Draft

Write to `knowledge/voice.md`:
- **First touch**: under 120 words, plain text, no attachment, at most one link. Open with one specific,
  true, dated fact about them and why it matters to what {{company_name}} does. One ask, small and easy to
  answer. No price, discount or date; a marked gap where one would go.
- **Follow-up**: a new reason each time (a relevant fact, an answer to a likely question, a smaller ask),
  short, never "just checking in". After the last agreed touch, write no more and mark the lead "closed
  quiet" in the notes.

Each draft carries the recipient, subject, body, and the one source that makes it true.

## 5. Update the pipeline notes

Update `knowledge/pipeline.md`: one line per lead with stage as the record shows it, last touch, next
step, follow-up due date. Remove nothing you cannot see is stale; mark it "check". These are your notes;
you do not touch the CRM. A stage change you think is due goes in the pack as a suggestion for the
person to make.

## 6. Write the pack and hand it over

Write `reports/YYYY-MM-DD-outreach-drafts.md` in the shape of `knowledge/examples/outreach-pack.md`: a
headline, who needs a person now, then each lead with its draft, then the notes changes and what you
could not read. Then:

    hub files publish reports/YYYY-MM-DD-outreach-drafts.md

Attach the drafts to the task. To have one sent, `hub approval request --kind send` with the exact text and
recipient; otherwise the sender copies it. Never send.

## 7. Finish

Commit, then `hub task update <id> --status done --note`: how many leads worked, how many drafts, who needs a
person, and which sources you could not read. Always finish it: an open scheduled task absorbs the next.
