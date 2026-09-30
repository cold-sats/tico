# Tag a batch of feedback

Triggered by a task that attaches feedback (an export, survey responses, call notes), and used in
`playbooks/weekly-feedback-report.md`. Budget 20 minutes for a hundred items. The outcome is a tagged log
and the counts.

---

## 1. Read the batch and the theme list

Read `knowledge/themes.md` first. Read the whole batch before tagging, so a new theme is noticed once and
named consistently.

## 2. Tag each item

For each item record, in one line of the log: source, date, one primary theme, severity (blocked: the
customer cannot do what they came to do; annoyed: they can, with pain; suggestion: a wish), sentiment,
segment from `knowledge/segments.md`. An item that spans two themes takes the one the customer is most
upset about, and the other is a note. Remove names, emails, account ids and any credential.

## 3. Handle what does not fit

- Three or more items on one new subject: add a theme with a definition and an example, dated today.
- Fewer: tag them "unclassified" and keep the count.
- Anything on the exclusion list, or that names safety, security or a legal threat: do not cluster it.
  Make a task for the person named in `knowledge/segments.md` the same day and leave a count only.

## 4. Check yourself

Re-tag a random ten items without looking at the first tags. If two or more differ, tighten the
definitions in `knowledge/themes.md` before counting.

## 5. Count

Add the counts to `knowledge/trends.md` and the item log to `knowledge/log/`. Put the totals on the task:
items read, by source and by theme.
