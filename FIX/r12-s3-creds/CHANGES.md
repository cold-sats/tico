Independent PR review: done - reviewed the original S3 candidate and fixed verified upload, concurrency and resource issues - focused fake-S3 tests listed below.
Upload selection race: done - all upload paths return retryable 503 before selection or after a failed probe, without HEAD, PUT or multipart calls to an unselected/denied source - test_uploads_reject_unselected_and_denied_sources_then_heal; test_blocked_probe_gates_uploads_and_reuses_one_in_flight_check.
Selection and healing: done - retained auto order keys/backup/default chain, explicit mode isolation, shared download identity and 30-minute failed-check retries; check_write now returns the real selection result so denied checks cannot start local copying - existing selection, explicit-mode, cleanup and healing tests plus new upload gate tests.
Multipart identity: done - each upload snapshots its client through parts, completion and abort, even if a later check changes the shared source - test_multipart_keeps_its_selected_identity_through_completion_or_abort and existing multipart integrity/copy tests.
Bounded checks and credential discovery: done - one probe remains in flight per Blobs instance, probe callers stop after five minutes, canceled work cannot select later, and client construction shares at most one worker per kind/access mode with a five-second wait - test_blocked_probe_gates_uploads_and_reuses_one_in_flight_check; test_probe_deadline_bounds_provider_and_s3_latency_without_reselecting_late; test_pending_read_client_construction_is_bounded_shared_and_keeps_local_fallback; existing shutdown tests.
Probe cleanup: done - retained the single durable pending multipart check, cross-source abort, NoSuchUpload handling, separate short-timeout clients and closed temporary clients; serialized Health snapshots and writes so timeout warnings cannot erase a concurrently returned cleanup ID - existing cleanup tests, new cancellation/deadline tests for client/create/abort stages and test_timeout_health_update_preserves_a_concurrently_returned_cleanup_id.
Read fallback and privacy: done - retained AccessDenied GET/HEAD retries, local byte-exact fallback, successful-reader signing and sanitized SDK failures; added safe handling around normal client construction - existing denied-read/download/health tests; test_upload_client_construction_errors_never_expose_credentials.
Download manifest bounds: done - one shared bucket fetch, a monotonic 60-second cache including failures, brief cold-cache waits, a 1 MiB parsing bound and response closure on every read outcome - test_bucket_manifest_reads_are_bounded_closed_and_failures_cached; test_bucket_manifest_fetch_is_single_flight_without_holding_lock.
Read network budget: done - GET/HEAD use separate cached clients with 2-second connect and 5-second read timeouts and one total attempt, while upload clients retain the existing budget - test_read_network_budgets_are_bounded_without_shortening_upload_timeouts; test_download_storage_uses_blob_region_endpoint_and_prefix; local botocore default inspection.
Main preservation and compatibility: done - rebased onto origin/main, kept support diagnostics, shared-bot policy and all migrations; runner upload contracts stay unchanged and the Health credential field is additive - existing byte-exact/range/legacy multipart tests in test_storage_delivery.py; diff review.
Earlier seven-review fixes: not done - the referenced v032-work/r12-fix/BRIEF.md does not exist; its seven findings cannot be identified or verified and are not claimed complete - filesystem check.
Live AWS verification: not done - no AWS calls, production changes, pushes, tags, PRs, issues or releases were made - all S3 evidence is from fakes.

Independent findings and evidence

- Critical: the original Sources.kind defaulted to the first candidate before selection, while Blobs._upload called that client with no readiness gate. A denied or merely slow startup check therefore allowed upload attempts. The 12 mode/upload-path gate cases now prove zero upload-side S3 calls before selection and after denial, followed by exact-byte success after healing.
- High: original check_write returned True whenever its worker completed, even when the probe found no writable identity. copy_local consequently attempted copies after denied checks. Returning the actual ready state prevents those attempts; the denied-storage delivery test now expects zero copy failures because copying never begins.
- High: original _upload looked up self.s3 again for every multipart operation and abort. A changing shared selection could send another identity a multipart upload ID. Success and failure tests change selection after creation and prove completion/abort remain on the original client.
- High: original check_write created a daemon for every concurrent caller. Callers that returned during shutdown left active probes that later callers could duplicate, defeating the single-pending-upload cleanup rule. Shared in-flight state and cancellation tests prove only one probe survives a stopped caller.
- High: original read-client construction ran synchronously under the shared client lock, and the probe's S3 Config did not bound work before client construction returned. Stalled credential discovery could block reads and a probe indefinitely. Tests block the SDK constructor and prove bounded caller waits, retained local bytes, one construction per kind, one shared probe, a Health timeout and no late selection.
- Medium: original bucket_manifest read the entire object and allowed simultaneous cache misses to fetch separately. Oversized/error streams and warm/cold concurrent callers now prove bounded reads, response closure, cached failures and one fetch.
- Medium: Sources constructed its first GET/HEAD client without Config, retaining the SDK's 60-second connect/read defaults and variable retry policy. Separately cached read clients now use the explicit short network budget; the focused test checks the forwarded Config, reuse and unchanged upload budget.

