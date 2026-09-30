# IT request

Triggered by a task from anyone: "I can't log in to the CRM", "my laptop is slow", "Omar needs access to
the finance folder". Budget 15 minutes. The outcome is a fix the human can follow, or a complete access
change in front of its approver, and the request logged.

---

## 1. Classify

    hub task show <id>

Category (account and access, device, network, software, security) and impact (how many people, how
blocked). Anything that looks like a compromise (a login they did not make, a clicked link that asked
for a password, a lost laptop) is P1: tell the Operations Manager now and say what to do first (change
that password, report the device) before anything else.

## 2. Look for a known fix

`knowledge/fixes/`, then `hub doc ask "<the problem>"`. If the team has a guide, point to it and
give the steps; if the guide is wrong, say so and report it to the Librarian after approval.

## 3. Give the fix

Numbered steps, one action each, and what the human should see after each. Ask for the exact error
text or a screenshot if the first try fails. Two failed attempts on a device problem means a human
looks at it: say who.

## 4. Access requests

Fill every field: human, tool, role (the least that does the job), reason, end date if temporary,
approver from `knowledge/tools.md`. Sensitive tools need the tool owner as well as the manager. Put it
on the task and ask the approver with `hub task create --owner <approver>` after the requester
confirms the details. Once approved, the admin applies it, or you do where the owner has given this bot
write access, and you confirm with the requester that it works.

## 5. Log

Add the row to `knowledge/requests.md`; a new fix that worked becomes `knowledge/fixes/<problem>.md`.
Close the task only when the human says it works.
