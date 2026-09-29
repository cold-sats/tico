---
service: aws
title: AWS
kind: cli
summary: The hub IAM user every turn carries (bucket only), an optional read-only platform view for an engineering bot, and an optional scoped production profile.
access: "the AWS CLI with the turn's preset `AWS_PROFILE`; a wider scope only where a bot's `access:` names it"
credentials:
  - "AWS_PROFILE — preset in every turn: the `hub` IAM user, which reaches only the bucket <company>-tico-hub"
  - an optional production profile in ~/.aws/credentials on the owner's computer, declared as `aws-production` only by the bots that need it
declared_as: |
  - service: aws
    identity: hub IAM user
    can: [read]
    env: AWS_PROFILE
    note: today this profile reaches only the S3 bucket
  - service: aws-production
    identity: AWS profile production, us-west-2
    can: [read, write]
    note: one application's EC2/S3 only; SSM, incremental writes, no instance or proxy changes
writes: approval
owner: owner
---

## What it is

Three different things share the name:

1. **The bucket profile.** `AWS_PROFILE` in every turn is the `hub` IAM user, and it
   can reach one thing: the `<company>-tico-hub` bucket (`integrations/hub-storage.md`).
2. **An optional platform view.** An engineering bot's `aws` access entry can ask for Cost
   Explorer, CloudWatch, ECS, RDS, CodePipeline and CodeBuild reads. Until a read-only policy
   for that is attached, its platform section says "needs access" instead of failing. What
   unlocks it: a second scoped IAM user or policy the owner adds, and the profile name in the
   bot's env file.
3. **Optional production access for one application.** A bot that deploys or reads one
   application can declare `aws-production`: a named profile for that application's EC2
   instance and S3 bucket only, SSM to a named instance, incremental writes, no instance or
   proxy changes. Such a profile is often the owner's own admin profile and is reachable from a
   run on their computer; the declared scope is the whole boundary, so a bot touches nothing
   outside it.

The reference deployment runs on one EC2 instance: SQLite on an encrypted EBS volume,
attachments in a private bucket, backups to S3 twice over (Litestream every ten seconds and a
daily verified bundle), KMS for the credential vault, Cloudflare Access in front. That is the
hub's infrastructure (`infra/`), operated by CI and the owner, not a bot's tool.

## What data it has

For a bot: the bucket (see hub-storage). For an engineering bot, once granted: cost and usage, CloudWatch
metrics and alarms, ECS services and events, RDS instances, pipeline and build history — the
same signals your alert channels in Slack carry. For a production-profile bot: the instance and
bucket that serve its application.

## How a bot uses it

```bash
aws sts get-caller-identity                                   # which user this turn is
aws s3 ls s3://$HUB_BUCKET/<slug>/                            # the bucket profile's whole world
aws cloudwatch get-metric-statistics --namespace AWS/RDS --metric-name CPUUtilization \
  --dimensions Name=DBInstanceIdentifier,Value=<id> --start-time ... --end-time ... --period 300 --statistics Average   # engineering bot, once granted
aws ssm start-session --target <instance-id> --profile production --region <region>   # production-profile bots only
```

## Rules

- Use the profile the turn gives you. Never pass `--profile production` unless your `access:`
  declares `aws-production`, and then only for the instance and bucket named on this page.
- No infrastructure changes from a bot: no instance, security-group, DNS, IAM, Caddy or
  deployment change. Those are production changes under `policies/approvals.md`.
- Read-only means read-only: describe, list, get. A "needs access" line in a report is the
  right answer to a missing permission; borrowing a wider profile is not.
- Nothing about the hub's own AWS account (the EC2 instance, its volume, its buckets, KMS) is
  a bot's to touch; deploys come from CI on every merge to `main`.

## Recipes

- Confirm the scope before a report: `aws sts get-caller-identity` and one `aws s3 ls`; an
  `AccessDenied` elsewhere is expected with the bucket profile.
- An engineering bot's platform watch: read the Slack alert channels first; switch the sections to the
  CLI calls above once the owner attaches the read-only policy.
- Application deploys and reads: through SSM on the named instance, with the repository's own
  documented commands, in an isolated worktree.

## Gotchas

- `AccessDenied` from the bucket profile on anything but `<company>-tico-hub` is the design, not
  a broken key.
- `~/.aws/credentials` on the owner's computer holds more than the bot profile; that a profile is
  reachable does not make it declared.
- Region matters: a call without `--region` uses the profile's default, which may not be the
  region your resources are in.

## Learnings

What bots and people learn about this integration is added with `hub learn aws "…"` and shown
under this page; a person folds it into the page over time. The page is the rule.
