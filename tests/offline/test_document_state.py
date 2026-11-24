"""Batch 5B-4: content identity, source transitions and raw UI boundary checks."""
from contextlib import nullcontext
import io
import sys
from unittest.mock import Mock, patch

from offline.fake_database import USER_A, USER_B, SESSION_A, SESSION_B, MemoryDatabase
from offline.support import OfflineCase
from offline.test_extraction import UploadUIFixtures, State, Stopped, upload


def saved(owner=USER_A, session=SESSION_A, text="saved source", history=None):
    return dict(id=session, user_id=owner, filename="saved.txt", pdf_text=text,
                notes="saved notes", chat_history=history or [])


class FingerprintContracts(OfflineCase):
    def setUp(self):
        super().setUp()
        self.state = self.app("src.utils.document_state")

    def test_same_name_different_bytes_has_different_identity(self):
        a, b = (self.state.snapshot(upload("same.txt", value)) for value in (b"first", b"second"))
        self.assertNotEqual(a.document_id(USER_A), b.document_id(USER_A))

    def test_names_do_not_define_identity_and_formats_do(self):
        a, b, c = (self.state.snapshot(upload(name, b"same")) for name in ("a.txt", "b.TXT", "a.pdf"))
        self.assertEqual(a.digest, b.digest)
        self.assertEqual(a.document_id(USER_A), b.document_id(USER_A))
        self.assertNotEqual(a.document_id(USER_A), c.document_id(USER_A))
        self.assertNotEqual(a.document_id(USER_A), a.document_id(USER_B))

    def test_fingerprint_is_sha256_and_cursor_is_preserved(self):
        value = upload("a.txt", b"abc")
        value.seek(2)
        item = self.state.snapshot(value)
        self.assertEqual(item.digest, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(value.tell(), 2)
        self.assertEqual(item.stream().read(), b"abc")
        self.assertEqual(item.stream().read(), b"abc")

    def test_non_getvalue_stream_restores_cursor(self):
        raw = io.BytesIO(b"whole source")
        raw.seek(5)
        class Stream:
            name = "a.txt"
            read, seek, tell = raw.read, raw.seek, raw.tell
        item = self.state.snapshot(Stream())
        self.assertEqual(item.data, b"whole source")
        self.assertEqual(raw.tell(), 5)

    def test_invalid_reads_and_failed_reads_fail_explicitly(self):
        class Stream:
            name = "bad.txt"
            tell = lambda self: 2
            seek = Mock()
            read = Mock(side_effect=RuntimeError("private read detail"))
        value = Stream()
        with self.assertRaises(RuntimeError):
            self.state.snapshot(value)
        value.seek.assert_called_with(2)
        raw = io.StringIO("not bytes")
        raw.name = "bad.txt"
        with self.assertRaises(ValueError):
            self.state.snapshot(raw)

    def test_bundle_order_and_processing_version_are_part_of_identity(self):
        a, b = (self.state.snapshot(upload("a.txt", value)) for value in (b"one", b"two"))
        first = self.state.upload_selection(USER_A, [a, b])
        self.assertNotEqual(first, self.state.upload_selection(USER_A, [b, a]))
        with patch.object(self.state, "PROCESSING_VERSION", "future-version"):
            self.assertNotEqual(first, self.state.upload_selection(USER_A, [a, b]))

    def test_restore_rejects_foreign_owner_and_invalid_source(self):
        for row in (saved(owner=USER_B), saved(text=" \n ")):
            with self.subTest(row=row), self.assertRaises((PermissionError, ValueError)):
                self.state.restore_saved_session({}, row, USER_A)

    def test_saved_state_is_copied_and_bound_to_its_id_and_source(self):
        row = saved(history=[{"role": "user", "content": "old question"}])
        state = {}
        self.state.restore_saved_session(state, row, USER_A)
        self.assertEqual(self.state.selected_source(state, USER_A)[0], "saved source")
        state["chat_history"].append({"role": "assistant", "content": "new answer"})
        self.assertEqual(len(row["chat_history"]), 1)
        state["current_session_id"] = SESSION_B
        with self.assertRaises(ValueError):
            self.state.selected_source(state, USER_A)

    def test_tampered_source_or_foreign_principal_fails_closed(self):
        state = {}
        self.state.restore_saved_session(state, saved(), USER_A)
        with self.assertRaises(ValueError):
            self.state.selected_source(state, USER_B)
        state["pdf_text"] = "different content"
        with self.assertRaises(ValueError):
            self.state.selected_source(state, USER_A)


class DocumentUIContracts(UploadUIFixtures):
    def setUp(self):
        super().setUp()
        self.state = self.app("src.utils.document_state")

    def process(self, name="same.txt", data=b"first source"):
        self.st.file_uploader.return_value = [upload(name, data)]
        self.render()

    def attach_notes(self):
        self.st.session_state.notes = "current notes"
        self.st.session_state.notes_source = self.st.session_state.ready_source

    def test_same_content_rerun_reuses_extraction_and_reverifies_index(self):
        self.process()
        self.attach_notes()
        self.extract.reset_mock()
        self.embedding.reset_mock()
        self.index.reset_mock()
        self.process()
        self.extract.assert_not_called()
        self.embedding.assert_not_called()
        self.index.assert_called_once()
        self.assertEqual(self.st.session_state.notes, "current notes")

    def test_moved_upload_cursor_never_changes_identity_or_extracted_bytes(self):
        file = upload("same.txt", b"complete source")
        file.seek(7)
        self.st.file_uploader.return_value = [file]
        self.render()
        self.assertIn("complete source", self.st.session_state.pdf_text)
        self.assertEqual(file.tell(), 7)
        self.render()
        self.assertEqual(self.extract.call_count, 1)

    def test_same_filename_changed_bytes_clear_all_dependent_state(self):
        self.process()
        self.attach_notes()
        old_ids = set(self.vector_store.rows)
        self.st.session_state.update(chat_session=object(), chat_history=[{"role": "user", "content": "old"}],
                                     podcast_bytes=b"old", anki_bytes=b"old", current_session_id=SESSION_A)
        self.process(data=b"second source")
        self.assertIn("second source", self.st.session_state.pdf_text)
        self.assertNotIn("first source", self.st.session_state.pdf_text)
        self.assertIsNone(self.st.session_state.notes)
        self.assertIsNone(self.st.session_state.chat_session)
        self.assertEqual(self.st.session_state.chat_history, [])
        self.assertIsNone(self.st.session_state.current_session_id)
        self.assertIsNone(self.st.session_state.podcast_bytes)
        self.assertIsNone(self.st.session_state.anki_bytes)
        self.assertTrue(old_ids.issubset(self.vector_store.rows))

    def test_different_filename_same_bytes_reuses_extraction_and_verified_index(self):
        self.process("first.txt")
        document_ids = set(self.st.session_state.index_receipts)
        self.extract.reset_mock()
        self.embedding.reset_mock()
        self.process("renamed.txt")
        self.extract.assert_not_called()
        self.embedding.assert_not_called()
        self.assertEqual(set(self.st.session_state.index_receipts), document_ids)
        self.assertEqual(self.st.session_state.current_file, ["renamed.txt"])
        self.assertIn("renamed.txt", self.st.session_state.pdf_text)

    def test_identical_bytes_different_formats_do_not_reuse_extraction(self):
        self.process("a.txt", b"same bytes")
        first = set(self.st.session_state.index_receipts)
        self.extract.reset_mock()
        self.extract.return_value = "synthetic markdown interpretation"
        self.process("a.md", b"same bytes")
        self.extract.assert_called_once()
        self.assertNotEqual(first, set(self.st.session_state.index_receipts))

    def test_identical_content_aliases_in_one_upload_are_extracted_and_indexed_once(self):
        self.st.file_uploader.return_value = [upload("a.txt", b"same source"), upload("b.txt", b"same source")]
        self.render()
        self.extract.assert_called_once()
        self.embedding.assert_called_once()
        self.assertEqual(len(self.st.session_state.index_receipts), 1)
        self.assertEqual(self.st.session_state.current_file, ["a.txt", "b.txt"])

    def test_same_filename_distinct_documents_in_one_upload_have_distinct_indexes(self):
        self.st.file_uploader.return_value = [upload("same.txt", b"source one"), upload("same.txt", b"source two")]
        self.render()
        self.assertEqual(len(self.st.session_state.index_receipts), 2)
        self.assertIn("source one", self.st.session_state.pdf_text)
        self.assertIn("source two", self.st.session_state.pdf_text)

    def test_reextraction_variation_creates_new_index_without_overwriting_prior_valid_vectors(self):
        self.process()
        previous = set(self.vector_store.rows)
        self.st.session_state.upload_cache = {}
        self.extract.return_value = "valid alternate OCR transcription"
        self.process()
        self.assertTrue(previous.issubset(self.vector_store.rows))
        self.assertGreater(self.vector_store.count(), len(previous))
        self.assertIn("valid alternate OCR transcription", self.st.session_state.pdf_text)

    def test_failed_new_upload_never_falls_back_to_prior_source(self):
        self.process()
        self.attach_notes()
        self.st.button.return_value = True
        self.process(data=b" \n ")
        self.assertIsNone(self.st.session_state.pdf_text)
        self.assertIsNone(self.st.session_state.notes)
        self.assertEqual(self.st.session_state.index_receipts, {})
        self.router.assert_not_called()

    def test_failed_revalidation_invalidates_previously_ready_same_document(self):
        self.process()
        self.attach_notes()
        self.index.side_effect = RuntimeError("synthetic readback outage")
        self.st.button.return_value = True
        self.process()
        self.assertIsNone(self.st.session_state.ready_source)
        self.assertIsNone(self.st.session_state.notes)
        self.assertIsNone(self.st.session_state.pdf_text)
        self.router.assert_not_called()

    def test_stale_receipt_cannot_bypass_current_readback(self):
        self.process()
        self.st.session_state.index_receipts = {"old": self.ui.rag.IndexReceipt(USER_B, "old", "old", 1)}
        self.process()
        self.assertNotIn("old", self.st.session_state.index_receipts)
        self.assertTrue(all(value.user_id == USER_A for value in self.st.session_state.index_receipts.values()))
        self.assertEqual(self.index.call_count, 2)

    def test_corrupt_cached_extraction_fails_closed_then_retry_recovers(self):
        self.process()
        next(iter(self.st.session_state.upload_cache.values()))["text"] = "corrupt cached text"
        self.process()
        self.assertIsNone(self.st.session_state.pdf_text)
        self.process()
        self.assertIn("first source", self.st.session_state.pdf_text)

    def test_removing_upload_clears_active_source_and_outputs_without_deletion(self):
        self.process()
        self.attach_notes()
        count = self.vector_store.count()
        self.st.file_uploader.return_value = []
        self.render()
        self.assertIsNone(self.st.session_state.notes)
        self.assertIsNone(self.st.session_state.ready_source)
        self.assertEqual(self.vector_store.count(), count)

    def test_owner_change_clears_state_before_reprocessing_private_upload(self):
        self.process()
        self.attach_notes()
        self.extract.reset_mock()
        self.index.reset_mock()
        self.st.session_state.user_id = USER_B
        self.render()
        self.extract.assert_not_called()
        self.index.assert_not_called()
        self.assertIsNone(self.st.session_state.pdf_text)
        self.assertIsNone(self.st.session_state.notes)
        self.assertGreater(self.st.session_state.upload_epoch, 0)

    def test_explicit_same_bytes_upload_for_new_owner_has_distinct_index(self):
        self.process()
        first = set(self.st.session_state.index_receipts)
        self.st.session_state.user_id = USER_B
        self.render()  # force re-selection after principal transition
        self.process()
        self.assertNotEqual(first, set(self.st.session_state.index_receipts))
        self.assertTrue(all(value.user_id == USER_B for value in self.st.session_state.index_receipts.values()))

    def test_saved_session_to_upload_clears_saved_context_without_deleting_record(self):
        self.state.restore_saved_session(self.st.session_state, saved(), USER_A)
        self.st.session_state.chat_session = object()
        self.process(data=b"new upload")
        self.assertEqual(self.st.session_state.source_selection["kind"], "upload")
        self.assertIsNone(self.st.session_state.current_session_id)
        self.assertIsNone(self.st.session_state.notes)
        self.assertEqual(self.st.session_state.chat_history, [])
        self.assertIn("new upload", self.st.session_state.pdf_text)

    def test_interrupted_indexing_does_not_publish_ready_source(self):
        self.process()
        self.index.side_effect = Stopped
        self.process()
        self.assertIsNone(self.st.session_state.ready_source)
        self.index.side_effect = None
        self.process()
        self.assertIn("first source", self.st.session_state.pdf_text)
        self.assertIsNotNone(self.st.session_state.ready_source)

    def test_generation_and_persistence_use_current_selected_source(self):
        self.process()
        self.st.button.return_value = True
        self.router.return_value = (True, "current generated notes", "offline", "direct")
        with patch.object(self.ui, "initialize_chat", return_value=object()) as chat, \
                patch.object(self.ui.database, "create_session", return_value=SESSION_A) as save:
            self.render()
        source = self.router.call_args.kwargs["raw_text"]
        self.assertEqual(chat.call_args.args[0], source)
        self.assertEqual(save.call_args.args[2], source)
        self.assertEqual(self.st.session_state.chat_source[0], self.st.session_state.notes_source)

    def test_source_switch_during_generation_cannot_save_old_notes_to_new_source(self):
        self.process()
        self.st.button.return_value = True
        def generate(**kwargs):
            self.state.restore_saved_session(self.st.session_state, saved(session=SESSION_B, text="new saved source"), USER_A)
            return True, "old source answer", "offline", "direct"
        self.router.side_effect = generate
        with patch.object(self.ui.database, "create_session") as create:
            self.render()
        create.assert_not_called()
        self.assertEqual(self.st.session_state.pdf_text, "new saved source")
        self.assertNotEqual(self.st.session_state.notes, "old source answer")

    def test_unbound_legacy_saved_state_requires_reopen(self):
        self.st.session_state.update(notes="unbound legacy notes", pdf_text="unbound source", current_session_id=SESSION_A)
        self.st.file_uploader.return_value = []
        self.render()
        self.notes_view.assert_not_called()
        self.st.error.assert_called_once()


class ChatSourceContracts(UploadUIFixtures):
    def setUp(self):
        super().setUp()
        self.state = self.app("src.utils.document_state")
        for name in ("divider", "subheader", "write", "markdown"):
            setattr(self.st, name, Mock())
        self.st.chat_message = Mock(side_effect=lambda *a, **k: nullcontext())
        self.st.chat_input = Mock(return_value=None)
        self.chat = self.stack.enter_context(patch.object(self.ui, "initialize_chat", return_value=object()))
        self.send = self.stack.enter_context(patch.object(self.ui, "send_chat_message", return_value="synthetic answer"))
        self.save = self.stack.enter_context(patch.object(self.ui.database, "save_chat_message"))
        self.stack.enter_context(patch.object(self.ui, "check_prompt", return_value={"safe": True}))

    def prepare_upload(self):
        self.st.file_uploader.return_value = [upload("current.txt", b"intended current source")]
        self.render()
        self.st.session_state.notes = "current notes"
        self.st.session_state.notes_source = self.st.session_state.ready_source
        self.st.session_state.current_session_id = SESSION_A
        self.st.session_state.session_source = (SESSION_A, self.st.session_state.ready_source)

    def test_stale_chat_object_and_history_are_not_reused(self):
        self.prepare_upload()
        self.st.session_state.chat_session = object()
        self.st.session_state.chat_source = ("old-source", SESSION_B)
        self.st.session_state.chat_history = [{"role": "user", "content": "old question"}]
        self.st.session_state.history_source = "old-source"
        self.real_chat_view(False)
        self.chat.assert_called_once()
        self.assertIn("intended current source", self.chat.call_args.args[0])
        self.assertEqual(self.chat.call_args.args[1], [])
        self.assertEqual(self.st.session_state.chat_history, [])

    def test_same_source_chat_context_is_reused(self):
        self.prepare_upload()
        self.real_chat_view(False)
        first = self.st.session_state.chat_session
        self.real_chat_view(False)
        self.chat.assert_called_once()
        self.assertIs(self.st.session_state.chat_session, first)

    def test_upload_chat_excludes_other_library_documents(self):
        self.prepare_upload()
        self.ui.rag.embed_and_store_document(USER_A, "other-id", "unrelated library source", "other.txt")
        self.st.chat_input.return_value = "question"
        self.real_chat_view(False)
        prompt = self.send.call_args.args[1]
        self.assertIn("intended current source", prompt)
        self.assertNotIn("unrelated library source", prompt)
        self.assertEqual(self.save.call_args_list[-1].args[0], SESSION_A)
        self.assertEqual(self.save.call_args_list[-1].kwargs["user_id"], USER_A)
        self.assertIn("$and", self.collection.query.call_args.kwargs["where"])

    def test_saved_chat_restores_only_saved_source_and_history_without_filename_index_guess(self):
        history = [{"role": "user", "content": "saved question"}]
        self.state.restore_saved_session(self.st.session_state, saved(history=history), USER_A)
        self.st.chat_input.return_value = "next question"
        self.real_chat_view(False)
        self.assertEqual(self.chat.call_args.args[0], "saved source")
        self.assertEqual(self.chat.call_args.args[1][0], history[0])
        self.collection.query.assert_not_called()
        self.send.assert_called_once()

    def test_invalid_source_cannot_initialize_or_send_chat(self):
        self.state.restore_saved_session(self.st.session_state, saved(), USER_A)
        self.st.session_state.pdf_text = "stale other source"
        self.st.chat_input.return_value = "question"
        self.real_chat_view(False)
        self.chat.assert_not_called()
        self.send.assert_not_called()
        self.save.assert_not_called()

    def test_replaced_session_id_cannot_receive_history_for_current_upload(self):
        self.prepare_upload()
        self.st.session_state.current_session_id = SESSION_B
        self.st.chat_input.return_value = "question"
        self.real_chat_view(False)
        self.chat.assert_not_called()
        self.send.assert_not_called()
        self.save.assert_not_called()

    def test_source_switch_during_reply_prevents_answer_persisting_to_another_session(self):
        self.prepare_upload()
        self.st.chat_input.return_value = "question"
        def reply(*args):
            self.state.restore_saved_session(self.st.session_state, saved(session=SESSION_B, text="other saved source"), USER_A)
            return "answer from old source"
        self.send.side_effect = reply
        self.real_chat_view(False)
        self.assertEqual(self.save.call_count, 1)  # original user message only
        self.assertEqual(self.save.call_args.args[0], SESSION_A)
        self.assertEqual(self.st.session_state.chat_history, [])
        self.assertNotIn("answer from old source", str(self.st.markdown.call_args_list))


class SavedTransitionContracts(OfflineCase):
    def setUp(self):
        super().setUp()
        self.sidebar = self.app("src.ui.sidebar")
        self.st = sys.modules["streamlit"]
        self.st.session_state = State(user_id=USER_A, current_session_id=None, notes=None)
        self.st.sidebar = nullcontext()
        self.st.columns = Mock(side_effect=lambda *a, **k: (nullcontext(), nullcontext()))
        self.selected = f"load_{SESSION_A}"
        self.st.button = Mock(side_effect=lambda *a, **k: k.get("key") == self.selected)
        for name in ("title", "divider", "write", "warning", "error"):
            setattr(self.st, name, Mock())
        self.st.toggle = Mock(return_value=False)
        self.st.selectbox = Mock(return_value="Academic")
        self.st.select_slider = Mock(return_value="Medium")
        self.st.rerun = Mock(side_effect=Stopped)
        self.st.stop = Mock(side_effect=Stopped)
        self.store = MemoryDatabase()
        self.stack.enter_context(patch.object(self.sidebar.database, "get_supabase", return_value=self.store))
        self.chat = self.stack.enter_context(patch.object(self.sidebar, "initialize_chat", return_value=object()))

    def render(self):
        try:
            self.sidebar.render_sidebar()
        except Stopped:
            pass

    def test_load_then_reopen_restores_fresh_owned_record_and_resets_uploader(self):
        self.render()
        first_epoch = self.st.session_state.upload_epoch
        self.st.session_state.pdf_text = "stale source"
        self.st.session_state.chat_history = [{"role": "user", "content": "stale question"}]
        self.store.row("sessions", SESSION_A)["chat_history"] = [{"role": "user", "content": "persisted question"}]
        self.render()
        self.assertEqual(self.st.session_state.pdf_text, "synthetic source A")
        self.assertEqual(self.st.session_state.chat_history[0]["content"], "persisted question")
        self.assertGreater(self.st.session_state.upload_epoch, first_epoch)
        self.assertEqual(self.st.session_state.index_receipts, {})
        self.assertEqual(self.st.session_state.source_selection["kind"], "saved")

    def test_failed_saved_lookup_clears_previous_source_and_never_initializes_foreign_chat(self):
        self.render()
        self.chat.reset_mock()
        self.store.after_select = lambda table: self.store.row("sessions", SESSION_A).update(user_id=USER_B)
        self.render()
        self.assertIsNone(self.st.session_state.pdf_text)
        self.assertIsNone(self.st.session_state.notes)
        self.assertIsNone(self.st.session_state.current_session_id)
        self.chat.assert_not_called()

    def test_new_session_clears_identity_and_widgets_without_deleting_saved_rows(self):
        self.render()
        self.st.button.side_effect = lambda label, **kwargs: "Start New Session" in label
        before = self.store.row("sessions", SESSION_A).copy()
        self.render()
        self.assertIsNone(self.st.session_state.pdf_text)
        self.assertIsNone(self.st.session_state.source_selection)
        self.assertEqual(self.store.row("sessions", SESSION_A), before)
