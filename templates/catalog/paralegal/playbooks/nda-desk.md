# Weekday NDA desk

Schedule: weekdays at 09:00 company time (routine `nda-desk`), once a person has approved the first desk
report. Also run by hand when an NDA arrives. Budget 20 minutes, plus 10 per NDA. The outcome is every open
NDA with a status and the exact changes, and the packets and index up to date. Nothing is sent or signed.

---

## 1. Collect the queue

    hub task list --owner me --status open --status doing --status waiting

Plus NDAs that arrived in the contracts mailbox, if it is connected. Yesterday's desk report tells you what
was waiting on a person; check whether each moved.

## 2. Check each inbound NDA

Read it whole, then compare with `knowledge/standard-nda.md`, clause by clause:
1. **Mutual or one-way**, and whether that matches who will share (both sides sharing on a one-way NDA is a flag).
2. **Definition** of confidential information, and the exclusions: already known, independently developed,
   received lawfully from a third party, public, required by law (with notice where lawful).
3. **Use and recipients**: only for the stated purpose; employees and advisers with a need to know.
4. **Period**: how long the duty lasts, and whether trade secrets are treated separately.
5. **Residuals**: any right to use what people remember. Always a flag unless the variations list allows it.
6. **Extras**: non-solicit, non-compete, exclusivity, IP licences, audit rights. Each a flag.
7. **Return or destruction, remedies, governing law and forum, assignment.**
Mark each: same as the standard, inside `knowledge/variations.md` (quote the line), or outside it.

## 3. Give the status

- **Ready for signature**: everything same or inside the variations list.
- **Needs changes**: list each change as "strike ... / insert ...", taken from the standard.
- **Needs counsel**: anything outside the variations with no company position.
Write `reports/ndas/<party>.md` in the shape of `knowledge/examples/nda-check.md`.

## 4. Outbound requests

For each request to send the company's NDA: fill the template from `knowledge/templates.md` with the party's
legal name, address for notices and purpose as the requester gave them; list every blank and its source; ask
the requester once for any missing value. Never guess a legal entity name.

## 5. Write the desk report

`reports/YYYY-MM-DD-nda-desk.md`: counts by status first, then each NDA in one line (party, status, the one
thing that matters, who acts), packets waiting, index rows added. `hub files publish` it, commit, and
`hub task update <id> --status done --note` with the counts first.
