# Subscriptions

A subscription profile is a named provider login on a Computer. Credentials stay on that Computer; Tico stores the name and sign-in state. Each profile has its own login directory.

## Names and weekly allowance

Open **Settings → AI providers → Subscriptions** to name and sign in subscriptions, choose group defaults, and see weekly allowance. Names are labels; Tico does not store subscription ownership. Each bot can override its group's subscription in Bot settings. Logins and credentials remain on the selected Computer.

Weekly reports are scoped to a Computer, profile and runtime. Codex reports its seven-day window when its running host emits one. Claude Code may report the seven-day reset and limit state without a percentage; that percentage stays unknown. No API calls or token-to-percentage estimates are used to invent a provider balance. Usage elsewhere on the same provider account can count toward that allowance. The page does not combine matching names across Computers because they might be different accounts.

The last provider report includes its observation time and reset. Reports older than a day are labelled as possibly out of date. After reset they stay labelled as the previous week, never automatically become zero. Reports survive a runner restart on the server; an updated runner must run a subscription-backed turn before fresh telemetry is available. Shorter windows are not displayed here. An unnamed computer-default login has no named subscription snapshot; it remains unknown rather than being assigned to another profile.

A Computer operator or administrator can **Record weekly usage** by copying the provider's percentage used and reset time. This is a labelled manual observation, not an editable provider quota. The newest manual or provider observation is shown. Clear manual report restores the last provider report, or unknown if none exists. This neither changes provider limits nor schedules or blocks bots. No account ownership records or new permissions are introduced.


Assign a profile to a group to use it for that group's bots and nested groups. A bot assignment overrides the nearest group's assignment. With no server assignment, the Computer keeps its local `bot_profiles` and `default_profile` behavior. Removing an assignment restores inheritance; it does not delete a login.

`GET /api/v2/subscriptions` returns `profiles_by_computer` and `assignments`. Set or clear an assignment with `PUT /api/v2/subscriptions`, for example `{"scope":"group","target":"engineering","profile":"engineering"}`; use `profile: null` to clear it. Owners and admins change group assignments; the bot's Computer operator, owners and admins change its override. `GET /api/v2/bots/{bot}/subscription` returns the effective profile, its source, Computer and sign-in state for the model picker. Unknown sign-in state is `null`.

The Computer operator can manage sign-in on their own Computer; owners and admins can manage it on any Computer. To sign in a named profile, use the existing Computer sign-in flow: `POST /api/v2/runners/{runner_id}/logins` with `{"runtime":"codex","profile":"engineering"}` (or `claude`). A current Computer creates the named profile if needed beside its registration (`profiles/<name>`, or beside its state directory on isolated Docker Computers when no registration path is available (inside state otherwise)). The profile is private and stays outside the team workspace. Adding a profile does not change the local default. The browser relays the provider's link and code; the provider writes its credentials locally. A group spanning several Computers needs the same named login on each.

Computers report their profiles on heartbeat. A bot with a server-assigned profile waits when that profile is missing or signed out; it never runs on another profile, the local default or the operator's login. Health and subscription status show `Subscription <name> isn't on <computer>` or `Subscription <name> isn't signed in on <computer>`. The server also holds these bots on older Computers that cannot report profiles, with `Update <computer> to use subscriptions`. Bots without an assignment keep their local profile and default behavior.

A current runner retries a rejected heartbeat without only the unsupported report: subscriptions, worktrees or repository clones. Other reports stay intact, and unrelated errors retain their original message. Invalid local profile names are omitted from reports. Provider sign-in probes are cached for one minute and refreshed after sign-in or a rejection. Turns and watcher scripts use the cached sign-in state without probing at every start. A probe timeout leaves sign-in unknown and allows a turn to try. A fallback harness uses the same assigned subscription and waits with `Subscription <name> isn't signed in on <computer>` when its login is missing. Start refusals record a diagnostic with the runtime in a detail field and requeue the job without posting a chat reply. The server waits for a fresh ready subscription report before handing it out again. Assigned profiles cover Codex, Claude Code, Grok and Gemini CLI. Other runtimes, including Cursor Agent, Pi and Antigravity, wait with `Subscription <name> doesn't cover <runtime>` in Health and the model picker. A rejection affects only that runtime on that profile. Claude profiles keep their existing HOME-based login layout. Completion and usage records include the selected profile when a turn starts; empty profile fields are omitted.

Profile directories separate provider logins. Browser-created profiles live outside the bot workspace, with directories set to 0700 and owned by the same user that runs sign-in, probes and turns. Linux Docker harnesses currently retain the existing shared bot Unix user; profiles do not yet provide a Unix permission boundary between groups. Do not rely on profile assignments to isolate files from another bot on the same Computer.

The Engineering Manager template gives owners and admins an initial read grant to all enabled repositories. Member-created bots keep the team default. Its child-task and worktree instructions require phases 2 and 3 to ship first.

### Refreshing weekly allowance

On **AI providers**, a computer operator or administrator can choose **Refresh weekly
usage** for a named Codex subscription. The computer reads the Codex app-server's
[`account/rateLimits/read`](https://learn.chatgpt.com/docs/app-server) endpoint in that
profile. It does not start a model turn, consume a reset credit, change a subscription,
or switch to another account. Repeated clicks are coalesced for one minute; only one
read runs at a time per computer and requests expire after two minutes. Older computers
without refresh support leave a request to expire; update the computer to enable it.

Sign-in status, weekly allowance and refresh status are separate. Failed or unsupported
reads keep the last successful reading, with its original timestamp. An elapsed reset
never means a fresh allowance or a repaired sign-in. Claude and other runtimes without
a supported standalone weekly read use observations from normal runs or a manual
provider reading. Missing percentages remain unknown, not zero.

Starting a new sign-in through Tico invalidates earlier readings and in-flight refresh
results for that profile/runtime. Replacing credentials outside Tico under the same
local profile cannot currently be detected: refresh and confirm the provider reading
after such a change. Usage reported by a turn that was already running during sign-in
can also refer to its earlier account; avoid replacing an active profile while turns
are running. This is approximate monitoring, not a spending limit.
