-- READ ONLY — Batch 4B-2C. PREPARED ONLY; NOT EXECUTED.
-- Independent SELECT-only catalog queries; no application rows or RPC calls.
-- Not a migration. Keep outside migration runners. Read README.md first.
-- PostgreSQL 13+ catalog shape assumed; check A01 before authorizing other queries.
-- Missing/withheld metadata is UNKNOWN, not evidence that access is safe.
-- OPTIONAL_BACKEND_ROLE_NAME is a NON-SECRET role-name placeholder, not a key.
-- Replace it consistently only after the intended backend role is independently
-- identified. Never paste credentials or tokens into this file.
-- OPTIONAL_MIGRATION_ROLE_NAME is the separate, approved future DDL operator.
-- Expressions containing internal CONST nodes are withheld BEFORE deparsing:
-- stored literals may be credentials/PII. Function bodies/default arguments,
-- arbitrary GUCs, role passwords, statistics and sequence current values omitted.

-- A. SAFE STRUCTURAL INSPECTION

-- A01: Version and inspection identity; does not identify the application's role.
SELECT pg_catalog.current_setting('server_version') AS server_version,
       pg_catalog.current_setting('server_version_num') AS server_version_num,
       current_user AS inspection_role, session_user AS connection_role;

-- A02: Four target relations, including absent objects and unexpected object kinds.
WITH wanted(schema_name, relation_name) AS (
  VALUES ('public', 'users'), ('public', 'sessions'),
         ('oauth_private', 'oauth_attempts'), ('oauth_private', 'oauth_handoffs')
)
SELECT w.schema_name, w.relation_name, c.oid IS NOT NULL AS present,
       c.relkind AS relation_kind, owner.rolname AS owner_role,
       c.relrowsecurity AS rls_enabled, c.relforcerowsecurity AS rls_forced
FROM wanted w
LEFT JOIN pg_catalog.pg_namespace n ON n.nspname = w.schema_name
LEFT JOIN pg_catalog.pg_class c ON c.relnamespace = n.oid AND c.relname = w.relation_name
LEFT JOIN pg_catalog.pg_roles owner ON owner.oid = c.relowner
ORDER BY w.schema_name, w.relation_name;

-- A03: Column definitions; stored constant defaults/generated expressions withheld.
WITH targets AS (
  SELECT c.oid, n.nspname, c.relname FROM pg_catalog.pg_class c
  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname = 'public' AND c.relname IN ('users', 'sessions'))
     OR (n.nspname = 'oauth_private' AND c.relname IN ('oauth_attempts', 'oauth_handoffs'))
)
SELECT t.nspname AS schema_name, t.relname AS relation_name, a.attnum AS ordinal,
       a.attname AS column_name, pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
       a.attnotnull AS column_not_null, a.attidentity AS identity_kind,
       a.attgenerated AS generated_kind, coll_ns.nspname AS collation_schema,
       coll.collname AS collation_name, coll.collisdeterministic AS collation_deterministic,
       d.oid IS NOT NULL AS has_default_or_generation_expression,
       CASE WHEN d.oid IS NULL THEN NULL
            WHEN pg_catalog.strpos(d.adbin::text, '{CONST') > 0 THEN '[WITHHELD: stored constant]'
            ELSE pg_catalog.pg_get_expr(d.adbin, d.adrelid) END AS default_or_generation_structure
FROM targets t
JOIN pg_catalog.pg_attribute a ON a.attrelid = t.oid AND a.attnum > 0 AND NOT a.attisdropped
LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
LEFT JOIN pg_catalog.pg_collation coll ON coll.oid = a.attcollation
LEFT JOIN pg_catalog.pg_namespace coll_ns ON coll_ns.oid = coll.collnamespace
ORDER BY t.nspname, t.relname, a.attnum;

-- A04: Constraints, key columns and FK targets; expression constants withheld.
WITH targets AS (
  SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname = 'public' AND c.relname IN ('users', 'sessions'))
     OR (n.nspname = 'oauth_private' AND c.relname IN ('oauth_attempts', 'oauth_handoffs'))
)
SELECT n.nspname AS schema_name, c.relname AS relation_name, k.conname,
       k.contype AS constraint_type, k.convalidated, k.condeferrable, k.condeferred,
       pg_catalog.to_jsonb(k) ->> 'conenforced' AS enforced_if_supported,
       ARRAY(SELECT a.attname FROM pg_catalog.unnest(k.conkey) WITH ORDINALITY AS x(attnum, ord)
             JOIN pg_catalog.pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = x.attnum
             ORDER BY x.ord) AS key_columns,
       rn.nspname AS referenced_schema, rc.relname AS referenced_relation,
       ARRAY(SELECT a.attname FROM pg_catalog.unnest(k.confkey) WITH ORDINALITY AS x(attnum, ord)
             JOIN pg_catalog.pg_attribute a ON a.attrelid = k.confrelid AND a.attnum = x.attnum
             ORDER BY x.ord) AS referenced_columns,
       k.confupdtype AS fk_update_action, k.confdeltype AS fk_delete_action,
       CASE WHEN pg_catalog.strpos(COALESCE(k.conbin::text, ''), '{CONST') > 0
              THEN '[WITHHELD: stored constant]'
            ELSE pg_catalog.pg_get_constraintdef(k.oid, false) END AS definition_structure
