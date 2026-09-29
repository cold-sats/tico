"""Rule 7's verb check (backend/hubdb.py `_is_verb_opener`): a real imperative passes, a label or a
noun phrase does not. `Connect` and `Authorize` were refused on 2026-09-28 because the list was short."""

import pytest

from backend import hubdb as H

PASS = [
    "Connect GitHub to the hub", "Authorize the GitHub app for the acme org", "Configure the Slack gateway",
    "Publish the pricing page", "Grant Ben access to the finance folder", "Rotate the OIDC client secret",
    "Approve the reply about 20% fees", "Enable sign-in for the new domain", "Disable the old webhook",
    "Migrate the mailbox to the new server", "Rename the support bot", "Verify the tico.team DNS record",
    "Provide the Cloudflare API token", "Review the Q3 budget", "Reply to Dana about the renewal",
    "Decide whether to renew the Vercel plan", "Sign the vendor agreement", "Install the runner on the Mac mini",
    "Approve: send the refund", "review the draft", "Choose a backup bucket", "Upgrade the runner to 0.2.4",
    "Create the empty repository for the new bot", "Sanity-check the export scan output", "Wire the Stripe webhook",
    "Reconcile the March invoices", "Unblock the deploy by approving the change", "Whitelist the office IP",
]
FAIL = [
    "Needs-you: the brief", "Needs you: sign the lease", "FYI: the brief", "URGENT budget question",
    "The budget needs a decision", "A question about the lease", "Reviewing the draft", "Reviews are waiting",
    "New hire paperwork", "3 drafts waiting", "PR needs review", "Decision on pricing",
    "Your token expired", "Waiting on legal", "Needs approval for the spend",
]


@pytest.mark.parametrize("title", PASS)
def test_a_real_imperative_passes(title):
    assert not [p for p in H.lint_human_item("Please do this by Friday.", title=title) if "verb" in p]


@pytest.mark.parametrize("title", FAIL)
def test_a_label_or_noun_phrase_is_refused(title):
    assert any("start the title with a verb" in p for p in H.lint_human_item("Please do this by Friday.", title=title))
