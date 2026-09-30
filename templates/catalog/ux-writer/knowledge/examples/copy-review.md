A sample of excellent output for a fictional company. Every name in it is a stand-in.

```markdown
# Acme interface copy review, Thu 2026-10-01

Sample output for Acme, a fictional studio-scheduling software company. Every pull request is invented.
Nothing was posted on GitHub; an engineer posts what they accept. First draft, not yet reviewed.

**Headline: 9 pull requests changed user-facing text; 3 blocking issues (2 in the new waitlist flow),
5 suggestions, 1 new term proposed.**

## Blocking
1. `web#1482` `src/booking/Waitlist.tsx:41`: "Error 409: capacity exceeded"
   Rewrite: "This class is full. Join the waitlist and we'll tell you if a spot opens."
   Rule: errors say what happened and what to do; no bare codes (error-rules 1, 3).
2. `web#1482` `src/booking/Waitlist.tsx:77`: "You are on the queue"
   Rewrite: "You're on the waitlist (position 3)." Rule: glossary: "waitlist", never "queue".
3. `mobile#633` `strings/en.json:212`: "Invalid card" on a declined payment.
   Rewrite: "Your card was declined. Try another card or contact your bank." Rule: no "invalid"; next step.

## Suggestions
- `web#1490` "Submit" on the class form → "Save class" (buttons say what they do).
- `web#1491` empty schedule "No data" → "No classes this week. Add a class to open bookings."
- 3 more in the review file, lines 40-52.

## Flagged to owners (no rewrite)
- `web#1488` changes the cancellation fee text on checkout. Owner: Dana (pricing).

## Glossary
- Proposed: "spot" for one place in a class, instead of "slot", "seat" and "space" (all three appear).
  Places it would change: 14 strings, 3 help articles (reported to the Librarian).

## Could not read
`partner-widget` repository is not in my GitHub access.
```
