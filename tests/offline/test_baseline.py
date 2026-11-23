"""Small baseline against real source modules with explicit dependency fakes."""

import io
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from offline.support import OfflineCase
from offline.fake_database import USER_A, SESSION_A


class IsolationTests(OfflineCase):
    def test_network_is_blocked(self):
        with self.sandbox.expected_block():
            sys.audit("socket.connect", None, ("offline.invalid", 443))
        with self.sandbox.expected_block():
            sys.audit("socket.getaddrinfo", "offline.invalid", 443, 0, 0, 0)

    def test_subprocess_is_blocked(self):
        with self.sandbox.expected_block():
            sys.audit("subprocess.Popen", "offline-probe", [], None, None)

    def test_secret_read_is_blocked_before_open(self):
        with self.sandbox.expected_block():
            sys.audit("open", self.sandbox.repository / ".env", "r", 0)

    def test_repository_writes_are_blocked(self):
        with self.sandbox.expected_block():
            sys.audit("open", self.sandbox.repository / "offline-probe.txt", "w", 0)

    def test_repository_delete_and_truncate_are_blocked(self):
        target = self.sandbox.repository / "offline-must-not-exist.txt"
        with self.sandbox.expected_block():
            sys.audit("os.remove", target, -1)
        with self.sandbox.expected_block():
            sys.audit("os.truncate", target, 0)

    def test_real_database_reads_are_blocked(self):
        with self.sandbox.expected_block():
            sys.audit("open", self.sandbox.repository / "chroma_db" / "chroma.sqlite3", "r", 0)

    def test_artifacts_are_temporary_and_cleaned(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            artifact = Path(folder) / "synthetic-output.txt"
            artifact.write_text("synthetic fixture")
            self.assertEqual(artifact.read_text(), "synthetic fixture")
        self.assertFalse(Path(folder).exists())

    def test_dotenv_is_noop_and_clients_are_fakes(self):
        llm = self.app("src.core.llm_client")
        self.assertEqual(llm.groq_api_key, "offline-placeholder")
        self.assertEqual(llm.hf_api_key, "offline-placeholder")
        sys.modules["dotenv"].load_dotenv.assert_called_once_with()
        with self.sandbox.expected_block():
            llm.gemini_client.models.generate_content(contents="synthetic")

    def test_unmocked_http_database_and_vectors_are_blocked(self):
        for module, method in (("requests", "get"), ("supabase", "create_client"),
                               ("chromadb", "PersistentClient")):
            with self.subTest(module=module), self.sandbox.expected_block():
                getattr(sys.modules[module], method)("https://offline.invalid")

    def test_rag_import_creates_only_a_temporary_directory(self):
        rag = self.app("src.core.rag")
        self.assertEqual(rag.CHROMA_DB_DIR, "./chroma_db")
        self.assertTrue((self.workdir / "chroma_db").is_dir())

    def test_agent_import_uses_fake_gemini(self):
        agent = self.app("src.core.agent")
        with self.sandbox.expected_block():
            agent.client.models.generate_content(contents="synthetic")


class ExistingCascadeTests(OfflineCase):
    def test_existing_full_cascade(self):
        self.legacy("test_cascade.py").test_full_cascade()

    def test_existing_groq_fallback(self):
        self.legacy("test_cascade.py").test_tier_2_fallback()

    def test_existing_huggingface_fallback(self):
        self.legacy("test_cascade.py").test_tier_3_fallback()


class MockedBaselineTests(OfflineCase):
    def test_primary_generation_does_not_call_fallback(self):
        llm = self.app("src.core.llm_client")
        primary = Mock(return_value=SimpleNamespace(text="synthetic notes"))
        with patch.object(llm.gemini_client.models, "generate_content", primary):
            self.assertEqual(llm.generate_content("synthetic source"),
                             (True, "synthetic notes", "Google Gemini"))
        primary.assert_called_once()
        llm.groq_client.chat.completions.create.assert_not_called()
        llm.hf_client.chat.completions.create.assert_not_called()

    def test_session_listing_uses_a_fake_database(self):
        sys.modules["streamlit"].session_state = SimpleNamespace(user_id=USER_A)
        database = self.app("src.database.database")
        client = Mock()
        query = client.table.return_value.select.return_value.eq.return_value
        query.order.return_value.execute.return_value.data = [{"id": SESSION_A, "user_id": USER_A}]
        with patch.object(database, "get_supabase", return_value=client):
            self.assertEqual(database.get_all_sessions(USER_A),
                             [{"id": SESSION_A, "user_id": USER_A}])
        client.table.return_value.select.return_value.eq.assert_called_once_with(
            "user_id", USER_A)

    def test_oauth_exchange_uses_only_mocked_http(self):
        oauth = self.app("src.auth.oauth")
        token = Mock(status_code=200)
        token.json.return_value = {"access_token": "synthetic-not-a-token"}
        emails = Mock(status_code=200)
        emails.json.return_value = [{"email": "student@example.invalid", "primary": True,
                                     "verified": True}]
        with patch.object(oauth.requests, "post", return_value=token) as post, \
                patch.object(oauth.requests, "get", return_value=emails) as get:
            self.assertEqual(oauth.get_github_user("synthetic-code"), "student@example.invalid")
        post.assert_called_once()
        get.assert_called_once()

    def test_existing_markdown_extraction_without_real_parsers(self):
        self.legacy("test_extractor.py").test_markdown()

    def test_txt_extraction_is_in_memory(self):
        extractor = self.app("src.utils.extractor")
        source = io.BytesIO(b"synthetic study material")
        source.name = "synthetic.txt"
        self.assertEqual(extractor.extract_universal_text(source), "synthetic study material")

    def test_audio_artifact_is_generated_only_in_temporary_workdir(self):
        audio = self.app("src.exporters.audio")
        saved = []

        def save(filename):
            path = Path(filename).resolve()
            self.assertEqual(path.parent, self.workdir)
            path.write_bytes(b"synthetic-not-real-audio")
            saved.append(path)

        speech = Mock()
        speech.save.side_effect = save
        with patch.object(audio, "gTTS", return_value=speech):
            self.assertEqual(audio.generate_audio_from_text("synthetic notes"),
                             b"synthetic-not-real-audio")
        self.assertEqual(len(saved), 1)
        self.assertFalse(saved[0].exists())
