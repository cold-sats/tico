# Starter bots

The catalog holds 38 templates, enough to staff a company of ten to a hundred people, in six packs that become the six teams of the
full org chart. A company picks about five of them for a starter team and gets a first useful, reviewable result in its first session,
or builds the whole org chart in one click and sets each bot up when its turn comes: every bot is created parked in "Needs
onboarding" and costs nothing until someone sets it up. They run on what a company already has, and none of them acts outside the
company on its own. The catalog format is in [First run](onboarding.md); how to write and tune a bot is in
[Creating bots](creating-bots.md).

## The catalog

Each pack is a team. Its first row is the pack's lead: a small coordinator that drafts the team's weekly summary from what the team's
bots reported and proposes who should take a stuck or misrouted request. The leads never do their team's work and never assign people.
The Librarian, built into every company, owns the docs, the FAQ and the answers built from them, so no template writes or
keeps docs: Support Agent asks it (`hub docs ask`) and reports a missing or wrong doc to it as a task, People & HR does the same for
policy questions, and Docs Writer covers only READMEs and API docs that live in the product repositories. The Goal Manager, also built in, keeps every KPI's readings and sets goals' colours from them ([goals and KPIs](goals-and-kpis.md)), so no template does either. The chooser has six teams, so finance sits in Operations, and product research and the docs and release bots sit in Engineering.

### Leadership (`basics`)

| Template | Name | What it produces | Needs |
|---|---|---|---|
| `chief-of-staff` | Chief of Staff (lead) | A weekly brief to the owner from goals, tasks, updates and meetings; stalled-goal follow-up; the Monday agenda | Tico only |
| `board-updates` | Board & Investor Updates | A one-page monthly investor update draft: metrics, asks, highlights, lowlights, recap; finance figures only as supplied | Tico only; docs and mail optional |
| `inbox` | Mail Drafts | A morning brief for one person's mailbox, drafted replies, what needs them | A Google Workspace mailbox for that person |
| `strategy-planning` | Strategy & Planning | A quarterly plan and OKR draft (three to five objectives, about three measurable key results each), last quarter graded 0 to 1, and a mid-quarter check-in | Tico only |

### Sales (`sales`)

| Template | Name | What it produces | Needs |
|---|---|---|---|
| `sales-lead` | Sales Lead (lead) | A weekly sales team summary (movement, stalled deals, what each sales bot produced, blocked work) and routing proposals; the sales team's lead | Tico only; a CRM optional |
| `customer-success` | Customer Success | A weekly renewal and health brief (renewals by 120, 90, 60 and 30 day stage, accounts at risk, a drafted next touch) and review packs | Tico only; a CRM, support mail and meetings optional |
| `proposal-writer` | Proposal Writer | A proposal draft with a gap list, and questionnaire or RFP answers marked reused, adapted or new; every price a gap for the seller | Tico only; docs optional |
| `sales` | Sales Drafter | Account research, first-touch and follow-up drafts, current pipeline notes | Public web; a CRM and mail are optional |
| `sales-ops` | Sales Ops | A weekly CRM hygiene and pipeline report with each exception and its proposed fix, and duplicate candidates; read only | A CRM (read only) |
| `sdr-research` | SDR & Lead Research | A daily pack: new leads scored A, B or C with a sourced brief, and a first-touch draft for each A lead | Public web; a CRM and mail are optional |

### Marketing (`marketing`)

| Template | Name | What it produces | Needs |
|---|---|---|---|
| `marketing-lead` | Marketing Lead (lead) | A weekly marketing summary with status per workstream, blockers, a six-week calendar and proposed priorities; routing proposals | Tico only |
| `content` | Content | A four-week content plan and one finished draft a week with short versions | Tico only |
| `email-marketing` | Email Marketing | A campaign or sequence draft with subject lines, a preview line and a send checklist | Tico only; past results optional |
| `listening` | Listening | One short digest per weekday sweep of public mentions, questions and competitor moves | Public web |
| `market` | Market Analyst | An evidence-backed market map and a weekly delta page | Tico only; public web, calls and CRM optional |
| `product-marketing` | Product Marketing | Launch briefs with a tier and checklist, a positioning document and battlecard drafts | Tico only; public web, calls and CRM optional |
| `reputation` | Reputation | A weekly review-listing digest, a ledger and one batch of replies and flags per surface for approval | Public web |
| `seo-visibility` | SEO & AI Visibility | A weekly report on search and AI-answer visibility with three drafted page fixes | Public web; Search Console or an AI-visibility tool are optional |

