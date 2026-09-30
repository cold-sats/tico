# Prepare a signature packet

Triggered when a human approves an NDA or standard agreement for signature on its task. Budget 10 minutes.
The outcome is a packet a human can send in one step, and, once signed, a filed copy and an index row. You
never send it and never sign it.

---

## 1. Confirm the final version

    hub task show <id>

The packet uses the exact version the human approved on the task: name the file and its date. If anyone
changed it after the approval, stop and ask.

## 2. Build the packet

`reports/packets/<party>-<kind>.md`:
- the document to sign (the approved file), and anything it references that must travel with it;
- the signers from `state.md` setup answers, their titles and the order (the other side first or us first);
- the legal names of both parties exactly as written in the document;
- a short cover note for the human to send, three sentences, no legal commentary.

## 3. Ask for the send

Put the packet on the task. If the human wants it sent from the platform, request
`hub approval request --kind send` with the file, the recipient and the cover note; otherwise the human sends
it from their own mail or e-signature tool. Either way, say "sent by a human" in the task.

## 4. File the signed copy

When the fully signed copy comes back on the task: check every signature block is complete and the dates are
filled; list anything missing instead of filing. Then add a row to `knowledge/executed-index.md` (parties, kind,
date signed, confidentiality period and its end date, where the file lives), commit, and
`hub task update <id> --status done --note`.
