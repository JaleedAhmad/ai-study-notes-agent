# Batch 4B-2C — read-only Supabase metadata preparation

**Prepared only. No SQL has been executed and no database connection is authorized
by this batch.** [supabase_schema_security_read_only.sql](supabase_schema_security_read_only.sql)
contains 24 independent SELECT/CTE queries. It is an inspection artifact outside
`migrations/`, not a migration or deployment hook. Do not configure a migration
runner to scan `inspections/`. Docker's existing allowlist excludes this directory.

The application currently creates a shared Supabase client in
`src/database/database.py:7-16`, uses custom password/OAuth authentication and
server-held UUIDs, and filters session operations by that identity. This does not
establish a Supabase Auth user token or `auth.uid()`. `scripts/keep_alive.py` has a
separate shared client and reads an application row; **do not run it for metadata
inspection**. The root README documents unqualified users/sessions tables and
RLS enablement, without deployed grants or policies. None is treated as deployed
evidence here. The OAuth proposal and current insecure callback remain unchanged.

## Scope and handling before any future authorized execution

- Obtain separate authorization and use an approved metadata-inspection session.
  Prefer an existing read-only credential/session with adequate catalog visibility,
  and a client-enforced read-only transaction if available. Do not create roles,
  grant privileges, change role, or bypass errors to run this script. SELECT-only
  source is not a replacement for connection-level controls or trusted operators.
- Check A01 and A02 first. Queries were designed around PostgreSQL 13+ catalogs,
  not executed or parser-validated on any server. If the server/catalog differs,
  a target is not an ordinary/partitioned table, a query errors, or visibility is
  restricted, stop and record UNKNOWN. Do not rewrite schemas or infer safety
  from missing results. Optional JSON-extracted catalog fields return NULL when
  absent in that version; NULL does not mean false.
- The four relation targets are public.users, public.sessions and the proposed
  oauth_private.oauth_attempts/oauth_handoffs. `public` is a hypothesis to check.
  A missing public table does not prove there is no equivalent in another schema.
  No broad all-schema search or application-table query is included.
- `OPTIONAL_BACKEND_ROLE_NAME` and `OPTIONAL_MIGRATION_ROLE_NAME` are literal
  non-secret placeholders. The first is the intended runtime/API role; the second
  is the future DDL object creator. They may be different. Leave placeholders
  missing until operators independently identify these roles, then replace only
  with safely SQL-quoted role **names**, never keys/JWTs/connection strings. The
  missing-placeholder rows in B01 are expected and do not establish an actual role.
- Results are scoped, ordered and not silently LIMITed. Function scope includes
  OAuth-name routines and SECURITY DEFINER routines in public/oauth_private, plus
  direct dependencies of the four tables' defaults/policies/constraints/indexes
  and non-internal triggers. It is not an exhaustive function/view/call-graph audit.
- Keep a private query-ID/version/time/inspection-role record. The statements are
  independent: separately obtained results need not represent one consistent
  snapshot if grants or schemas change during inspection. Do not commit raw output
  or paste it into chat automatically. No connection command or credential lookup
  is supplied, and neither Supabase SQL Editor nor production access was used here.

## Query purpose and expected output

### A — structural inspection

| ID | Purpose | Expected output / interpretation |
| --- | --- | --- |
| A01 | Establish version and inspection identity. | One row with version text/number and session/current roles. These are the inspector's roles, not the app's key selection. |
| A02 | Locate four exact relations and their owners/RLS flags. | Four rows, with `present=false` for missing names. `r`/`p` mean ordinary/partitioned table; unexpected kinds need reconciliation. |
| A03 | Describe columns, types, nullability, identity/generation and collation. | One row per live column; includes `password_hash` as a column name only, never its contents. Default/generation expression structure is shown only without stored constants. |
| A04 | Inspect PK/FK/unique/check constraints and validation. | Constraint names/types, ordered key columns, referenced columns and actions, deferral/validation and optional enforcement flags. Constant-bearing definitions withheld. `p/f/u/c` mean primary/foreign/unique/check; FK action `a/r/c/n/d` means no-action/restrict/cascade/set-null/set-default. |
| A05 | Inspect relevant index structure and health. | Index method, key/include column order, opclasses, collations, unique/primary/ready/valid flags and optional NULLS NOT DISTINCT flag. Constant-bearing expressions/predicates withheld; storage/opclass option values and full index DDL intentionally omitted. Interpret key option flags for the actual access method. |
| A06 | Identify application-table triggers needing separate review. | Non-internal trigger names/enabled/type flags and function identity. No trigger arguments, WHEN expression or function body. Modes `O/D/R/A` mean origin/disabled/replica/always. Empty output means none visible in scope, not that all indirect effects are absent. |

