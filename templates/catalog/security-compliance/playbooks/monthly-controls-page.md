# Monthly evidence and controls page

Schedule: the first of each month at 10:00 company time (routine `monthly-controls-page`), once a
person has approved the first page. Budget 40 minutes. The outcome is one page and, for the approved
owners, one evidence request each. Nothing in any system is changed.

---

## 1. Close last month

For every control due last month: is the evidence filed in the evidence folder and logged in
`knowledge/evidence-log.md`, with a date inside the period? Mark **collected**, **claimed** (owner says
done, no file), or **missing**. A missing item for a closed period is the page's first line.

## 2. Open this month

List every control due this month from `knowledge/controls.md`: owner, what evidence exactly (for
example "screenshot of backup restore test with date", "export of admin users from the cloud console
with the review note"), and the due date. Quarterly and yearly controls appear in their month.

## 3. Access reviews

In the first month of a quarter, start `playbooks/access-review.md` for every in-scope tool, and list
last quarter's reviews that are still undecided.

## 4. People and vendors

From `knowledge/acknowledgements.md`: people who joined more than 14 days ago without accepting the
policies, and yearly acceptances overdue. From `knowledge/vendor-reviews.md` and the vendor register:
vendors holding company or customer data with no security review, or one older than a year.

## 5. Write and hand over

Write `reports/YYYY-MM-DD-controls.md` in the shape of `knowledge/examples/controls-page.md` and
`hub file publish` it. For owners on the approved list, `hub task create --owner <person>` with the
exact evidence, the control and the due date. Commit, then `hub task update <id> --status done --note`.