FROM pg_catalog.pg_constraint k JOIN targets t ON t.oid = k.conrelid
JOIN pg_catalog.pg_class c ON c.oid = k.conrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_catalog.pg_class rc ON rc.oid = k.confrelid
LEFT JOIN pg_catalog.pg_namespace rn ON rn.oid = rc.relnamespace
ORDER BY n.nspname, c.relname, k.conname;

-- A05: Relevant indexes, validity and key/include layout; no indexed data read.
WITH targets AS (
  SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname = 'public' AND c.relname IN ('users', 'sessions'))
     OR (n.nspname = 'oauth_private' AND c.relname IN ('oauth_attempts', 'oauth_handoffs'))
)
SELECT n.nspname AS schema_name, c.relname AS relation_name, idx.relname AS index_name,
       i.indisprimary, i.indisunique, i.indisvalid, i.indisready,
       pg_catalog.to_jsonb(i) ->> 'indnullsnotdistinct' AS nulls_not_distinct_if_supported,
       am.amname AS index_method, i.indoption::smallint[] AS key_option_flags,
       i.indnkeyatts AS key_attribute_count, i.indnatts AS total_attribute_count,
       ARRAY(SELECT CASE WHEN x.attnum = 0 THEN '<expression>' ELSE a.attname::text END
             FROM pg_catalog.unnest(i.indkey::smallint[]) WITH ORDINALITY AS x(attnum, ord)
             LEFT JOIN pg_catalog.pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = x.attnum
             ORDER BY x.ord) AS key_then_include_columns,
       ARRAY(SELECT opn.nspname || '.' || op.opcname
             FROM pg_catalog.unnest(i.indclass::oid[]) WITH ORDINALITY AS x(op_oid, ord)
             JOIN pg_catalog.pg_opclass op ON op.oid = x.op_oid
             JOIN pg_catalog.pg_namespace opn ON opn.oid = op.opcnamespace
             ORDER BY x.ord) AS key_operator_classes,
       ARRAY(SELECT coll_ns.nspname || '.' || coll.collname FROM pg_catalog.unnest(i.indcollation::oid[])
             WITH ORDINALITY AS x(coll_oid, ord)
             LEFT JOIN pg_catalog.pg_collation coll ON coll.oid = x.coll_oid
             LEFT JOIN pg_catalog.pg_namespace coll_ns ON coll_ns.oid = coll.collnamespace
             ORDER BY x.ord) AS key_collations,
       CASE WHEN i.indexprs IS NULL THEN NULL
            WHEN pg_catalog.strpos(i.indexprs::text, '{CONST') > 0 THEN '[WITHHELD: stored constant]'
            ELSE pg_catalog.pg_get_expr(i.indexprs, i.indrelid) END AS expression_structure,
       CASE WHEN i.indpred IS NULL THEN NULL
            WHEN pg_catalog.strpos(i.indpred::text, '{CONST') > 0 THEN '[WITHHELD: stored constant]'
            ELSE pg_catalog.pg_get_expr(i.indpred, i.indrelid) END AS predicate_structure
FROM pg_catalog.pg_index i JOIN targets t ON t.oid = i.indrelid
JOIN pg_catalog.pg_class c ON c.oid = i.indrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
JOIN pg_catalog.pg_am am ON am.oid = idx.relam
ORDER BY n.nspname, c.relname, idx.relname;

-- A06: Non-internal triggers. Never return trigger arguments or function bodies.
SELECT n.nspname AS schema_name, c.relname AS relation_name, tr.tgname,
       tr.tgenabled AS enabled_mode, tr.tgtype AS trigger_type_mask,
       pn.nspname AS function_schema, p.proname AS function_name,
       pg_catalog.pg_get_function_identity_arguments(p.oid) AS identity_arguments
FROM pg_catalog.pg_trigger tr
JOIN pg_catalog.pg_class c ON c.oid = tr.tgrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_proc p ON p.oid = tr.tgfoid
JOIN pg_catalog.pg_namespace pn ON pn.oid = p.pronamespace
WHERE NOT tr.tgisinternal AND (
  (n.nspname = 'public' AND c.relname IN ('users', 'sessions')) OR
  (n.nspname = 'oauth_private' AND c.relname IN ('oauth_attempts', 'oauth_handoffs'))
)
ORDER BY n.nspname, c.relname, tr.tgname;

-- B. AUTHORIZATION AND RLS INSPECTION

-- B01: Named roles and attributes; missing role remains an explicit missing row.
WITH wanted(role_name) AS (
  VALUES ('anon'), ('authenticated'), ('service_role'), ('authenticator'),
         ('oauth_storage_owner'), ('postgres'), ('OPTIONAL_BACKEND_ROLE_NAME'),
         ('OPTIONAL_MIGRATION_ROLE_NAME')
)
SELECT w.role_name, r.oid IS NOT NULL AS present, r.rolcanlogin, r.rolsuper,
       r.rolbypassrls, r.rolinherit, r.rolcreaterole, r.rolcreatedb, r.rolreplication
FROM wanted w LEFT JOIN pg_catalog.pg_roles r ON r.rolname = w.role_name
ORDER BY w.role_name;

