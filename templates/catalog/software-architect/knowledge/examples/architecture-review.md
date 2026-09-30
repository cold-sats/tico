A sample of excellent output for a fictional company. Every name in it is a stand-in.

```markdown
# Acme architecture review, Wed 2026-09-30

Sample output for Acme, a fictional studio-software company. Every service, document and name is
invented. Nothing was committed or posted. First draft, not yet reviewed.

**Headline: the waitlist redesign adds a second queue system and needs an answer on ordering before
build starts; 2 decisions merged last week have no ADR (drafts ready).**

## Design docs
- **"Waitlist v2" (Sofia, design/waitlist-v2.md, updated 2026-09-28).** Blocking: two studios booking the
  last spot at once; the doc moves waitlist events to a new queue but the booking service still writes
  directly to the database, so order is not guaranteed. Options: (a) keep one writer, the booking service,
  and publish events after commit; (b) the new queue as the only writer. (a) is smaller and reversible.
  Non-blocking: the retry limit is unstated. Notes: reports/reviews/waitlist-v2.md.

## Decisions without a record (ADRs proposed, for an engineer to commit)
- `adr/0014-use-managed-search-for-class-lookup.md`: from pull request #611 (merged 2026-09-24) and the
  planning call of 2026-09-22. Inferred: why the self-hosted option was dropped (marked).
- `adr/0015-sms-reminders-through-one-provider.md`: from #603. Consequence recorded: no fallback provider.

## System map changes
- New: `search-sync` worker (owner Omar), reads bookings, writes the managed search index.

## Technical debt, top five (knowledge/tech-debt.md)
| Item | Cost today | Risk if left | Fix size | Owner |
|---|---|---|---|---|
| Timezone math duplicated in 4 places | 2 bugs in September, both reminders | high: DST change 2026-11-01 | 3 days | Kenji |
| Monolith owns payments and bookings in one transaction | every payment change needs a booking review | medium | 3 weeks | Priya |
| No contract tests on the public API | 1 breaking change shipped (2026-09-10) | medium | 1 week | Tomas |
| Background jobs share one queue | reminders delayed during exports | medium | 4 days | Omar |
| Old admin UI framework | slow changes, feels bad | low, recorded as a feeling | 6 weeks | Lena |

## Could not read
- The billing design folder in Google Docs: link needs sharing with the bot's account.

## Sources
- design/ and adr/ in web-app and api, 2026-09-30; pull requests #603, #611; planning call 2026-09-22
```
