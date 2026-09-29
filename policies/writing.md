# Writing policy

- Lead with the outcome. Then what the reader must do, if anything.
- Short sentences. No filler, no restating the request.
- Task titles: verb first, under 70 characters. "Investigate organic traffic drop", not "SEO stuff".
- Comments: only when they change what someone should do next.
- Reports go in your repo under `reports/YYYY-MM-DD-<slug>.md`. When a person is to read one,
  attach it to the task (`hub task attach <task-id> reports/<file>.md`) and put the link it prints
  in your note. A path on your Mac or an `s3://` URI is not a link anyone can open.
- Durable learnings go in `memory/learnings.md`. Decisions and their reasons in `memory/decisions.md`.
- Shared knowledge goes to the hub via PR to `docs/`.
- Follow `documentation.md`: bot-local docs are autonomous, ordinary shared internal `docs/` PRs
  may be self-merged, and external docs stop in one reusable pull request for the owner to review.

## Rules and the log

`AGENT.md` and `policies/*.md` hold only current rules: present tense, no dates, no history, no
measurements. When a rule changes, replace it rather than appending an exception. Every dated
decision and its reason goes to the log: `memory/decisions.md` for one bot, the decision log for shared rules; newest first, one line each, `YYYY-MM-DD — <decision> — <reason>`. A number
that justifies a rule goes in the log; the rule states the threshold.
