"""Proposed storage contracts: static SQL and a separate test-only reference model.

These passing tests do NOT repair or prove the existing production OAuth flow.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import re
from uuid import UUID

from offline.oauth_storage_model import StorageFailure, StorageModel, hashed
from offline.support import OfflineCase


class ProposalStructureTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.path = self.sandbox.repository / "migrations/proposals/4b2a_oauth_storage.sql.md"
        self.document = self.path.read_text()
        blocks = re.findall(r"```sql\n(.*?)\n```", self.document, re.S)
        self.assertEqual(len(blocks), 1)
        self.sql = blocks[0]
        self.code = re.sub(r"--[^\n]*", "", self.sql)
        self.functions = dict(re.findall(
            r"CREATE FUNCTION public\.(oauth_\w+)\(.*?AS \$\$(.*?)END \$\$;",
            self.sql, re.S))

    def test_artifact_is_explicitly_non_executable(self):
        self.assertTrue(self.path.name.endswith(".sql.md"))
        self.assertIn("NON-EXECUTABLE PROPOSAL", self.document)
        self.assertIn("not a deployable migration", self.document)
        self.assertEqual(len(self.functions), 6)

    def test_subject_is_nullable_unique_and_github_only(self):
        self.assertIn("ADD COLUMN github_subject text;", self.sql)
        self.assertIn("UNIQUE (github_subject)", self.sql)
        self.assertIn("github_subject IS NULL OR", self.sql)
        self.assertIn("provider IS NOT DISTINCT FROM 'github' AND password_hash IS NULL", self.sql)
        self.assertNotRegex(self.code, r"github_subject\s+text\s+NOT NULL.*?ALTER TABLE public.users")

    def test_existing_ids_sessions_and_legacy_rows_are_not_rewritten(self):
        self.assertNotRegex(self.code, r"(?i)(UPDATE|DELETE FROM)\s+public\.users")
        self.assertNotRegex(self.code, r"(?i)(UPDATE|DELETE FROM|ALTER TABLE)\s+public\.sessions")
        self.assertNotRegex(self.code, r"(?i)\b(DROP|TRUNCATE)\b|ALTER COLUMN id")
        self.assertIn("REFERENCES public.users(id) ON DELETE CASCADE", self.sql)

    def test_storage_hashes_and_explicit_lifecycle_constraints(self):
        for name in ("state_hash", "ticket_hash", "browser_binding_hash"):
            self.assertRegex(self.sql, rf"{name} bytea")
            self.assertIn(f"octet_length({name}) = 32", self.sql)
        self.assertIn("attempt_state_hash bytea NOT NULL UNIQUE", self.sql)
        self.assertIn("interval '5 minutes'", self.sql)
        self.assertIn("interval '60 seconds'", self.sql)
        for field in ("raw_state", "raw_ticket", "access_token", "authorization_code"):
            self.assertNotRegex(self.code, rf"\b{field}\s+(text|bytea)")

    def test_private_tables_force_rls_without_browser_policies(self):
        for name in ("oauth_attempts", "oauth_handoffs"):
            self.assertIn(f"ALTER TABLE oauth_private.{name} FORCE ROW LEVEL SECURITY;", self.sql)
        policies = re.findall(r"CREATE POLICY.*?;", self.code, re.S)
        self.assertEqual(len(policies), 4)
        for policy in policies:
            self.assertIn("TO oauth_storage_owner", policy)
            self.assertNotRegex(policy, r"\b(anon|authenticated|PUBLIC)\b")
        self.assertIn("REVOKE ALL ON ALL TABLES IN SCHEMA oauth_private FROM PUBLIC, anon, authenticated, service_role;", self.sql)

    def test_function_owner_search_path_and_explicit_rpc_acl(self):
        self.assertEqual(self.sql.count("SECURITY DEFINER SET search_path = pg_catalog"), 6)
        self.assertEqual(self.sql.count("OWNER TO oauth_storage_owner;"), 8)
        self.assertIn("NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE", self.sql)
        self.assertIn("NOINHERIT NOBYPASSRLS", self.sql)
        self.assertIn("REVOKE ALL ON FUNCTION", self.sql)
        self.assertIn("FROM PUBLIC, anon, authenticated, service_role;", self.sql)
        grant = re.search(r"GRANT EXECUTE ON FUNCTION(.*?)TO service_role;", self.sql, re.S)[1]
        for function in self.functions:
            self.assertIn(f"public.{function}(", grant)
        self.assertNotRegex(self.sql, r"GRANT EXECUTE.*?TO (anon|authenticated|PUBLIC);")
        self.assertIn("REVOKE CREATE ON SCHEMA public FROM oauth_storage_owner;", self.sql)

    def test_attempt_claim_predicates_and_lock_precede_clock(self):
        body = self.functions["oauth_consume_attempt"]
        for predicate in ("state_hash = p_state_hash", "browser_binding_hash = p_binding_hash",
                          "provider = 'github'", "consumed_at IS NULL", "revoked_at IS NULL",
                          "expires_at > t", "RETURNING state_hash INTO claimed"):
            self.assertIn(predicate, body)
        self.assertLess(body.index("FOR UPDATE"), body.index("t := pg_catalog.clock_timestamp()"))

    def test_completion_resolves_only_subject_and_handles_unique_races(self):
        body = self.functions["oauth_finish_attempt"]
        self.assertIn("WHERE u.github_subject = p_subject", body)
        self.assertIn("EXCEPTION WHEN unique_violation", body)
        self.assertNotRegex(body, r"(?i)WHERE\s+(u\.)?email\s*=")
        for part in ("consumed_at IS NOT NULL", "completed_at IS NULL", "revoked_at IS NULL",
                     "IF deadline <= t THEN RAISE EXCEPTION", "SET completed_at = t"):
            self.assertIn(part, body)
        self.assertNotRegex(body, r"(?i)UPDATE\s+public\.users|ON CONFLICT.*?DO UPDATE")

    def test_nil_uuid_failure_raises_to_roll_back_partial_account(self):
        body = self.functions["oauth_finish_attempt"]
        nil_branch = re.search(
            r"IF local_id = '00000000-0000-0000-0000-000000000000'::uuid THEN(.*?)END IF;",
            body, re.S)[1]
        self.assertIn("RAISE EXCEPTION", nil_branch)
        self.assertIn("ERRCODE = '22023'", nil_branch)
        self.assertNotIn("RETURN false", nil_branch)

    def test_redemption_has_no_uuid_argument_and_rechecks_binding(self):
        signature = re.search(r"CREATE FUNCTION public.oauth_redeem_handoff\((.*?)\)", self.sql)[1]
        self.assertEqual(signature, "p_ticket_hash bytea, p_binding_hash bytea")
        body = self.functions["oauth_redeem_handoff"]
        for part in ("RETURN QUERY UPDATE", "h.ticket_hash = p_ticket_hash",
                     "h.browser_binding_hash = p_binding_hash", "h.consumed_at IS NULL",
                     "h.revoked_at IS NULL", "h.expires_at > t", "a.revoked_at IS NULL",
                     "u.id = h.user_id AND u.github_subject = h.github_subject",
                     "RETURNING h.user_id, h.github_subject"):
            self.assertIn(part, body)
        self.assertLess(body.index("FOR UPDATE"), body.index("t := pg_catalog.clock_timestamp()"))

    def test_start_and_logout_revoke_inflight_attempts_and_handoffs(self):
        for name in ("oauth_start", "oauth_revoke_browser"):
            body = self.functions[name]
            self.assertIn("UPDATE oauth_private.oauth_attempts SET revoked_at = t", body)
            self.assertIn("UPDATE oauth_private.oauth_handoffs SET revoked_at = t", body)
            self.assertNotIn("consumed_at IS NULL", body)
        for name, body in self.functions.items():
            if name != "oauth_purge_expired":
                self.assertIn("pg_catalog.pg_advisory_xact_lock", body)

    def test_purge_only_deletes_expired_transient_records(self):
        body = self.functions["oauth_purge_expired"]
        self.assertIn("interval '24 hours'", body)
        self.assertEqual(body.count("WHERE expires_at <= cutoff"), 2)
        self.assertNotIn("public.users", body)
        self.assertNotIn("public.sessions", body)

    def test_transaction_and_lexical_delimiters_are_balanced_not_a_parser(self):
        self.assertTrue(self.code.strip().startswith("BEGIN;"))
        self.assertTrue(self.code.strip().endswith("COMMIT;"))
        self.assertEqual(self.code.count("$$"), 12)
        unquoted = re.sub(r"'(?:''|[^'])*'", "''", self.code)
        self.assertEqual(unquoted.count("("), unquoted.count(")"))
        self.assertNotIn("EXECUTE ", self.functions["oauth_finish_attempt"])


class ProposedStorageModelTests(OfflineCase):
    """Behavior of the design reference ONLY; SQL enforcement remains untested."""

    def setUp(self):
        super().setUp()
        self.store = StorageModel()
        self.state = hashed("state", "synthetic-state")
        self.binding = hashed("binding", "synthetic-browser")
        self.other = hashed("binding", "synthetic-other-browser")
        self.ticket = hashed("ticket", "synthetic-ticket")

    def pending(self):
        self.assertTrue(self.store.start(self.state, self.binding))

    def finished(self, subject="700", email="bound@example.invalid"):
        self.pending()
        self.assertTrue(self.store.consume(self.state, self.binding))
        self.assertTrue(self.store.finish(self.state, self.binding, self.ticket, subject, email))

    def test_anonymous_and_user_roles_cannot_use_any_operation(self):
        for role in (None, "anon", "authenticated", "PUBLIC"):
            for call in (lambda: self.store.start(self.state, self.binding, role),
                         lambda: self.store.consume(self.state, self.binding, role),
                         lambda: self.store.finish(self.state, self.binding, self.ticket, "700", "x@example.invalid", role),
                         lambda: self.store.redeem(self.ticket, self.binding, role),
                         lambda: self.store.revoke(self.binding, role),
                         lambda: self.store.purge(role)):
                with self.subTest(role=role), self.assertRaises(PermissionError):
                    call()
        self.assertFalse(self.store.attempts)

    def test_unknown_or_malformed_hashes_fail_closed(self):
        self.assertFalse(self.store.consume(self.state, self.binding))
        self.assertIsNone(self.store.redeem(self.ticket, self.binding))
        for value in (None, b"", b"x" * 31, str(UUID(int=1))):
            self.assertFalse(self.store.start(value, self.binding))
            self.assertIsNone(self.store.redeem(value, self.binding))
        self.pending()
        self.store.consume(self.state, self.binding)
        for subject in (None, "", "0", "0700", "-1", "700\n", "1" * 21, 700):
            self.assertFalse(self.store.finish(
                self.state, self.binding, self.ticket, subject, "new@example.invalid"))
        self.assertFalse(self.store.handoffs)

    def test_wrong_browser_does_not_consume_owner_attempt(self):
        self.pending()
        self.assertFalse(self.store.consume(self.state, self.other))
        self.assertTrue(self.store.consume(self.state, self.binding))

    def test_attempt_expires_at_equality_without_cleanup(self):
        self.pending()
        self.store.now += 300
        self.assertFalse(self.store.consume(self.state, self.binding))
        self.assertIn(self.state, self.store.attempts)

    def test_attempt_consume_once_under_model_threads(self):
        self.pending()
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: self.store.consume(self.state, self.binding), range(2)))
        self.assertEqual(sorted(results), [False, True])

    def test_completion_requires_consumed_unexpired_attempt(self):
        self.pending()
        self.assertFalse(self.store.finish(self.state, self.binding, self.ticket, "700", "b@example.invalid"))
        self.assertTrue(self.store.consume(self.state, self.binding))
        self.store.now += 300
        self.assertFalse(self.store.finish(self.state, self.binding, self.ticket, "700", "b@example.invalid"))

    def test_handoff_expires_and_cannot_outlive_attempt(self):
        self.pending()
        self.assertTrue(self.store.consume(self.state, self.binding))
        self.store.now += 280
        self.assertTrue(self.store.finish(self.state, self.binding, self.ticket, "700", "b@example.invalid"))
        self.assertEqual(self.store.handoffs[self.ticket]["expires"], 1300)
        self.store.now += 20
        self.assertIsNone(self.store.redeem(self.ticket, self.binding))
        # Ordinary ticket expiry is independently 60 seconds, even when the
        # attempt has much longer left and no cleanup has run.
        self.store = StorageModel()
        self.finished()
        self.store.now += 60
        self.assertIsNone(self.store.redeem(self.ticket, self.binding))
        self.assertIn(self.ticket, self.store.handoffs)

    def test_handoff_wrong_browser_does_not_burn_ticket(self):
        self.finished()
        self.assertIsNone(self.store.redeem(self.ticket, self.other))
        self.assertEqual(self.store.redeem(self.ticket, self.binding), (str(UUID(int=3)), "700"))
        self.assertIsNone(self.store.redeem(self.ticket, self.binding))

    def test_handoff_redemption_once_under_model_threads(self):
        self.finished()
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: self.store.redeem(self.ticket, self.binding), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_redeemed_attempt_cannot_issue_another_handoff(self):
        self.finished()
        self.store.redeem(self.ticket, self.binding)
        self.assertFalse(self.store.finish(self.state, self.binding, hashed("ticket", "new"), "700", "b@example.invalid"))

    def test_logout_blocks_finish_and_pending_redemption(self):
        self.pending()
        self.store.consume(self.state, self.binding)
        self.store.revoke(self.binding)
        self.assertFalse(self.store.finish(self.state, self.binding, self.ticket, "700", "b@example.invalid"))
        fresh = StorageModel()
        fresh.start(self.state, self.binding)
        fresh.consume(self.state, self.binding)
        fresh.finish(self.state, self.binding, self.ticket, "700", "b@example.invalid")
        fresh.revoke(self.binding)
        self.assertIsNone(fresh.redeem(self.ticket, self.binding))

    def test_latest_start_revokes_existing_handoff(self):
        self.finished()
        self.store.start(hashed("state", "new"), self.binding)
        self.assertIsNone(self.store.redeem(self.ticket, self.binding))

    def test_legacy_and_password_email_collisions_never_link(self):
        before = deepcopy(self.store.users)
        for index, email in enumerate(("legacy@example.invalid", "password@example.invalid", "bound@example.invalid")):
            state = hashed("state", str(index)); ticket = hashed("ticket", str(index))
            self.store.start(state, self.binding); self.store.consume(state, self.binding)
            self.assertFalse(self.store.finish(state, self.binding, ticket, "999", email))
        self.assertEqual(self.store.users, before)
        self.assertFalse(self.store.handoffs)

    def test_subject_not_email_determines_existing_uuid(self):
        before = deepcopy(self.store.users)
        self.finished(email="password@example.invalid")
        self.assertEqual(self.store.redeem(self.ticket, self.binding), (str(UUID(int=3)), "700"))
        self.assertEqual(self.store.users, before)

    def test_same_subject_concurrent_creation_preserves_one_new_uuid(self):
        inputs = []
        for index in range(2):
            state = hashed("state", str(index))
            binding = hashed("binding", str(index))
            ticket = hashed("ticket", str(index))
            self.store.start(state, binding)
            self.store.consume(state, binding)
            inputs.append((state, binding, ticket))
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(
                lambda args: self.store.finish(*args, "999", "new@example.invalid"), inputs))
        self.assertEqual(results, [True, True])
        self.assertEqual(len([u for u in self.store.users if u["github_subject"] == "999"]), 1)
        self.assertEqual(len({row["user_id"] for row in self.store.handoffs.values()}), 1)

    def test_different_subjects_same_email_create_one_account(self):
        inputs = []
        for index in range(2):
            state = hashed("state", str(index))
            binding = hashed("binding", str(index))
            ticket = hashed("ticket", str(index))
            self.store.start(state, binding)
            self.store.consume(state, binding)
            inputs.append((state, binding, ticket, str(900 + index)))
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(
                lambda args: self.store.finish(*args, "new@example.invalid"), inputs))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(len(self.store.users), 4)

    def test_storage_failure_leaves_consumed_attempt_closed(self):
        self.pending()
        self.store.consume(self.state, self.binding)
        self.store.available = False
        for call in (lambda: self.store.finish(
                self.state, self.binding, self.ticket, "700", "b@example.invalid"),
                lambda: self.store.redeem(self.ticket, self.binding)):
            with self.assertRaises(StorageFailure):
                call()
        self.store.available = True
        self.assertFalse(self.store.consume(self.state, self.binding))
        self.assertFalse(self.store.handoffs)

    def test_current_binding_and_non_nil_uuid_are_rechecked(self):
        self.finished()
        for field, value in (("github_subject", "701"), ("provider", "email"),
                             ("password_hash", "synthetic-hash"), ("id", str(UUID(int=0)))):
            user = self.store.users[2]
            old = user[field]
            user[field] = value
            self.assertIsNone(self.store.redeem(self.ticket, self.binding))
            user[field] = old
        self.assertIsNotNone(self.store.redeem(self.ticket, self.binding))

    def test_no_browser_uuid_parameter_can_establish_identity(self):
        self.finished()
        with self.assertRaises(TypeError):
            self.store.redeem(self.ticket, self.binding, user_id=str(UUID(int=1)))
        self.assertIsNone(self.store.redeem(str(UUID(int=3)), self.binding))

    def test_cleanup_preserves_all_users_and_uuid_relationships(self):
        self.finished()
        before = deepcopy(self.store.users)
        self.store.now += 90000
        self.store.purge()
        self.assertFalse(self.store.attempts)
        self.assertFalse(self.store.handoffs)
        self.assertEqual(self.store.users, before)
