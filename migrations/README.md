# OAuth storage preparation — Batch 4B-2A

**Proposal only. Nothing here has been executed against Supabase.**
The artifact is [a non-executable Markdown SQL proposal](proposals/4b2a_oauth_storage.sql.md),
not a migration runner input. Batch 4B-2A used only static checks; Batch 4B-2B
subsequently tested a converted candidate in a disposable official PostgreSQL
16.16 container, found and corrected a nil-UUID rollback defect, and passed 58
real database checks. See [experiment details](POSTGRES_VALIDATION.md). No host
PostgreSQL packages were installed. These local results do not validate deployed
schema, grants, RLS or PostgREST behavior. Promote to executable SQL only after
the remaining evidence and approvals below exist.

## Reconciliation with local source

| Evidence | Confirmed locally | Not established for deployment |
| --- | --- | --- |
| `README.md:180-201` | Documents unqualified users: UUID PK/default, unique non-null email, nullable password_hash/provider; sessions have a nullable user_id FK with cascade. Only RLS enable statements, no policies. | Actual schemas/types/defaults/indexes/constraints, extensions, triggers, schema drift and existing data compatibility. `public` is a proposal assumption, not an explicit qualifier in that README SQL. |
| `src/database/database.py:7-16` | Loads shared Supabase URL/key; each operation creates a shared client. No user-bound Supabase Auth token. | Actual credential role, RLS bypass, grants, API exposure and server-only handling. Do not inspect credential values to discover this. |
| `src/database/database.py:27-89` | Lowercases new emails, custom bcrypt login, email-only GitHub lookup. Batch 3B refuses password/mixed-provider linking. | Legacy normalized-email uniqueness, provider/password consistency and historical ownership evidence. |
| `src/auth/identity.py:12-33`, `src/ui/auth.py:9-19` | Auth result must be literal success plus non-nil validated local UUID. Session operations compare explicit owner to server state. | Real row-return behavior and anonymous denial of users/sessions. UUID syntax alone is not authentication. |
| `src/auth/oauth.py:16-50`, `src/ui/auth.py:36-62` | Fixed state, unverified email selection, no provider subject; current flow remains unchanged and insecure. | Browser/host behavior or exploitability in deployment. |

The proposed functions are not called by current code. This proposal does not fix
the old callback and must not be advertised as an OAuth repair or deploy approval.
Current README key guidance names an anonymous key; that cannot be used for these
backend-only RPCs. Do not silently substitute credentials or grant anonymous RPC
execution to make login work.

## Schema and identity rules

- Add nullable `public.users.github_subject text`, unique across non-null values.
  Canonical positive decimal text, 1–20 digits, must match a GitHub-only row with
  no password. NULL remains valid for every legacy row. No backfill or UPDATE of
  users, existing UUIDs, sessions or existing FKs. PostgreSQL's nullable uniqueness
  must be tested, not approximated with a universal NOT NULL requirement.
- Private `oauth_attempts`: SHA-256 state PK, browser-binding hash, fixed github
  provider, created/expires/consumed/completed/revoked timestamps. Five-minute TTL.
- Private `oauth_handoffs`: SHA-256 opaque ticket PK, unique attempt FK, binding
  hash, local users.id FK, GitHub subject snapshot and lifecycle timestamps. TTL
  at most 60 seconds, capped at the attempt deadline. Foreign-key cascades affect
  only these new subordinate transient rows, never historical users or sessions.
- Generate independent random state, binding secret and ticket with at least 32
  cryptographic random bytes in the future trusted handler. Store only
  purpose-separated hashes (`SHA256(purpose || NUL || secret)`, distinct domains
  state/binding/ticket). Check length before hashing. Hashes are still sensitive
  correlation data: restrict access and redact logs. SQL cannot prove entropy or
  browser-cookie provenance. No code/token/raw cookie in these tables.
- Resolve an already bound user **by GitHub subject only**, validating provider,
  password absence and local UUID. Email is verified contact metadata, never the
  account identifier. Existing bindings retain the same UUID if email changes;
  this batch proposes no email update. A contact-email collision does not switch
  an existing subject to another account.
