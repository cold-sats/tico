# Daily support triage

Schedule: weekdays at 09:00 company time (routine `daily-support-triage`), once a person has approved
the first digest. Also run by hand on request. Budget 20 minutes. The outcome is one digest on the
task: every ticket in a bucket with a draft where it can be answered, escalations sent, and repeats
promoted. Nothing goes to a customer.

---

## 1. Read what came in since the last pass

    hub task show <id>

Then the source the onboarding named: tasks routed to you (`hub task list --owner me --status open`),
the support mailbox (`$HUB_DIR/scripts/mail.sh inbox --untriaged --format brief`), a Slack channel. Read
what arrived since the watermark in `state.md` and nothing older. If a source refuses you, name it
and go on. An unread queue and an empty queue must never read the same.

## 2. Sort each ticket with `playbooks/triage-a-ticket.md`

Every ticket is in exactly one bucket: answered before, known issue, needs a person, or new. Put the
whole batch through the decision model rather than reading each thread twice:

    hub decisions --set covered --state-file cand.json --option covered=existing.json

`existing` holds the headings of `knowledge/answers.md` and `known-issues.md`. At 0.7 or above use that
entry; between 0.5 and 0.7 read the ticket yourself; below, it is new.

## 3. Draft, route, cluster

- **Draft** a reply for each ticket you can answer, following `playbooks/triage-a-ticket.md`
  step 3. Put every draft on the task. Never in the support tool.
- **Route** what needs a person: `hub task create --owner <person> --parent <id>` with the ticket and
  one line on what they decide. Money, a deadline, a legal matter, a security concern or an
  outage goes first, before you finish the pass.
- **Cluster** the repeats. Three tickets that ask the same question become a standing answer in
  `knowledge/answers.md`, drafted for a person to confirm. Three that report the same failure become
  one line in `knowledge/known-issues.md` and one task for the owner of the fix, with the count and the
  ticket references. Add a repeat to an existing entry's count, not a new entry.

## 4. Write the digest

In the shape of `knowledge/examples/triage-digest.md`: counts first, what needs a person today, then
tickets by bucket with the draft, then patterns. Save it to `reports/YYYY-MM-DD-triage.md` only when the
pass is worth keeping. Paraphrase; no personal details, no credentials.

## 5. Finish

Update the watermark in `state.md`, commit, then `hub task update <id> --status done --note`: how many
arrived, how many you drafted, how many went to a person and to whom, and anything you could not read.
Always finish it: an open scheduled task absorbs the next occurrence.

## When the source is unreadable

Record which source, the exact refusal and the window it covers. One line on the owner's task if it
failed twice in a row. Never report zero tickets for a source you could not open.