-- B02: Direct membership edges touching named roles (not a full role dump).
-- JSON field extraction tolerates pre-16 absence of membership inherit/set options.
WITH wanted AS (
  SELECT oid FROM pg_catalog.pg_roles WHERE rolname IN
    ('anon', 'authenticated', 'service_role', 'authenticator', 'oauth_storage_owner',
     'postgres', 'OPTIONAL_BACKEND_ROLE_NAME')
)
SELECT member.rolname AS member_role, granted.rolname AS granted_role,
       grantor.rolname AS grantor_role, m.admin_option,
       pg_catalog.to_jsonb(m) ->> 'inherit_option' AS membership_inherit_option,
       pg_catalog.to_jsonb(m) ->> 'set_option' AS membership_set_option
FROM pg_catalog.pg_auth_members m
JOIN pg_catalog.pg_roles member ON member.oid = m.member
JOIN pg_catalog.pg_roles granted ON granted.oid = m.roleid
LEFT JOIN pg_catalog.pg_roles grantor ON grantor.oid = m.grantor
WHERE m.member IN (SELECT oid FROM wanted) OR m.roleid IN (SELECT oid FROM wanted)
ORDER BY member.rolname, granted.rolname;

-- B03: Transitive capability toward backend, table and public/private definer owners.
-- Superuser results must be interpreted with the superuser flag, not as an ACL grant.
WITH sensitive AS (
  SELECT oid FROM pg_catalog.pg_roles
    WHERE rolname IN ('service_role', 'oauth_storage_owner', 'OPTIONAL_BACKEND_ROLE_NAME')
  UNION
  SELECT c.relowner FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE (n.nspname = 'public' AND c.relname IN ('users', 'sessions'))
       OR (n.nspname = 'oauth_private' AND c.relname IN ('oauth_attempts', 'oauth_handoffs'))
  UNION
  SELECT p.proowner FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname IN ('public', 'oauth_private') AND (p.prosecdef OR pg_catalog.left(p.proname, 6) = 'oauth_')
)
SELECT candidate.rolname AS candidate_role, candidate.rolsuper,
       target.rolname AS sensitive_role,
       pg_catalog.pg_has_role(candidate.oid, target.oid, 'MEMBER') AS member_direct_or_indirect,
       pg_catalog.pg_has_role(candidate.oid, target.oid, 'USAGE') AS privileges_available_without_set_role
FROM pg_catalog.pg_roles candidate CROSS JOIN sensitive s
JOIN pg_catalog.pg_roles target ON target.oid = s.oid
WHERE candidate.oid <> target.oid
  AND pg_catalog.pg_has_role(candidate.oid, target.oid, 'MEMBER')
ORDER BY target.rolname, candidate.rolname;

-- B04: Policies on the four target relations; PUBLIC is role OID zero.
-- WITHHELD expressions are NOT proven safe. No literal is emitted or evaluated.
SELECT n.nspname AS schema_name, c.relname AS relation_name, pol.polname,
       c.relrowsecurity AS rls_enabled, c.relforcerowsecurity AS rls_forced,
       pol.polpermissive, pol.polcmd AS command_code,
       ARRAY(SELECT CASE WHEN x.role_oid = 0 THEN 'PUBLIC' ELSE r.rolname::text END
             FROM pg_catalog.unnest(pol.polroles) AS x(role_oid)
             LEFT JOIN pg_catalog.pg_roles r ON r.oid = x.role_oid ORDER BY x.role_oid) AS applicable_roles,
       CASE WHEN pol.polqual IS NULL THEN NULL
            WHEN pg_catalog.strpos(pol.polqual::text, '{CONST') > 0 THEN '[WITHHELD: stored constant]'
            ELSE pg_catalog.pg_get_expr(pol.polqual, pol.polrelid) END AS using_structure,
       CASE WHEN pol.polwithcheck IS NULL THEN NULL
            WHEN pg_catalog.strpos(pol.polwithcheck::text, '{CONST') > 0 THEN '[WITHHELD: stored constant]'
            ELSE pg_catalog.pg_get_expr(pol.polwithcheck, pol.polrelid) END AS with_check_structure
FROM pg_catalog.pg_policy pol
JOIN pg_catalog.pg_class c ON c.oid = pol.polrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE (n.nspname = 'public' AND c.relname IN ('users', 'sessions'))
   OR (n.nspname = 'oauth_private' AND c.relname IN ('oauth_attempts', 'oauth_handoffs'))
ORDER BY n.nspname, c.relname, pol.polname;

