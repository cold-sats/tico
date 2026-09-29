# Starter bots

Six catalog templates a 10 to 50 person company can pick from on day one, about five of them, and get
a first useful, reviewable result in its first session. They are deliberately few, they run on what a
company already has, and none of them acts outside the company on its own. The catalog format is in
[First run](onboarding.md); how to write and tune a bot is in [Creating bots](creating-bots.md).

## The six

| Template | Name | Pack | What it produces | Needs |
|---|---|---|---|---|
| `chief-of-staff` | Chief of Staff | basics | A weekly brief to the owner from goals, tasks, updates and meetings; stalled-goal follow-up; the Monday agenda | Tico only |
| `support` | Support Triage | support | A triage digest, a draft reply per ticket for a person to approve, standing answers and product issues from repeats | Support mail or tickets routed as tasks |
| `sales` | Sales Drafter | sales | Account research, first-touch and follow-up drafts, current pipeline notes | Public web; a CRM and mail are optional |
| `meeting-notes` | Meeting Notes | operations | A summary, decisions and action items per imported meeting, with tasks proposed for their owners | A meeting importer (Fireflies, Zoom, Google Meet, Granola) or manual imports |
| `inbox` | Mail Drafts | basics | A morning brief for one person's mailbox, drafted replies, what needs them | A Google Workspace mailbox for that person |
| `issue-triage` | Issue Triage | engineering | Label and duplicate proposals, drafted requests for missing repro steps, a weekly digest | GitHub connected; offer it only then |

Every one of them is internal until a person says otherwise: it drafts, and a person confirms anything
that would send, post, pay, change a record or delete.

## What every starter does the same way

1. **First message: onboarding.** On its first task the bot introduces itself in three lines, asks the
   template's `onboarding` questions in one message (each with its why), records the answers in
   `state.md`, and does not ask what the hub already answers.
2. **A first result in the same session.** It produces a real draft of its `first_routine` output from
   the company's own data, labelled "First draft, not yet reviewed". A person reacts to something real.
3. **A routine that waits.** It proposes the first routine and stops. The routine is declared in
   `employee.yaml` with `enabled: false`, so `hub bot create` seeds it paused. The bot arms it with
   `hub routine update <id> --enable` only after a person says yes on the task, and logs the decision.
4. **An approval before anything external.** The card's `approval_required` list is what the bot never
   does alone. The platform's own gates still apply (`outbound_send: false`, the approvals policy).
5. **Parked until then.** First run creates every starter `needs_onboarding`: it answers a person's message and nothing else
   (no routine, task notice, Slack route or bot request wakes it) until its onboarding playbook ends with `hub bot onboarded`,
   which it calls only after a person says yes to its first routine. **Start setup** on its page, or any first message, begins the
   conversation. Parked starters do not count toward a member's bot limit. See [First run](onboarding.md#needs-onboarding).

## What stops a starter sending things outside the company

A starter's own prompt is not the gate. What the platform does, checked for these six templates:

| It might | The gate | Where |
|---|---|---|
| Send, reply to or forward mail | The mail connector downgrades a send to a Gmail draft unless the mailbox declares the `send` verb, `outbound_send: true` is set and the recipient is internal, allowed or covered by an approval. The starters declare `read` and `draft` only and `outbound_send: false`; a test refuses `send` in any starter's `access:` | `connectors/mail/policy.py`, `clients/tests/test_catalog.py` |
| Post to Slack | A post needs `post: true` for that channel in `registry/slack-channels.yaml`, and reading grants no posting right. The starters declare Slack read only, commented out until the owner connects it | [Slack gateway](slack-gateway.md) |
| Comment on or label a GitHub issue | **Added in this release.** The company's GitHub App token carries Issues: write, so nothing but a prompt stood between Issue Triage and a public comment. Its access is now `read`, and its `.claude/settings.json` denies `gh issue edit` and `gh issue comment` next to close, reopen, lock, transfer and create. It proposes labels and comments with an approval and the exact commands on the task, and a person runs them. Turning writing on is the owner's edit of `employee.yaml` and the settings file, described in a comment there. The harness reads `.claude/settings.json`; the Codex runtime does not, so for a Codex-run bot the gate is the read-only access declared, the absence of any default write credential to a product repository, and the prompt | `templates/catalog/issue-triage`, `clients/tests/test_catalog.py` |
| Invite someone to a calendar event | **Added in this release.** `hub calendar schedule` was open to every bot and sent invitations to any address. A bot may now invite only people on the company roster (`403 external_attendee` otherwise); an invitation to anyone else is a person's act | `backend/connectors.py`, `backend/tests/test_security_review.py` |
| Message a person inside the company | Bot-to-person messages are linted and capped at three unsolicited a day | `hub say` |
| Change a record in a CRM, the support tool or a repository | The starters declare no such access. A CRM stage change is on `approval_required`, and a tool the company adds is the owner's decision | the card |