### Support (`support`)

| Template | Name | What it produces | Needs |
|---|---|---|---|
| `support-lead` | Support Lead (lead) | A weekly support summary: volume, response and resolution times against target, the oldest waiting tickets, repeats and the decisions needed, plus routing proposals | Tico only |
| `feedback-analyst` | Feedback Analyst | A weekly report of customer feedback themes with counts, anonymised quotes, the trend and three suggested actions | Feedback routed as tasks; mail, meetings and chat are optional |
| `support` | Support Agent | Works each ticket end to end as drafts: a bucket and a draft reply per ticket with the docs it rests on (asked of the Librarian), follow-ups, product issues from repeats, and doc gaps reported to the Librarian | Support mail or tickets routed as tasks |
| `support-qa` | Support QA | A weekly scored sample of sent replies with patterns and coaching drafts for a person | Sent replies routed as tasks or a support mailbox |

### Operations and finance (`operations`)

| Template | Name | What it produces | Needs |
|---|---|---|---|
| `ops-manager` | Ops Manager (lead) | A weekly checklist of what is due, overdue and blocked, vendor follow-up drafts and a summary of the Operations team; the team's lead | Tico only |
| `ar-followup` | AR Follow-up | A weekly aging summary and a draft reminder per overdue invoice, friendly first and firmer later; a person sends each one | An invoice aging export on a task |
| `bookkeeping` | Bookkeeping Assistant | Proposed categories for uncategorised transactions and a monthly close status: checklist, missing receipts, batched owner questions, items for the accountant. Read-only to the books | An exported transaction file on a task |
| `legal-review` | Legal Review | A plain-language contract summary, key terms, flags against your preferred positions and a contract calendar; not legal advice | Contracts attached to tasks |
| `meeting-notes` | Meeting Notes | A summary, decisions and action items per imported meeting, with tasks proposed for their owners | A meeting importer (Fireflies, Zoom, Google Meet, Granola) or manual imports |
| `people-hr` | People & HR Assistant | An onboarding checklist per new hire, a weekly tracker and policy answers the Librarian cites from the handbook | The handbook in the company docs |
| `procurement` | Procurement | A weighted vendor comparison per purchase request, with claims and their sources, and draft questions for a person to send; a weekly digest of open requests | A purchase request on a task; public web |
| `recruiting` | Recruiting Coordinator | Job post drafts, a summary per application against the stated criteria, an interview kit and scheduling drafts | Role briefs and applications handed over as tasks |
| `spend-watcher` | Spend Watcher | A weekly software and cloud spend report: movers, new vendors, overlaps, anomalies, renewals in 60 days, each with its source line | Card, bank or billing exports on a task |

### Engineering and product (`engineering`)

| Template | Name | What it produces | Needs |
|---|---|---|---|
| `engineering-lead` | Engineering Lead (lead) | A weekly engineering summary: what shipped, stuck pull requests, incidents, docs and release status, blocked work, and routing proposals | GitHub connected |
| `docs-writer` | Docs Writer | A weekly drift report on READMEs and API docs in the product repositories, with draft fixes for an engineer to commit; internal docs stay with the Librarian | GitHub connected |
| `incident-scribe` | Incident Scribe | An incident timeline, a blameless postmortem draft, action items with owners and dates, and a weekly incident review | Tico only; an incident channel or Sentry is optional |
| `issue-triage` | Issue Triage | Label and duplicate proposals, drafted requests for missing repro steps, a weekly digest | GitHub connected; offer it only then |
| `pr-reviewer` | PR Reviewer | A weekday review queue with a draft review per pull request (blocking issues first) for a person to post | GitHub connected |
| `product-researcher` | Product Researcher | Interview snapshots, an opportunity map with source counts, research briefs and a weekly research digest | Tico only; a meetings importer is optional |
| `release-notes` | Release Notes | A draft changelog entry and plain-language release notes from merged pull requests, and a suggested version | GitHub connected |

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

