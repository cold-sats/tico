# State

## Onboarding
Not started. The first message walks the person through `playbooks/onboarding.md`.

## Answers
None yet. Record each onboarding answer here, one line each, dated.

## Routine
`daily-support-queue`: declared, not armed. Arm it only after a person approves the first digest.

## Watchers
`hq-tickets` and `gh-support` run every 5 minutes on the runner with no model. Each stays quiet until it has its settings
(`HQ_STAFF_KEY` and `TICO_HQ_URL` in secrets; `config/github.yaml`), then opens a task per new ticket or thread.

## Current focus
None.

## Open threads
None.

## Next
On the first message, start onboarding.