-- B05: Direct schema/table/column/related-sequence ACLs, including PUBLIC and defaults.
-- A NULL table/schema/sequence ACL uses acldefault; column NULL means no extra ACL.
WITH targets AS (
  SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname = 'public' AND c.relname IN ('users', 'sessions'))
     OR (n.nspname = 'oauth_private' AND c.relname IN ('oauth_attempts', 'oauth_handoffs'))
), sequences AS (
  SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  WHERE c.relkind = 'S' AND (EXISTS (
    SELECT 1 FROM pg_catalog.pg_depend d WHERE d.classid = 'pg_catalog.pg_class'::regclass
      AND d.objid = c.oid AND d.refclassid = 'pg_catalog.pg_class'::regclass
      AND d.refobjid IN (SELECT oid FROM targets) AND d.deptype IN ('a', 'i')
  ) OR EXISTS (
    SELECT 1 FROM pg_catalog.pg_depend d JOIN pg_catalog.pg_attrdef ad ON ad.oid = d.objid
    WHERE d.classid = 'pg_catalog.pg_attrdef'::regclass
      AND d.refclassid = 'pg_catalog.pg_class'::regclass AND d.refobjid = c.oid
      AND ad.adrelid IN (SELECT oid FROM targets)
  ))
), objects AS (
  SELECT 'schema' AS object_kind, n.nspname::text AS schema_name,
         n.nspname::text AS object_name, NULL::text AS column_name,
         n.nspowner AS owner_oid, n.nspacl IS NULL AS uses_builtin_acl,
         COALESCE(n.nspacl, pg_catalog.acldefault('n', n.nspowner)) AS acl
    FROM pg_catalog.pg_namespace n WHERE n.nspname IN ('public', 'oauth_private')
  UNION ALL
  SELECT CASE WHEN c.relkind = 'S' THEN 'sequence' ELSE 'table' END,
         n.nspname, c.relname, NULL, c.relowner, c.relacl IS NULL,
         COALESCE(c.relacl, pg_catalog.acldefault(
           CASE WHEN c.relkind = 'S' THEN 's'::"char" ELSE 'r'::"char" END, c.relowner))
    FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE c.oid IN (SELECT oid FROM targets) OR c.oid IN (SELECT oid FROM sequences)
  UNION ALL
  SELECT 'column', n.nspname, c.relname, a.attname, c.relowner, a.attacl IS NULL,
         COALESCE(a.attacl, ARRAY[]::pg_catalog.aclitem[])
    FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE c.oid IN (SELECT oid FROM targets) AND a.attnum > 0 AND NOT a.attisdropped
)
SELECT o.object_kind, o.schema_name, o.object_name, o.column_name,
       owner.rolname AS owner_role, o.uses_builtin_acl,
       CASE WHEN x.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname::text END AS grantee_role,
       grantor.rolname AS grantor_role, x.privilege_type, x.is_grantable
FROM objects o LEFT JOIN LATERAL pg_catalog.aclexplode(o.acl) x ON true
LEFT JOIN pg_catalog.pg_roles owner ON owner.oid = o.owner_oid
LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = x.grantee
LEFT JOIN pg_catalog.pg_roles grantor ON grantor.oid = x.grantor
ORDER BY o.object_kind, o.schema_name, o.object_name, o.column_name, grantee_role, x.privilege_type;

-- B06: Effective role/table/schema privileges. Grantability is NOT row authorization.
WITH roles AS (
  SELECT oid, rolname, rolsuper, rolbypassrls FROM pg_catalog.pg_roles WHERE rolname IN
    ('anon', 'authenticated', 'service_role', 'authenticator', 'oauth_storage_owner',
     'postgres', 'OPTIONAL_BACKEND_ROLE_NAME')
), targets AS (
  SELECT c.oid, c.relowner, c.relrowsecurity, c.relforcerowsecurity,
         n.oid AS schema_oid, n.nspname, c.relname
  FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname = 'public' AND c.relname IN ('users', 'sessions'))
     OR (n.nspname = 'oauth_private' AND c.relname IN ('oauth_attempts', 'oauth_handoffs'))
)
SELECT r.rolname, t.nspname AS schema_name, t.relname AS relation_name,
       r.rolsuper, r.rolbypassrls, r.oid = t.relowner AS is_direct_owner,
       pg_catalog.pg_has_role(r.oid, t.relowner, 'USAGE') AS owner_privileges_available,
       t.relrowsecurity, t.relforcerowsecurity,
       pg_catalog.has_schema_privilege(r.oid, t.schema_oid, 'USAGE') AS schema_usage,
       pg_catalog.has_schema_privilege(r.oid, t.schema_oid, 'CREATE') AS schema_create,
       pg_catalog.has_table_privilege(r.oid, t.oid, 'SELECT') AS table_select,
       pg_catalog.has_table_privilege(r.oid, t.oid, 'INSERT') AS table_insert,
       pg_catalog.has_table_privilege(r.oid, t.oid, 'UPDATE') AS table_update,
       pg_catalog.has_table_privilege(r.oid, t.oid, 'DELETE') AS table_delete,
       pg_catalog.has_any_column_privilege(r.oid, t.oid, 'SELECT') AS any_column_select
FROM roles r CROSS JOIN targets t ORDER BY r.rolname, t.nspname, t.relname;

-- B07: Effective column rights (table and inherited grants also count).
WITH roles AS (
  SELECT oid, rolname FROM pg_catalog.pg_roles WHERE rolname IN
    ('anon', 'authenticated', 'service_role', 'authenticator', 'oauth_storage_owner',
     'postgres', 'OPTIONAL_BACKEND_ROLE_NAME')
)
SELECT r.rolname, n.nspname AS schema_name, c.relname AS relation_name,
       a.attname AS column_name,
       pg_catalog.has_column_privilege(r.oid, c.oid, a.attnum, 'SELECT') AS can_select,
       pg_catalog.has_column_privilege(r.oid, c.oid, a.attnum, 'INSERT') AS can_insert,
       pg_catalog.has_column_privilege(r.oid, c.oid, a.attnum, 'UPDATE') AS can_update
FROM pg_catalog.pg_attribute a
JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace CROSS JOIN roles r
WHERE a.attnum > 0 AND NOT a.attisdropped AND (
  (n.nspname = 'public' AND c.relname IN ('users', 'sessions')) OR
  (n.nspname = 'oauth_private' AND c.relname IN ('oauth_attempts', 'oauth_handoffs'))
)
ORDER BY r.rolname, n.nspname, c.relname, a.attnum;

