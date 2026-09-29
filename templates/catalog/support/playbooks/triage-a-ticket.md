# Triage a ticket

Triggered by a task that hands you one ticket, or a pass over everything new since the last one.
Budget 20 minutes for a pass, five minutes for a single ticket. The outcome is a draft reply for
every ticket you can answer, a task for every one you cannot, and a note saying what the queue
looked like.

---

## 1. Read the queue

    hub task show <id>

Read what arrived since the last pass and nothing older. If you cannot reach the source at all, say
so and stop: an unread queue and an empty queue must never read the same.

## 2. Sort each one

Four buckets, and every ticket is in exactly one:

| Bucket | What it is | What you do |
|---|---|---|
| Answered before | `knowledge/answers.md` already covers it | Draft the standing answer, adjusted to what they asked |
| Known issue | `knowledge/known-issues.md` names it | Draft the standing answer and add this ticket to the count |
| Needs a person | A refund, a credit, an exception, an angry customer, anything in `knowledge/escalation.md` | One task on the person who owns it, with the ticket and one line on what they are deciding |
| New | None of the above | Draft what you can, name what you do not know, and ask |

A ticket that is two of these is the more serious one. Anything that mentions money, a deadline, a
legal matter, or a person's safety goes to a person immediately, before you finish the pass.

## 3. Draft the reply

One draft per ticket, on the task, never in the support tool. Each draft:

- starts by naming what they asked, in one line, so the person approving it can check the match;
- answers from a source you can point at, not from a policy you assembled;
- leaves a marked gap wherever it would need a refund, a credit, a discount, a fix, or a date, and
  says on the task what the gap needs;
- carries no personal detail beyond what the person approving already has.

## 4. Route what is left

    hub task create --owner <person> --parent <id>
    hub task create --owner <slug> --parent <id>

One task per thing, with the ticket reference, what the customer could not do, and what you need
decided. Never two tasks for the same thing, and never a second escalation of something an open task
already names. If the same problem has now arrived three times, that is one line in
`knowledge/known-issues.md` and one task for whoever owns the fix, not three escalations.

## 5. Finish the pass

Commit, then `hub task update <id> --status done --note`, in this order: how many arrived, how many
you drafted, how many went to a person and to whom, and anything you could not read. Numbers you
actually counted. Then, in the same run, add any answer you had to work out from scratch to
`knowledge/answers.md` with today's date, so the next pass does not work it out again.

## When the source is unreadable

Record which source, the exact refusal, and the window it covers. Put one line on the task for the
owner if it has failed twice in a row. Never report zero tickets for a source you could not open.
