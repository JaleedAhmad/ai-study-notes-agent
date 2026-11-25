# Authorization contracts: Batches 3A and 3B

Baseline: development, production commit `57bce0f`. Batch 3A preserved 22 failing
contracts; Batch 3B fixes application authorization without changing schema,
deployment, existing data, or authentication providers. Deployed grants, key roles,
RLS policies, and exploitability remain unknown. Run
`python -I -S -B tests/run_offline.py` from the repository root.

The inventory and original source line references below describe the Batch 3A
baseline. See the final section for the implemented Batch 3B contract and results.

## Historical Batch 3A access inventory

| Location | Operation / caller | Identity and ownership behavior |
| --- | --- | --- |
| `src/database/database.py:7-16` | Import configuration; `get_supabase()` | Dotenv at import; fresh client using shared URL/key. No Supabase Auth sign-in or per-user token. Called by every table operation. |
| `scripts/keep_alive.py:9-26` | Independent client inside `main()` | Shared configuration; selects one user ID. Administrative maintenance path, not user-authenticated. Not executed by tests. |
| `src/database/database.py:17-38` | `create_user`; signup and OAuth helper | Lowercased email lookup, optional bcrypt hash, insert. Returns tuple, raw ID, or None depending on branch. |
| `src/database/database.py:40-52` | `authenticate_user`; login form | Looks up email and checks hash; no database-authenticated session. Successful row ID is not validated. |
| `src/database/database.py:54-58` | `get_user_by_email`; authentication, creation, signup completion | Selects all user columns by email, including hash. Must be private authentication infrastructure, not a self-service user-read endpoint. |
| `src/database/database.py:60-64` | `get_user_by_id`; no production caller found | Selects all user columns by ID. Same private-infrastructure requirement. |
| `src/database/database.py:66-77` | `authenticate_oauth_user`; OAuth callback | Accepts existing matching email regardless of provider. Creation has a second existence check and truthy failure-tuple race. |
| `src/database/database.py:79-88` | `create_session`; `src/ui/main_content.py:100-105` | Persists passed user ID, filename, source, notes, empty history. No principal validation. |
| `src/database/database.py:90-93` | `get_all_sessions`; `src/ui/sidebar.py:34` | Filters by supplied user ID. Returns full source, notes and history. No invalid-principal rejection. |
| `src/database/database.py:95-99` | `get_session`; `save_chat_message` | Session-ID-only read. No principal parameter or ownership predicate. |
| `src/database/database.py:101-106` | `save_chat_message`; main-content user/assistant paths at lines 220 and 251 | ID-only read then ID-only update of history. Neither ownership nor concurrent-write protection. |
| `src/database/database.py:108-109` | `delete_session`; `src/ui/sidebar.py:63` | ID-only delete, including source and notes stored in row. No ownership predicate, affected-row check, or vector cleanup. |
| `src/ui/sidebar.py:49-57` | Load notes/source/history | Uses row from user-filtered listing directly; no separate `get_session` call or fresh owner verification. |
| `src/core/rag.py:13-17,38-73,75-104` | Local persistent Chroma | Shared collection; indexing duplicate check filters document ID alone; inserted metadata includes user/document IDs. Query filters supplied user ID. Local storage has no Supabase RLS. |
| `src/core/pipeline_router.py:55-87` | Ephemeral Chroma for notes | Per-request random collection, no user metadata; uses passed request source. No explicit collection deletion. Not a durable authorization boundary. |

### Authentication and record state sources

- `app.py:11-12`: default identity is None; `app.py:45` rejects only None.
- `src/ui/auth.py:86-90`: password-login success copies returned ID into state.
- `src/ui/auth.py:115-120`: signup re-queries email and logs in immediately.
- `src/ui/auth.py:24-39`: GitHub callback copies returned ID into state.
- `src/auth/oauth.py:16-50`: static state, code exchange, selected email without
  checking verification. No Supabase Auth identity is established here either.
- `src/ui/sidebar.py:13-16`: logout clears session keys; lines 20-29 clear study
  state only. Loaded session IDs come from listing rows at lines 49-50.
- `src/ui/main_content.py:100-105`: newly created session ID comes from Supabase.
  Chat writes use that state ID, without passing the current owner.

Current UI IDs come from server-held state or filtered results; the tests do not
establish a browser route for arbitrary session-ID injection. Nevertheless, record
IDs are selectors, not proof of ownership; database services must not rely on
every present and future caller having obtained them correctly.

