# Route a request

Triggered by a task or message asking marketing for something ("we need a case study", "can we
announce this?"). Budget 10 minutes. The outcome is a routing proposal on the task that a person can
approve with one word. You route; you never do the work and never create the task yourself.

---

## 1. Read the request

    hub task show <id>

Find the ask, the deadline and who wants it. If the ask, the audience or the date is missing, ask
the requester once with `hub task ask <id>` and stop.

## 2. Match it to an owner

Use `knowledge/routing.md`. Kinds of work that usually go to a marketing bot: a post or article
(content), a search or AI-visibility question (search), a campaign email (email), what people say
publicly (listening), reviews (reputation), a launch or positioning (product marketing), competitor
facts (market). If two owners could take it, say why one fits better. If none fits, say so.

## 3. Check the load and the calendar

Read `knowledge/calendar.md` and the owner's open tasks. If the deadline collides with something
already planned, say what would slip.

## 4. Write the proposal

On the task, in under 100 words: owner, one-line brief, deadline, what it displaces if anything,
and the one thing the owner needs from the requester. Anything that leaves the company or changes a
live page is marked "needs approval before it goes out".

## 5. Finish

On the marketing owner's yes, run `hub task create --owner <slug>` with the brief, link it to this
task, and log the routing in `knowledge/routing.md` if it teaches a rule. Then
`hub task update <id> --status done --note`. A no or a change is recorded and nothing is created.