- A new subject creates a new GitHub-only user via the existing UUID default.
  Email collision with a password account, NULL-subject GitHub account or another
  subject fails generically. Never UPDATE/link/merge that row. Concurrent same-
  subject insert losers re-read only that subject; different subjects competing
  for one email yield one winner and one denial. Unknown constraints/errors fail
  closed. No raw DB exception should become a public error in later handlers.
- Preflight must confirm existing emails follow the lowercase normalization and
  uniqueness assumed here, including collation/citext/case variants. Otherwise
  block promotion and approve a collision policy; do not silently rewrite data
  or add a lower(email) constraint over unknown legacy rows.

## Backend permission boundary

| Role | Proposed rights / limits |
| --- | --- |
| PUBLIC, anon, authenticated | No private schema usage, table access or RPC execution; no browser RLS policies. Inspect inherited/default grants too. Existing users/sessions must already be inaccessible directly to these clients before public release. |
| service_role | Explicit EXECUTE only on the six new public RPC signatures; no private schema/table privileges. Must be server-only. Has BYPASSRLS in standard Supabase; revoking grants is necessary even with RLS enabled. Existing broad privileges elsewhere remain a material limitation. |
| oauth_storage_owner | New NOLOGIN/NOBYPASSRLS/non-superuser/non-role-admin owner; never granted to authenticator/browser/runtime roles. Owns new tables/functions, explicit owner-only RLS policies under FORCE RLS. SELECT required identity columns and INSERT GitHub-only columns on users; no UPDATE/DELETE users and no sessions privileges. |
| authenticator and any custom roles | No owner membership or inherited route to EXECUTE except verified server-role switching. Audit actual role hierarchy and JWT role selection. Names/membership are deployment facts, not repository facts. |
| privileged migration operator/postgres/admin | Trusted administration only; can defeat ACL/RLS and is outside the untrusted-browser threat model. Needs ownership/role/policy creation privileges and transactional DDL. Never used by app. |

RPCs use SECURITY DEFINER only to bridge public PostgREST-callable functions to
private storage. Fixed `search_path = pg_catalog`, fully qualified relation names,
no dynamic SQL, explicit signatures, NOLOGIN owner, same-transaction revocations
of PUBLIC defaults, and selective EXECUTE are mandatory. Public CREATE is granted
to the owner only during function ownership transfer and revoked before commit.
Audit inherited PUBLIC CREATE on public as well; a direct revoke does not override
an inherited grant. The schema must be non-writable by untrusted roles.

The private schema stays outside PostgREST exposed schemas. RLS is enabled/forced
on new tables with owner-only policies, but does not authenticate the custom app
user. The owner-only users SELECT/INSERT policies are conditional on the actual
RLS arrangement; existing restrictive policies may still deny them. No auth.uid()
policy is invented for custom UUID identities. The table owner/admin and service
role are not equivalent to an untrusted browser.

The draft deliberately does not alter existing users/sessions grants or policies
for browser roles. Validate their expected denial separately: blanket revocation
could break current password login if its shared key really is anonymous. A
reviewed existing-table grant/key change may be a release prerequisite, requiring
separate explicit approval and compatibility tests. Do not claim that private
OAuth tables secure publicly readable password hashes or unscoped database APIs.

Least-disruptive conditional transport: server-only service-role PostgREST RPCs
over existing HTTPS, avoiding a direct PostgreSQL connection or extra service.
Approval is required because the actual backend credential boundary is unknown.
A dedicated narrowly scoped backend role with approved JWT/connection plumbing
offers less privilege but adds credential/routing work; not selected automatically.

## Atomic lifecycle and failure behavior

