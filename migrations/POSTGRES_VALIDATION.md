# Batch 4B-2B — isolated PostgreSQL validation

Date: 2026-11-24 (Asia/Karachi). Local experiment only; no Supabase access,
production data, authentication changes, executable repository migration or release.

## Runtime and containment

No database version was documented in the repository. Selected supported official
`docker.io/library/postgres:16`, then ran its immutable digest:

`postgres@sha256:3950ad7c3148ca2175ef1b6c36c9efbf78957ae8fbe8b3a5d7c35af50500382f`

Actual server: **16.16 (Debian 16.16-1.pgdg13+1)**. This is vanilla PostgreSQL,
not a Supabase image or evidence of the deployed PostgreSQL version.

- Unique disposable container; `--network none`, no published ports, no host
  networking, no bind mounts, no Docker socket or repository mounted inside.
- `--user postgres`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`;
  512 MiB memory, one CPU, 128 PIDs. Verified using selected Docker inspect fields.
- Three tmpfs mounts only: PGDATA parent 256 MiB, Unix-socket directory 16 MiB,
  temporary directory 32 MiB. No named/anonymous volumes or experiment network.
- `listen_addresses=''` verified in PostgreSQL. Every connection used container-
  local `psql` via `docker exec`; independent processes/backend PIDs for races.
- Fresh random container-admin password was generated in an owner-only temporary
  env file, never printed or reused. Local Unix authentication used trust strictly
  inside this unreachable test container. Network/password/JWT authentication was
  not validated. Non-admin LOGIN probes separately tested database ACLs and owner
  role escalation denial; simulated Supabase roles were synthetic.
- Docker log driver `none`; PostgreSQL statement logging off, error-statement and
  message thresholds panic, logging collector off, error parameter length zero.
  Client errors captured SQLSTATE only, not SQL payloads. Generated credential
  was absent from result artifacts. No raw browser state/tickets/codes/tokens
  reached PostgreSQL: only synthetic hashes. No browser/OAuth flow was executed.

Commands used, with experiment-only path/name placeholders:

```sh
docker --host unix:///var/run/docker.sock pull docker.io/library/postgres:16
# Run by digest, not by a mutable tag. All storage is disposable tmpfs.
docker --host unix:///var/run/docker.sock run --detach --name UNIQUE_NAME \
  --network none --read-only --user postgres --cap-drop ALL \
  --security-opt no-new-privileges --memory 512m --cpus 1 --pids-limit 128 \
  --log-driver none \
  --tmpfs /var/lib/postgresql/data:rw,mode=1777,size=256m \
  --tmpfs /var/run/postgresql:rw,mode=1777,size=16m \
  --tmpfs /tmp:rw,mode=1777,size=32m --env-file PRIVATE_TEMP_ENV IMAGE_DIGEST \
  postgres -c listen_addresses= -c log_statement=none \
  -c log_min_error_statement=panic -c log_min_messages=panic \
  -c log_error_verbosity=terse -c log_parameter_max_length_on_error=0 \
  -c logging_collector=off
# SQL supplied on stdin, never as credential-bearing command-line arguments.
docker --host unix:///var/run/docker.sock exec -i --user postgres UNIQUE_NAME \
  psql -X -qAt -v ON_ERROR_STOP=1 -v VERBOSITY=sqlstate \
  -U TEST_LOGIN -d oauth_synthetic
