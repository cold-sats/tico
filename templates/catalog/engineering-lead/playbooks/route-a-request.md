# Route a request

Triggered when a task or message asks engineering for something and does not say who should do it, and for
each unowned or stuck item in the weekly summary. Budget 10 minutes. The outcome is one routing proposal a
person approves in a single click. Nothing is assigned.

---

## 1. Read the request

    hub task show <id>

Restate it in one sentence: what is wanted, by whom, by when, and what the requester will do with it.

## 2. Find the owner

1. `knowledge/routing.md`: has a request like this been routed and approved before? Follow that.
2. `knowledge/areas.md`: which repository or area does it touch, and who owns it?
3. The engineering team's lines: a pull request needing a look is `pr-reviewer` (Senior Software Engineer); a
   release, its checklist or its notes is `release-notes` (Release Manager); an outage or an on-call handoff is
   `incident-scribe` (Site Reliability Engineer); an outdated README or API page is `docs-writer` (Technical
   Writer); an incoming bug or a test plan is `issue-triage` (QA Engineer); a vulnerable dependency or a leaked
   secret is `security-engineer`; a red or slow pipeline is `devops-engineer`; a design doc or an architecture
   decision is `software-architect`; a developer's public question or a sample app is `developer-advocate`. What
   users need, a spec or a roadmap question belongs to Product: route it to `product-lead` (Head of Product).

If two owners fit equally, name both and say what decides it. If none fits, say so; never force a fit.

## 3. Check load and urgency

`hub task list --owner <person or bot> --status open --status doing`. Note how many open tasks the owner has
and whether anything on it is older than a week. Say it as a fact, never as a judgement of the person.

## 4. Write the proposal

On the task, in this shape, under 120 words: **Route to** <owner>, **why** (the area and the earlier decision),
**urgency** and the date it matters, **what they need** (links), **alternative** owner. Then `hub task ask <id>`
once and stop.

## 5. On a yes

`hub task create --owner <slug> --title "<the ask>" --parent <id>` with the links. On a no or a change, write
the correction into `knowledge/routing.md` as a present-tense rule, dated. Commit, then
`hub task update <id> --status done --note` with the owner chosen or the question still open.

## When you cannot tell

An area with no owner is the finding: put it in the summary as "no owner for <area>" and ask the requester,
not a guess.
