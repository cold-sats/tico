delegation: done - BotOps keeps its actual runner, attempt and agent identity when acting for a requester; write-lock revocation checks and private participant intersection remain enforced - 67 original failing cases pass.
claim selection: done - end the privacy read snapshot before checking data_version under the write lock, so a concurrent drain or private reassignment forces selection again - original drain case and six focused security/claim cases pass.
contract expectations: done - ordinary company reads still deny unrelated writes; task downloads require no-store; ordering fixtures use existing ordinary sources; migration checks include the appended schemas and retain data-preservation assertions - 67 original failing cases pass.
combined release gate: not done - the coordinator owns the complete integrated Python and browser checks; two unrelated original failures remain assigned to that lane - no full suite run here.

New checks cover actual BotOps identity, private read intersection, human-only publication, runner and lease revocation between authentication and the write lock, and private reassignment between claim selection and mutation. The bounded claim checks retain unchanged-selection reuse and idle claims that avoid the write lock. No authorization rule or released migration changes in this follow-up.

DONE