| RPC | Contract |
| --- | --- |
| oauth_start | Trusted backend supplies state/binding hashes. Serializes browser binding; latest deliberate start revokes that binding's old attempts and handoffs, including consumed in-flight attempts. Inserts a fresh five-minute attempt. Form rerenders must not call it automatically. |
| oauth_consume_attempt | Locks binding and matching row, reads DB wall clock after locks, UPDATE ... WHERE matching state, binding, provider, unexpired/unconsumed/unrevoked RETURNING. Exactly one true result; wrong-browser requests do not burn the owner's attempt. Commit before provider HTTP. |
| oauth_finish_attempt | Locks binding/attempt, requires consumed, uncompleted, unrevoked and unexpired attempt. Trusted verified profile subject/email resolve/create identity. Unique attempt FK plus completed_at prevents ticket reissuance. Account creation, ticket insertion and completion commit together. Recheck time after uniqueness waits; expiry raises to roll back any new account. |
| oauth_redeem_handoff | No UUID parameter. Locks binding/ticket before DB-clock check; one conditional UPDATE RETURNING the internally stored UUID/subject. Checks ticket, binding, expiry, attempt completion/revocation and current subject/owner relation. No row is a denial, never an authenticated NULL. |
| oauth_revoke_browser | Same binding lock; marks all matching attempts and handoffs revoked, including consumed attempts waiting for provider response. Finish after revocation fails; finish before revocation has its resulting ticket revoked. |
| oauth_purge_expired | Explicit server maintenance call deletes transient records expired at least 24h ago, with dependent handoffs cascading. No identities or user content deleted. Schedule is not installed. Expiry denial never depends on cleanup running. |

All lifecycle RPCs acquire the same transaction-scoped advisory lock before row
locks; different binding hash collisions cause extra serialization, not access.
Atomic consume-once semantics are proposed under PostgreSQL READ COMMITTED, not
proved by the reference model. Test real concurrent connections and rollback.
Purge does not take browser locks; it touches only long-expired rows. Bound the
cleanup job's batch size/timeout and monitor retention/volume before high traffic.
The migration's SET LOCAL timeouts do NOT bound later RPCs: the local backend
session had statement_timeout=0. Approved runtime statement/lock deadlines must be
configured and verified through the actual connection/API path, including cleanup.

No transaction spans external HTTP. A successfully committed consume remains
consumed after timeout, cancellation, malformed profile, email denial, DB failure,
or rollback of finish. Connection loss after ambiguous commit is never retried
as code exchange or authentication: start a fresh attempt. Wrong/malformed/unknown
inputs return no identity; unexpected storage errors propagate to a later generic
logged-out failure. No fallback to email-only authentication is permitted.

Logout semantics: revocation invalidates pending handoffs, not an already redeemed
Streamlit session. Later code must clear that session, revoke server records,
clear/rotate browser cookies and serialize logout with redemption. Failure to
confirm revocation must not report a successful secure logout. Cookie rotation
is necessary for a new start racing logout; no HTTP/cookie/session code is here.

## Legacy handling and rollback

All NULL-subject GitHub rows remain intact but must be rejected by the future
subject-based login. Existing password rows remain untouched. Before cutover,
approve whether GitHub-only users are temporarily locked out and provide manual
recovery: independent historical provider-ID evidence or an already authenticated,
explicit re-verification workflow. Current possession of a matching verified email
alone is insufficient. No automated linking endpoint or backfill SQL is supplied.
Historical UUIDs/FKs must survive any separately authorized, audited binding.

Before deployment the transaction can roll back completely. After bindings exist,
prefer disabling new OAuth entry/EXECUTE while retaining storage and mappings;
do not restore unsafe old callback behavior. Dropping the subject column loses
identity provenance and can strand users. No destructive down migration is supplied.
Removing policies/grants/roles requires an ownership/dependency audit. Removing
new FKs/records affects revocation evidence. Credential/grant rollback must not
re-expose old authorization gaps. Active attempts can safely expire; user data and
password login must be verified independently during any rollback.

## Evidence and validation gates before Batch 4B-2B

1. Approve this proposal's roles, schema names, TTLs, latest-start-wins policy,
   unique-subject representation, email collision policy, and legacy recovery.
2. In an authorized isolated Supabase/PostgreSQL environment, inspect metadata
   only: PostgreSQL version; schemas and columns; users UUID default and its
   EXECUTE permissions; constraint/index definitions; triggers; RLS/forced RLS;
   table/column/schema/function ACLs and defaults; role memberships/BYPASSRLS;
   exposed schemas and PostgREST roles. Do not request production row exports.
3. Obtain privacy-preserving aggregate compatibility results for NULL subject,
   provider/password inconsistencies, normalized-email collisions, invalid UUID
   defaults, name conflicts and existing extensions. If unknown, do not promote.