A starter's own prompt is not the gate. What the platform does, checked for every template in the catalog:

| It might | The gate | Where |
|---|---|---|
| Send, reply to or forward mail | The mail connector downgrades a send to a Gmail draft unless the mailbox declares the `send` verb, `outbound_send: true` is set and the recipient is internal, allowed or covered by an approval. The starters declare `read` and `draft` only and `outbound_send: false`; a test refuses `send` in any starter's `access:` | `connectors/mail/policy.py`, `clients/tests/test_catalog.py` |
| Post to Slack | A post needs `post: true` for that channel in `registry/slack-channels.yaml`, and reading grants no posting right. The starters declare Slack read only, commented out until the owner connects it | [Slack gateway](slack-gateway.md) |
| Comment on or label a GitHub issue, or review a pull request | **Added in this release.** The company's GitHub App token carries Issues: write, so nothing but a prompt stood between Issue Triage and a public comment. Its access is now `read`, and its `.claude/settings.json` denies `gh issue edit` and `gh issue comment` next to close, reopen, lock, transfer and create. It proposes labels and comments with an approval and the exact commands on the task, and a person runs them. PR Reviewer, Release Notes, Docs Writer and Engineering Lead read GitHub the same way: `read` access, only `gh pr list`, `view`, `diff` and `checks` allowed, and `gh pr review`, `comment`, `merge`, `close`, `edit` and `create` denied, so a review is a draft on the task that a person posts. Turning writing on is the owner's edit of `employee.yaml` and the settings file, described in a comment there. The harness reads `.claude/settings.json`; the Codex runtime does not, so for a Codex-run bot the gate is the read-only access declared, the absence of any default write credential to a product repository, and the prompt | `templates/catalog/issue-triage`, `clients/tests/test_catalog.py` |
| Invite someone to a calendar event | **Added in this release.** `hub calendar schedule` was open to every bot and sent invitations to any address. A bot may now invite only people on the company roster (`403 external_attendee` otherwise); an invitation to anyone else is a person's act | `backend/connectors.py`, `backend/tests/test_security_review.py` |
| Message a person inside the company | Bot-to-person messages are linted and capped at three unsolicited a day | `hub say` |
| Change a record in a CRM, the support tool, the books or a repository | The starters declare no such access. Sales Ops reads the CRM and only lists the fixes; Bookkeeping, Spend Watcher and AR Follow-up read exports and never post, pay or send. A CRM stage change is on `approval_required`, and a tool the company adds is the owner's decision | the card |
| Act on a public review surface | Reputation declares `read` on its review surfaces and on Slack, and keeps `act` and `post` as a commented block the owner uncomments after a person has approved the first batch; until then a person carries out each approved batch | `templates/catalog/reputation`, `clients/tests/test_catalog.py` |

No template declares a `send`, `write`, `modify` or `delete` verb in `access:`, and the catalog test fails one that does. A template's `.claude/settings.json` allows only its own repository's `git` and, for the GitHub bots, the read-only `gh` commands above; none allows `gh issue *` or `gh pr *` as a whole.

## The card

`card.yaml` is read by whoever is choosing; it is never copied into a bot's repository. The starter
templates add these fields to the existing ones (`template`, `slug`, `name`, `summary`, `owns`,
`never`, `reasoning_effort`, `recommend_when`):

