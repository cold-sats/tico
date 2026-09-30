# Approvals policy

The following actions require a Tico approval with the exact action attached before it is taken:

Apply the owner's newer scoped instructions before older default restrictions. A scoped
instruction covers exactly what it names and does not grant other bots new publication or sending
authority. Purchases always need approval of the exact vendor and amount.

- Spending money or changing budgets, bids, or subscriptions.
- Sending email, DMs, or posts to anyone outside the company.
- Publishing or deleting public content. Opening or updating an unmerged external-documentation
  review pull request is preparation, not publishing.
- Changing production infrastructure, configuration outside the normal tested Tico release,
  DNS, or credentials. A CI-passing Tico code merge and its automatic deployment do not need
  a separate approval unless the change performs another action listed here.
- Deleting data that cannot be regenerated.
- Committing to a customer, partner, or candidate.

Calendar appointments need no approval: every bot may read appointments and create
events/invitations through `hub_calendar_*`. The event's title, time, calendar and attendees are
the exact scoped action; this does not authorize a separate email, another commitment, spending,
or publication.

Bots request approval through `hub approval request --kind send|spend|publish|merge` when the
specific action is gated by this policy or another current rule. The payload
must identify the exact message, amount, public content, or pull request. Only a human decides it,
and an approval can be consumed once. Drafts, analysis, internal reports, and changes to a bot's own
repository need no approval. A bot may open and merge pull requests into its own `bot-<slug>`
repository after required checks pass; older blanket merge holds in bot instructions do not apply
to that bot's own repository. Authorized maintainers may merge Tico repository pull requests after
required checks pass; the normal automatic deployment needs no second approval. External
documentation follows `documentation.md`: an employee may prepare one reusable review pull
request, but only the owner reviews and merges it.

Outbound sends are also gated by `outbound_send` in the employee's `bot.yaml`. With it false,
approved material remains a draft unless the exact-message approval authorizes that one send: a
matching GitHub Issue, a decided Tico `send` approval, or the owner telling the employee in Tico to
send it (`--approval-issue` with that message id). See `docs/mail-service.md` for the connector
contract.
