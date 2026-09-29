# People and access

Who is on the roster, who may sign in and who owns the environment are settings in the app, not
files on the server. The owner manages them in **Settings > People**; nothing needs a restart.

## What the owner can do

- **Add a person** (name, email, title, team), **edit** them, and set or unset **bot administrator**.
- **Mark someone as left.** They drop off the org chart, their API tokens are revoked, and they can
  no longer sign in. **Restore** brings them back (their old tokens stay revoked).
- **See who can sign in.** Everyone on the roster with an email who has not left.
- **Who may join.** One box for addresses and domains. An address (`ana@company.com`) lets that
  person join; a domain (`company.com`, `@company.com` or `*@company.com`) lets anyone at it join. The
  server sorts each entry into `allowed` or `allowed_domains`, the page shows what it understood, and it
  refuses, naming the entry, a wildcard inside an address (`a*@company.com`), a malformed address and a
  public mail domain such as gmail.com (that would let anyone with such an account join). Someone who is
  not on the roster but whose verified sign-in matches joins as a normal person on first sign-in
  (audit event `person.joined`). Narrowing the list stops new people; it does not remove anyone
  already on the roster, so mark them as left for that.
- **Transfer ownership** to another active person.

## Transferring ownership

The owner picks an active person, ticks whether they stay a bot administrator, and types the new
owner's email to confirm. On commit the new owner is the owner at once, in the same transaction that
writes the `owner.transferred` audit event. The previous owner becomes a normal person. Owner-only
routes, the runner rule that only the owner's machines host any bot, onboarding's machine wiring,
the credential administrators (when `TICO_CREDENTIAL_ADMINS` is unset), mail and calendar defaults
all read the owner in force. A machine stays with the person who enrolled it: if a bot the new
owner operates was placed on the old owner's machine, reassign it in Settings > Devices.

## Where it is stored

Two revisioned records in `registry_metadata`, like the AI provider choice:

| Key | Holds |
| --- | --- |
| `owner` | the owner's email, revision, who changed it |
| `access` | `allowed`, `allowed_domains`, `bot_admins`, revision |

`TICO_OWNER_EMAIL` and `registry/hub-access.yaml` only seed them on the first boot (or when
upgrading a database that has neither). Once the records exist those settings are never read again, so
editing `api.env` or the file changes nothing. `private_owners` and `routing_permissions` in
`hub-access.yaml` are no longer read: who may see, read and write to each bot is set per bot in Settings > Bots
([permissions.md](permissions.md)).

## The identity proxy must agree

With `TICO_AUTH_PROXY=cloudflare` (Cloudflare Access) or `aws-alb` (Cognito) the proxy authenticates
people before Tico sees them. Adding a person or an allowed domain here does not change that
policy: also allow the same addresses in the Access policy or the Cognito user pool, or the person is
stopped before they reach the app. Settings > People shows a note saying so when either proxy is on.

## API

All owner only. `GET /api/v2/access`, `POST /api/v2/access/people`,
`POST /api/v2/access/people/{id}`, `PUT /api/v2/access/allow` (with `expected_revision`),
`POST /api/v2/access/owner` (with `expected_revision` and `confirm: true`). Marking someone as left
uses `POST /api/v2/people/{id}` with `left: true`.

## Directory sync

Instead of adding people one by one, the owner can sync them from the company directory in
**Settings > People > Directory sync**. Pick one source: Google Workspace or Microsoft Entra ID
(Tico reads the directory on a schedule) or SCIM (your identity provider pushes changes).

Everyone a sync adds joins the roster and **can sign in**, so scope it (group, organizational unit,
domain) to the people who should use Tico.

### What a sync does

- Adds people with name, email, title and manager (who they report to). Photos come from the
  same photo cache as the org chart: Workspace thumbnails and Entra profile photos are fetched
  for people added or updated by a pull.
- Updates those fields for people a sync created. The directory wins over hand edits to them.
- **Leavers are marked left, never deleted.** A suspended or archived Google user, a disabled Entra
  user, or (for a pull) someone who is no longer in scope is marked left: off the chart, API tokens
  and sessions ended, exactly as **Mark as left** does. If the directory turns them back on, a sync
  restores them, unless you marked them left by hand.
