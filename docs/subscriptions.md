# Subscriptions

A subscription profile is a named provider login on a Computer. Credentials stay on that Computer; Tico stores the name and sign-in state. Each profile has its own login directory.

Assign a profile to a group to use it for that group's bots and nested groups. A bot assignment overrides the nearest group's assignment. With no server assignment, the Computer keeps its local `bot_profiles` and `default_profile` behavior. Removing an assignment restores inheritance; it does not delete a login.

`GET /api/v2/subscriptions` returns `profiles_by_computer` and `assignments`. Set or clear an assignment with `PUT /api/v2/subscriptions`, for example `{"scope":"group","target":"engineering","profile":"engineering"}`; use `profile: null` to clear it. Owners and admins change group assignments; a bot's operator or manager changes its override. `GET /api/v2/bots/{bot}/subscription` returns the effective profile, its source, Computer and sign-in state for the model picker. Unknown sign-in state is `null`.

To sign in a named profile, use the existing Computer sign-in flow: `POST /api/v2/runners/{runner_id}/logins` with `{"runtime":"codex","profile":"engineering"}` (or `claude`). A current Computer creates the named profile if needed and keeps it in its registration. Adding a profile does not change the local default. The browser relays the provider's link and code; the provider writes its credentials locally. A group spanning several Computers needs the same named login on each.

Computers report their profiles on heartbeat. If an assigned profile is absent, the runner continues using its local bot profile or default and reports `profile <name> not on this computer` in Health and subscription status. Older Computers keep running as before; their profile state remains unknown until they update. A current runner retries without profile reporting when an older server rejects it.

Profile directories separate provider logins. Linux Docker harnesses currently retain the existing shared bot Unix user; profiles do not yet provide a Unix permission boundary between groups. Do not rely on profile assignments to isolate files from another bot on the same Computer.
