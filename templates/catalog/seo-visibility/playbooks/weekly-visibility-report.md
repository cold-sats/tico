# Weekly search and AI visibility report

Schedule: Mondays at 08:00 company time (routine `weekly-visibility-report`), once a person has
approved the first report. Also run by hand on request. Budget 45 minutes. The outcome is one report:
how the company shows up in search and AI answers, three fixes with drafted changes, and the gaps.
Nothing on the site changes.

---

## 1. Read where things stand

    hub task show <id>

Then last week's report, `knowledge/prompts.md`, `knowledge/pages.md` and `knowledge/competitors.md`.

## 2. Check the tracked questions

For each question in `knowledge/prompts.md`, ask each assistant the owner uses, or read the
AI-visibility tool where connected. Record: was {{company_name}} named, in what words, which
competitors were named, which pages were cited. Quote the phrase and date it. Compare with last week.
A single answer is an anecdote; report movement only where it repeated.

## 3. Read search performance

Where Search Console is connected, read clicks, impressions and position for the pages in
`knowledge/pages.md`, and the queries that gained or lost most since last week. Where it is not,
say so in the report and use public checks only. Never estimate a number.

## 4. Look at the pages as a stranger

For the two or three pages that matter most this week, follow `playbooks/page-audit.md`.

## 5. Choose three fixes

Rank what you found by likely effect on a buyer finding an answer. For each: the page, the problem,
the drafted change (exact new title, description or paragraph, in the company's voice), and how a
person applies it. Put drafts in `knowledge/drafts/`. A content gap is a proposed brief for the
content bot, not a task you create.

## 6. Write the report and hand it over

`reports/YYYY-MM-DD-visibility.md` in the shape of `knowledge/examples/visibility-report.md`. Then:

    hub files publish reports/YYYY-MM-DD-visibility.md

Commit, then `hub task update <id> --status done --note`: the headline, the path, what you could not
read. Always finish it: an open scheduled task absorbs the next.

## When a source fails

Name it in the closing line: which assistant, page or export could not be read, and what is
therefore unknown. A blocked source is never "no change".
