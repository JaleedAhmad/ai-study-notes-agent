"""Authorization contracts against real queries; no simulated RLS or xfails.

Call-site adapters pass the server-held identity through the required owner
keyword. The query-evaluating store never enforces an actor implicitly.
"""

from copy import deepcopy
import runpy
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from offline.fake_database import (
    DatabaseFailure, MemoryDatabase, ORPHAN, SESSION_A, SESSION_B, USER_A, USER_B,
)
from offline.support import OfflineCase


class DatabaseContracts(OfflineCase):
    def setUp(self):
        super().setUp()
        self.database = self.app("src.database.database")
        self.store = MemoryDatabase()
        self.stack.enter_context(patch.object(self.database, "get_supabase", return_value=self.store))
        sys.modules["streamlit"].session_state = SimpleNamespace(user_id=USER_A)

    def read_session(self, session_id):
        return self.database.get_session(
            session_id, user_id=sys.modules["streamlit"].session_state.user_id)

    def append_message(self, session_id, role, content):
        return self.database.save_chat_message(
            session_id, role, content, user_id=sys.modules["streamlit"].session_state.user_id)

    def remove_session(self, session_id):
        return self.database.delete_session(
            session_id, user_id=sys.modules["streamlit"].session_state.user_id)

    def deny(self, operation, *args):
        """Only PermissionError counts as explicit denial; other errors surface."""
        try:
            return operation(*args)
        except PermissionError:
            return None

    def test_owner_can_list_and_read_own_notes(self):
        self.assertEqual([row["id"] for row in self.database.get_all_sessions(USER_A)], [SESSION_A])
        sys.modules["streamlit"].session_state.user_id = USER_B
        self.assertEqual([row["id"] for row in self.database.get_all_sessions(USER_B)], [SESSION_B])
        sys.modules["streamlit"].session_state.user_id = USER_A
        self.assertEqual(self.read_session(SESSION_A)["notes"], "synthetic notes A")

    def test_owner_can_save_notes_with_its_identity(self):
        record_id = self.database.create_session(USER_A, "synthetic.txt", "source", "notes")
        self.assertEqual(self.store.row("sessions", record_id)["user_id"], USER_A)

    def test_owner_can_append_chat(self):
        self.append_message(SESSION_A, "user", "synthetic question")
        self.assertEqual(self.store.row("sessions", SESSION_A)["chat_history"],
                         [{"role": "user", "content": "synthetic question"}])
        self.assertEqual(self.store.row("sessions", SESSION_B)["chat_history"], [])

    def test_owner_can_delete_own_session(self):
        self.remove_session(SESSION_A)
        self.assertIsNone(self.store.row("sessions", SESSION_A))
        self.assertIsNotNone(self.store.row("sessions", SESSION_B))

    def test_another_users_notes_are_not_returned(self):
        self.assertIsNone(self.deny(self.read_session, SESSION_B),
                          "AUTH-01: ID-only lookup disclosed B's source and notes to A")

    def test_another_users_chat_is_not_modified(self):
        self.deny(self.append_message, SESSION_B, "user", "untrusted question")
        self.assertEqual(self.store.row("sessions", SESSION_B)["chat_history"], [],
                         "AUTH-02: ID-only update modified B's history")

    def test_another_users_session_is_not_deleted(self):
        self.deny(self.remove_session, SESSION_B)
        self.assertIsNotNone(self.store.row("sessions", SESSION_B),
                             "AUTH-03: ID-only delete removed B's source and notes")

    def test_update_predicate_contains_authenticated_owner(self):
        self.append_message(SESSION_A, "user", "question")
        update = next(call for call in self.store.calls if call["operation"] == "update")
        self.assertIn(("user_id", USER_A), update["filters"],
                      "AUTH-04: ownership must constrain the mutation itself")

    def test_delete_predicate_contains_authenticated_owner(self):
        self.remove_session(SESSION_A)
        self.assertIn(("user_id", USER_A), self.store.calls[-1]["filters"],
                      "AUTH-05: delete requires both owner and record ID")

    def test_owner_change_between_read_and_write_does_not_grant_access(self):
        def transfer(table):
            if table == "sessions":
                self.store.row("sessions", SESSION_A)["user_id"] = USER_B
        self.store.after_select = transfer
        self.deny(self.append_message, SESSION_A, "user", "question")
        self.assertEqual(self.store.row("sessions", SESSION_A)["chat_history"], [],
                         "AUTH-06: a prior read is not a mutation ownership predicate")

    def test_ownerless_session_is_not_readable(self):
        self.assertIsNone(self.deny(self.read_session, ORPHAN),
                          "AUTH-07: missing ownership must not grant access")

    def test_missing_owner_column_does_not_grant_access(self):
        del self.store.row("sessions", ORPHAN)["user_id"]
        self.assertIsNone(self.deny(self.read_session, ORPHAN),
                          "AUTH-08: absent ownership must not grant access")

    def test_missing_principal_cannot_read_session(self):
        sys.modules["streamlit"].session_state.user_id = None
        self.assertIsNone(self.deny(self.read_session, SESSION_A),
                          "AUTH-09: the repository has no authenticated-owner input")

    def test_ownerless_session_cannot_be_modified(self):
        self.deny(self.append_message, ORPHAN, "user", "question")
        self.assertEqual(self.store.row("sessions", ORPHAN)["chat_history"], [],
                         "AUTH-19: ownerless data must not be writable")

    def test_ownerless_session_cannot_be_deleted(self):
        self.deny(self.remove_session, ORPHAN)
        self.assertIsNotNone(self.store.row("sessions", ORPHAN),
                             "AUTH-20: ownerless data needs explicit repair, not access")

    def test_missing_principal_cannot_modify_session(self):
        sys.modules["streamlit"].session_state.user_id = None
        self.deny(self.append_message, SESSION_A, "user", "question")
        self.assertEqual(self.store.row("sessions", SESSION_A)["chat_history"], [],
                         "AUTH-21: unauthenticated repository mutation must fail closed")

    def test_missing_principal_cannot_delete_session(self):
        sys.modules["streamlit"].session_state.user_id = None
        self.deny(self.remove_session, SESSION_A)
        self.assertIsNotNone(self.store.row("sessions", SESSION_A),
                             "AUTH-22: unauthenticated repository deletion must fail closed")

    def test_missing_principal_cannot_insert_session(self):
        before = deepcopy(self.store.rows)
        self.deny(self.database.create_session, None, "synthetic.txt", "source", "notes")
        self.assertEqual(self.store.rows, before, "AUTH-10: reject missing principal before insert")
        self.assertEqual(self.store.calls, [])

    def test_invalid_principal_cannot_insert_session(self):
        before = deepcopy(self.store.rows)
        self.deny(self.database.create_session, (False, "failure"), "synthetic.txt", "source", "notes")
        self.assertEqual(self.store.rows, before, "AUTH-11: reject malformed principal before insert")
        self.assertEqual(self.store.calls, [])

    def test_missing_principal_is_rejected_before_listing(self):
        self.deny(self.database.get_all_sessions, None)
        self.assertEqual(self.store.calls, [], "AUTH-12: validate identity before querying")

    def test_invalid_principal_is_rejected_before_listing(self):
        self.deny(self.database.get_all_sessions, "")
        self.assertEqual(self.store.calls, [], "AUTH-13: empty identity is not authenticated")

    def test_unknown_identifiers_do_not_match_records(self):
        before = deepcopy(self.store.rows)
        for target in ("unknown", SESSION_B + " or 1=1"):
            self.assertIsNone(self.read_session(target))
            with self.assertRaises(PermissionError):
                self.append_message(target, "user", "question")
            with self.assertRaises(PermissionError):
                self.remove_session(target)
        self.assertEqual(self.store.rows, before)

    def test_denial_helper_does_not_hide_unrelated_errors(self):
        for error in (TypeError("synthetic"), ValueError("synthetic"),
                      DatabaseFailure("synthetic"), AssertionError("synthetic")):
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                self.deny(Mock(side_effect=error))

    def test_read_database_error_does_not_return_notes(self):
        self.store.errors["sessions", "select"] = DatabaseFailure("synthetic outage")
        with self.assertRaises(DatabaseFailure):
            self.read_session(SESSION_A)

    def test_list_database_error_is_not_an_authorization_success(self):
        self.store.errors["sessions", "select"] = DatabaseFailure("synthetic outage")
        with self.assertRaises(DatabaseFailure):
            self.database.get_all_sessions(USER_A)

    def test_update_database_error_does_not_mutate_data(self):
        self.store.errors["sessions", "update"] = DatabaseFailure("synthetic outage")
        before = deepcopy(self.store.rows)
        with self.assertRaises(DatabaseFailure):
            self.append_message(SESSION_A, "user", "question")
        self.assertEqual(self.store.rows, before)

    def test_delete_database_error_does_not_mutate_data(self):
        self.store.errors["sessions", "delete"] = DatabaseFailure("synthetic outage")
        with self.assertRaises(DatabaseFailure):
            self.remove_session(SESSION_A)
        self.assertIsNotNone(self.store.row("sessions", SESSION_A))

    def test_password_login_accepts_a_verified_hash_match(self):
        with patch.object(self.database.bcrypt, "checkpw", return_value=True):
            self.assertEqual(self.database.authenticate_user("a@example.invalid", "synthetic-password"),
                             (True, USER_A))

    def test_wrong_password_and_unknown_email_do_not_authorize(self):
        with patch.object(self.database.bcrypt, "checkpw", return_value=False):
            self.assertFalse(self.database.authenticate_user("a@example.invalid", "wrong")[0])
        self.assertFalse(self.database.authenticate_user("unknown@example.invalid", "wrong")[0])

    def test_password_account_without_valid_id_does_not_authorize(self):
        self.store.row("users", USER_A)["id"] = None
        with patch.object(self.database.bcrypt, "checkpw", return_value=True):
            success, _ = self.database.authenticate_user("a@example.invalid", "synthetic-password")
        self.assertFalse(success, "AUTH-14: successful hash comparison is not a valid identity")

    def test_database_error_during_login_does_not_authorize(self):
        self.store.errors["users", "select"] = DatabaseFailure("synthetic outage")
        with self.assertRaises(DatabaseFailure):
            self.database.authenticate_user("a@example.invalid", "synthetic-password")

    def test_internal_user_lookup_and_signup_continue_to_work(self):
        self.assertEqual(self.database.get_user_by_id(USER_B)["id"], USER_B)
        self.assertEqual(self.database.get_user_by_email("B@EXAMPLE.INVALID")["id"], USER_B)
        self.assertIs(self.database.create_user("new@example.invalid", provider="github")[0], True)
        self.assertIsNotNone(self.database.get_user_by_email("new@example.invalid"))

    def test_duplicate_signup_is_not_success(self):
        self.assertEqual(self.database.create_user("a@example.invalid", provider="github")[0], False)

    def test_email_signup_stores_only_a_mocked_hash(self):
        with patch.object(self.database.bcrypt, "gensalt", return_value=b"synthetic-salt"), \
                patch.object(self.database.bcrypt, "hashpw", return_value=b"synthetic-hash"):
            self.assertTrue(self.database.create_user("new@example.invalid", "synthetic-password")[0])
        user = self.database.get_user_by_email("new@example.invalid")
        self.assertEqual(user["password_hash"], "synthetic-hash")
        self.assertNotIn("password", user)

    def test_signup_database_error_is_failure(self):
        self.store.errors["users", "insert"] = DatabaseFailure("synthetic outage")
        result = self.database.create_user("new@example.invalid", provider="email")
        self.assertIs(result[0], False)

    def test_existing_github_identity_can_authenticate(self):
        self.assertEqual(self.database.authenticate_oauth_user("b@example.invalid", "github"),
                         (True, USER_B))

    def test_oauth_does_not_implicitly_link_a_password_account(self):
        success, _ = self.database.authenticate_oauth_user("a@example.invalid", "github")
        self.assertFalse(success, "AUTH-15: linking requires an explicit identity policy")

    def test_oauth_creation_race_never_authenticates_a_failure_tuple(self):
        with patch.object(self.database, "get_user_by_email", side_effect=[None, {"id": USER_B}]):
            success, identity = self.database.authenticate_oauth_user("b@example.invalid", "github")
        if success:
            self.assertEqual(identity, USER_B, "AUTH-16: successful identity must be a real user ID")

    def test_oauth_database_error_does_not_authorize(self):
        self.store.errors["users", "select"] = DatabaseFailure("synthetic outage")
        with self.assertRaises(DatabaseFailure):
            self.database.authenticate_oauth_user("b@example.invalid", "github")