Chief of Staff, Support Triage, Sales Drafter and Meeting Notes declare no write access at all. A starter's `.claude/settings.json` allows
only its own repository's `git`, and none of them allows `gh issue *`.

## The card

`card.yaml` is read by whoever is choosing; it is never copied into a bot's repository. The starter
templates add these fields to the existing ones (`template`, `slug`, `name`, `summary`, `owns`,
`never`, `reasoning_effort`, `recommend_when`):

| Field | What it holds |
|---|---|
| `pack` | `basics`, `sales`, `marketing`, `support`, `operations` or `engineering`: the team the template sits in on the full org chart (Leadership, Sales, Marketing, Support, Operations, Engineering), and how a chooser groups templates. The four catalog templates that are not starters carry `marketing` |
| `pains` | Plain phrases a person might say ("too much email", "leads go cold", "meetings without follow-up"). They are the chips on the first-run screen, and the local chooser matches a company's stated pains against them |
| `prerequisites` | A list of `{tool, why, required}`. `tool` is one of `hub`, `mail`, `chat`, `crm`, `github`, `meetings`, `calendar`, `docs`, `web`. A required tool the company did not tick means the chooser does not propose the template (it says what it needs); a person can still add it |
| `onboarding` | Four to seven `{ask, why}` questions the bot asks on its first message |
| `first_routine` | `{title, cadence, output, draft_only: true}`: the reviewable internal artifact the bot produces first |
| `approval_required` | Actions that always need a person's Confirm: send, post, comment on GitHub, change a CRM stage, arm a routine |
| `example_output` | Path, inside the template, to a short sample of excellent output under `knowledge/examples/` |
| `when` | Optional, existing: one sentence saying who wants the template |