| Field | What it holds |
|---|---|
| `pack` | `basics`, `sales`, `marketing`, `support`, `operations` or `engineering`: the team the template sits in on the full org chart (Leadership, Sales, Marketing, Support, Operations, Engineering), and how a chooser groups templates. Those are the only six teams the chooser has (`TEAMS` in `backend/onboarding.py`), so finance templates use `operations` and product research uses `engineering` |
| `lead` | `true` on exactly one template per pack: the team's coordinator, and the person the rest of the team reports to on the full chart. Chief of Staff for Leadership. The catalog test requires exactly one. `full_chart` in `backend/onboarding.py` does not read the field yet and picks a team's lead by best match, so a card carrying it changes nothing until it does |
| `pains` | Plain phrases a person might say ("too much email", "leads go cold", "meetings without follow-up"). The first-run screen shows about a dozen of them as chips (`FEATURED_PAINS` in `backend/onboarding.py`, two per team), and the local chooser matches a company's stated pains against them |
| `prerequisites` | A list of `{tool, why, required}`. `tool` is one of `hub`, `mail`, `chat`, `crm`, `github`, `meetings`, `calendar`, `docs`, `web`. A required tool the company did not tick means the chooser does not propose the template (it says what it needs); a person can still add it |
| `onboarding` | Four to seven `{ask, why}` questions the bot asks on its first message |
| `first_routine` | `{title, cadence, output, draft_only: true}`: the reviewable internal artifact the bot produces first |
| `approval_required` | Actions that always need a person's Confirm: send, post, comment on GitHub, change a CRM stage, arm a routine |
| `example_output` | Path, inside the template, to a short sample of excellent output under `knowledge/examples/` |
| `when` | Optional, existing: one sentence saying who wants the template |