class EntryPointContracts(OfflineCase):
    def run_entry(self, principal):
        class State(dict):
            __getattr__ = dict.__getitem__
            __setattr__ = dict.__setitem__

        class Stopped(Exception):
            pass

        streamlit = sys.modules["streamlit"]
        streamlit.session_state = State(user_id=principal)
        streamlit.set_page_config = Mock()
        streamlit.stop = Mock(side_effect=Stopped)
        auth, sidebar, main = (ModuleType(name) for name in (
            "src.ui.auth", "src.ui.sidebar", "src.ui.main_content"))
        auth.handle_oauth_callback = Mock()
        auth.render_login_signup_form = Mock()
        sidebar.render_sidebar = Mock(return_value=(False, "Academic", "General Summary", "Medium"))
        main.render_main_content = Mock()
        with patch.dict(sys.modules, {item.__name__: item for item in (auth, sidebar, main)}):
            try:
                runpy.run_path(str(self.sandbox.repository / "app.py"), run_name="offline_entry")
            except Stopped:
                pass
        return main.render_main_content

    def test_none_identity_is_stopped(self):
        self.run_entry(None).assert_not_called()

    def test_valid_identity_can_reach_application(self):
        self.run_entry(USER_A).assert_called_once()

    def test_empty_identity_cannot_reach_application(self):
        self.run_entry("").assert_not_called()  # AUTH-17

    def test_failure_tuple_cannot_reach_application(self):
        self.run_entry((False, "failure")).assert_not_called()  # AUTH-18

    def test_callback_database_error_does_not_set_identity(self):
        auth = self.app("src.ui.auth")
        streamlit = sys.modules["streamlit"]
        streamlit.session_state = SimpleNamespace(user_id=None)
        streamlit.query_params = {"code": "synthetic-code", "state": "github"}
        streamlit.write, streamlit.rerun = Mock(), Mock()
        with patch.object(auth.oauth, "get_github_user", return_value="b@example.invalid"), \
                patch.object(auth.database, "authenticate_oauth_user",
                             side_effect=DatabaseFailure("synthetic outage")):
            auth.handle_oauth_callback()
        self.assertIsNone(streamlit.session_state.user_id)
        streamlit.rerun.assert_not_called()
        self.assertEqual(streamlit.query_params, {})


