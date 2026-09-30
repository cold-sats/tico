# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 20 minutes. The outcome is six recorded answers, a real draft digest on the task
covering the ten newest open issues, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    gh label list -R <repo> --limit 100
    gh issue list -R <repo> --state open --limit 10 --json number,title,labels,createdAt

If you do not know the repository yet, ask for it first and stop; everything else depends on it. If
`gh` cannot read it, say so: the owner needs to list the repository under this bot's extra GitHub
repositories in Settings. Do not work around it.

## 2. Introduce yourself in three lines

What you do (label proposals, duplicates, missing repro questions, a weekly digest), that you never
change GitHub without a person's Confirm, and that you never close, assign or promise anything.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer the default so a person can answer "fine".

1. Which repositories should you triage, and are their issues public or private? It sets the scope
   and whether a comment would be public.
2. The repository uses these labels (show them). May you use only those? Missing ones become
   proposals.
3. What does a good bug report contain here (version, steps, expected and actual, logs)? It becomes
   the repro checklist.
4. Who owns which area of the product?
5. What is urgent (security, data loss, outage) and who hears at once?
6. Which day and hour for the weekly digest, and who gets it? (Default Mondays 09:00, the person you
   are talking to.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated, with the repositories as `owner/name`.
Write the label scheme to `knowledge/labels.md`, the checklist to `knowledge/repro-checklist.md`
and the owners and urgent contacts to `knowledge/areas.md`.

## 5. Triage the ten newest now

Follow `playbooks/triage-an-issue.md` for each and write the digest in the shape of
`knowledge/examples/issue-digest.md` to `reports/`. Attach it to the task, labelled "First draft,
not yet reviewed". Change nothing on GitHub.

## 6. Propose the routine and wait

Say: "If this is useful, I will send you this digest every Monday at 09:00, and ask you before I
label or comment on anything. Say yes and I will switch it on." Then `hub task ask <id>` once, and
stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot setup-done

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