-- B08: Effective sequence rights. No nextval, currval, setval or last_value read.
WITH roles AS (
  SELECT oid, rolname FROM pg_catalog.pg_roles WHERE rolname IN
    ('anon', 'authenticated', 'service_role', 'authenticator', 'oauth_storage_owner',
     'postgres', 'OPTIONAL_BACKEND_ROLE_NAME')
), targets AS (
  SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname = 'public' AND c.relname IN ('users', 'sessions'))
     OR (n.nspname = 'oauth_private' AND c.relname IN ('oauth_attempts', 'oauth_handoffs'))
)
SELECT r.rolname, n.nspname AS schema_name, c.relname AS sequence_name,
       pg_catalog.has_sequence_privilege(r.oid, c.oid, 'USAGE') AS can_use,
       pg_catalog.has_sequence_privilege(r.oid, c.oid, 'SELECT') AS can_select,
       pg_catalog.has_sequence_privilege(r.oid, c.oid, 'UPDATE') AS can_update
FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN roles r
WHERE c.relkind = 'S' AND (EXISTS (
  SELECT 1 FROM pg_catalog.pg_depend d WHERE d.classid = 'pg_catalog.pg_class'::regclass
    AND d.objid = c.oid AND d.refclassid = 'pg_catalog.pg_class'::regclass
    AND d.refobjid IN (SELECT oid FROM targets) AND d.deptype IN ('a', 'i')
) OR EXISTS (
  SELECT 1 FROM pg_catalog.pg_depend d JOIN pg_catalog.pg_attrdef ad ON ad.oid = d.objid
  WHERE d.classid = 'pg_catalog.pg_attrdef'::regclass
    AND d.refclassid = 'pg_catalog.pg_class'::regclass AND d.refobjid = c.oid
    AND ad.adrelid IN (SELECT oid FROM targets)
)) ORDER BY r.rolname, n.nspname, c.relname;

-- C. FUNCTION / RPC PERMISSION INSPECTION
-- Scope: public/private OAuth-name routines, SECURITY DEFINER routines in those
-- two schemas, and direct function dependencies of target policies/defaults/
-- constraints/indexes/non-internal triggers. Not an exhaustive call-graph audit.

-- C01: Routine identity/owner/security/search_path; no body, defaults or arbitrary GUCs.
WITH targets AS (
  SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname = 'public' AND c.relname IN ('users', 'sessions'))
     OR (n.nspname = 'oauth_private' AND c.relname IN ('oauth_attempts', 'oauth_handoffs'))
), dependent_objects(classid, objid) AS (
  SELECT 'pg_catalog.pg_policy'::regclass, p.oid FROM pg_catalog.pg_policy p WHERE p.polrelid IN (SELECT oid FROM targets)
  UNION SELECT 'pg_catalog.pg_attrdef'::regclass, d.oid FROM pg_catalog.pg_attrdef d WHERE d.adrelid IN (SELECT oid FROM targets)
  UNION SELECT 'pg_catalog.pg_constraint'::regclass, k.oid FROM pg_catalog.pg_constraint k WHERE k.conrelid IN (SELECT oid FROM targets)
  UNION SELECT 'pg_catalog.pg_class'::regclass, i.indexrelid FROM pg_catalog.pg_index i WHERE i.indrelid IN (SELECT oid FROM targets)
), scope AS (
  SELECT p.oid FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname IN ('public', 'oauth_private') AND (p.prosecdef OR pg_catalog.left(p.proname, 6) = 'oauth_')
  UNION SELECT d.refobjid FROM pg_catalog.pg_depend d JOIN dependent_objects o ON o.classid = d.classid AND o.objid = d.objid
    WHERE d.refclassid = 'pg_catalog.pg_proc'::regclass
  UNION SELECT tr.tgfoid FROM pg_catalog.pg_trigger tr WHERE tr.tgrelid IN (SELECT oid FROM targets) AND NOT tr.tgisinternal
)
SELECT n.nspname AS schema_name, p.proname, p.prokind AS routine_kind,
       pg_catalog.pg_get_function_identity_arguments(p.oid) AS identity_arguments,
       pg_catalog.pg_get_function_result(p.oid) AS result_type,
       owner.rolname AS owner_role, p.prosecdef AS security_definer,
       owner.rolsuper AS owner_superuser, owner.rolbypassrls AS owner_bypasses_rls,
       l.lanname AS language, p.provolatile AS volatility, p.proleakproof,
       cfg.search_path, cfg.other_setting_count,
       'BODY_AND_ARGUMENT_DEFAULTS_INTENTIONALLY_OMITTED' AS definition_status
FROM scope s JOIN pg_catalog.pg_proc p ON p.oid = s.oid
JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
JOIN pg_catalog.pg_roles owner ON owner.oid = p.proowner
JOIN pg_catalog.pg_language l ON l.oid = p.prolang
LEFT JOIN LATERAL (
  SELECT pg_catalog.max(pg_catalog.substr(setting, 13))
           FILTER (WHERE pg_catalog.left(setting, 12) = 'search_path=') AS search_path,
         pg_catalog.count(*) FILTER (WHERE pg_catalog.left(setting, 12) <> 'search_path=') AS other_setting_count
  FROM pg_catalog.unnest(p.proconfig) AS x(setting)
) cfg ON true
ORDER BY n.nspname, p.proname, identity_arguments;

