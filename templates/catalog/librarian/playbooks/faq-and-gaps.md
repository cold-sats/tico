# Gaps, the log and the FAQ

Three docs record what people ask and what the docs could not say. You write them after the answer is
sent, never before. Each is written with `hub doc write <path> --title "<title>" --body-file <file>
--note "<what>"`. Read the current one first; add to it; never rewrite what is there.

Keep names, emails and any personal detail out of all three. Paraphrase a question to its general form
("how long do refunds take") rather than quoting a person's wording with their details in it.

## `_librarian/faq-log.md`: one line per answered question

    - 2026-09-29 | How long do refunds take? | 14 days, annual plans only | [Internal doc · Refund policy](doc:d7f3) v5 | covered
    - 2026-09-29 | Do we sell gift cards? | not in the docs | - | gap

- Date, the question in its general form, the answer in a few words, the docs it rests on with the version
  you read, and `covered` or `gap`.
- One line per answered question, newest at the bottom. If the same question is already there, add another
  line: the count is what matters.
- When the log passes 300 lines, fold the oldest 200 into a `## Older, counted` list of question and
  how many times it was asked, and keep the rest.

## `_librarian/missing.md`: what the docs could not answer

    ## Not in the docs
    - Do we sell gift cards? Asked 3 times, last 2026-09-29. Closest: [Internal doc · Refund policy](doc:d7f3).

    ## Docs that disagree
    - Trial length: [Internal doc · Pricing](doc:a1) says 14 days, [Linked · help.example.com](https://help.example.com/trial) says 30.

    ## Sources I could not read
    - Drive folder "Contracts": not shared with anyone with the link (2026-09-27).

    ## Out of date
    - [Internal doc · Onboarding](doc:b2) names a tool the pricing doc says was retired.

- Add a gap the first time you say "Not in the docs", with the count and the date after that; a gap is
  its most useful when it says how often it is asked.
- When a question is now answered (someone wrote the doc), remove its line and say so in the `--note`.
- Order each section with the most-asked first.
- This is a to-do list for people. The daily routine's task note tells them to read it; keep it short
  and specific enough to act on.

## `FAQ.md`: the answers that keep being asked

Promote a question to `FAQ.md` when it has been asked **three times** in the log and its answer is stable
(the same docs, a covered answer). One entry: the question, a short answer, its citations, the date last
confirmed.

    ## How long do refunds take?
    Within 14 days of the request, for annual plans only. [Internal doc · Refund policy](doc:d7f3)
    *Confirmed 2026-09-29.*

- Group under headings by topic once there are more than ten.
- Only what docs say now: when you answer a question that has an FAQ entry, read the docs anyway and
  update the entry (or remove it) if they changed.
- Never promote a gap: an answer the docs do not give is not an FAQ.
- FAQ.md is an internal doc like any other and is searched first: that is the point, since the next
  person's question finds it directly.
- An owner or a bot admin may lock it. If a write is refused as locked, put the entry in `missing.md`
  under "Docs that need an update" and move on.
