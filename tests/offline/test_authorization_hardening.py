"""Additional Batch 3B checks for identity substitution and real UI callers."""

from contextlib import nullcontext
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from offline.fake_database import DatabaseFailure, MemoryDatabase, SESSION_A, SESSION_B, USER_A, USER_B
from offline.support import OfflineCase


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class PrincipalTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.database = self.app("src.database.database")
        self.store = MemoryDatabase()
        self.factory = self.stack.enter_context(
            patch.object(self.database, "get_supabase", return_value=self.store))
        sys.modules["streamlit"].session_state = State(user_id=USER_A)

    def operations(self, owner):
        return (
            lambda: self.database.create_session(owner, "synthetic.txt", "source", "notes"),
            lambda: self.database.get_all_sessions(owner),
            lambda: self.database.get_session(SESSION_A, user_id=owner),
            lambda: self.database.save_chat_message(SESSION_A, "user", "question", user_id=owner),
            lambda: self.database.delete_session(SESSION_A, user_id=owner),
        )

    def test_invalid_explicit_owner_never_reaches_database(self):
        for owner in (None, "", (), (False, "failure"), {}, 1, "not-a-uuid", "0" * 32):
            for operation in self.operations(owner):
                with self.subTest(owner=repr(owner)), self.assertRaises(PermissionError):
                    operation()
        self.factory.assert_not_called()

    def test_invalid_server_identity_never_reaches_database(self):
        for owner in (None, "", (False, "failure"), "not-a-uuid", 1):
            sys.modules["streamlit"].session_state.user_id = owner
            for operation in self.operations(USER_A):
                with self.subTest(owner=repr(owner)), self.assertRaises(PermissionError):
                    operation()
        self.factory.assert_not_called()

    def test_valid_foreign_uuid_cannot_replace_authenticated_owner(self):
        for operation in self.operations(USER_B):
            with self.assertRaises(PermissionError):
                operation()
        self.factory.assert_not_called()

    def test_owner_keyword_is_required(self):
        for operation in (
            lambda: self.database.get_session(SESSION_A),
            lambda: self.database.save_chat_message(SESSION_A, "user", "question"),
            lambda: self.database.delete_session(SESSION_A),
        ):
            with self.assertRaises(TypeError):
                operation()
        self.factory.assert_not_called()

    def test_user_b_can_use_its_own_session(self):
        sys.modules["streamlit"].session_state.user_id = USER_B
        self.assertIsNone(self.database.get_session(SESSION_A, user_id=USER_B))
        self.assertEqual(self.database.get_session(SESSION_B, user_id=USER_B)["notes"],
                         "synthetic notes B")
        self.database.save_chat_message(SESSION_B, "user", "question", user_id=USER_B)
        self.database.delete_session(SESSION_B, user_id=USER_B)
        self.assertIsNotNone(self.store.row("sessions", SESSION_A))

    def test_ownership_change_is_reported_as_failed_update(self):
        self.store.after_select = lambda table: self.store.row("sessions", SESSION_A).update(
            user_id=USER_B) if table == "sessions" else None
        with self.assertRaises(PermissionError):
            self.database.save_chat_message(SESSION_A, "user", "question", user_id=USER_A)
        self.assertEqual(self.store.row("sessions", SESSION_A)["chat_history"], [])

    def test_no_match_mutations_are_not_reported_as_success(self):
        for operation in (
            lambda: self.database.save_chat_message(SESSION_B, "user", "question", user_id=USER_A),
            lambda: self.database.delete_session(SESSION_B, user_id=USER_A),
        ):
            with self.assertRaisesRegex(PermissionError, "Session unavailable"):
                operation()
        self.assertIsNotNone(self.store.row("sessions", SESSION_B))

    def test_vector_operations_reject_identity_substitution_before_client_access(self):
        rag = self.app("src.core.rag")
        with patch.object(rag, "get_chroma_client") as client:
            for owner in (None, "not-a-uuid", USER_B):
                with self.assertRaises(PermissionError):
                    rag.query_relevant_chunks(owner, "question")
                with self.assertRaises(PermissionError):
                    rag.embed_and_store_document(owner, "doc", "source", "synthetic.txt")
            client.assert_not_called()