-- C02: Direct routine EXECUTE ACLs, including PUBLIC's built-in defaults.
WITH targets AS (
  SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname = 'public' AND c.relname IN ('users', 'sessions'))
     OR (n.nspname = 'oauth_private' AND c.relname IN ('oauth_attempts', 'oauth_handoffs'))
), dependent_objects(classid, objid) AS (
  SELECT 'pg_catalog.pg_policy'::regclass, p.oid FROM pg_catalog.pg_policy p WHERE p.polrelid IN (SELECT oid FROM targets)
  UNION SELECT 'pg_catalog.pg_attrdef'::regclass, d.oid FROM pg_catalog.pg_attrdef d WHERE d.adrelid IN (SELECT oid FROM targets)
  UNION SELECT 'pg_catalog.pg_constraint'::regclass, k.oid FROM pg_catalog.pg_constraint k WHERE k.conrelid IN (SELECT oid FROM targets)
  UNION SELECT 'pg_catalog.pg_class'::regclass, i.indexrelid FROM pg_catalog.pg_index i WHERE i.indrelid IN (SELECT oid FROM targets)
), scope AS (
  SELECT p.oid FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname IN ('public', 'oauth_private') AND (p.prosecdef OR pg_catalog.left(p.proname, 6) = 'oauth_')
  UNION SELECT d.refobjid FROM pg_catalog.pg_depend d JOIN dependent_objects o ON o.classid = d.classid AND o.objid = d.objid
    WHERE d.refclassid = 'pg_catalog.pg_proc'::regclass
  UNION SELECT tr.tgfoid FROM pg_catalog.pg_trigger tr WHERE tr.tgrelid IN (SELECT oid FROM targets) AND NOT tr.tgisinternal
)
SELECT n.nspname AS schema_name, p.proname,
       pg_catalog.pg_get_function_identity_arguments(p.oid) AS identity_arguments,
       owner.rolname AS owner_role, p.proacl IS NULL AS uses_builtin_acl,
       CASE WHEN x.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname::text END AS grantee_role,
       grantor.rolname AS grantor_role, x.privilege_type, x.is_grantable
FROM scope s JOIN pg_catalog.pg_proc p ON p.oid = s.oid
JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
JOIN pg_catalog.pg_roles owner ON owner.oid = p.proowner
LEFT JOIN LATERAL pg_catalog.aclexplode(COALESCE(p.proacl, pg_catalog.acldefault('f', p.proowner))) x ON true
LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = x.grantee
LEFT JOIN pg_catalog.pg_roles grantor ON grantor.oid = x.grantor
ORDER BY n.nspname, p.proname, identity_arguments, grantee_role;

-- C03: Effective EXECUTE privileges for the named roles, not API reachability.
WITH roles AS (
  SELECT oid, rolname FROM pg_catalog.pg_roles WHERE rolname IN
    ('anon', 'authenticated', 'service_role', 'authenticator', 'oauth_storage_owner',
     'postgres', 'OPTIONAL_BACKEND_ROLE_NAME')
), targets AS (
  SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname = 'public' AND c.relname IN ('users', 'sessions'))
     OR (n.nspname = 'oauth_private' AND c.relname IN ('oauth_attempts', 'oauth_handoffs'))
), dependent_objects(classid, objid) AS (
  SELECT 'pg_catalog.pg_policy'::regclass, p.oid FROM pg_catalog.pg_policy p WHERE p.polrelid IN (SELECT oid FROM targets)
  UNION SELECT 'pg_catalog.pg_attrdef'::regclass, d.oid FROM pg_catalog.pg_attrdef d WHERE d.adrelid IN (SELECT oid FROM targets)
  UNION SELECT 'pg_catalog.pg_constraint'::regclass, k.oid FROM pg_catalog.pg_constraint k WHERE k.conrelid IN (SELECT oid FROM targets)
  UNION SELECT 'pg_catalog.pg_class'::regclass, i.indexrelid FROM pg_catalog.pg_index i WHERE i.indrelid IN (SELECT oid FROM targets)
), scope AS (
  SELECT p.oid FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname IN ('public', 'oauth_private') AND (p.prosecdef OR pg_catalog.left(p.proname, 6) = 'oauth_')
  UNION SELECT d.refobjid FROM pg_catalog.pg_depend d JOIN dependent_objects o ON o.classid = d.classid AND o.objid = d.objid
    WHERE d.refclassid = 'pg_catalog.pg_proc'::regclass
  UNION SELECT tr.tgfoid FROM pg_catalog.pg_trigger tr WHERE tr.tgrelid IN (SELECT oid FROM targets) AND NOT tr.tgisinternal
)
SELECT r.rolname, n.nspname AS schema_name, p.proname,
       pg_catalog.pg_get_function_identity_arguments(p.oid) AS identity_arguments,
       pg_catalog.has_schema_privilege(r.oid, n.oid, 'USAGE') AS schema_usage,
       pg_catalog.has_function_privilege(r.oid, p.oid, 'EXECUTE') AS can_execute
FROM roles r CROSS JOIN scope s JOIN pg_catalog.pg_proc p ON p.oid = s.oid
JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
ORDER BY r.rolname, n.nspname, p.proname, identity_arguments;

-- D. MIGRATION COMPATIBILITY CHECKS

