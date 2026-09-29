---
service: hub-storage
title: Hub storage (S3)
kind: cli
summary: The private company bucket where files handed to a bot arrive and finished deliverables go, one prefix per employee.
access: "the AWS CLI with the turn's preset `AWS_PROFILE` and `HUB_BUCKET`; task attachments through `clients/files.py`"
credentials:
  - AWS_PROFILE — preset in every turn; an IAM user that can reach only the bucket <company>-tico-hub
  - HUB_BUCKET — preset in every turn; the bucket name (<company>-tico-hub)
declared_as: |
  nothing to declare: every employee implicitly has its own prefix in the bucket and read
  access to shared/ (policies/access.md). Reading another employee's deliverables is declared:
  - service: hub-storage
    identity: <company>-tico-hub S3 bucket
    can: [read]
    note: reads listening/deliverables/ and seo/deliverables/; writes only <slug>/
writes: allowed
owner: owner
aliases: [s3]
---

## What it is

One private S3 bucket, `<company>-tico-hub`, for the files the company's bots produce and
receive. Every turn gets `AWS_PROFILE` (an IAM user that can only reach this bucket) and
`HUB_BUCKET`. Bots use the AWS CLI; keys never go in files or tasks. Rules:
[policies/shared-rules.md](../policies/shared-rules.md), "Files and deliverables".

## What data it has

One prefix per employee:

| Prefix | What |
|---|---|
| `<slug>/inbox/<task>/` | files handed to the bot; the task lists them as `s3://` URIs |
| `<slug>/deliverables/<task>/` | finished output, listed in the task's completion note |
| `<slug>/working/` | scratch; objects expire after 30 days |
| `shared/` | company-wide assets any employee may read |

Small text deliverables can also live in the bot's own repo under `reports/`; large or binary
ones go to the bucket. Files attached to a hub task or a chat message are not in the bucket
under a prefix a bot browses: they arrive as file IDs in the task.

## How a bot uses it

```bash
aws s3 ls s3://$HUB_BUCKET/<slug>/inbox/<task-id>/
aws s3 cp s3://$HUB_BUCKET/<slug>/inbox/<task-id>/brief.pdf ./brief.pdf
aws s3 cp report.md s3://$HUB_BUCKET/<slug>/deliverables/<task-id>/report.md
aws s3 cp scratch.csv s3://$HUB_BUCKET/<slug>/working/scratch.csv
aws s3 ls s3://$HUB_BUCKET/shared/
python3 "$HUB_DIR/clients/files.py" FILE_ID NEW_DESTINATION      # an attachment named in the task
```

In the completion note, list the finished files under **Deliverable** as full `s3://` URIs.

## Rules

- Write only under your own prefix; read `shared/` and your own prefix, plus another
  employee's `deliverables/` only when your `access:` says so.
- Reference files by full `s3://` URI, never by presigned link (they expire) and never by a
  local path on the Mac.
- A deliverable in the bucket is still internal. Anything customer-facing goes through
  `policies/approvals.md` and the outbound gate before it leaves.
- Never put keys in files, tasks or messages; the profile is preset and that is the whole
  interface.
- Large or regenerable data that is not a deliverable belongs in the bot's `<slug>.data/`
  sibling directory on the Mac, never in git and never in the bucket.

## Recipes

- Start of a task with attachments: copy everything under `<slug>/inbox/<task>/` to a working
  directory, then work from there.
- End of a task: copy the outputs to `<slug>/deliverables/<task>/`, then paste the `s3://`
  URIs under **Deliverable** in `hub task update <id> --status done --note ...`.
- Topic research from other bots' work (Content & Social): `aws s3 ls
  s3://$HUB_BUCKET/listening/deliverables/ --recursive` when the bot's `access:` grants it.

## Gotchas

- `working/` objects disappear after 30 days; anything worth keeping goes to `deliverables/`.
- The profile reaches one bucket only; an `AccessDenied` on any other bucket or service is the
  design, not a broken key (see `integrations/aws.md`).
- A presigned URL pasted into a task is dead by the time a person opens it.

## Learnings

What bots and people learn about this integration is added with `hub learn hub-storage "…"`
and shown under this page; a person folds it into the page over time. The page is the rule.