### B — authorization and RLS

| ID | Purpose | Expected output / interpretation |
| --- | --- | --- |
| B01 | Check named roles exist and inspect role attributes. | Explicit present/missing rows; login, superuser, bypass-RLS, inheritance, role/database creation and replication flags. No password, role configuration dump or login credential. |
| B02 | Inspect direct role-membership edges touching named roles. | Member/granted/grantor names, admin option, and version-dependent inherit/SET options. Direct edges alone do not show every transitive path. |
| B03 | Find transitive capability toward backend/owner/table-owner and public/private definer-owner roles. | Only candidates with membership toward a sensitive role; includes superuser and effective-USAGE flags. This is a capability check, not a live SET ROLE or JWT test. Superusers can produce positive results without ordinary membership grants. |
| B04 | Inspect policy roles, command, mode and definitions safely. | One row per target policy, permissive/restrictive flag, PUBLIC or named roles, and no-constant USING/WITH CHECK structures. Command codes `r/a/w/d/*` mean select/insert/update/delete/all. Withheld or NULL expressions must not be interpreted as denial or permission without reviewing PostgreSQL's policy semantics. |
| B05 | Expand direct schema/table/column/sequence ACLs. | Owner/grantee/grantor, privilege/grant option and ACL-default flag, including PUBLIC (OID zero). Column NULL ACL means no extra column ACL, while table privileges may still apply. A NULL privilege in an empty expanded ACL is not a grant. |
| B06 | Inspect effective schema/table privileges for named existing roles. | Per-role/object booleans for schema usage/create, SELECT/INSERT/UPDATE/DELETE and any-column SELECT, alongside ownership/RLS/bypass flags. Effective ACL rights include inheritance/PUBLIC; they do not prove which rows RLS allows. |
| B07 | Detect column-level access missed by table-only checks. | Per-role/column effective SELECT/INSERT/UPDATE rights. Important for password_hash, user IDs and source/chat content, without reading any values. |
| B08 | Inspect effective rights on sequences tied to target columns. | Role/schema/sequence USAGE/SELECT/UPDATE booleans. Covers ownership dependencies and explicit default references; an empty result is normal for UUID defaults. No sequence state read or mutation. Dynamic sequence use hidden inside functions is outside this dependency query. |

### C — function/RPC permissions

| ID | Purpose | Expected output / interpretation |
| --- | --- | --- |
| C01 | Inventory scoped routines and SECURITY DEFINER risk. | Names, identity signatures, return types, owner/security/language/volatility/leakproof fields, search_path and number of other settings. No default argument values, function definitions or arbitrary config values. NULL search_path means not fixed on the routine, not a proven safe caller path. |
| C02 | Expand routine EXECUTE ACLs. | Explicit/default owner and PUBLIC grants, grantor/grantee and grantability, for the same scope as C01. NULL proacl uses built-in defaults, which normally include PUBLIC EXECUTE. |
| C03 | Inspect effective EXECUTE and schema usage. | Per named existing role/routine booleans, including inherited/PUBLIC grants. Neither proves PostgREST exposure or a safe SECURITY DEFINER body. |

### D — migration compatibility

