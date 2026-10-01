# Open an escalation

Triggered by a task that escalates a ticket, or by the digest finding one that meets a trigger. Budget
15 minutes. The outcome is a case file, a register line, an owner proposed and, if it is a defect, an
engineering-ready bug report.

---

## 1. Check it is not already open

Search `knowledge/register.md` and `hub task list` for the customer and the problem. If a case exists,
add to it; never open a second one.

## 2. Set severity from the rules

Match the impact to `knowledge/escalation-rules.md`: who is affected, can they work, is there a
workaround, is a contractual time at risk. Write the reason in one line. When unsure, choose the higher
severity and say so; a human may lower it.

## 3. Propose one owner

A named human from the rules, never a team. Put it on the task and ask the head of support to confirm
if the rules do not decide it.

## 4. Build the timeline

From the first customer message to now: each touch with time, channel and one line. Mark the gaps where
the customer waited without hearing from us.

## 5. Write the bug report, if it is a defect

Title (what breaks, where), steps to reproduce from a known state, expected and actual result,
environment (plan, browser or app version, region), how often, how many customers, evidence (ticket
quotes, screenshots named, log lines with credentials removed). If you cannot reproduce it, ask the Technical
Support Engineer with `hub task create --owner technical-support` first.

## 6. Prepare the first update

Acknowledge the problem in the customer's terms, say who owns it and when they will hear next. Ready
for review on the task. Save the case file, add the register line, commit.
