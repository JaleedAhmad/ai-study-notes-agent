"""Batch 4A: real OAuth code with synthetic HTTP and local database records.

No fixture validates state, consumes codes, filters email verification, or binds
subjects. Security assertions remain ordinary failures until production is fixed.
"""

from copy import deepcopy
import runpy
import sys
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

from offline.fake_database import DatabaseFailure, MemoryDatabase, USER_B
from offline.support import OfflineCase


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class GitHubOAuthTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.auth = self.app("src.ui.auth")
        self.oauth = self.auth.oauth
        self.st = sys.modules["streamlit"]
        self.browser()
        self.store = MemoryDatabase()
        self.stack.enter_context(patch.object(self.auth.database, "get_supabase", return_value=self.store))
        self.token = {"access_token": "synthetic-not-a-real-token"}
        self.token_status = self.email_status = 200
        self.profile_status = 200
        self.profile = {"id": 701, "login": "synthetic-account"}
        self.emails = [{"email": "b@example.invalid", "primary": True, "verified": True}]
        self.post = self.stack.enter_context(patch.object(
            self.oauth.requests, "post", side_effect=lambda *a, **kw: self.response(self.token, self.token_status)))
        self.get = self.stack.enter_context(patch.object(self.oauth.requests, "get", side_effect=self.http_get))

    def browser(self):
        # Model a fresh server session, not a real cookie/redirect or hidden nonce store.
        self.st.session_state = State(user_id=None)
        self.st.query_params = {}
        self.st.write, self.st.rerun, self.st.set_page_config = Mock(), Mock(), Mock()

    @staticmethod
    def response(payload, status):
        def json():
            if isinstance(payload, Exception):
                raise payload
            return deepcopy(payload)
        return SimpleNamespace(status_code=status, json=json)

    def http_get(self, url, **kwargs):
        if url == "https://api.github.com/user/emails":
            return self.response(self.emails, self.email_status)
        if url == "https://api.github.com/user":
            return self.response(self.profile, self.profile_status)
        self.sandbox.block("unexpected OAuth endpoint in HTTP fixture")

    def start(self):
        # This test variable is NOT stored in production session state.
        return parse_qs(urlparse(self.oauth.get_github_auth_url()).query)["state"][0]

    def callback(self, state, code="synthetic-code"):
        self.st.query_params = {"code": code, "state": state}
        self.auth.handle_oauth_callback()

    def login(self):
        self.callback(self.start())

    def app_boundary(self):
        """Exercise the real app's exception boundary for provider failures."""
        class Stopped(Exception):
            pass

        self.st.stop = Mock(side_effect=Stopped)
        sidebar, main = ModuleType("src.ui.sidebar"), ModuleType("src.ui.main_content")
        sidebar.render_sidebar = Mock(return_value=(False, "Academic", "General Summary", "Medium"))
        main.render_main_content = Mock()
        with patch.dict(sys.modules, {sidebar.__name__: sidebar, main.__name__: main}), \
                patch.object(self.auth, "render_login_signup_form"):
            try:
                runpy.run_path(str(self.sandbox.repository / "app.py"), run_name="offline_oauth_entry")
            except Stopped:
                pass
        self.assertIsNone(self.st.session_state.user_id)
        main.render_main_content.assert_not_called()

    def test_authorization_url_has_expected_endpoint_scope_and_redirect(self):
        parsed = urlparse(self.oauth.get_github_auth_url())
        query = parse_qs(parsed.query)
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path),
                         ("https", "github.com", "/login/oauth/authorize"))
        self.assertEqual(query["scope"], ["user:email"])
        self.assertEqual(query["client_id"], ["offline-placeholder"])
        self.assertEqual(query["redirect_uri"], [self.oauth.REDIRECT_URI])

    def test_state_is_not_a_public_provider_constant(self):
        self.assertNotEqual(self.start(), "github", "OAUTH-01: state is public and predictable")

    def test_independent_sessions_have_distinct_states(self):
        first = self.start()
        self.browser()
        self.assertNotEqual(first, self.start(), "OAUTH-02: sessions share identical state")

    def test_same_session_rerender_does_not_break_pending_login(self):
        state = self.start()
        self.oauth.get_github_auth_url()
        self.callback(state)
        self.assertEqual(self.st.session_state.user_id, USER_B)

    def test_missing_state_does_not_exchange_code(self):
        self.start()
        self.st.query_params = {"code": "synthetic-code"}
        self.auth.handle_oauth_callback()
        self.post.assert_not_called()
        self.assertIsNone(self.st.session_state.user_id)

    def test_mismatched_state_does_not_exchange_code(self):
        self.start()
        self.callback("synthetic-mismatch")
        self.post.assert_not_called()
        self.assertIsNone(self.st.session_state.user_id)

    def test_callback_without_pending_login_does_not_exchange_code(self):
        self.callback("github")
        self.post.assert_not_called()  # OAUTH-03
        self.assertIsNone(self.st.session_state.user_id)

    def test_another_sessions_callback_is_rejected_before_exchange(self):
        first_session_state = self.start()
        self.browser()
        self.start()
        self.callback(first_session_state)
        self.post.assert_not_called()  # OAUTH-04
        self.assertIsNone(self.st.session_state.user_id)

    def test_expired_state_is_rejected_before_exchange(self):
        with patch.object(self.auth.time, "time", return_value=1000):
            state = self.start()
        with patch.object(self.auth.time, "time", return_value=1000 + 7 * 24 * 3600):
            self.callback(state)
        self.post.assert_not_called()  # OAUTH-05: a login attempt needs bounded lifetime

    def test_consumed_callback_is_not_exchanged_after_logout(self):
        state = self.start()
        self.callback(state)
        self.assertEqual(self.st.session_state.user_id, USER_B)
        self.browser()
        self.callback(state)
        self.assertEqual(self.post.call_count, 1, "OAUTH-06: state must reject replay before provider access")

    def test_inflight_duplicate_callback_is_rejected_before_exchange(self):
        state = self.start()

        def exchange(*args, **kwargs):
            if self.post.call_count == 1:
                self.auth.handle_oauth_callback()
            return self.response(self.token, 200)

        self.post.side_effect = exchange
        self.callback(state)
        self.assertEqual(self.post.call_count, 1, "OAUTH-07: consume state before starting exchange")

    def test_cancellation_clears_callback_without_authentication(self):
        self.st.query_params = {"error": "access_denied", "state": self.start()}
        self.auth.handle_oauth_callback()
        self.post.assert_not_called()
        self.assertIsNone(self.st.session_state.user_id)
        self.assertEqual(self.st.query_params, {}, "OAUTH-08: cancellation parameters remain active")

    def test_already_authenticated_rerun_does_not_repeat_exchange(self):
        state = self.start()
        self.st.session_state.user_id = USER_B
        self.callback(state)
        self.post.assert_not_called()
        self.assertEqual(self.st.session_state.user_id, USER_B)

    def test_verified_existing_github_user_can_log_in(self):
        self.login()
        self.assertEqual(self.st.session_state.user_id, USER_B)
        self.assertEqual(len(self.store.rows["users"]), 2)
        self.st.rerun.assert_called_once()

    def test_unverified_primary_email_cannot_authenticate(self):
        self.emails[0]["verified"] = False
        self.login()
        self.assertIsNone(self.st.session_state.user_id, "OAUTH-09: unverified email authenticated")
        self.assertEqual(self.store.calls, [])

    def test_missing_verification_flag_cannot_authenticate(self):
        del self.emails[0]["verified"]
        self.login()
        self.assertIsNone(self.st.session_state.user_id, "OAUTH-10: missing verification is not verification")
        self.assertEqual(self.store.calls, [])

    def test_verified_secondary_is_used_instead_of_unverified_primary(self):
        self.emails.insert(0, {"email": "unverified@example.invalid", "primary": True, "verified": False})
        self.emails[1]["primary"] = False
        self.login()
        self.assertEqual(self.st.session_state.user_id, USER_B, "OAUTH-11: selected unverified primary")
        self.assertEqual(len(self.store.rows["users"]), 2)

    def test_verified_email_is_used_when_first_email_is_unverified(self):
        self.emails[0]["primary"] = False
        self.emails.insert(0, {"email": "unverified@example.invalid", "primary": False, "verified": False})
        self.login()
        self.assertEqual(self.st.session_state.user_id, USER_B, "OAUTH-12: selected unverified first email")

    def test_empty_email_response_does_not_authenticate(self):
        self.emails = []
        self.login()
        self.assertIsNone(self.st.session_state.user_id)
        self.assertEqual(self.store.calls, [])

    def test_provider_http_errors_do_not_authenticate(self):
        for stage in ("token", "emails"):
            with self.subTest(stage=stage):
                self.browser()
                self.token_status = 400 if stage == "token" else 200
                self.email_status = 401 if stage == "emails" else 200
                self.login()
                self.assertIsNone(self.st.session_state.user_id)
                self.assertEqual(self.store.calls, [])

    def test_missing_access_token_does_not_authenticate(self):
        self.token = {"error": "synthetic-invalid-code"}
        self.login()
        self.get.assert_not_called()
        self.assertIsNone(self.st.session_state.user_id)

    def test_malformed_responses_do_not_authenticate_at_app_boundary(self):
        for stage, payload in (("token", []), ("token", ValueError("synthetic JSON error")),
                               ("emails", [None]), ("emails", {"message": "synthetic error"})):
            with self.subTest(stage=stage, payload=payload):
                self.browser()
                self.token = payload if stage == "token" else {"access_token": "synthetic-token"}
                self.emails = payload if stage == "emails" else []
                self.st.query_params = {"code": "synthetic-code", "state": self.start()}
                self.app_boundary()
                self.assertEqual(self.store.calls, [])

    def test_transport_error_does_not_authenticate_at_app_boundary(self):
        self.post.side_effect = TimeoutError("synthetic transport timeout")
        self.st.query_params = {"code": "synthetic-code", "state": self.start()}
        self.app_boundary()
        self.assertEqual(self.store.calls, [])

    def test_database_error_does_not_authenticate(self):
        self.store.errors["users", "select"] = DatabaseFailure("synthetic database error")
        self.login()
        self.assertIsNone(self.st.session_state.user_id)
        self.assertEqual(self.st.query_params, {})

    def test_database_creation_error_does_not_authenticate(self):
        self.emails[0]["email"] = "new@example.invalid"
        self.store.errors["users", "insert"] = DatabaseFailure("synthetic database error")
        self.login()
        self.assertIsNone(self.st.session_state.user_id)
        self.assertEqual(len(self.store.rows["users"]), 2)

    def test_profile_is_retrieved_before_local_authentication(self):
        self.login()
        urls = [call.args[0] for call in self.get.call_args_list]
        self.assertIn("https://api.github.com/user", urls, "OAUTH-13: stable provider ID is never fetched")

    def test_distinct_subjects_do_not_collapse_to_the_same_email_identity(self):
        first = self.oauth.get_github_user("synthetic-code-1")
        self.profile["id"] = 702
        second = self.oauth.get_github_user("synthetic-code-2")
        self.assertNotEqual(first, second, "OAUTH-14: provider identity discards the subject entirely")

    def test_invalid_profile_cannot_authenticate(self):
        self.profile = {"id": None}
        self.login()
        self.assertIsNone(self.st.session_state.user_id, "OAUTH-15: invalid profile is ignored")
        self.assertEqual(self.store.calls, [])

    def test_http_requests_have_bounded_timeouts(self):
        self.login()
        calls = [*self.post.call_args_list, *self.get.call_args_list]
        self.assertEqual([call.args[0] for call in calls if call.kwargs.get("timeout") is None],
                         [], "OAUTH-16: HTTP requests lack explicit timeouts")
        for call in calls:
            with self.subTest(endpoint=call.args[0]):
                timeout = call.kwargs.get("timeout")
                values = timeout if isinstance(timeout, tuple) else (timeout,)
                self.assertTrue(values and all(isinstance(v, (int, float)) and 0 < v < 300 for v in values))

    def test_transport_failure_cleans_callback_parameters(self):
        self.post.side_effect = TimeoutError("synthetic transport timeout")
        self.st.query_params = {"code": "synthetic-code", "state": self.start()}
        self.app_boundary()
        self.assertEqual(self.st.query_params, {}, "OAUTH-17: outer error boundary leaves callback intact")

    def test_malformed_access_token_cannot_authenticate(self):
        self.token = {"access_token": 7}
        self.login()
        self.assertIsNone(self.st.session_state.user_id, "OAUTH-18: malformed token accepted")

    def test_failed_exchange_does_not_leave_reusable_state(self):
        state = self.start()
        self.token_status = 400
        self.callback(state)
        self.assertIsNone(self.st.session_state.user_id)
        self.token_status = 200
        self.callback(state)
        self.assertEqual(self.post.call_count, 1, "OAUTH-19: failed attempt can be exchanged again")

    def test_non_boolean_verified_flag_cannot_authenticate(self):
        self.emails[0]["verified"] = "false"
        self.login()
        self.assertIsNone(self.st.session_state.user_id, "OAUTH-20: verification must be literal true")
        self.assertEqual(self.store.calls, [])

    def test_password_account_is_not_implicitly_linked(self):
        before = deepcopy(self.store.rows)
        self.emails[0]["email"] = "a@example.invalid"
        self.login()
        self.assertIsNone(self.st.session_state.user_id)
        self.assertEqual(self.store.rows, before)

    def test_first_time_github_user_gets_a_valid_local_identity(self):
        self.profile["id"] = 999
        self.emails[0]["email"] = "new@example.invalid"
        self.login()
        user = self.store.row("users", self.st.session_state.user_id)
        self.assertIsNotNone(user)
        self.assertEqual(user["provider"], "github")
        self.assertIsNone(user["password_hash"])
        self.assertEqual(self.auth.validate_user_id(user["id"]), user["id"])

    def test_exchange_sends_only_synthetic_code_and_expected_redirect(self):
        self.login()
        self.assertEqual(self.post.call_args.kwargs["data"]["code"], "synthetic-code")
        self.assertEqual(self.post.call_args.kwargs["data"]["redirect_uri"], self.oauth.REDIRECT_URI)
        self.assertEqual(self.post.call_args.kwargs["data"]["client_secret"], "offline-placeholder")
        email_call = next(call for call in self.get.call_args_list if call.args[0].endswith("/emails"))
        self.assertEqual(email_call.kwargs["headers"]["Authorization"], "token synthetic-not-a-real-token")