Exact validation

- python -m pytest -n 0 backend/tests/test_blob_s3.py backend/tests/test_blobs.py backend/tests/test_downloads.py backend/tests/test_storage_delivery.py -q
  - Initial run: 176 passed, 1 failed in 39.92s; the failure was a missing content_type argument in a newly added test, corrected before the final runs.
  - Implementation run: 181 passed in 47.42s.
  - Rebased candidate run: 181 passed in 41.28s.
  - Final cleanup serialization run: 181 passed, 1 failed in 43.14s; the new database test proxy omitted commit/rollback forwarding, corrected before the final S3 run. All 83 cases outside test_blob_s3.py passed on the final implementation in this run.
- python -m pytest -n 0 backend/tests/test_blob_s3.py -q
  - Final run after correcting the test proxy: 99 passed in 6.23s, including the cleanup-ID race regression. Together with the 83 unchanged focused cases above, all 182 focused cases were verified. Total focused test time across all runs: 177.99s.
- python -m pytest -n 0 backend/tests/test_blob_s3.py backend/tests/test_downloads.py -q
  - Read-budget follow-up: 118 passed in 9.89s, including the additional network-budget test. The 65 unchanged focused storage cases passed above. Total focused time including this requested follow-up: 187.88s; no full suite.
- Local Config() inspection confirmed the previous defaults: connect_timeout=60, read_timeout=60, retries=None. Exact local interpreter details are retained only in the private takeover notes.
- git diff --check: passed.
- The full suite was not run; the coordinator owns that integrated-candidate check.

Integration contract for the separate downloads change

- Keep install_downloads constructing Downloads(store.settings, s3_source=app.state.blobs). The production Downloads instance must share Blobs rather than allocate an independent Sources selection.
- The source supplies s3 for the currently preferred read/selected client and read_s3(operation, **options), returning (response, successful_client). file_url must sign with the successful HEAD client. Read fallback does not mutate write selection.
- Upload permission is governed by Blobs, not by accessing source.s3. A caller-provided Blobs client is an explicit selection used by offline storage tests; assigning the private _s3 field does not select a source.
- Preserve the single-flight bucket manifest state, monotonic cache, bounded body read and stream.close when integrating other download changes.
- GET/HEAD use a separate short-timeout client for the same credential kind; callers must sign with that successful reader, not replace it with the normal upload client.

Remaining limits and review provenance

- SDK calls already running cannot be forcibly interrupted. The server bounds construction/probe waits and retains at most one probe worker plus one construction per available kind/access mode (at most six), instead of spawning replacements while those calls remain active. Socket timeouts still apply to probe S3 operations; shutdown remains prompt.
- Read budget: each candidate has at most a five-second client-construction wait, 2-second connect timeout, 5-second read inactivity timeout and one request attempt. At most three candidates are tried, only after AccessDenied. These are not an overall wall-clock guarantee: DNS resolution, credential refresh after construction and a continuously active streaming response may outlast the socket budget. Actual AWS timing is unverified; the fake test proves Config forwarding and reuse, not live network deadlines.
- Real IAM/provider behavior and remote cleanup after abrupt process loss are unverified without AWS access. The existing bucket lifecycle remains the backstop for incomplete remote uploads; the fake tests verify known pending IDs, denied cleanup, cross-source abort and restart-style recovery.
- Local backup ref: backup/r12-s3-creds-takeover-20261002, retaining original commit 0b77fb6d. The unpublished feature commit was rewritten without its old session trailer before rebasing; all new commits use plain messages.
- These are independent findings, not a reconstruction of the missing seven-fix brief.

DONE