-- D01: Exact schema, role, relation/index/column name collisions. No object creation.
WITH expected(kind, schema_name, object_name) AS (
  VALUES ('schema', 'oauth_private', 'oauth_private'), ('role', NULL, 'oauth_storage_owner'),
    ('relation', 'oauth_private', 'oauth_attempts'), ('relation', 'oauth_private', 'oauth_handoffs'),
    ('relation', 'oauth_private', 'oauth_attempts_binding_idx'), ('relation', 'oauth_private', 'oauth_attempts_expiry_idx'),
    ('relation', 'oauth_private', 'oauth_handoffs_binding_idx'), ('relation', 'oauth_private', 'oauth_handoffs_expiry_idx'),
    ('column', 'public', 'github_subject')
)
SELECT e.kind, e.schema_name, e.object_name,
       CASE e.kind
         WHEN 'schema' THEN EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n WHERE n.nspname = e.object_name)
         WHEN 'role' THEN EXISTS (SELECT 1 FROM pg_catalog.pg_roles r WHERE r.rolname = e.object_name)
         WHEN 'relation' THEN EXISTS (
           SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = e.schema_name AND c.relname = e.object_name)
         WHEN 'column' THEN EXISTS (
           SELECT 1 FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
           JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relname = 'users' AND a.attname = e.object_name
             AND a.attnum > 0 AND NOT a.attisdropped)
       END AS name_already_exists
FROM expected e ORDER BY e.kind, e.schema_name, e.object_name;

-- D02: Expected constraint/policy names already present on their intended tables.
WITH expected(kind, schema_name, table_name, object_name) AS (
  VALUES ('constraint', 'public', 'users', 'users_github_subject_unique'),
    ('constraint', 'public', 'users', 'users_github_subject_account_check'),
    ('policy', 'public', 'users', 'oauth_identity_lookup'), ('policy', 'public', 'users', 'oauth_identity_create'),
    ('policy', 'oauth_private', 'oauth_attempts', 'oauth_attempts_owner'),
    ('policy', 'oauth_private', 'oauth_handoffs', 'oauth_handoffs_owner')
)
SELECT e.kind, e.schema_name, e.table_name, e.object_name, CASE e.kind
  WHEN 'constraint' THEN EXISTS (
    SELECT 1 FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid = k.conrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = e.schema_name AND c.relname = e.table_name AND k.conname = e.object_name)
  WHEN 'policy' THEN EXISTS (
    SELECT 1 FROM pg_catalog.pg_policy p JOIN pg_catalog.pg_class c ON c.oid = p.polrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = e.schema_name AND c.relname = e.table_name AND p.polname = e.object_name)
  END AS name_already_exists
FROM expected e ORDER BY e.kind, e.schema_name, e.table_name, e.object_name;

-- D03: All overloads of the six RPC names; any existing name needs reconciliation.
WITH expected(routine_name, expected_argument_types) AS (
  VALUES ('oauth_start', 'bytea, bytea'), ('oauth_consume_attempt', 'bytea, bytea'),
    ('oauth_finish_attempt', 'bytea, bytea, bytea, text, text'),
    ('oauth_redeem_handoff', 'bytea, bytea'), ('oauth_revoke_browser', 'bytea'), ('oauth_purge_expired', '')
)
SELECT e.routine_name, e.expected_argument_types, p.oid IS NOT NULL AS name_present,
       p.prokind AS routine_kind, pg_catalog.oidvectortypes(p.proargtypes) AS actual_argument_types,
       pg_catalog.pg_get_function_identity_arguments(p.oid) AS identity_arguments,
       owner.rolname AS owner_role,
       p.prokind = 'f' AND pg_catalog.oidvectortypes(p.proargtypes) = e.expected_argument_types AS matches_expected_signature
FROM expected e LEFT JOIN pg_catalog.pg_namespace n ON n.nspname = 'public'
LEFT JOIN pg_catalog.pg_proc p ON p.pronamespace = n.oid AND p.proname = e.routine_name
LEFT JOIN pg_catalog.pg_roles owner ON owner.oid = p.proowner
ORDER BY e.routine_name, actual_argument_types;

-- D04: Scoped explicit default ACLs: global entries plus public/private entries.
-- They concern the actual object CREATOR, not merely the eventual ALTER OWNER role.
WITH creators AS (
  SELECT oid FROM pg_catalog.pg_roles WHERE rolname IN
    ('postgres', 'oauth_storage_owner', 'OPTIONAL_BACKEND_ROLE_NAME', 'OPTIONAL_MIGRATION_ROLE_NAME')
  UNION SELECT c.relowner FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE (n.nspname = 'public' AND c.relname IN ('users', 'sessions'))
       OR n.nspname = 'oauth_private'
  UNION SELECT p.proowner FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname IN ('public', 'oauth_private') AND (p.prosecdef OR pg_catalog.left(p.proname, 6) = 'oauth_')
)
SELECT creator.rolname AS creator_role,
       CASE WHEN d.defaclnamespace = 0 THEN '<global>' ELSE n.nspname::text END AS default_scope,
       d.defaclobjtype AS object_type_code,
       CASE WHEN x.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname::text END AS grantee_role,
       grantor.rolname AS grantor_role, x.privilege_type, x.is_grantable
FROM pg_catalog.pg_default_acl d JOIN creators c ON c.oid = d.defaclrole
JOIN pg_catalog.pg_roles creator ON creator.oid = d.defaclrole
LEFT JOIN pg_catalog.pg_namespace n ON n.oid = d.defaclnamespace
LEFT JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) x ON true
LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = x.grantee
LEFT JOIN pg_catalog.pg_roles grantor ON grantor.oid = x.grantor
WHERE d.defaclnamespace = 0 OR n.nspname IN ('public', 'oauth_private')
ORDER BY creator.rolname, default_scope, d.defaclobjtype, grantee_role, x.privilege_type;