class ClientConfigurationContracts(OfflineCase):
    def test_repository_client_uses_only_synthetic_shared_configuration(self):
        database = self.app("src.database.database")
        client = MemoryDatabase()
        with patch.object(database, "create_client", return_value=client) as factory:
            self.assertIs(database.get_supabase(), client)
        factory.assert_called_once_with("https://offline.invalid", "offline-placeholder")


class VectorOwnershipContracts(OfflineCase):
    def test_library_query_filters_the_supplied_user(self):
        sys.modules["streamlit"].session_state = SimpleNamespace(user_id=USER_A)
        rag = self.app("src.core.rag")
        records = [(USER_B, "synthetic B"), (USER_A, "synthetic A")]

        def query(**kwargs):
            where = kwargs.get("where", {})
            selected = [(owner, text) for owner, text in records
                        if all({"user_id": owner}.get(key) == value for key, value in where.items())]
            return {"documents": [[text for _, text in selected]],
                    "metadatas": [[{"filename": "synthetic.txt"} for _ in selected]]}

        collection = Mock()
        collection.count.return_value = len(records)
        collection.query.side_effect = query
        client = Mock()
        client.get_or_create_collection.return_value = collection
        with patch.object(rag, "get_chroma_client", return_value=client), \
                patch.object(rag, "get_gemini_embedding", return_value=[0.0]):
            context = rag.query_relevant_chunks(USER_A, "synthetic question")
        self.assertIn("synthetic A", context)
        self.assertNotIn("synthetic B", context)
        self.assertEqual(collection.query.call_args.kwargs["where"], {"user_id": USER_A})


class FakeQueryControls(OfflineCase):
    def test_unfiltered_fake_does_not_hide_foreign_or_ownerless_rows(self):
        store = MemoryDatabase()
        self.assertEqual(len(store.table("sessions").select("*").execute().data), 3)
        rows = store.table("sessions").select("*").eq("id", SESSION_B).execute().data
        self.assertEqual(rows[0]["user_id"], USER_B)

    def test_fake_owner_predicate_really_controls_a_mutation(self):
        store = MemoryDatabase()
        result = store.table("sessions").delete().eq("id", SESSION_B).eq("user_id", USER_A).execute()
        self.assertEqual(result.data, [])
        self.assertIsNotNone(store.row("sessions", SESSION_B))