`recommend_when` tags come from [First run](onboarding.md#the-chooser). `uses_meetings` and `uses_github` are derived from the tools a
company ticks (a meetings importer, GitHub), and a ticked tool that names a starter outright recommends it even with no matching pain.

```yaml
template: sales
slug: sales
name: Sales Drafter
pack: sales
summary: "Researches leads and accounts, drafts first-touch and follow-up emails for a person to approve, and keeps the pipeline notes current. It never sends."
pains:
  - "leads go cold"
  - "follow-ups fall through the cracks"
prerequisites:
  - tool: web
    why: "Public sources are what research is built from."
    required: true
  - tool: crm
    why: "Optional. Read-only stages let follow-ups start from the real record."
    required: false
onboarding:
  - ask: "What do you sell, and to whom? What rules a lead out?"
    why: "Becomes knowledge/icp.md. Research is judged against it."
first_routine:
  title: "Weekly outreach drafts"
  cadence: "Mondays at 09:00 company time, after you approve the first pack"
  output: "reports/YYYY-MM-DD-outreach-drafts.md: research and drafts for up to ten leads"
  draft_only: true
approval_required:
  - "Send, schedule or reply to any email or message to a prospect, customer or partner"
  - "Change a lead, contact, stage or note in the CRM"
example_output: knowledge/examples/outreach-pack.md
```

## The repository each one starts from

Same layout as every catalog template, plus what makes a starter reviewable:

- `AGENT.md`, under 150 lines: mandate, what it owns, its onboarding conversation, `## Never without
  approval` (matching `approval_required`), how it starts and ends a run, how it uses `hub`, quality
  standards and how it escalates.
- `playbooks/`: one for the first routine, one for the most common request, and `onboarding.md`.
- `knowledge/examples/`: one sample of excellent output for the fictional company Acme. Never a real
  company or person.
- `employee.yaml`: `outbound_send: false`, the first routine declared with `enabled: false`, and
  `access:` with `read` unless drafting needs more. A tool the company may not have is a commented block
  the owner uncomments when it is connected, because changing access is an owner decision.

## What a good bot looks like

The quality bar, in five checks a reviewer can apply to any bot in ten minutes:

1. **Answer first.** The first line of every output is the result, not the process.
2. **Short and scannable.** One page. One line per item. A person decides in two minutes.
3. **Cited.** Every claim points at the record it came from and the date. A number with no source is
   left out.
4. **Honest about gaps.** What it could not read is named. "Not found" is never used for "could not
   look". A missing fact is a marked gap, never an invented one.
5. **Gated.** Nothing leaves the company, changes a record or commits a person without a Confirm, and the
   draft it leaves is ready to approve with one edit.

A worked example. A person asks Support Triage about a ticket. Weak:

> I looked at the ticket. The customer seems unhappy about their calendar and probably needs help.
> I would suggest replying soon and maybe offering a refund.

It buries the answer, cites nothing, and promises money it may not promise. Good:

> **T-2038: how to reset the calendar link. Answered before; draft ready.**
>
> Draft (nothing sent): "Hi Priya, thanks for asking about resetting the calendar link. Open Settings,
> then Calendar, and choose Reset link. Your old link stops working straight away, so share the new one
> with your studio."
> Source: `knowledge/answers.md`, "Reset calendar link", confirmed 2026-09-12. Not covered: whether their
> plan includes SMS reminders; asked to Cara Mendes.

It names the request, gives the draft, cites the answer and its date, says what is not covered, and
sends nothing. The full samples live in each template's `knowledge/examples/`.

## Best practice each template draws on

The methods are standard practice, not proprietary. Public sources consulted while writing them:

- Chief of staff: the weekly Monday and Friday rhythm and three to five priorities, from
  [First Round Review on the chief of staff role](https://review.firstround.com/how-to-be-an-exceptional-chief-of-staff-advice-for-scaling-impact-at-startups/)
  and [McKinsey on being a great chief of staff](https://www.mckinsey.com/capabilities/strategy-and-corporate-finance/our-insights/how-to-be-a-better-chief-of-staff).
- Support triage: category, priority and routing, macros checked by a knowledgeable reviewer, and
  knowledge base gaps filled from repeated tickets, from public triage guides such as
  [Pylon](https://www.usepylon.com/blog/customer-support-triage) and
  [Tidio](https://www.tidio.com/blog/ticket-triage/).
- Sales outreach: short plain-text first touches with one ask, relevance before pitch, and follow-ups
  three to five days apart that each add a new reason, from public cold-email guides such as
  [Cleverly](https://www.cleverly.co/blog/cold-email-outreach-best-practices) and
  [Instantly](https://instantly.ai/blog/email-tips/).
- Meeting notes: decisions with their reasons, one named owner and a due date per action item,
  and a review of open items at the next meeting, from public guides such as
  [Fellow](https://fellow.ai/blog/how-to-manage-meeting-tasks-and-action-items/) and
  [Asana](https://asana.com/resources/meeting-notes-tips).
- Inbox: the four Ds (do, delegate, defer, delete), a handful of labels, and set review times, from
  [Superhuman on executive email management](https://blog.superhuman.com/executive-email-management/).
- Issue triage: reproduce, deduplicate, ask for information, label kind and priority, and watch for stale
  issues, from the [Kubernetes issue triage guide](https://www.kubernetes.dev/docs/guide/issue-triage/) and the
  [Python developer guide](https://devguide.python.org/triage/triaging/).

## Adding your own

Copy the nearest starter and keep the card fields above. `clients/tests/test_catalog.py` checks every
starter in its `STARTERS` list for those fields, the 150 line limit, a declared but paused first routine and
no `send` verb in `access:`; add a template you contribute to the catalog to that list.
