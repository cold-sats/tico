# Research an account

Triggered by a task that names one account. Budget 25 minutes. The outcome is one file in
`knowledge/accounts/` a salesperson can read in the minute before a call, and a task note that says
what is worth knowing and what could not be found.

---

## 1. Read what you already have

    hub task show <id>

Then look for an existing file for this account in `knowledge/accounts/`. If there is one, this run
updates it. Do not start a second file for the same account under a slightly different name.

Read `knowledge/icp.md` before you decide anything is interesting, so you are measuring this account
against what actually buys rather than against how impressive it looks. If the account is a
competitor, or the note will state who they compete with, `hub market show` that entity first.
What you learn about the market is `hub market report`, not a competitor file in this repo.

## 2. Read the public sources, in this order

1. What the company says about itself: its site, its product pages, its pricing page if it has one.
2. What it announced recently: news, its own posts, its changelog.
3. Who the people in the task are and what they are responsible for, from public profiles only.
4. What its customers or users say in public.

Stop at the budget. Depth on the first two beats a thin pass over all four.

## 3. Sort what you found

- **Worth writing down**: something that changes how someone would open a conversation. A new
  market, a hiring push in the relevant team, a stated problem, a change of system, a public
  commitment to a date.
- **Context**: size, what they sell, who they sell to. One line each, no more.
- **Noise**: award announcements, generic marketing, anything more than a year old and unchanged.
  Leave it out entirely.

## 4. Write the file

`knowledge/accounts/<account>.md`, in this shape and nothing longer:

- **What they do**, two lines.
- **Why they might buy**, measured against `knowledge/icp.md`, with the one fact that supports it.
- **Who is involved**, name and role, from a public source, nothing personal.
- **What they would push back on**, and what `knowledge/objections.md` says has answered it.
- **What is unknown**, plainly listed.
- **## Sources**, one dated line per source.

Every fact carries its date. A fact from last year and a fact from last week are different facts.

## 5. Draft, if the task asked for one

A draft is one message, on the task, for a person to send. It says one specific true thing from the
research, it asks for one thing, and it leaves a marked gap wherever it would need a price, a
discount, a term, or a date. You never send it. When the owner wants it sent, that is
`hub approval request` with the exact text and the exact recipient.

## 6. Finish

Commit, then `hub task update <id> --status done --note`: what you learned in two lines, the path to
the file, the draft if there is one, and which sources you could not read. A source that refused you
is a named gap, never silence.

## When a source fails

Record which one and what is therefore unknown, keep going with the rest, and say it in the note. A
research pass that read two sources out of four and reads like a complete picture is worse than no
pass at all.
