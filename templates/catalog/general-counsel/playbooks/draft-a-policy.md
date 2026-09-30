# Draft a policy

Triggered by a task asking for a policy, or by a gap `knowledge/policies.md` records. Budget 45 minutes. The
outcome is a draft a person can adopt with small edits, with its sources and its open questions. It is a draft
for a person, not legal advice, and it is not in force until the owner adopts it.

---

## 1. Scope it

    hub task show <id>
    hub docs search "<policy topic>"

Write down: who it applies to, what it covers and does not, which laws or customer contracts require it (from
`knowledge/obligations.md`; "not checked" where you have not), and who will own it after adoption. Read the
company's existing policies so the new one uses the same terms and does not contradict them.

## 2. Draft

Plain language, one page where the subject allows: purpose, scope, the rules as numbered "we do / we do not"
statements, who to ask, what happens on a breach (a person's decision, never automatic), owner and review date.
Mark every choice the company must make as `[DECIDE: ...]` with the options. Do not copy another company's policy.

## 3. List what it rests on

Under `## Sources`: each law, contract or document it draws on with its date, and every place you assumed.
Under `## Open questions`: the decisions, and whether counsel should review before adoption.

## 4. Hand over

Save `reports/policies/<name>-draft.md`, `hub files publish` it, and put it on the task with the one line:
"Draft for a person, not legal advice. Adopt it here, and I will hand it to the Librarian to publish." Add it to
`knowledge/policies.md` as "draft". Only after the owner adopts it on the task: `hub task create --owner librarian
--title "Publish the <name> policy" --body "<path, adopted by, date>"`.