-- D05: Built-in fallback ACLs for named potential creators. NOT the effective
-- result when D04 overrides/additions exist; notably functions grant PUBLIC EXECUTE.
WITH creators AS (
  SELECT oid, rolname FROM pg_catalog.pg_roles
  WHERE rolname IN ('postgres', 'oauth_storage_owner', 'OPTIONAL_BACKEND_ROLE_NAME', 'OPTIONAL_MIGRATION_ROLE_NAME')
), kinds(object_kind, acl_kind) AS (
  VALUES ('table', 'r'::"char"), ('sequence', 's'::"char"), ('function', 'f'::"char"), ('schema', 'n'::"char")
)
SELECT creator.rolname AS creator_role, k.object_kind,
       CASE WHEN x.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname::text END AS grantee_role,
       x.privilege_type, x.is_grantable
FROM creators creator CROSS JOIN kinds k
CROSS JOIN LATERAL pg_catalog.aclexplode(pg_catalog.acldefault(k.acl_kind, creator.oid)) x
LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = x.grantee
ORDER BY creator.rolname, k.object_kind, grantee_role, x.privilege_type;

-- D06: UUID/default/domain/type prerequisites without evaluating any default.
SELECT n.nspname AS schema_name, c.relname AS relation_name, a.attname AS column_name,
       tn.nspname AS type_schema, ty.typname AS type_name, ty.typtype AS type_kind,
       ty.typnotnull AS type_not_null, ty.typdefaultbin IS NOT NULL AS has_type_default,
       CASE WHEN ty.typtype = 'd' THEN pg_catalog.format_type(ty.typbasetype, ty.typtypmod) END AS domain_base_type,
       pn.nspname AS default_function_schema, p.proname AS default_function_name,
       pg_catalog.pg_get_function_identity_arguments(p.oid) AS identity_arguments,
       ext.extname AS owning_extension, ext.extversion AS extension_version
FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_type ty ON ty.oid = a.atttypid
JOIN pg_catalog.pg_namespace tn ON tn.oid = ty.typnamespace
LEFT JOIN pg_catalog.pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
LEFT JOIN pg_catalog.pg_depend dep ON dep.classid = 'pg_catalog.pg_attrdef'::regclass
  AND dep.objid = ad.oid AND dep.refclassid = 'pg_catalog.pg_proc'::regclass
LEFT JOIN pg_catalog.pg_proc p ON p.oid = dep.refobjid
LEFT JOIN pg_catalog.pg_namespace pn ON pn.oid = p.pronamespace
LEFT JOIN pg_catalog.pg_depend ed ON ed.classid = 'pg_catalog.pg_proc'::regclass
  AND ed.objid = p.oid AND ed.refclassid = 'pg_catalog.pg_extension'::regclass AND ed.deptype = 'e'
LEFT JOIN pg_catalog.pg_extension ext ON ext.oid = ed.refobjid
WHERE n.nspname = 'public' AND c.relname IN ('users', 'sessions')
  AND a.attname IN ('id', 'user_id', 'email') AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum, pn.nspname, p.proname;

-- D07: Allowlisted role/database runtime defaults, never arbitrary configuration.
-- These are metadata defaults, NOT proof that a live PostgREST request uses them.
WITH roles AS (
  SELECT oid FROM pg_catalog.pg_roles WHERE rolname IN
    ('anon', 'authenticated', 'service_role', 'authenticator', 'oauth_storage_owner',
     'postgres', 'OPTIONAL_BACKEND_ROLE_NAME', 'OPTIONAL_MIGRATION_ROLE_NAME')
), selected_settings AS (
  SELECT cfg.setrole, cfg.setdatabase,
         pg_catalog.split_part(x.setting, '=', 1) AS setting_name,
         pg_catalog.substr(x.setting, pg_catalog.strpos(x.setting, '=') + 1) AS setting_value
  FROM pg_catalog.pg_db_role_setting cfg
  CROSS JOIN LATERAL pg_catalog.unnest(cfg.setconfig) AS x(setting)
  WHERE (cfg.setrole = 0 OR cfg.setrole IN (SELECT oid FROM roles))
    AND (cfg.setdatabase = 0 OR cfg.setdatabase = (
      SELECT oid FROM pg_catalog.pg_database WHERE datname = pg_catalog.current_database()))
    AND pg_catalog.split_part(x.setting, '=', 1) IN
      ('statement_timeout', 'lock_timeout', 'idle_in_transaction_session_timeout',
       'transaction_timeout', 'default_transaction_read_only', 'row_security')
)
SELECT CASE WHEN s.setrole = 0 THEN '<all roles>' ELSE r.rolname::text END AS role_scope,
       CASE WHEN s.setdatabase = 0 THEN '<all databases>' ELSE '<current database>' END AS database_scope,
       s.setting_name,
       CASE WHEN s.setting_value ~ '^[0-9]+(us|ms|s|min|h|d)?$'
                   OR s.setting_value IN ('on', 'off', 'true', 'false')
              THEN s.setting_value ELSE '[WITHHELD: unexpected format]' END AS setting_value
FROM selected_settings s LEFT JOIN pg_catalog.pg_roles r ON r.oid = s.setrole
ORDER BY role_scope, database_scope, s.setting_name;
