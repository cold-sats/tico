PR14 inbound scope: done - one authenticated inbound write route, per-key task mapping, task-id acknowledgments and private-task rejection - five focused service-key tests passed
PR14 credential handling: done - write-lock revocation recheck and hash-only mint storage, including retry acknowledgments - five focused service-key tests passed
PR16 authorization: done - author-only plain comments, current task reads on cached retries, existing comment write/contact gates and safe delivery exclusions - nine new security tests and four existing comment contracts passed
PR16 withdrawn content: done - clear tombstone text, metadata-only events, refreshed cached message objects and deletion filtering for SQL, API and bot reads - comment security and SQL guards passed
PR16 compatibility: done - preserve structured file reviews, task UI, existing support and shared-bot behavior while adding comment edit/delete operations - four OpenAPI contracts passed; JavaScript syntax checks passed
Validation limits: partly - optional broader SQL/file-review checks interrupted after 25 passing tests; first pass fixed one test-only inbox assertion - total pytest time 200.08 seconds
Delivery exclusions are conservative: possible bot contexts, tracked posts, untracked external agents and comments with independent file/review records cannot be recalled here. The separate private-task core gate remains coordinator-owned.
DONE