### RLS versus application filtering

`README.md:164-200` recommends an anonymous key and enables RLS without defining
policies. Policy-less RLS may deny operations; a privileged key may bypass RLS;
permissive policies may expose data. None of those deployed configurations was
inspected. A custom bcrypt login and a Streamlit user ID do not establish
`auth.uid()`. Adding `auth.uid()` policies alone therefore cannot repair the
current login path. Private authentication lookup functions legitimately need
pre-login access, but that access must never be granted directly to a browser.

## Required invariants

1. A validated server-authenticated principal is required for session and document
   operations; None, empty values, failure tuples and malformed identities fail
   before database execution. UUID shape alone does not authenticate a caller.
2. A's sessions, source text, notes and chat are inaccessible to B, and vice versa.
   All supplied record IDs are untrusted, even if generated by the server.
3. Reads and mutations constrain both record ID and owner. A preliminary read is
   insufficient: ownership must also constrain the final UPDATE/DELETE.
4. Missing/null ownership or inconsistent identity metadata never grants access.
5. Database errors do not authorize a user or become successful mutations.
6. Successful authentication yields a valid user ID, never an error tuple or None.
7. Linking authentication methods requires an explicit verified identity policy.
   The provisional contract rejects implicit linking of a password account.
8. Valid login/signup, owner-scoped reads/writes/deletes and library retrieval keep
   working. Private pre-login user lookup is not treated as a public user API.

## Batch 3A test model and failure policy (historical)

`offline/fake_database.py` is a small in-memory query evaluator. It uses only the
actual production predicates, with no current-user field and no implicit RLS.
Rows for B precede rows for A; ownerless data is also present. Select responses
are deep copies so mutating a fetched JSON history cannot accidentally mutate
the fixture before UPDATE. Query operations and predicates are recorded.

It does not emulate Postgres constraints, UUID parsing, SDK validation, grants,
or full SQL NULL behavior. Missing/invalid-principal insert tests require rejection
before execute; fake insert acceptance does NOT prove that a real database accepts
invalid UUIDs. Missing user-ID/owner-column cases are defensive malformed-response
contracts, not evidence that the documented primary-key schema permits them.

Tests set a synthetic Streamlit principal to represent the UI request. Current
ID-only repository functions ignore it; the store never uses it. A future explicit
owner parameter must be passed from that principal when updating test call sites
in Batch 3B; do not make the fake enforce ownership on the application's behalf.

Known gaps remain ordinary RED assertions. No expectedFailure decorator, broad
exception suppression, or exclusion list is used. Only PermissionError is accepted
as an explicit authorization denial; unrelated errors remain test errors. The
complete command exits 1 until these contracts are satisfied. Do not weaken the
assertions merely to restore green. Explicit validation-error assertions may be
added alongside an approved Batch 3B error contract.

### Original failing contracts and source boundaries

All named tests below are in `offline/test_authorization.py` (prefix `test_`).

| ID | Test suffix | Production boundary |
| --- | --- | --- |
| AUTH-01 | another_users_notes_are_not_returned | database.py:95-99, read |
| AUTH-02 | another_users_chat_is_not_modified | database.py:101-106, update |
| AUTH-03 | another_users_session_is_not_deleted | database.py:108-109, delete |
| AUTH-04 | update_predicate_contains_authenticated_owner | database.py:106, final predicate |
| AUTH-05 | delete_predicate_contains_authenticated_owner | database.py:109, final predicate |
| AUTH-06 | owner_change_between_read_and_write_does_not_grant_access | database.py:102-106, synthetic ownership change after read |
| AUTH-07 | ownerless_session_is_not_readable | database.py:95-99, null owner |
| AUTH-08 | missing_owner_column_does_not_grant_access | database.py:95-99, malformed response |
| AUTH-09 | missing_principal_cannot_read_session | database.py:95-99, no identity input |
| AUTH-10 | missing_principal_cannot_insert_session | database.py:79-87, missing owner |
| AUTH-11 | invalid_principal_cannot_insert_session | database.py:79-87, malformed owner |
| AUTH-12 | missing_principal_is_rejected_before_listing | database.py:90-92 |
| AUTH-13 | invalid_principal_is_rejected_before_listing | database.py:90-92 |
| AUTH-14 | password_account_without_valid_id_does_not_authorize | database.py:47-48, malformed identity row |
| AUTH-15 | oauth_does_not_implicitly_link_a_password_account | database.py:67-69, proposed linking policy |
| AUTH-16 | oauth_creation_race_never_authenticates_a_failure_tuple | database.py:18-20,74-76 |
| AUTH-17 | empty_identity_cannot_reach_application | app.py:45-53 |
| AUTH-18 | failure_tuple_cannot_reach_application | app.py:45-53 |
| AUTH-19 | ownerless_session_cannot_be_modified | database.py:101-106 |
| AUTH-20 | ownerless_session_cannot_be_deleted | database.py:108-109 |
| AUTH-21 | missing_principal_cannot_modify_session | database.py:101-106 |
| AUTH-22 | missing_principal_cannot_delete_session | database.py:108-109 |

