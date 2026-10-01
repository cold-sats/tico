# Write a change request

Triggered by a task asking for a help desk change ("send billing questions to the finance queue", "add
a macro for the new plan"), or by an audit finding. Budget 15 minutes. The outcome is one change request
ready to apply in five minutes with the necessary Tools.

---

## 1. Restate the intent

One line: what should happen to which tickets, and why. If the request is really a target or policy
decision, send it to the head of support as a question instead.

## 2. Find what already touches it

Search `knowledge/config-map.md` for rules, automations and macros that act on the same tickets. Prefer
editing or removing one of them over adding a new rule. Name any rule the change would conflict with.

## 3. Write the steps

- Where in the tool (the menu path).
- The current setting, quoted exactly.
- The new setting, exactly.
- How to check it worked: a test ticket to send, and where it should land or what it should show.
- How to undo it.

For a macro, the full new text; if it states a policy, cite the doc the Librarian gave, with its date.

## 4. Put it forward

Attach the steps to the task and apply the requested change with your Tools. If access or a setting is missing, name it on the task and ask only for that information or Tool. Verify the result, update `knowledge/config-map.md` and `knowledge/change-log.md`, commit, and finish the task. Check its effect at the next monthly audit.
