# NON-EXECUTABLE PROPOSAL — Batch 4B-2A

This Markdown document is not a deployable migration. Do not extract/run its SQL
until the gates in [README](../README.md) are approved and verified in isolation.
The corrected transaction was tested only in a disposable PostgreSQL 16.16
fixture in Batch 4B-2B; it is not a deployable migration or Supabase validation.
See [local validation results](../POSTGRES_VALIDATION.md).
It assumes `public.users` matches the documented schema, standard Supabase roles,
and a privileged migration operator able to create/own roles, policies and RPCs.
Those assumptions are NOT established for the deployed database.

The proposal adds storage only. No email backfill, UUID replacement, legacy
binding, session rewrite, schema drop, or authentication cutover is included.
Raw state, browser secrets, tickets, OAuth codes and access tokens are never stored.

```sql
BEGIN;
SET LOCAL search_path = pg_catalog;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

-- Abort on existing names: no IF NOT EXISTS / OR REPLACE masking schema drift.
-- Provisioning requires an approved privileged operator, not the runtime key.
CREATE ROLE oauth_storage_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOBYPASSRLS;
CREATE SCHEMA oauth_private AUTHORIZATION oauth_storage_owner;
REVOKE ALL ON SCHEMA oauth_private FROM PUBLIC, anon, authenticated, service_role;

ALTER TABLE public.users ADD COLUMN github_subject text;
ALTER TABLE public.users ADD CONSTRAINT users_github_subject_unique UNIQUE (github_subject);
ALTER TABLE public.users ADD CONSTRAINT users_github_subject_account_check CHECK (
  github_subject IS NULL OR (
    github_subject ~ '^[1-9][0-9]{0,19}$'
    AND provider IS NOT DISTINCT FROM 'github' AND password_hash IS NULL
  )
);

CREATE TABLE oauth_private.oauth_attempts (
  state_hash bytea PRIMARY KEY CHECK (octet_length(state_hash) = 32),
  browser_binding_hash bytea NOT NULL CHECK (octet_length(browser_binding_hash) = 32),
  provider text NOT NULL CHECK (provider = 'github'),
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  completed_at timestamptz,
  revoked_at timestamptz,
  CHECK (expires_at > created_at AND expires_at <= created_at + interval '5 minutes'),
  CHECK (consumed_at IS NULL OR (consumed_at >= created_at AND consumed_at < expires_at)),
  CHECK (completed_at IS NULL OR (consumed_at IS NOT NULL
    AND completed_at >= consumed_at AND completed_at < expires_at)),
  CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
CREATE TABLE oauth_private.oauth_handoffs (
  ticket_hash bytea PRIMARY KEY CHECK (octet_length(ticket_hash) = 32),
  attempt_state_hash bytea NOT NULL UNIQUE
    REFERENCES oauth_private.oauth_attempts(state_hash) ON DELETE CASCADE,
  browser_binding_hash bytea NOT NULL CHECK (octet_length(browser_binding_hash) = 32),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE
    CHECK (user_id <> '00000000-0000-0000-0000-000000000000'::uuid),
  github_subject text NOT NULL CHECK (github_subject ~ '^[1-9][0-9]{0,19}$'),
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  revoked_at timestamptz,
  CHECK (expires_at > created_at AND expires_at <= created_at + interval '60 seconds'),
  CHECK (consumed_at IS NULL OR (consumed_at >= created_at AND consumed_at < expires_at)),
  CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
ALTER TABLE oauth_private.oauth_attempts OWNER TO oauth_storage_owner;
ALTER TABLE oauth_private.oauth_handoffs OWNER TO oauth_storage_owner;
CREATE INDEX oauth_attempts_binding_idx ON oauth_private.oauth_attempts(browser_binding_hash);
CREATE INDEX oauth_attempts_expiry_idx ON oauth_private.oauth_attempts(expires_at);
CREATE INDEX oauth_handoffs_binding_idx ON oauth_private.oauth_handoffs(browser_binding_hash);
CREATE INDEX oauth_handoffs_expiry_idx ON oauth_private.oauth_handoffs(expires_at);
REVOKE ALL ON ALL TABLES IN SCHEMA oauth_private FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE oauth_private.oauth_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_private.oauth_attempts FORCE ROW LEVEL SECURITY;
ALTER TABLE oauth_private.oauth_handoffs ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_private.oauth_handoffs FORCE ROW LEVEL SECURITY;
CREATE POLICY oauth_attempts_owner ON oauth_private.oauth_attempts
  FOR ALL TO oauth_storage_owner USING (true) WITH CHECK (true);
CREATE POLICY oauth_handoffs_owner ON oauth_private.oauth_handoffs
  FOR ALL TO oauth_storage_owner USING (true) WITH CHECK (true);

-- Narrow identity privileges for the NOLOGIN function owner, not browser roles.
-- Existing users RLS must already be enabled; restrictive policies may still deny.
GRANT USAGE ON SCHEMA public TO oauth_storage_owner;
GRANT SELECT (id, email, provider, password_hash, github_subject),
  INSERT (email, password_hash, provider, github_subject)
  ON public.users TO oauth_storage_owner;
CREATE POLICY oauth_identity_lookup ON public.users FOR SELECT
  TO oauth_storage_owner USING (true);
CREATE POLICY oauth_identity_create ON public.users FOR INSERT
  TO oauth_storage_owner WITH CHECK (
    provider IS NOT DISTINCT FROM 'github' AND password_hash IS NULL
    AND github_subject IS NOT NULL AND github_subject ~ '^[1-9][0-9]{0,19}$'
  );

-- Each hash is computed by the trusted backend, with purpose separation.
-- A browser must never call these RPCs or provide identity/verification claims.
CREATE FUNCTION public.oauth_start(p_state_hash bytea, p_binding_hash bytea)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE t timestamptz;
BEGIN
  IF p_state_hash IS NULL OR octet_length(p_state_hash) <> 32
    OR p_binding_hash IS NULL OR octet_length(p_binding_hash) <> 32 THEN RETURN false; END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    pg_catalog.encode(p_binding_hash, 'hex'), 0));
  t := pg_catalog.clock_timestamp();
  -- Latest deliberate start wins; revoke consumed-but-unfinished attempts too.
  UPDATE oauth_private.oauth_attempts SET revoked_at = t
    WHERE browser_binding_hash = p_binding_hash AND revoked_at IS NULL;
  UPDATE oauth_private.oauth_handoffs SET revoked_at = t
    WHERE browser_binding_hash = p_binding_hash AND revoked_at IS NULL;
  INSERT INTO oauth_private.oauth_attempts
    (state_hash, browser_binding_hash, provider, created_at, expires_at)
    VALUES (p_state_hash, p_binding_hash, 'github', t, t + interval '5 minutes');
  RETURN true;
END $$;

CREATE FUNCTION public.oauth_consume_attempt(p_state_hash bytea, p_binding_hash bytea)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE t timestamptz; claimed bytea;
BEGIN
  IF p_state_hash IS NULL OR octet_length(p_state_hash) <> 32
    OR p_binding_hash IS NULL OR octet_length(p_binding_hash) <> 32 THEN RETURN false; END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    pg_catalog.encode(p_binding_hash, 'hex'), 0));
  PERFORM 1 FROM oauth_private.oauth_attempts
    WHERE state_hash = p_state_hash AND browser_binding_hash = p_binding_hash FOR UPDATE;
  t := pg_catalog.clock_timestamp();
  UPDATE oauth_private.oauth_attempts SET consumed_at = t
    WHERE state_hash = p_state_hash AND browser_binding_hash = p_binding_hash
      AND provider = 'github' AND consumed_at IS NULL AND revoked_at IS NULL
      AND expires_at > t
    RETURNING state_hash INTO claimed;
  RETURN claimed IS NOT NULL;
END $$;

-- After a separate, committed consume RPC and successful provider verification.
-- No caller-supplied user UUID and no lookup/link by email.
CREATE FUNCTION public.oauth_finish_attempt(p_state_hash bytea, p_binding_hash bytea,
  p_ticket_hash bytea, p_subject text, p_verified_email text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE t timestamptz; deadline timestamptz; local_id uuid;
BEGIN
  IF p_state_hash IS NULL OR octet_length(p_state_hash) <> 32
    OR p_binding_hash IS NULL OR octet_length(p_binding_hash) <> 32
    OR p_ticket_hash IS NULL OR octet_length(p_ticket_hash) <> 32
    OR p_subject IS NULL OR p_subject !~ '^[1-9][0-9]{0,19}$'
    OR p_verified_email IS NULL OR btrim(p_verified_email) = '' THEN RETURN false; END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    pg_catalog.encode(p_binding_hash, 'hex'), 0));
  t := pg_catalog.clock_timestamp();
  SELECT expires_at INTO deadline FROM oauth_private.oauth_attempts
    WHERE state_hash = p_state_hash AND browser_binding_hash = p_binding_hash
      AND provider = 'github' AND consumed_at IS NOT NULL AND completed_at IS NULL
      AND revoked_at IS NULL AND expires_at > t FOR UPDATE;
  IF deadline IS NULL THEN RETURN false; END IF;
  SELECT u.id INTO local_id FROM public.users AS u
    WHERE u.github_subject = p_subject AND u.provider = 'github'
      AND u.password_hash IS NULL
      AND u.id <> '00000000-0000-0000-0000-000000000000'::uuid;
  IF local_id IS NULL THEN
    BEGIN
      INSERT INTO public.users (email, password_hash, provider, github_subject)
        VALUES (lower(p_verified_email), NULL, 'github', p_subject)
        RETURNING id INTO local_id;
    EXCEPTION WHEN unique_violation THEN
      -- Concurrent same-subject creation can converge on the winning UUID.
      -- An email collision without that subject must never recover an account.
      SELECT u.id INTO local_id FROM public.users AS u
        WHERE u.github_subject = p_subject AND u.provider = 'github'
          AND u.password_hash IS NULL
          AND u.id <> '00000000-0000-0000-0000-000000000000'::uuid;
    END;
  END IF;
  IF local_id IS NULL THEN RETURN false; END IF;
  -- A malformed UUID default must not commit a partial newly created account.
  IF local_id = '00000000-0000-0000-0000-000000000000'::uuid THEN
    RAISE EXCEPTION 'Invalid OAuth identity' USING ERRCODE = '22023';
  END IF;
  -- Recheck time after possible row/uniqueness waits. An expired attempt is denied.
  t := pg_catalog.clock_timestamp();
  IF deadline <= t THEN RAISE EXCEPTION 'OAuth attempt expired'; END IF;
  INSERT INTO oauth_private.oauth_handoffs
    (ticket_hash, attempt_state_hash, browser_binding_hash, user_id,
     github_subject, created_at, expires_at)
    VALUES (p_ticket_hash, p_state_hash, p_binding_hash, local_id,
      p_subject, t, least(t + interval '60 seconds', deadline));
  UPDATE oauth_private.oauth_attempts SET completed_at = t WHERE state_hash = p_state_hash;
  RETURN true;
END $$;

CREATE FUNCTION public.oauth_redeem_handoff(p_ticket_hash bytea, p_binding_hash bytea)
RETURNS TABLE(user_id uuid, github_subject text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE t timestamptz;
BEGIN
  IF p_ticket_hash IS NULL OR octet_length(p_ticket_hash) <> 32
    OR p_binding_hash IS NULL OR octet_length(p_binding_hash) <> 32 THEN RETURN; END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    pg_catalog.encode(p_binding_hash, 'hex'), 0));
  PERFORM 1 FROM oauth_private.oauth_handoffs
    WHERE ticket_hash = p_ticket_hash AND browser_binding_hash = p_binding_hash FOR UPDATE;
  t := pg_catalog.clock_timestamp();
  RETURN QUERY UPDATE oauth_private.oauth_handoffs AS h SET consumed_at = t
    FROM public.users AS u, oauth_private.oauth_attempts AS a
    WHERE h.ticket_hash = p_ticket_hash AND h.browser_binding_hash = p_binding_hash
      AND h.consumed_at IS NULL AND h.revoked_at IS NULL AND h.expires_at > t
      AND a.state_hash = h.attempt_state_hash AND a.browser_binding_hash = p_binding_hash
      AND a.provider = 'github' AND a.consumed_at IS NOT NULL AND a.completed_at IS NOT NULL
      AND a.revoked_at IS NULL AND a.expires_at > t
      AND u.id = h.user_id AND u.github_subject = h.github_subject
      AND u.provider = 'github' AND u.password_hash IS NULL
      AND u.id <> '00000000-0000-0000-0000-000000000000'::uuid
    RETURNING h.user_id, h.github_subject;
END $$;

CREATE FUNCTION public.oauth_revoke_browser(p_binding_hash bytea)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE t timestamptz;
BEGIN
  IF p_binding_hash IS NULL OR octet_length(p_binding_hash) <> 32 THEN RETURN; END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    pg_catalog.encode(p_binding_hash, 'hex'), 0));
  t := pg_catalog.clock_timestamp();
  UPDATE oauth_private.oauth_attempts SET revoked_at = t
    WHERE browser_binding_hash = p_binding_hash AND revoked_at IS NULL;
  UPDATE oauth_private.oauth_handoffs SET revoked_at = t
    WHERE browser_binding_hash = p_binding_hash AND revoked_at IS NULL;
END $$;

-- Operator-scheduled, bounded retention; never required for authorization expiry.
CREATE FUNCTION public.oauth_purge_expired()
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE cutoff timestamptz := pg_catalog.clock_timestamp() - interval '24 hours';
BEGIN
  DELETE FROM oauth_private.oauth_handoffs WHERE expires_at <= cutoff;
  DELETE FROM oauth_private.oauth_attempts WHERE expires_at <= cutoff;
END $$;

-- Operator must be permitted to change function ownership. All ownership and
-- ACL changes are in this same transaction, before anything is callable.
GRANT CREATE ON SCHEMA public TO oauth_storage_owner;
ALTER FUNCTION public.oauth_start(bytea, bytea) OWNER TO oauth_storage_owner;
ALTER FUNCTION public.oauth_consume_attempt(bytea, bytea) OWNER TO oauth_storage_owner;
ALTER FUNCTION public.oauth_finish_attempt(bytea, bytea, bytea, text, text) OWNER TO oauth_storage_owner;
ALTER FUNCTION public.oauth_redeem_handoff(bytea, bytea) OWNER TO oauth_storage_owner;
ALTER FUNCTION public.oauth_revoke_browser(bytea) OWNER TO oauth_storage_owner;
ALTER FUNCTION public.oauth_purge_expired() OWNER TO oauth_storage_owner;
REVOKE CREATE ON SCHEMA public FROM oauth_storage_owner;
REVOKE ALL ON FUNCTION public.oauth_start(bytea, bytea),
  public.oauth_consume_attempt(bytea, bytea),
  public.oauth_finish_attempt(bytea, bytea, bytea, text, text),
  public.oauth_redeem_handoff(bytea, bytea), public.oauth_revoke_browser(bytea),
  public.oauth_purge_expired() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.oauth_start(bytea, bytea),
  public.oauth_consume_attempt(bytea, bytea),
  public.oauth_finish_attempt(bytea, bytea, bytea, text, text),
  public.oauth_redeem_handoff(bytea, bytea), public.oauth_revoke_browser(bytea),
  public.oauth_purge_expired() TO service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE oauth_storage_owner IN SCHEMA oauth_private
  REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated, service_role;
-- Functions added later still need explicit owner/ACL review. This does not
-- change default function privileges globally in the existing public schema.
COMMIT;
```

Public wrapper functions are intentionally exposed to PostgREST discovery but
executable only by the trusted backend role. The private schema must NOT be in
the API exposed-schema list. Subject verification and email verification are
backend obligations: a privileged caller can forge either. This is a credential
trust boundary, not proof that GitHub assertions were verified by PostgreSQL.

All private mutations use a transaction-scoped lock on the binding hash before
reading rows, except expiry-only purge. Hash-lock collisions only serialize
unrelated browsers. Lock/hash behavior, function overloads, ACL inheritance, RLS,
READ COMMITTED races and PostgREST transaction commit behavior need real tests.
Do not hold a database transaction over HTTP code exchange. Consume and commit
first; later failure must not reset consumed_at or reuse the authorization code.
