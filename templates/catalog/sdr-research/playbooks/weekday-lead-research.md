# Weekday lead research and first touches

Schedule: weekdays at 07:30 company time (routine `weekday-lead-research`), once a person has
approved the first pack. Also run by hand. Budget 40 minutes for up to ten leads. The outcome is one
pack: a tier and a brief per lead, first-touch drafts for the A leads. Nothing is sent, and nothing in
the CRM changes.

---

## 1. Read where things stand

    hub task show <id>

Then `knowledge/icp.md`, `knowledge/scoring.md`, `knowledge/voice.md`, `knowledge/do-not-contact.md` and
yesterday's pack. Get the new leads from the source onboarding named: the task, a CRM read, or the
form inbox. A lead on the do-not-contact list is skipped and named as skipped.

## 2. Filter fast

Take at most ten. Newest inbound first, then the fittest from a list. Drop leads that are customers,
competitors or already in a live conversation (a reply, a booked call) and put them under "Needs a
person now". Mail history, if connected, shows earlier contact.

## 3. Research each lead, 10 minutes

Follow `playbooks/research-a-lead.md`: the company's own site and news, then hiring and product
changes, then public profiles for the people who would buy. Two sources read well beat four skimmed.

## 4. Score and tier

Apply `knowledge/scoring.md`: fit criteria (4 to 6), buying signals (4 to 6, dated, recent ones weigh
most), negatives (2 to 3). Tier A: fit and a signal from the last 30 days. Tier B: fit, no recent
signal, or a signal with weak fit. Tier C: poor fit or a negative that rules it out; park it with the reason.

## 5. Draft first touches for the A leads

Write to `knowledge/voice.md`: under 100 words, plain text, no attachment, at most one link; open with one
specific, true, dated fact about them and why it matters; one small ask; no price, discount or date, only
a marked gap. Each draft lists the recipient, subject, body and the source that makes it true.

## 6. Write the pack and hand it over

Write `reports/YYYY-MM-DD-lead-briefs.md` in the shape of `knowledge/examples/lead-briefs.md`: headline,
who needs a person now, then each lead with tier, brief and draft, "Hand to Sales" for leads a person has
already touched, and what you could not read. Then `hub files publish reports/YYYY-MM-DD-lead-briefs.md`.
Attach the drafts to the task. Never send.

## 7. Finish

Commit, then `hub task update <id> --status done --note`: leads worked, A/B/C counts, drafts made, who
needs a person, sources not read. Always finish it: an open scheduled task absorbs tomorrow's.
