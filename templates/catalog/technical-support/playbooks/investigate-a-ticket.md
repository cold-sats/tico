# Investigate a ticket

Triggered by a task routing a ticket to tier 2. Budget 45 minutes before you stop and report what you
have. The outcome is a verdict, an answer or workaround for the Support Agent, and a bug report when it
is a bug.

---

## 1. Check what is known

Search `knowledge/workarounds.md`, then existing issues (`gh search issues "<error text>"` where
connected). A match means: link it, add this ticket's evidence, reuse the workaround, done.

## 2. Pin down the report

From the ticket: what the customer did, what they expected, what happened, when, on which plan,
browser, app version, integration and region. List what is missing; ask the Support Agent for it in one
note rather than guessing.

## 3. Check expected behaviour

`hub doc ask` for what the product should do. If the docs are silent or disagree, that is a doc gap
for the Librarian whatever else you find.

## 4. Reproduce

In the sandbox, from a known state, step by step, noting each value you used. Try the customer's
environment where it differs. Two tries that fail to reproduce lead to "could not reproduce" with what
evidence would change that (an export, a screen recording, a request id).

## 5. Decide and write

- **Setup mistake**: the fix in steps the customer can follow, for the Support Agent's reply.
- **Doc gap**: the answer, plus a task to the Librarian.
- **Bug**: the report (title, steps, expected, actual, environment, frequency, customers affected,
  evidence with credentials removed), a workaround if one exists and is tested, and the filing command for a
  human.

## 6. Hand back

Put the verdict and the prepared customer reply on the Support Agent's task, the bug report on a task
to whoever files bugs, and update `knowledge/workarounds.md`. Commit and finish the task.
