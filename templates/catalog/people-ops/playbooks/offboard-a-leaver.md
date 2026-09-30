# Offboard a leaver

Triggered by a task naming a leaver and a last day. Budget 25 minutes. The outcome is a checklist with
an owner and a date for every item, proposed for approval, and a plan to confirm access is gone. You
remove nothing yourself.

---

## 1. Read the request

    hub task show <id>
    hub team show

Role, team, manager, last day. If the HR owner marked it sensitive (a dismissal, a dispute), build only
what they ask for and record no reason anywhere.

## 2. Build the checklist

Start from `knowledge/offboarding-base.md`; cut what does not apply.
- **Before the last day:** knowledge handover plan with the manager (open work, documents, customer and
  vendor contacts), shared passwords this person knows listed for rotation, final pay information to the
  payroll owner, benefits end date to `benefits`, exit interview offered, equipment return arranged.
- **Last day:** privileged access removed (admin, finance, production, owner roles), single sign-on and
  mail disabled, other tools removed, devices returned, building access ended.
- **Day after:** each access owner confirms in writing; mail forwarding or an auto-reply per policy.
Each item: what, owner from `knowledge/systems.md`, due date.

## 3. Propose

Attach the checklist and ask the HR owner once with `hub task ask <id>`. On a yes, create one task per
owner: `hub task create --owner <owner> --title "<leaver ref>: <item>" --due <date> --parent <id>`.

## 4. Confirm

The day after the last day, read each item's task. Anything without a dated confirmation is chased once
and, for privileged access, goes straight to the HR owner. Update `knowledge/leavers.md`.

## 5. Close

When every item is confirmed, `hub task update <id> --status done --note` with the confirmation dates.