`recommend_when` tags come from [First run](onboarding.md#the-chooser). `uses_meetings` and `uses_github` are derived from the tools a
company ticks (a meetings importer, GitHub), and a ticked tool that names a starter outright recommends it even with no matching pain, so
only Meeting Notes and Issue Triage use those two tags; every other template names a situation instead (`sells_software`, `uses_crm`,
`has_support_inbox`) or a broad one (`uses_docs`, `uses_email`), or the starter team would fill with everything a ticked tool touches. Only
Chief of Staff is `always`. A required tool the company did not tick holds the template back, so require only what the bot cannot work
without: `hub` (files and tasks a person hands it) is an honest requirement for a bot fed by exports.

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

A worked example. A person asks Support Agent about a ticket. Weak:

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
- Strategy and planning: three to five objectives with about three measurable key results each, grading on a 0 to 1 scale with 0.6 to 0.7 as healthy for stretch goals, outcomes not activities, and mid-quarter check-ins, from [Google re:Work, Set goals with OKRs](https://rework.withgoogle.com/intl/en/guides/set-goals-with-okrs).
- Board and investor updates: metrics and asks first and a short recap last, three to five highlights and one to three lowlights, the same metric definitions every month, and bad news paired with what is being done, from [Visible on Y Combinator's investor update advice](https://visible.vc/blog/tips-from-yc-using-asks-metrics-and-a-recap-to-power-your-investor-updates/) and [Visible on writing an investor update](https://visible.vc/blog/how-to-write-the-perfect-investor-update/).
- Sales lead: a weekly review of three to five priority deals, deals quiet for 14 days or more as stalled, and last week's actions checked first, from [Sybill on running a pipeline review](https://www.sybill.ai/blogs/sales-pipeline-review-meeting).
- SDR and lead research: separate fit and buying-signal scores with a few criteria each, negative signals that subtract, and recent signals weighted most, from [AI SDR on lead scoring](https://aisdr.com/blog/lead-scoring-examples/); the first-touch rules are those under Sales outreach above.
- Sales ops: weekly checks of stage, close date, amount and a specific dated next step on open deals, monthly duplicate and stale-record checks, quarterly picklist review, and trending exceptions older than 30 days, from [Default on CRM data hygiene](https://www.default.com/post/crm-data-hygiene) and [ORM on a CRM data hygiene checklist](https://orm-tech.com/blog/crm-data-hygiene-checklist).
- Proposal writer: an executive summary written last around one central message and two or three win themes, a problem-solution-scope-timeline-pricing-next-step structure, and three pricing options, from [Loopio on proposal executive summaries](https://loopio.com/blog/proposal-executive-summary/) and [Xero on writing a business proposal](https://www.xero.com/us/guides/write-a-business-proposal/).
- Customer success: a renewal motion that starts 90 to 120 days out (health check, value review, objections, commercial terms), health from usage, support and relationship signals, and health owned by customer success while price and contract stay with sales, from [June on the renewal playbook](https://www.june.so/blog/customer-success-renewal-playbook) and [Planhat on B2B renewals](https://www.planhat.com/customer-success/renewals).
- Marketing lead: a weekly team review that opens with red/yellow/green status per workstream, then blockers, the marketing calendar and next week's priorities, from [Range and Emily Kramer's weekly marketing meeting agenda](https://www.range.co/templates/marketing-team-weekly-meeting-agenda).
- SEO and AI visibility: the fundamentals (unique titles and descriptions, headings, internal links, alt text, sitemaps, structured data), people-first content questions, and the point that AI features need no special markup, only the same helpful pages, from Google's [SEO starter guide](https://developers.google.com/search/docs/fundamentals/seo-starter-guide), [helpful, reliable, people-first content](https://developers.google.com/search/docs/fundamentals/creating-helpful-content) and [AI features and your website](https://developers.google.com/search/docs/appearance/ai-features).
- Email marketing: one variable per subject-line test on a slice of the list, and the sending checklist (accurate sender, honest subject, postal address, working unsubscribe honoured within ten business days, sender authentication, complaint rate under 0.3 percent), from [Mailchimp on subject line testing](https://mailchimp.com/resources/subject-line-testing/), the [FTC CAN-SPAM compliance guide](https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business) and [Google's email sender guidelines](https://support.google.com/a/answer/81126).
- Product marketing: positioning built in order (competitive alternatives, unique attributes, value, best-fit customers, category) and launches sized by expected impact into three tiers, from [April Dunford's positioning quickstart](https://www.aprildunford.com/post/a-quickstart-guide-to-positioning) and [Pragmatic Institute on launch tiers](https://www.pragmaticinstitute.com/resources/articles/product/prioritize-product-launch-resources-with-launch-tiers/); one-screen battlecards kept current, from [Klue](https://klue.com/blog/competitive-battlecards-101) and the [Competitive Intelligence Alliance](https://www.competitiveintelligencealliance.io/competitive-battlecards-guide-2022/).
- Content: three to five content pillars, four to six weeks planned ahead, a status per piece and one owner, from [CoSchedule on editorial calendars](https://coschedule.com/content-marketing/editorial-calendar), with the same people-first questions from [Google Search Central](https://developers.google.com/search/docs/fundamentals/creating-helpful-content).
- Market analyst: a small set of core competitors (the three to five you actually lose to), evidence before claims and cards refreshed against win/loss data, from the [Competitive Intelligence Alliance](https://www.competitiveintelligencealliance.io/competitive-battlecards-guide-2022/) and [Klue](https://klue.com/blog/competitive-battlecards-101), and Dunford's warning against phantom competitors from the [positioning quickstart](https://www.aprildunford.com/post/a-quickstart-guide-to-positioning).
- Listening: goals first, Boolean queries with exclusions, sorting into sentiment, pain points and competitor moves, and routing findings to named owners, from [Hootsuite on social listening](https://blog.hootsuite.com/social-listening-business/).
- Reputation: no compensation conditioned on sentiment or rating, no suppressing negative reviews, a public reply is allowed, from the [FTC Consumer Reviews and Testimonials Rule Q&A](https://www.ftc.gov/business-guidance/resources/consumer-reviews-testimonials-rule-questions-answers), and the surface's own flag grounds and incentive ban from [Google Maps user-generated content policy](https://support.google.com/contributionpolicy/answer/7400114).
- Support lead: a weekly review on named measures (first response time, time to resolution, backlog growth, CSAT, escalations) with two or three owned actions, and backlog aging buckets because a ticket open for two weeks is almost always misrouted or stuck, from [Supportbench on the weekly support ops review](https://www.supportbench.com/weekly-support-ops-review-drive-real-improvements/).
- Support QA: a short scorecard of accuracy, tone, completeness, policy and next step on a 1 to 3 scale, 4 to 6 categories at most, scored from a 5 to 10 percent random sample with some targeted tickets, from [Zendesk on building a QA scorecard](https://www.zendesk.com/blog/quality-assurance/workforce-optimization/qa-scorecard/) and [Featurebase on customer service quality assurance](https://www.featurebase.app/blog/customer-service-quality-assurance).
- Feedback analyst: one shared theme list, tagging each item, ranking by frequency and severity weighted by account value, weekly triage of feedback, and closing the loop with customers (a person's job; the bot only lists who to tell), from [CustomerGauge on voice of customer analysis](https://customergauge.com/blog/voice-of-customer-analysis) and [Umbrex on voice of the customer feedback loops](https://umbrex.com/resources/customer-retention-playbook/voice-of-the-customer-feedback-loops/).
- Engineering lead: a weekly review of what shipped, what is stuck and what is blocked, using delivery measures about the process and never a person (change lead time, deployment frequency, failed deployment recovery time, change fail rate) and review turnaround, from [DORA's software delivery metrics](https://dora.dev/guides/dora-metrics-four-keys/) and [Google's engineering practices on small changes](https://google.github.io/eng-practices/review/developer/small-cls.html).
- PR reviewer: review the design before the detail, favour approving what improves code health, mark preferences as nits, keep changes small (about 100 lines is reasonable, 1,000 too large), and label each comment as blocking or not, from [Google's standard of code review](https://google.github.io/eng-practices/review/reviewer/standard.html), [why small changes](https://google.github.io/eng-practices/review/developer/small-cls.html) and [Conventional Comments](https://conventionalcomments.org/).
- Release notes: written for humans, grouped Added, Changed, Deprecated, Removed, Fixed and Security, newest first with dates and links, never a raw commit log, with the version bump taken from the change (major for breaking, minor for a feature, patch for a fix), from [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), [Semantic Versioning](https://semver.org/) and [GitHub's generated release notes](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes) (labels decide the categories).
- Incident scribe: a blameless postmortem with impact, root causes, a detailed timeline, what went right and follow-up actions, written soon after the incident and reviewed before it is shared, from [Google's SRE book on postmortem culture](https://sre.google/sre-book/postmortem-culture/), [PagerDuty's postmortem process](https://response.pagerduty.com/after/post_mortem_process/) and [PagerDuty's postmortem guidance](https://postmortems.pagerduty.com/).
- Docs writer: one page, one documentation type (tutorial, how-to, reference, explanation), second person, present tense, docs kept with the code so a change ships with its documentation, from [Diataxis](https://diataxis.fr/), the [Google developer documentation style guide](https://developers.google.com/style) and [Write the Docs on docs as code](https://www.writethedocs.org/guide/docs-as-code/).
- Product researcher: story-based interviews, an opportunity map grouped under one outcome, refined every three to four interviews, and assumption tests before solutions, from [Product Talk on the opportunity solution tree](https://www.producttalk.org/opportunity-solution-tree/).
- Ops Manager: a short weekly checklist of five to nine items, the ones costly to miss or easy to forget, marked read-do or do-confirm, with a named owner, a review date and a proof of completion for every recurring duty, from [The Checklist Manifesto design notes (BYU Design Review)](https://www.designreview.byu.edu/collections/good-checklist-design-from-the-checklist-manifesto) and [Atlassian's guide to writing an SOP](https://www.atlassian.com/software/confluence/templates/sop); notice windows flagged when they open (a renewal's lead time), from [Harvey's contract review checklist](https://www.harvey.ai/blog/contract-review-checklist).
- Recruiting Coordinator: job-related, uniformly applied criteria, no protected-characteristic or proxy screening and job posts that do not discourage applicants, from the [EEOC's best practices for employers](https://www.eeoc.gov/initiatives/e-race/best-practices-employers-and-human-resourceseeo-professionals) and [EEOC prohibited practices](https://www.eeoc.gov/prohibited-employment-policiespractices); the same questions and a poor-to-outstanding scoring guide for every interviewer, from [Google re:Work's structured interviewing guide](https://rework.withgoogle.com/intl/en/guides/a-guide-to-structured-interviewing-for-better-hiring-practices) and [VidCruiter's interview scorecard guide](https://vidcruiter.com/interview/structured/scorecard/); required kept apart from preferred and gender-coded words removed, from [LinkedIn's inclusive job description guidance](https://www.linkedin.com/business/talent/blog/talent-acquisition/must-dos-for-writing-inclusive-job-descriptions).
- People & HR Assistant: compliance, clarification, culture and connection across preboarding, day one, the first week and 30, 60 and 90 day check-ins, from [SHRM's 4 Cs as summarised by HR Cloud](https://www.hrcloud.com/blog/onboarding-best-practices-the-4-cs); collecting only what the purpose needs and reviewing what is held, from the [ICO's data minimisation principle](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/data-minimisation/).
- Legal Review: read limitation of liability, indemnity, renewal, termination and IP first, tabulate key terms with clause references, flag deviations from the company's own playbook rather than a general view, and have a lawyer review any AI-assisted analysis, from [Spellbook's contract review checklist](https://spellbook.com/learn/contract-review-checklist) and [Harvey's contract review checklist](https://www.harvey.ai/blog/contract-review-checklist).
- Bookkeeping: a month-end checklist that runs in order (feeds complete, receipts collected, uncategorised transactions cleared, accounts reconciled, receivables and payables reviewed, statements compared with last month, period locked by a person), categorising weekly instead of in one batch, and one batched list of owner questions with items for the accountant kept separate, from [Business.com's month-end close checklist](https://www.business.com/articles/month-end-close-checklist/) and [Chaser's monthly bookkeeping checklist](https://www.trychaser.com/checklist-articles/monthly-bookkeeping-checklist-for-small-businesses).
- Spend Watcher: inform, optimise, operate; an anomaly defined as an unforecast rise against history with severity thresholds and a named owner, from the [FinOps Foundation anomaly management capability](https://www.finops.org/framework/capabilities/anomaly-management/) and [its guide to managing cloud cost anomalies](https://www.finops.org/wg/managing-cloud-cost-anomalies/); renewal calendars with alerts at 90 and 60 days, notice periods and usage evidence (inactive 90 days, 30 for expensive seats) before any change, from [Zylo's SaaS renewal guide](https://zylo.com/blog/guide-saas-renewal).
- AR Follow-up: overdue invoices followed up in full with polite early reminders and firmer later ones, 50 to 125 words, the invoice details and a clear action in each, a person taking over at the last step, from [Chaser on dunning](https://www.chaserhq.com/blog/what-is-dunning-in-accounts-receivables-and-how-to-optimize-it) and [Gaviti's collection email templates](https://gaviti.com/5-most-effective-collection-email-templates/).
- Procurement: must-haves before scoring, three to five shortlisted vendors, percentage weights that total 100, a scoring rubric agreed first, total cost of ownership including renewal rises, security and reference checks, from [Ramp's vendor comparison matrix guide](https://ramp.com/blog/vendor-comparison-matrix) and [Ivalua's vendor selection process](https://www.ivalua.com/blog/vendor-selection-process/).

## Adding your own

Copy the nearest template and keep the card fields above. `clients/tests/test_catalog.py` checks every template in the catalog except the
three built-ins (no list to update) for those fields, the 150 line limit, a first sentence of the summary that fits the onboarding line,
a declared but paused routine, an example that names the fictional company, one lead per pack, no pain phrase used twice and no
`send`, `write`, `modify` or `delete` verb in `access:`. The card's `first_routine.title` must be the title of the routine in `employee.yaml`.