class AuthenticationCallerTests(OfflineCase):
    def configure(self):
        auth = self.app("src.ui.auth")
        st = sys.modules["streamlit"]
        st.session_state = State(user_id=None)
        for name in ("title", "write", "markdown", "divider", "rerun"):
            setattr(st, name, Mock())
        st.tabs = Mock(return_value=(nullcontext(), nullcontext()))
        st.form = Mock(side_effect=lambda name: nullcontext())
        st.text_input = Mock(side_effect=["a@example.invalid", "SyntheticPassword1",
                                         "new@example.invalid", "SyntheticPassword1"])
        return auth, st

    def test_failed_login_and_signup_never_establish_identity(self):
        for workflow in ("login", "signup"):
            for result in ((False, USER_A), (True, None), (True, (False, "failure")),
                           (True, "invalid"), (1, USER_A), True, (True,), [True, USER_A]):
                with self.subTest(workflow=workflow, result=result):
                    auth, st = self.configure()
                    st.form_submit_button = Mock(side_effect=[workflow == "login", workflow == "signup"])
                    with patch.object(auth.database, "authenticate_user", return_value=result), \
                            patch.object(auth.database, "create_user", return_value=result):
                        auth.render_login_signup_form()
                    self.assertIsNone(st.session_state.user_id)
                    st.rerun.assert_not_called()

    def test_legitimate_login_and_signup_use_returned_valid_identity(self):
        for workflow in ("login", "signup"):
            with self.subTest(workflow=workflow):
                auth, st = self.configure()
                st.form_submit_button = Mock(side_effect=[workflow == "login", workflow == "signup"])
                with patch.object(auth.database, "authenticate_user", return_value=(True, USER_A)), \
                        patch.object(auth.database, "create_user", return_value=(True, USER_A)), \
                        patch.object(auth.database, "get_user_by_email") as lookup:
                    auth.render_login_signup_form()
                self.assertEqual(st.session_state.user_id, USER_A)
                st.rerun.assert_called_once()
                lookup.assert_not_called()

    def test_login_and_signup_database_errors_leave_identity_unset(self):
        for workflow in ("login", "signup"):
            with self.subTest(workflow=workflow):
                auth, st = self.configure()
                st.form_submit_button = Mock(side_effect=[workflow == "login", workflow == "signup"])
                with patch.object(auth.database, "authenticate_user",
                                  side_effect=DatabaseFailure("synthetic-private-detail")), \
                        patch.object(auth.database, "create_user",
                                     side_effect=DatabaseFailure("synthetic-private-detail")):
                    auth.render_login_signup_form()
                self.assertIsNone(st.session_state.user_id)
                st.rerun.assert_not_called()
                self.assertNotIn("synthetic-private-detail", str(st.error.call_args_list))

    def test_callback_rejects_invalid_results_and_accepts_valid_identity(self):
        for result, expected in (((False, USER_B), None), ((True, None), None),
                                 ((True, (False, "failure")), None), ((True, USER_B), USER_B)):
            with self.subTest(result=result):
                auth, st = self.configure()
                st.query_params = {"code": "synthetic-code", "state": "github"}
                with patch.object(auth.oauth, "get_github_user", return_value="b@example.invalid"), \
                        patch.object(auth.database, "authenticate_oauth_user", return_value=result):
                    auth.handle_oauth_callback()
                self.assertEqual(st.session_state.user_id, expected)
                self.assertEqual(st.query_params, {})
                self.assertEqual(st.rerun.call_count, int(expected is not None))


class SidebarCallerTests(OfflineCase):
    def configure(self, selected):
        sidebar = self.app("src.ui.sidebar")
        st = sys.modules["streamlit"]
        st.session_state = State(user_id=USER_A, current_session_id=None, notes=None)
        st.sidebar = nullcontext()
        st.columns = Mock(side_effect=lambda widths: (nullcontext(), nullcontext()))
        st.button = Mock(side_effect=lambda *args, **kwargs: kwargs.get("key") == selected)
        for name in ("title", "divider", "write", "rerun"):
            setattr(st, name, Mock())
        st.toggle = Mock(return_value=False)
        st.selectbox = Mock(return_value="Academic")
        st.select_slider = Mock(return_value="Medium")
        store = MemoryDatabase()
        self.stack.enter_context(patch.object(sidebar.database, "get_supabase", return_value=store))
        chat = self.stack.enter_context(patch.object(sidebar, "initialize_chat", return_value=object()))
        return sidebar, st, store, chat

    def test_load_uses_a_fresh_owner_scoped_read(self):
        sidebar, st, store, chat = self.configure(f"load_{SESSION_A}")
        sidebar.render_sidebar()
        self.assertEqual(st.session_state.notes, "synthetic notes A")
        self.assertIn(("id", SESSION_A), store.calls[-1]["filters"])
        self.assertIn(("user_id", USER_A), store.calls[-1]["filters"])
        chat.assert_called_once()

    def test_stale_history_selection_does_not_load_foreign_notes(self):
        sidebar, st, store, chat = self.configure(f"load_{SESSION_A}")
        store.after_select = lambda table: store.row("sessions", SESSION_A).update(user_id=USER_B)
        sidebar.render_sidebar()
        self.assertIsNone(st.session_state.notes)
        self.assertIsNone(st.session_state.current_session_id)
        chat.assert_not_called()

    def test_delete_passes_authenticated_owner(self):
        sidebar, st, store, chat = self.configure(f"del_{SESSION_A}")
        sidebar.render_sidebar()
        self.assertIsNone(store.row("sessions", SESSION_A))
        self.assertIsNotNone(store.row("sessions", SESSION_B))
        self.assertIn(("user_id", USER_A), store.calls[-1]["filters"])