- **Never removes a person you added by hand**, and only fills blank fields on them (a title, a
  manager). Someone created by another source is treated the same way.
- **Never demotes or marks the owner as left**, even if the directory disables the owner's
  account. The preview lists them as protected.

### Preview, confirmation and the interval

Every pull starts as a dry run: **Sync now** shows what would be added, updated, restored and
marked left, and what is protected or skipped. Nothing changes until you press **Apply**. You must
tick a confirmation for the **first** sync, and for any sync that would mark **more than N people as
left** (N is the "ask me first" number, default 10). The confirmation is for that exact list: if
the directory changes before you apply, Tico asks you to review again.

The interval (hourly, every 6 hours, daily, or off) runs the same pull in the background, but only
after the first sync was confirmed, and it applies only what needs no confirmation. A plan that
would exceed N leavers is held (audit event `directory.sync_held`, shown as "held for your
confirmation") until you press Sync now. Changing the source or the scope makes the next sync a
first sync again.

SCIM has no preview, because the identity provider decides each change. Creating the token and
selecting SCIM is the confirmation. The mass-leave guard applies as a rate limit: after N
deactivations in an hour, further ones get `429` with `Retry-After` and audit event
`directory.scim_guard` until the hour passes or you raise the limit.

### Audit events

`directory.configured`, `directory.scim_token_created`, `directory.person_added`,
`directory.person_updated`, `directory.person_left`, `directory.person_restored`,
`directory.synced` (one per sync, with counts and protected people), `directory.sync_held`,
`directory.scim_guard`. Credentials never appear in an event. Actors are the owner for Sync now,
`directory` for the interval and `scim` for pushes.

### Google Workspace

Tico calls the Admin SDK Directory API `users.list` (and `groups.members.list` when you filter by
group) with read-only scopes. Google only lets an admin read users, so the service account acts as an
admin through domain-wide delegation. (Google's option of assigning an admin role directly to a
service account, with no delegation, is documented for the Groups APIs only, so it is not used for
users.)

1. In the [Google Cloud console](https://console.cloud.google.com), pick or create a project.
   **APIs & Services > Library**, search **Admin SDK API**, **Enable**.
2. **IAM & Admin > Service Accounts > Create service account.** It needs no Cloud roles. Open it,
   copy the **Unique ID** (a long number, the client ID), then **Keys > Add key > Create new key >
   JSON** and save the file. (If key creation is blocked, your organization policy
   `iam.disableServiceAccountKeyCreation` must allow it for this project.)
3. In the [Admin console](https://admin.google.com): **Security > Access and data control > API
   controls > Manage domain-wide delegation > Add new.** Enter the client ID and these OAuth
   scopes, comma-separated:
   `https://www.googleapis.com/auth/admin.directory.user.readonly`, and only if you will filter by
   group, `https://www.googleapis.com/auth/admin.directory.group.member.readonly`. **Authorize.**
4. Choose who Tico acts as. A dedicated admin user with a custom role limited to reading users
   (and groups) is better than a super admin: **Account > Admin roles > Create new role**, under
   Admin API privileges tick **Users > Read** (and **Groups > Read**), then assign it to that user.
5. In Tico: Source **Google Workspace**, paste the JSON key, enter that admin's email, and set the
   filter, then **Save** and **Sync now**. The key is stored encrypted and is never shown again.

Filter: **groups** are group email addresses (direct and nested user members),
**organizational units** are paths like `/Sales` (sub-units are included), **domains** limit by
email domain. A person in any listed group or unit is in scope, then the domain limit applies.
Empty means everyone. Suspended and archived users are leavers. Manager comes from the user's
`manager` relation.

### Microsoft Entra ID

Tico calls Microsoft Graph `GET /users` (with the manager expanded) using the client-credentials
flow, and `GET /groups/{id}/members/microsoft.graph.user` for a group filter.

1. In the [Entra admin center](https://entra.microsoft.com): **Entra ID > App registrations > New
   registration.** Name it, choose **Single tenant**, **Register.** Copy the **Application (client)
   ID** and **Directory (tenant) ID**.
2. **Certificates & secrets > New client secret.** Copy the secret **Value** now; it is shown once.
3. **API permissions > Add a permission > Microsoft Graph > Application permissions**, add
   **User.Read.All**, and **GroupMember.Read.All** only if you will filter by group. Then **Grant
   admin consent for your organization.**
4. In Tico: Source **Microsoft Entra ID**, enter the tenant, client ID and secret, set the filter,
   **Save**, **Sync now.**

Filter: **groups** are group object IDs (direct user members only; nested groups are not
expanded), **domains** limit by email domain. Disabled accounts (`accountEnabled: false`) are
leavers; guest users are ignored. The email is `mail`, or the user principal name when that is an
email address. Profile photos come from `/users/{id}/photo/$value`. Client secrets expire, so
note the date and create a new one before then.

### SCIM (Okta, Microsoft Entra provisioning, JumpCloud)

Select **SCIM**, **Create token** (shown once), and give the identity provider the **Base URL**
(`https://your-tico/scim/v2`) and the token as a bearer token. Tico implements SCIM 2.0 `Users`
(create, get, list with `filter=userName eq "..."`, `startIndex`/`count`, replace, patch,
delete), plus `ServiceProviderConfig`, `ResourceTypes` and `Schemas`. `Groups` is answered with an
empty list and refuses writes: turn group provisioning off. `userName` must be the person's email
address and cannot be changed; `active: false` marks them left; a `DELETE` does the same, never a
removal. A create for an email that already exists is `409`, as both vendors expect, and the
identity provider then looks the person up and updates them.

With `TICO_AUTH_PROXY=cloudflare` or `aws-alb`, the identity provider cannot sign in, so allow
`/scim/v2/*` through the proxy (a Cloudflare Access **Bypass** policy for that path, or an ALB
rule that skips Cognito for it). The bearer token is the only credential on that path.

**Okta:** **Applications > Browse App Catalog**, add **SCIM 2.0 Test App (Header Auth)**. On the
**Provisioning** tab choose **Configure API Integration**, tick **Enable API integration**, enter
the Base URL, set **Unique identifier field for users** to `userName`, tick **Push New Users** and
**Push Profile Updates**, and put the token in **Authorization** (if Tico answers 401, enter
`Bearer <token>`). **Test API Credentials**, **Save.** Under **To App**, enable **Create Users**,
**Update User Attributes** and **Deactivate Users.** Assign the people or groups to sync. Do not
use **Push Groups.** Okta deactivates with `PATCH` and `active: false` and never sends `DELETE`.

**Microsoft Entra:** **Enterprise applications > New application > Create your own application**
("Integrate any other application you don't find in the gallery"). Open **Provisioning > Get
started**, set **Provisioning Mode** to **Automatic**, **Tenant URL** to the Base URL, **Secret
Token** to the token, **Test Connection** (it asks for a random user and expects an empty list),
then **Create.** In **Mappings**, open **Provision Microsoft Entra ID Groups** and set **Enabled**
to **No.** In **Provision Microsoft Entra ID Users**, keep `userName` (from the email or user
principal name, as an email address) as the matching attribute, keep `active`, `displayName`,
`title`, and add `manager` (to
`urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:manager`) if you want the org chart.
**Users and groups:** assign who to provision (scope **Sync only assigned users and groups**),
then set **Provisioning Status** to **On.** Entra pushes changes about every 40 minutes.

### API

Owner only: `GET` and `PUT /api/v2/directory` (`PUT` takes `expected_revision`),
`POST /api/v2/directory/scim-token`, `POST /api/v2/directory/preview`,
`POST /api/v2/directory/sync` (`confirm` and `plan_hash` from the preview). Settings, one
encrypted credential per source (`directory_credentials`, sealed with the same key as the GitHub
App private key) and the last sync result are stored with the other access records.
