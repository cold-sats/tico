PR14 inbound scope: done - one authenticated inbound write route, per-key task mapping, task-id acknowledgments and private-task rejection - five focused service-key tests passed
PR14 credential handling: done - write-lock revocation recheck and hash-only mint storage, including retry acknowledgments - five focused service-key tests passed
PR16 authorization: done - author-only plain comments, current task reads on cached retries and existing comment write/contact gates - initial nine security tests and four existing comment contracts passed; integrated revision recorded in FIX/privacy/CHANGES.md
PR16 withdrawn content: done - clear tombstone text, metadata-only events, refreshed cached message objects and deletion filtering for SQL, API and bot reads - comment security and SQL guards passed
PR16 compatibility: done - preserve structured file reviews, task UI, existing support and shared-bot behavior while adding comment edit/delete operations - four OpenAPI contracts passed; JavaScript syntax checks passed
Validation limits: partly - optional broader SQL/file-review checks interrupted after 25 passing tests; first pass fixed one test-only inbox assertion - total pytest time 200.08 seconds
The integrated revision permits current plain-comment edits and deletion after delivery, cancels unsent copies and does not send retroactive updates. Existing provider sessions and delivered copies cannot be recalled. Comments with independent file/review records remain unsupported for mutation; the initial broader delivery exclusion was removed during coordinator review.
DONE