| ID | Purpose | Expected output / interpretation |
| --- | --- | --- |
| D01 | Detect proposed schema/role/relation/index/column name conflicts. | One row per explicit draft name with an existence flag. Existing names require reconciliation; do not bypass with IF NOT EXISTS or overwrite objects. |
| D02 | Detect draft constraint/policy collisions on intended tables. | Expected names and existence flags. Definitions and owners still need inspection if a name is already present. |
| D03 | Find every overload of each of the six proposed RPC names. | Present/missing, routine kind, actual/expected argument types, owner and exact-signature match. A same-name different overload may still introduce API ambiguity. No default arguments returned. |
| D04 | Inspect scoped default ACL overrides/additions. | Actual creator, global or schema scope, object kind, grantee/grantor and privileges. Covers named prospective creators and relevant current owners, not every role in the database. A missing row is not a default-deny policy. |
| D05 | Show built-in fallback ACLs for named prospective creators. | Owner/PUBLIC baseline table, sequence, routine and schema privileges. This is a baseline, not the effective merged result when D04 entries exist. If the real creator is neither named nor a relevant current owner, identify it before drawing conclusions. |
| D06 | Check UUID/default/type/extension prerequisites without evaluation. | id/user_id/email type and domain flags, directly recorded default function dependencies and extension versions. No UUID generated or default called. Built-in pinned dependencies can be absent; missing dependency output does not prove there is no default function. |
| D07 | Inspect allowlisted runtime role/database defaults. | Only timeout/read-only/row-security settings, with nonstandard values withheld. No arbitrary GUCs, JWT keys, URLs or credentials. Missing settings, or zero timeout values, do not establish an enforced runtime budget. SET ROLE/pool/client/per-request behavior can differ from role defaults. |

## Interpretation boundaries

RLS enabled alone is insufficient. Combine table/column/schema privileges, role
inheritance, owner/BYPASSRLS/superuser status, forced RLS and all applicable
permissive/restrictive policies. Policy inheritance, USING versus WITH CHECK,
NULL expressions and default-deny behavior require version-appropriate review.
`has_*_privilege` answers ACL questions; it does not execute a query as that user,
evaluate policy row predicates or prove the anonymous API is denied.

The proposed owner must remain NOLOGIN/NOBYPASSRLS with no untrusted membership.
An EXECUTE-only backend can still impersonate a provider subject if a future
handler forwards unverified browser claims. SECURITY DEFINER is a privilege
boundary, not provider authentication. A fixed search_path does not prove the
body is safe; review qualified object references, dynamic SQL, overloads,
indirect call chains, triggers and helper-function privileges separately.

Default ACL entries concern the role that originally CREATES an object, which
may differ from its later owner. Global defaults can override built-ins;
schema-local entries add privileges. Current object ACL NULL uses built-in object
defaults, not the current pg_default_acl entries. After changing ownership,
existing grants/default-derived grants still require audit. Do not inspect only
oauth_storage_owner if a migration operator creates functions before ALTER OWNER.

Column NOT NULL and domain NOT NULL/defaults are distinct. Index readiness,
validity, partial predicates, expression keys, collation/opclasses and NULLS
NOT DISTINCT can affect uniqueness. Names alone do not prove a usable uniqueness
constraint. Domain rules, opaque extension options and withheld expressions
require a separately authorized local review; do not evaluate application
functions or defaults to discover their behavior in production.

## Withholding and sanitizing metadata

No application table is queried, counted or sampled. No password hashes, emails,
UUID records, notes, filenames, chat, provider tokens or attempt/ticket values
are retrieved. The script avoids auth/vault tables, pg_authid, pg_stats/statistics,
pg_stat_activity query text, connection/FDW options, sequence current values,
comments, function bodies, argument defaults and general settings/config dumps.

Stored metadata can itself contain sensitive literals. A03/A04/A05/B04 inspect
the internal expression tree solely to detect a CONST node; if present, the
entire expression is withheld before deparsing. This deliberately hides harmless
constants too, including provider names, true/false policies and sequence OIDs.
WITHHELD is an outstanding review item, not a sanitized proof of authorization.
The internal catalog format is version-dependent; do not broaden the extraction
or output raw trees if the detector is incompatible. Return UNKNOWN instead.

Even no-constant expression structure, object/role names, memberships, ACLs,
search_path and function signatures reveal the authorization design. Identifiers
can themselves contain private labels. Before sharing any output:

