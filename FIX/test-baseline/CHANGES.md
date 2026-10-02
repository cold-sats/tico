Download concurrency: done - a fixed module-local monotonic clock expires the cache on freshly booted workers; cold callers still prove the 100 ms bounded wait and warm callers skip it - focused Mac 34 passed in 17.29s; Linux 36 passed in 20.05s.
Multipart header limits: done - normalize only the parser's two known header-cap errors without changing its caps or generic malformed-upload response; reject closes earlier part spools and staging stays private - final Linux subset 15 passed in 7.35s with python-multipart 0.0.32.
Runner config permissions: done - emit BSD stat output only on success before the GNU fallback, assert installation success and retain explicit rejection of mode 0644 - final Linux subset includes all 11 systemd tests.
Shared-bot rebases: done - configure fictional repository-local commit identities while keeping ambient Git config and identity isolation - all shared-bot tests passed locally and in a network-disabled Linux container.
Maintenance lease renewal: done - advance one controlled renewal tick after execute reaches the held real maintenance lock, retaining the real renewal loop and completion assertion - Mac and Linux focused sets passed.
SSE fixture: done - disconnect after the real initial snapshot and goal frames instead of buffering 55 unused updates; assert both frames and preserve execution text and message run metadata - final Linux subset passed.
Granola fake time: done - use the server's three-second interval, exact 3s/4.5s sync deadlines, stopped-timer and cancel checks; install the clock before its fixed pause target to survive host scheduling delays - final Granola script passed in 17.7s at load near 48.
Agent connection fake time: done - keep desktop/phone, light/dark, token storage/URL/log privacy, revoke and copy checks; verify the exact three-second poll and no poll after close - final script passed in 19.5s at load near 48 (earlier lower-load pass 7.7s).
Chat timing: done - advance the offline retry horizon with fake time; retain real EventSource delivery with explicit initial/stale/current barriers so a fresh snapshot cannot hide a stale-snapshot failure - chat script passed in 28.3s during heavy load; final early-send script passed in 11.1s.
Duplicate theme workflows: done - remove six duplicate light-theme Granola functional scenarios after coordinator review; retain all functional contracts once plus desktop/phone code, connected row and menu geometry in both themes - final Granola script passed; no Python tests or browser scripts deleted.
Combined release gate: done - scripts/release_checks.py runs unfiltered Python and all browser scripts, reports each duration and start/end load, and fails a green run taking 300 seconds or more - syntax checked only; coordinator owns the combined run.
Integrated full-suite acceptance: not done - the coordinator must verify one green under-300-second combined run on the actual integrated release candidate; focused results do not establish that acceptance.

Coverage map

| Removed duplicate | Retained contract | Retained presentation |
| --- | --- | --- |
| Light connect/pending/connected flow | Dark code, safe link, focus, live region, server interval, exactly one sync and stopped device polling | Code fits desktop/phone in dark/light |
| Light expired, denied, needs-sign-in flows (three copies) | Dark error text, alert role, restored focus, no code, no sync and stopped polling | Both themes retain code and account layout |
| Light connected sync/menu/disconnect flow | Dark list refresh after sync, 3s/4.5s backoff, no duplicate sync, note/skip counts, keyboard menu and disconnect | Connected row and open menu fit desktop/phone in dark/light |
| Light signed-out/reconnect/cancel flow | Dark signed-out facts, no sync, reconnect and cancellation | Both themes retain account layout |

Owner/member, old-server API-key fallback, unsafe sign-in links and existing in-flight sync checks remain unchanged in scope. Real SSE wire parsing remains covered in chat and early-send; goal stream updates remain in backend/tests/test_chat_goals.py. All tests for request rights, storage selection, token isolation, byte integrity and data safety remain in the release suite.

Run the combined gate with the test Python, for example `.venv/bin/python scripts/release_checks.py`. It lets both suites finish so their process cleanup and complete evidence are preserved, then enforces the total wall-clock budget; it does not terminate children at the deadline.
DONE