4. Verify users/sessions browser denial and legitimate custom password operations
   with synthetic users and separate role credentials. Do not print credentials.
   Verify RPC/table denial for PUBLIC/anon/authenticated and backend success.
5. Run a real parser/server on extracted reviewed SQL inside a disposable schema
   fixture matching the confirmed version. Check fresh install, duplicate install
   failure, transactional failure rollback and no UUID/FK changes. No auto-execution
   is authorized by this batch.
   Measure index/constraint construction and table locks on representative synthetic
   volumes. The draft times out rather than waiting indefinitely; large tables may
   need an approved maintenance window or a separately reviewed concurrent-index
   rollout outside this single-transaction sketch.
6. Exercise parallel consume/redeem (one winner), wrong browser (no burn), expiry
   at equality and after lock waits, start/logout/finish/redeem races, duplicate
   subject and email inserts, storage errors and lost commit acknowledgement.
   Check private schema invisibility, function ownership/search_path, overloads,
   default/inherited grants, malicious search_path/temp objects and RLS policies.
7. Approve server-only credential transport and atomic cutover: new subject login
   cannot coexist with the old email-only callback as an alternative. Migration
   alone is not a safe intermediate public deployment. No new flow is enabled here.

Metadata-only query sketches for that isolated review (not run here):

```sql
SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE (table_schema = 'public' AND table_name IN ('users', 'sessions'))
   OR table_schema = 'oauth_private';
SELECT schemaname, tablename, policyname, roles, cmd, qual, with_check
FROM pg_catalog.pg_policies
WHERE schemaname IN ('public', 'oauth_private');
SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity, c.relacl
FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('public', 'oauth_private') AND c.relkind IN ('r', 'p');
SELECT n.nspname, p.proname, pg_catalog.pg_get_function_identity_arguments(p.oid),
       p.proowner::regrole, p.prosecdef, p.proconfig, p.proacl
FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
WHERE p.proname LIKE 'oauth_%';
SELECT rolname, rolcanlogin, rolsuper, rolbypassrls FROM pg_catalog.pg_roles;
SELECT roleid::regrole, member::regrole FROM pg_catalog.pg_auth_members;
SELECT conname, pg_catalog.pg_get_constraintdef(oid)
FROM pg_catalog.pg_constraint WHERE conrelid IN ('public.users'::regclass, 'public.sessions'::regclass);
```

Also inspect schema ACLs, information_schema column/table privileges and
pg_default_acl; use has_schema_privilege / has_table_privilege /
has_column_privilege / has_function_privilege and real role calls. Catalog ACL
NULL does not mean no privileges; expand defaults/inheritance. API exposure and
credential/JWT-role configuration need service configuration evidence, not SQL
alone. Never SELECT password hashes or actual user rows for this review.

## Offline evidence

The new SQL checks read the exact proposal file; they are text/lexical contracts,
not parser/DDL/ACL tests. The reference-model tests execute only a test-only
state machine of the proposed invariants, not the existing production OAuth flow
or PostgreSQL. They deliberately do not retrofit security into existing mocks.
The original 20 current-production OAuth assertions remain ordinary failures.
Run `python -I -S -B tests/run_offline.py`. See the final response for counts.

Recorded result: 156 tests, 136 passing, the same 20 ordinary OAuth failures;
32 new passing checks comprise 12 static/lexical checks and 20 reference-model
tests. No errors, unexpected sandbox violations or remaining temporary artifacts.
Exit 1 intentionally preserves current-production failure evidence. The threaded
reference checks serialize a Python model; they do not test PostgreSQL
row locking or concurrent PostgREST transactions.

Batch 4B-2B adds one static regression for the real nil-UUID rollback defect:
157 tests, 137 passing, the same 20 ordinary OAuth failures, zero errors and
unexpected sandbox violations, with successful temporary-workspace cleanup.
The 58 real PostgreSQL checks ran separately in the disposable container; they
are not part of, or substituted for, this offline suite.

Primary references: [PostgreSQL SECURITY DEFINER and privileges](https://www.postgresql.org/docs/current/sql-createfunction.html),
[Supabase RLS and role limitations](https://supabase.com/docs/guides/database/postgres/row-level-security),
[Supabase database function privileges](https://supabase.com/docs/guides/database/functions).