Passing controls exercise legitimate CRUD, valid/invalid password outcomes,
normal signup and same-provider OAuth, private user lookups, unknown record IDs,
select/update/delete/login/signup errors, callback failure preserving logged-out
state, entry gating for None/valid identities, shared synthetic client setup,
user-filtered vector retrieval, and the fake's ability to expose unfiltered data.
The original 20 Batch 2 tests remain included, including safety-guard tests.

Recorded Batch 3A result: 68 tests, 46 passing, 22 ordinary failures, no test
errors/skips/expected failures. Exit status 1 preserves the unmet contracts;
unexpected sandbox violations are zero and temporary-workspace cleanup succeeds.

## Batch 3B design recorded before implementation

- Validate successful authentication IDs and the UI gate. Preserve existing UUIDs
  and bcrypt hashes; do not treat syntactic UUID validation as authentication.
- Add a required keyword-only authenticated owner to get_session,
  save_chat_message and delete_session; validate existing create/list owner inputs.
  Pass it only from trusted session state. Update every caller together.
- Put owner predicates on both SELECT and the final UPDATE/DELETE. Null/missing
  owners do not match; unknown/foreign records have the same denial behavior.
  Define no-match/zero-row outcomes explicitly and preserve database errors.
- Normalize create/authenticate return contracts. A concurrent existing-user result
  must be re-read and identity/provider-validated or rejected, never truth-tested
  as an ID. Signup should use a validated returned identity rather than an
  unvalidated second email lookup where practical.
- Reject implicit cross-method linking unless a separately approved verification
  policy authorizes it. Stable provider-subject migration and OAuth state binding
  are separate decisions; this batch does not implement those fixes.

Session CRUD validation needs no schema migration. Ownerless legacy data must be
quarantined or repaired from reliable provenance, not assigned to whoever requests
it. Malformed/linked legacy accounts may need recovery rather than automatic login.
Read-modify-write history concurrency and document/vector deletion remain outside
these ownership fixes.

## Architecture, compatibility and rollback decisions

Recommended least disruptive architecture: retain custom authentication and the
trusted Streamlit backend, require explicit owner-scoped repository calls, and
verify that users/password hashes/sessions are inaccessible to anonymous browser
database clients. Backend credentials must be server-only with appropriate grants.
Application filtering is sufficient only inside that verified private boundary;
it does not secure a publicly accessible database API with permissive policies.

Alternative: Supabase Auth plus user-bound JWT/RLS. That adds managed identity but
requires auth UI/OAuth changes, legacy UUID/FK mapping and a supported password
migration/reset plan. Custom JWT integration adds signing/revocation complexity
and is not the smallest repair. A privileged key swap alone is not a security fix.

Deployment verification is required for the chosen private-backend model. Any
Supabase Auth migration, cross-method linking beyond failing closed, legacy-data
repair, or later credential/grant/policy migration requires separate approval.
None is inferred from unknown deployment state. Public deployment remains gated
on real grants/RLS/credential-boundary tests.

Roll out repository signatures and UI callers together. Preserve old user IDs and
schema for the small fix. Do not run incompatible old writers alongside a changed
contract. If rollback reintroduces unscoped access, restrict public access instead
of treating that rollback as safe. Schema/policy migrations require their own
validated rollback plans; they have not been performed here.

## Implemented Batch 3B contract

The trusted Streamlit/custom-auth architecture is retained. No database/schema,
RLS, credential, Docker, CI, or deployment configuration changes are included.

`src/auth/identity.py` validates a non-null, non-nil string UUID and normalizes it
to canonical form. Every session operation compares its owner argument with the
validated server-held `st.session_state.user_id`, before client access. Passing
another valid UUID is denied; UUID syntax alone is not authentication. The same
check protects persistent vector indexing/retrieval. Only trusted authentication
code may establish server identity; there is no new client-supplied identity path.

