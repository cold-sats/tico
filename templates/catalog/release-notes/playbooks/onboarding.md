# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 25 minutes. The outcome is six recorded answers, a real draft of the next release's notes on the task, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    gh release list -R <repo> --limit 5
    gh pr list -R <repo> --state merged --limit 40 --json number,title,labels,mergedAt

Check what you can already reach: the last release and its notes, the repository's CHANGELOG format, and the labels its pull
requests carry. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (draft a changelog entry and plain-language release notes from merged pull requests), that you never publish, tag or edit the CHANGELOG, and that a human decides the version.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine".

1. Which repositories are released, and how: on every merge, on a schedule, or by hand? What was the last release? Why: Sets the range of merged changes I read: everything since that release.
2. Where do release notes go today: a CHANGELOG file, GitHub releases, a help page, an email? Can you paste the last two? Why: I match your format and voice, and I draft for the place you use.
3. Who reads them: customers, internal staff, both? How technical are they? Why: Sets the language. Customers get what changed for them, never a pull request title.
4. Which labels or prefixes mark a change as a feature, a fix, a breaking change or a security fix? Which changes never appear (dependency bumps, refactors)? Why: I group by your labels first. Without them I classify from the text and mark each guess.
5. How do you number versions? (Default: semantic versioning, major.minor.patch.) Why: I suggest the next number from what changed: breaking is major, a feature is minor, a fix is patch.
6. Which day should the draft land, and who reviews it? (Default: Fridays at 14:00, to you.) Why: Sets the recipient and the first routine's schedule.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/versioning.md` (how versions are numbered and what makes a breaking change) and `knowledge/voice.md` (the format and voice, with the two pasted examples).

## 5. Do the first piece of work now

Take everything merged since the last release and follow `playbooks/weekly-release-notes.md`. Write the draft in the shape of `knowledge/examples/release-notes.md` to `reports/`, attach it to the task, labelled "First draft, not yet reviewed". Publish nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will draft the release notes every Friday at 14:00, and a human publishes them. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a human approved your first routine. That clears your "Needs setup"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer humans only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the run; the
human's next message is the answer.