```

## SQL tested and corrections

Extracted exactly one fenced SQL transaction into a private /tmp candidate file.
The repository proposal remains **non-executable Markdown**. Assumed public schema,
README users/sessions types and UUID defaults, `uuid-ossp` extension, lowercase
unique emails, users/sessions RLS enabled, browser table grants revoked, public
schema CREATE restricted, and synthetic anon/authenticated/service_role roles.
The service role had BYPASSRLS but no direct private grants. These are explicit
fixture facts, not discovered deployment facts.

Applied the original complete DDL/RPC/ACL transaction successfully. It preserved
the two synthetic legacy user UUIDs and their session FKs. Actual calls exercised
all six RPC signatures, private SELECT/INSERT denial, malicious inputs and
search_path, unique/check constraints, real RLS and column privileges. Expected
negative SQLSTATEs included 42501 (permissions/RLS), 23505 (uniqueness), 23514
(checks), 42710 (repeat install) and deliberately raised transaction errors.

**One SQL defect corrected:** with an injected nil-UUID default, the original
finish function returned false yet left one newly inserted user inside its
transaction. This was reproduced and the entire proof transaction rolled back.
The corrected nil branch raises SQLSTATE **22023**, rolling back the account,
handoff and completion changes. Missing subject resolution/email collision still
returns false. The prior, separately committed state consumption remains consumed.
A static offline regression protects the new raise/rollback branch.

Freshly recreated the synthetic database and roles, applied the corrected entire
candidate from scratch, and reran the checks. Final result: **58 real PostgreSQL
checks passed; zero unresolved failures**. The original nil-UUID failure is retained
here as evidence, not counted as a passing test of the original SQL.

One temporary cleanup fixture initially used separate wall-clock calls at an exact
TTL ceiling, exceeding the constraint by microseconds. Capturing one timestamp
fixed the fixture; no SQL constraint was loosened. A separate 301-second attempt
was correctly rejected by the real five-minute constraint.

**Runtime deadline gap:** `SET LOCAL statement_timeout` / `lock_timeout` in the
migration do not govern later RPC sessions. The synthetic backend reported
`statement_timeout=0`. Configure and verify appropriate runtime statement/lock
budgets through the intended PostgREST/connection path before implementation
approval; do not assume an HTTP timeout cancels database work. Likewise, cleanup
requires a bounded scheduling/batching plan. These limits were not silently added
to deployment configuration here.

## Real PostgreSQL checks (all PASS after correction)

1. Private records and RPC denial: anon.
2. Private records and RPC denial: authenticated.
3. Private records and RPC denial: outsider.
4. All six RPCs denied to browser roles and granted only to backend/owner.
5. Real non-admin login denied private RPC: anon_client.
6. Real non-admin login denied private RPC: browser_client.
7. Real backend login executes restricted RPC.
8. Backend login cannot SET ROLE function owner.
9. Backend has no direct private table read even with BYPASSRLS.
10. Backend cannot directly insert user UUIDs.
11. Function owner has no sessions access.
12. Backend cannot escalate its role.
13. All six definers have fixed search_path and restricted nonlogin owner.
14. Private tables enable and force RLS.
15. Forced RLS denies browser even after temporary SELECT grants.
16. BYPASSRLS bypasses policies if grants are reintroduced (limitation).
17. No backend owner membership or inherited public CREATE.
18. Malformed and unknown attempt fail closed.
19. Wrong browser does not burn state; successful state cannot replay.
20. Expired state denied without cleanup.
21. Independent PostgreSQL connections: one concurrent state winner.
22. Finish cannot issue a ticket before attempt consumption.
23. Password/legacy/other-subject email collisions never link accounts.
24. Existing subject retains UUID despite changed/colliding contact email.
25. Nullable unique subjects preserve multiple legacy NULL mappings.
26. Duplicate stable subject rejected by real unique constraint.
27. Password row cannot acquire subject via constraint.
28. Noncanonical subject fails before account work.
29. Subject SQL injection string is data and denied.
30. Concurrent same-subject inserts converge on one UUID.
31. Concurrent different subjects sharing email yield one winner.
32. Wrong browser does not burn ticket; redeem/reissue replay denied.
33. Independent PostgreSQL connections: one concurrent handoff winner.
34. Unknown/malformed handoffs return no identity.
35. Expired handoff denied without cleanup.
36. Logout revokes in-flight attempts and pending handoffs.
37. Latest deliberate start revokes previous ticket.
38. Redemption rechecks current subject/UUID relationship without burning denial.
39. No RPC accepts a UUID input parameter.
40. Ticket uniqueness failure rolls account creation back; state stays consumed.
41. Storage/RLS failure rolls transaction back and never reopens state.
42. Invalid UUID default must not leave a partial account.
43. Expiry after an independent row-lock wait: state cannot be consumed.
44. Expiry after an independent row-lock wait: handoff cannot be redeemed.
45. Expiry during account insert rolls the new account back.
46. Concurrent finish/logout leaves no redeemable pending ticket.
47. Concurrent new start/logout cannot revive the old ticket.
48. Duplicate start rolls revocation back instead of burning existing ticket.
49. Caller temp objects/search_path cannot spoof the qualified identity lookup.
50. Caller JWT subject/GUC cannot replace stored handoff UUID.
51. Handoff deadline capped at attempt deadline and 60 seconds.
52. Deleting synthetic identity removes its transient handoff and denies login.
53. Repeated migration aborts at existing role without modifying data.
54. Late migration failure rolls all DDL/role creation back and preserves base rows.
55. Legacy UUID/session relationships still intact after all tests.
56. New RPC runtime statement timeout is not set by migration SET LOCAL (deployment requirement).
57. Repeated cleanup removes long-expired transient rows only.
58. Database rejects attempts exceeding maximum five-minute TTL.

The concurrency tests used independent psql connections, not model locks. State
and ticket races each had exactly one winner. Same-subject creation yielded one
UUID; different subjects sharing an email yielded one success and one denial.
Row-lock holders delayed claim/redemption past expiry: no consumed result escaped.
Slow account creation past expiry rolled its new row back. Finish/logout and
start/logout races left no old redeemable ticket. Already redeemed sessions are
outside this storage-only experiment; later UI logout coordination is still needed.

A second synthetic database tested a fault just before migration COMMIT: schema,
column, function and new role changes rolled back, with base rows intact. Repeated
installation intentionally failed at the existing owner role without data changes.
Repeated cleanup removed long-expired transient records and preserved users,
sessions and current attempts. This does not benchmark large-table locks or volume.

## Six-RPC design review

All six public RPCs execute only for the trusted backend role (plus owner/admin).
SECURITY DEFINER is needed for that exec-only boundary because callers have no
private-table grants. Owner is NOLOGIN/NOBYPASSRLS; all six have fixed pg_catalog
search_path, qualified relations and no dynamic SQL. Security-invoker alternatives
would require broader direct table privileges. PostgreSQL cannot attest that the
privileged caller verified GitHub: subject/email inputs must come exclusively from
future validated provider responses, never from browser identity assertions.

| RPC | Inputs / purpose | Separation and failure behavior |
| --- | --- | --- |
| oauth_start | State and binding hashes; create bounded attempt and revoke previous browser attempts/tickets. | Must be one transaction. Logout revocation shares the lock protocol; combining the APIs would complicate intent and inputs. Duplicate state aborts and rolls revocation back. |
| oauth_consume_attempt | State and binding hashes; atomic claim before provider HTTP. | Must remain a separately committed step. Wrong, expired, consumed or revoked input returns false; HTTP/storage failure cannot reopen committed state. |
| oauth_finish_attempt | State/binding/ticket hashes, verified subject/email; resolve/create user and issue ticket. | Account creation, ticket and completion belong together. Unique collision re-reads subject only; email cannot link legacy/password rows. Unexpected errors roll back. No UUID argument. |
| oauth_redeem_handoff | Ticket and binding hashes; atomically return stored local UUID/subject once. | Separate fresh-session handoff phase; cannot safely collapse into finish. Rechecks current mapping, expiry and revocation. No UUID argument; wrong/missing input yields no identity. |
| oauth_revoke_browser | Binding hash; invalidate pending/in-flight attempts and tickets. | Required independently for logout. A shared private helper could remove repeated UPDATE text, but is not necessary for correctness and was not added. Does not terminate already authenticated sessions. |
| oauth_purge_expired | No identity input; delete old transient records only. | Optional public RPC: an administrator maintenance job could execute equivalent SQL instead. Keep maintenance separate from latency-sensitive login. Consider admin-only execution when scheduling is approved. Expiry checks never depend on purge. |

## Remaining gates and recommendation

Retain the existing Streamlit/custom-auth architecture and the proposed private
storage plus exec-only backend RPC boundary. No extra service or direct database
port is required by this design. Prefer the existing HTTPS transport if its
server-only credential and PostgREST grants are verified. A dedicated narrower
backend role is an alternative requiring approved credential/JWT plumbing.

Before an executable migration or OAuth implementation stage:

- Reconcile the actual Supabase version, schema, UUID defaults, normalized-email
  uniqueness, triggers, extensions, role memberships, default/inherited/column
  ACLs, restrictive policies, exposed schemas, API role switching and return/
  commit semantics. Local CREATE ROLE/service-role simulation is not Supabase.
- Confirm anonymous/browser denial of existing users/password hashes/sessions;
  verify legitimate password operations through the actual trusted boundary.
  BYPASSRLS was demonstrated to bypass policies when table grants were temporarily
  restored: RLS alone is insufficient, and existing service-role rights are unknown.
- Approve runtime deadlines, bounded cleanup, legacy recovery and the exact backend
  credential scope. A matching current verified email must never backfill a legacy
  subject. Preserve all existing UUIDs and foreign keys during approved recovery.
- Cut over atomically with the old email-only callback disabled/replaced. Do not
  leave it as an alternate path to new subject-bound accounts. Current OAuth still
  fails 20 security contracts and must not be publicly released.
- Validate actual browser cookies, fresh-session handoff, logout/session ordering,
  provider validation and transport in their separately authorized batches.

**Assessment:** corrected local SQL design passes this synthetic PostgreSQL gate.
No-go for remote execution, production OAuth, deployment or release until those
schema/permission/transport/recovery gates and approvals are satisfied. No Batch
4B-3 work is authorized by these results.

Offline suite remains separate: **157 tests, 137 passing, exactly the same 20
ordinary OAuth failures**, zero errors/unexpected isolation violations; temporary
workspace removed and exit 1 preserved. It includes 13 SQL static checks and 20
reference-model checks, neither a substitute for these real PostgreSQL tests.

## Cleanup

Container and its tmpfs database/socket/temp storage were removed after testing;
no experiment network or persistent volume was created. All private /tmp scripts,
SQL candidates, result files and generated credential file were removed. The
single official image was retained to avoid deleting possibly shared image data.
No other container/image/network/volume was modified. No commit, push, branch
change or deployment occurred. Production app/auth/database callers are unchanged.

Sources: [official PostgreSQL version support](https://www.postgresql.org/support/versioning/),
[official PostgreSQL image](https://hub.docker.com/_/postgres).