### API and error semantics

- `get_session(session_id, *, user_id)` requires the authenticated owner. Its query
  constrains ID and owner; foreign/missing/unverifiable records return None.
- `save_chat_message(session_id, role, content, *, user_id)` constrains both its
  read and final update. A lost ownership match or zero returned rows raises
  PermissionError, including ownership changes after the initial read.
- `delete_session(session_id, *, user_id)` constrains the final deletion by both
  fields and raises PermissionError on zero matching returned rows.
- `create_session(user_id, ...)` and `get_all_sessions(user_id)` keep their
  positional signatures but reject invalid/substituted owners. Listing excludes
  results lacking matching ownership metadata; inserts require returned ownership.
- Database execution errors in session operations and authentication lookups
  propagate. UI handlers display generic messages. Account insertion failures
  return a public failure tuple rather than raw database exception text.
- Mutation verification expects returned row representations with ID/user_id.
  Real SDK/PostgREST return behavior and privileges must be verified before
  deployment. If a mutation executes but no representation is returned, the
  application reports failure; it cannot roll back that already executed action.

All session callers are updated together. The sidebar re-fetches the selected
session through the scoped read before assigning its notes/source/history. Both
chat writes pass the validated current owner. Upload saving and vector operations
use the same identity contract. No history concurrency or indexing lifecycle
redesign is included.

### Authentication and legacy behavior

Create/login/OAuth functions use `(bool, validated_user_id_or_public_error)`.
The UI accepts only a tuple of length two with literal True and a validated ID;
failed results and malformed values leave identity unset. Signup uses the returned
ID instead of a second email lookup. The application gate rejects malformed state
and clears stale study state when a non-null invalid identity is found. Ordinary
logged-out renders retain failed-login counters.

OAuth accounts with the existing GitHub provider and no password remain usable.
Password accounts, mismatched provider records, and mixed password/GitHub records
are not implicitly linked by email; users must use their existing sign-in method
or a separately approved recovery process. Concurrent creation may return a safe
failure/retry instead of logging in. Existing IDs and bcrypt hashes are unchanged.

Ownerless records remain stored and excluded from user access, without automatic
assignment or deletion. Manual repair requires independently established owner
provenance. No users, notes, sessions, or vector data were migrated or deleted.

### Test adjustments and results

All original 68 cases remain; 15 additional hardening tests bring the suite to 83.
No security assertion is removed or marked expected-failure. Changes to fixtures
and call sites are required by the new contract:

- Test adapters explicitly pass server identity to the new keyword-only APIs.
- Listing B's legitimate records switches the synthetic authenticated request to
  B and back; the former fixture treated a supplied owner as authentication.
- The baseline listing fixture now supplies a real synthetic UUID, server identity
  and ownership metadata instead of an invalid `synthetic-user` and ownerless row.
- Unknown-record mutation tests now assert PermissionError, strengthening the old
  silent no-op expectation to match the required zero-row failure contract.
- Signup assertions inspect the success flag instead of the truthiness of a tuple.
- Vector tests establish a synthetic authenticated request before retrieval.

The fake database is unchanged: it still evaluates only the predicates the real
application issues, with no implicit actor or RLS enforcement. Added tests cover
identity substitution, malformed/missing principals before client access, required
owner keywords, both users' legitimate operations, zero-row failures, ownership
changes, actual login/signup/OAuth handlers, and sidebar load/delete/stale selection.

Validated command: `python -I -S -B tests/run_offline.py`. Result: 83 passing, zero
failures/errors/skips/expected failures, exit 0, zero unexpected sandbox violations,
and successful temporary-workspace cleanup. No real services or credentials used.

### Remaining deployment gates

This is application-side authorization, not a verified production security boundary.
Check actual key roles, anonymous/browser denial of sensitive tables, grants/RLS,
server-only credential handling, and row-return behavior in an authorized isolated
deployment. Pre-login user lookup functions remain private backend functions.

GitHub callback state binding, verified provider email selection, and stable
provider subject IDs are not repaired here; the OAuth transport remains a later
batch and a public-release limitation. No claim of deployed RLS or end-to-end
OAuth verification is made. Import-time initialization, shared-key configuration,
read-modify-write history races, and document/vector retention are unchanged.

Deploy signatures, helper and callers as one change. No schema rollback is needed.
Rollback to the original unscoped methods reopens the demonstrated gaps; restrict
public access if such a rollback is necessary. Batch 4 has not begun.