1. Review it locally in an approved private workspace; do not assume metadata is
   public or automatically safe. Remove project/customer/person labels and
   unexpected URL/token-like identifiers. Do not save raw exports in this repo.
2. Use consistent aliases for custom roles/schemas/objects while retaining their
   relationships. Preserve semantic markers PUBLIC, anon/authenticated/service_role,
   owner/bypass flags, grantability, policy command/mode, and search-path order/
   pg_temp/$user meaning. Removing those can hide the security issue.
3. Prefer structured findings: for example, “browser role has password_hash SELECT
   privilege”, “RPC owner bypasses RLS”, or “provider default privately verified”,
   instead of raw definitions. Distinguish confirmed flags from UNKNOWN/withheld.
4. Do not share entire policy/function definitions to resolve withheld fields.
   A trusted owner can independently review literal-bearing metadata and provide
   sanitized conclusions under separate approval. Function definitions may
   contain hardcoded credentials, endpoints, personal identifiers or dynamic SQL;
   they are intentionally outside this script.
5. Preserve query IDs, PostgreSQL version and visibility limitations in the
   sanitized evidence. Never include keys, JWTs, cookies, connection strings or
   actual application records. If a sensitive value is discovered incidentally,
   stop exporting it and follow the project's private response process.

## Evidence required before promoting the OAuth proposal

- Confirm the real schema/types/defaults/PKs/FKs/indexes/collations and RLS match
  the design, or prepare a separately reviewed reconciliation. All name conflicts,
  domain/default/trigger behavior and withheld security-relevant expressions need
  resolution. No automatic UPDATE/backfill/linking or destructive reconciliation.
- Verify actual backend and migration-creator roles without inspecting/pasting
  their keys. Show that anonymous/browser roles cannot access existing users,
  password hashes, sessions or private OAuth storage, directly or through another
  view/function/API path. Identify any custom/default/inherited EXECUTE grants.
- Confirm the proposed definer owner has no unsafe membership/CREATE privilege,
  keeps NOBYPASSRLS/NOLOGIN, and has only the required column/storage privileges.
  Reconcile all PUBLIC/default grants and actual helper/default function rights.
- Approve actual runtime statement/lock budgets and bounded cleanup. D07 provides
  metadata clues only; real API cancellation and lock-wait behavior need isolated
  tests through the intended transport. Migration-local SET LOCAL is insufficient.
- Obtain separately authorized, privacy-preserving compatibility attestations
  about legacy provider/password metadata and normalized-email collisions. This
  script intentionally cannot answer those data questions, even as aggregates.
  Never backfill a subject from email. Approve independent legacy recovery.
- Validate the resulting candidate in an isolated Supabase-compatible environment
  with synthetic users/roles and real concurrency/rollback tests. Prior vanilla
  PostgreSQL 16.16 results do not validate the deployed Supabase configuration.

## Questions SQL metadata cannot settle

Actual PostgREST exposed schemas, schema cache/routing, gateway behavior, request
role switching, JWT validation, per-request GUCs, returned row representations and
commit/timeout semantics need service configuration evidence and isolated API
tests. An SQL Editor session's role/settings cannot establish the application's
key selection. Application credential handling, deployment secret distribution,
server-only storage, provider response verification, Secure/HttpOnly browser
cookies, logout ordering and fresh Streamlit-session handoffs require separate
application/deployment/browser evidence. No key or token should be decoded or
printed just to complete this inspection.

Behavioral browser/anonymous denial and legitimate password/ownership operations
must be tested later in an authorized isolated environment with synthetic records,
not by querying or attempting mutations on real users here. Other views, dynamic
SQL and deeper helper call chains may create access paths outside this scoped
catalog report. No complete security conclusion follows from this script alone.

The old OAuth callback remains insecure. These queries do not authorize a remote
migration, credential change, production OAuth implementation or deployment.

References: [PostgreSQL privilege/metadata functions](https://www.postgresql.org/docs/16/functions-info.html),
[policy catalog](https://www.postgresql.org/docs/16/catalog-pg-policy.html),
[default ACL semantics](https://www.postgresql.org/docs/16/catalog-pg-default-acl.html).
