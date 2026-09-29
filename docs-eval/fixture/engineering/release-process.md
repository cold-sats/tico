# Release process

Acme Projects ships a release every second Tuesday.

## The freeze

The code freeze starts at noon on the Monday before a release. After the freeze only fixes for the release
itself may merge. Everything else waits for the next cycle.

## Release day

1. The release branch is tagged in the morning and deployed to staging.
2. Smoke tests must pass before the production deploy in the afternoon.
3. Support and marketing are told in the release channel when it is live.

## Hotfixes and rollback

A hotfix outside the cycle needs the head of engineering's approval. A bad release is rolled back by
redeploying the previous tag; the database migrations are written so that one release back always works.
