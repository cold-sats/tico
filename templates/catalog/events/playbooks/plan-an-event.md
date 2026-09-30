# Plan an event

Triggered by a task like "should we go to this conference?", "plan the October webinar" or "we have a
booth at the regional studio expo". Budget 45 minutes. The outcome is a complete brief on the task,
with every commitment and every outbound message waiting for approval.

---

## 1. Read the request

    hub task show <id>

Find the event, the date and who asked. If the goal or the budget is unknown, propose defaults from
`knowledge/rules.md` and past results, and ask once with `hub task ask <id>`.

## 2. Decide whether it is worth it

From the public event page: audience, expected attendance, cost of attending (ticket, booth, travel,
staff days). From `knowledge/results.md`: what similar events returned. Say plainly "go", "go small"
or "skip", with the numbers.

## 3. Write the brief

`reports/<event>/brief.md`, one page:
- **Goal** in one number (e.g. 15 meetings with studio owners) and the budget ceiling.
- **Audience** and the three accounts or profiles worth meeting.
- **Before:** promotion (two emails and posts, dates), pre-booked meetings, what sales should prepare.
- **During:** run-of-show or booth schedule, staffing, the one question every conversation asks, how
  leads are captured (with a note field for what was said).
- **After:** thank-you email within 48 hours, lead handoff with context, a post-event review within a
  week, the results line in `knowledge/results.md`.
- **Checklist** with dates and owners.

## 4. Prepare the outbound

Draft the promotion and follow-up emails and posts in `reports/<event>/`. Each goes out only via
`hub approval request --kind publish` with its text and list, or a person sends it.

## 5. Put it up for approval

On the task: the brief path, the money (as `hub approval request --kind spend` with the amount and
supplier), and the staff ask. After the yes, add the event to `knowledge/calendar.md` and create the
staffing tasks the owner approved. `hub task update <id> --status done --note`.
