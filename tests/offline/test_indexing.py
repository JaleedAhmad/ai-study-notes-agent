"""Batch 5B-3: actual orchestration with raw partial-write-capable vector fakes."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from offline.fake_database import USER_A, USER_B
from offline.fake_vectors import MemoryCollection
from offline.support import OfflineCase


class IndexingContracts(OfflineCase):
    def setUp(self):
        super().setUp()
        sys.modules["streamlit"].session_state = SimpleNamespace(user_id=USER_A)
        self.rag = self.app("src.core.rag")
        self.contract = self.app("src.core.indexing")
        self.store = MemoryCollection()
        self.collection = Mock(wraps=self.store)
        client = Mock()
        client.get_or_create_collection.return_value = self.collection
        self.stack.enter_context(patch.object(self.rag, "get_chroma_client", return_value=client))
        self.split = self.stack.enter_context(patch.object(self.rag, "chunk_text", return_value=["first", "second"]))
        self.real_embedding = self.rag.get_gemini_embedding
        self.embed = self.stack.enter_context(patch.object(self.rag, "get_gemini_embedding", return_value=[0.1, 0.2]))

    def index(self, text="source", document="doc"):
        return self.rag.embed_and_store_document(USER_A, document, text, "synthetic.txt")

    def test_every_chunk_has_verified_content_vectors_metadata_and_receipt(self):
        receipt = self.index()
        self.assertIsInstance(receipt, self.rag.IndexReceipt)
        self.assertEqual(receipt.chunk_count, 2)
        self.assertEqual(self.embed.call_count, 2)
        self.assertEqual(self.store.count(), 2)
        rows = self.rag._revision_rows(self.collection, USER_A, "doc", receipt.index_id)
        self.assertEqual(self.rag._complete_revision(rows, USER_A, "doc", receipt.index_id), receipt)
        self.assertEqual(rows["documents"], ["first", "second"])
        self.assertTrue(all(meta["user_id"] == USER_A and meta["document_id"] == "doc"
                            for meta in rows["metadatas"]))

    def test_empty_source_fails_before_provider_or_store(self):
        with self.assertRaises(ValueError):
            self.index(" \n ")
        self.embed.assert_not_called()
        self.collection.add.assert_not_called()

    def test_zero_valid_chunks_fail_explicitly(self):
        for chunks in ([], [" ", "\n"]):
            with self.subTest(chunks=chunks):
                self.split.return_value = chunks
                with self.assertRaises(self.rag.IndexingError):
                    self.index()
        self.embed.assert_not_called()
        self.collection.add.assert_not_called()

    def test_invalid_splitter_outputs_fail(self):
        for chunks in (None, "not a list", [None], ["\x00"]):
            with self.subTest(chunks=chunks):
                self.split.return_value = chunks
                with self.assertRaises(self.rag.IndexingError):
                    self.index()
        self.collection.add.assert_not_called()

    def test_empty_chunks_filtered_but_required_chunks_all_written(self):
        self.split.return_value = ["first", " ", "second"]
        self.assertEqual(self.index().chunk_count, 2)
        self.assertEqual(self.collection.add.call_args.kwargs["documents"], ["first", "second"])

    def test_partial_embedding_failure_never_writes(self):
        self.embed.side_effect = [[0.1, 0.2], RuntimeError("private provider detail")]
        with self.assertRaises(self.rag.IndexingError) as caught:
            self.index()
        self.collection.add.assert_not_called()
        self.assertNotIn("private provider detail", str(caught.exception))

    def test_invalid_vectors_never_write(self):
        for vector in (None, [], "vector", {}, [True], [float("nan")], [float("inf")], ["0.1"]):
            with self.subTest(vector=vector):
                self.embed.return_value = vector
                with self.assertRaises(self.rag.IndexingError):
                    self.index()
        self.collection.add.assert_not_called()

    def test_inconsistent_dimensions_never_write(self):
        self.embed.side_effect = [[0.1], [0.1, 0.2]]
        with self.assertRaises(self.rag.IndexingError):
            self.index()
        self.collection.add.assert_not_called()

    def test_partial_silent_insert_fails_readback_and_cleans_own_ids(self):
        self.store.write_limit = 1
        with self.assertRaises(self.rag.IndexingError):
            self.index()
        self.assertEqual(self.store.count(), 0)
        self.collection.delete.assert_called_once_with(ids=self.collection.add.call_args.kwargs["ids"])

    def test_insert_exception_after_partial_write_cleans_up(self):
        self.store.write_limit = 1
        self.store.add_error = RuntimeError("private insertion detail")
        with self.assertRaises(self.rag.IndexingError) as caught:
            self.index()
        self.assertEqual(self.store.count(), 0)
        self.assertNotIn("private insertion detail", str(caught.exception))

    def test_readback_error_is_failure_and_cleanup_is_attempted(self):
        def get(**kwargs):
            if kwargs.get("ids"):
                raise RuntimeError("synthetic readback outage")
            return self.store.get(**kwargs)
        self.collection.get.side_effect = get
        with self.assertRaises(self.rag.IndexingError):
            self.index()
        self.assertEqual(self.store.count(), 0)

    def test_readback_content_corruption_is_rejected(self):
        def get(**kwargs):
            rows = self.store.get(**kwargs)
            if kwargs.get("ids"):
                rows["documents"][0] = "corrupted"
            return rows
        self.collection.get.side_effect = get
        with self.assertRaises(self.rag.IndexingError):
            self.index()
        self.assertEqual(self.store.count(), 0)

    def test_readback_vector_corruption_is_rejected(self):
        def get(**kwargs):
            rows = self.store.get(**kwargs)
            if kwargs.get("ids"):
                rows["embeddings"][0] = [9.0, 9.0]
            return rows
        self.collection.get.side_effect = get
        with self.assertRaises(self.rag.IndexingError):
            self.index()
        self.assertEqual(self.store.count(), 0)

    def test_cleanup_failure_leaves_partial_revision_unusable_and_retry_recovers(self):
        self.store.write_limit = 1
        self.store.delete_error = RuntimeError("synthetic cleanup failure")
        with self.assertRaises(self.rag.IndexingError) as caught:
            self.index()
        self.assertIn("cleanup", str(caught.exception))
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.rag.query_relevant_chunks(USER_A, "question"), "")
        self.store.write_limit = None
        self.store.delete_error = None
        receipt = self.index()
        self.assertEqual(receipt.chunk_count, 2)
        self.assertEqual(self.embed.call_count, 5)  # two + query + two, never duplicate-skip partial
        self.assertIn("second", self.rag.query_relevant_chunks(USER_A, "question"))

    def test_complete_duplicate_verifies_all_chunks_and_skips_new_embeddings(self):
        receipt = self.index()
        self.embed.reset_mock()
        self.collection.add.reset_mock()
        self.assertEqual(self.index(), receipt)
        self.embed.assert_not_called()
        self.collection.add.assert_not_called()

    def test_one_missing_chunk_does_not_satisfy_duplicate_check(self):
        first = self.index()
        self.store.rows.pop(next(iter(self.store.rows)))
        second = self.index()
        self.assertNotEqual(first.index_id, second.index_id)
        self.assertEqual(self.embed.call_count, 4)

    def test_same_document_id_other_user_cannot_satisfy_duplicate(self):
        self.index()
        sys.modules["streamlit"].session_state = SimpleNamespace(user_id=USER_B)
        receipt = self.rag.embed_and_store_document(USER_B, "doc", "source", "synthetic.txt")
        self.assertEqual(receipt.user_id, USER_B)
        self.assertEqual(self.embed.call_count, 4)
        self.assertEqual(self.store.count(), 4)

    def test_replacement_refused_and_valid_index_unchanged(self):
        self.index()
        before = self.store.get()
        with self.assertRaises(self.rag.IndexingError):
            self.index("different source")
        self.assertEqual(self.store.get(), before)
        self.collection.delete.assert_not_called()

    def test_failed_new_document_preserves_previous_valid_document(self):
        self.index()
        before = self.store.get()
        self.store.write_limit = 1
        self.store.add_error = RuntimeError("synthetic error")
        with self.assertRaises(self.rag.IndexingError):
            self.index(document="replacement-id")
        self.assertEqual(self.store.get(), before)

    def test_legacy_rows_are_not_completion_evidence_or_deleted(self):
        self.store.add(ids=["legacy"], documents=["old"], embeddings=[[0.1, 0.2]],
                       metadatas=[{"user_id": USER_A, "document_id": "doc", "filename": "old.txt"}])
        self.index()
        self.assertIn("legacy", self.store.rows)
        self.assertEqual(self.embed.call_count, 2)

    def test_verified_library_search_preserves_source_and_user_filter(self):
        self.index()
        context = self.rag.query_relevant_chunks(USER_A, "question")
        self.assertIn("first", context)
        self.assertIn("second", context)
        self.assertEqual(self.collection.query.call_args.kwargs["where"], {"user_id": USER_A})

    def test_missing_chunk_invalidates_previously_complete_revision(self):
        self.index()
        self.store.rows.pop(next(iter(self.store.rows)))
        self.assertEqual(self.rag.query_relevant_chunks(USER_A, "question"), "")

    def test_embedding_response_requires_exactly_one_valid_vector(self):
        # Exercise actual provider response parsing, without constructing a real client.
        client = Mock()
        with patch.object(self.rag.genai, "Client", return_value=client):
            for result in (SimpleNamespace(embeddings=[]), SimpleNamespace(embeddings=[None]),
                           SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0]), SimpleNamespace(values=[2.0])])):
                client.models.embed_content.return_value = result
                with self.assertRaises(self.rag.IndexingError):
                    self.real_embedding("chunk")

    def test_actual_embedding_response_accepts_one_valid_vector(self):
        client = Mock()
        client.models.embed_content.return_value = SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.1, 0.2])])
        with patch.object(self.rag.genai, "Client", return_value=client):
            self.assertEqual(self.real_embedding("chunk"), [0.1, 0.2])
        self.assertEqual(client.models.embed_content.call_args.kwargs["model"], "gemini-embedding-001")

    def test_unordered_readback_is_validated_by_id(self):
        def get(**kwargs):
            rows = self.store.get(**kwargs)
            if kwargs.get("ids"):
                rows = {key: list(reversed(value)) for key, value in rows.items()}
            return rows
        self.collection.get.side_effect = get
        self.assertEqual(self.index().chunk_count, 2)
        self.assertEqual(self.index().chunk_count, 2)
        self.assertEqual(self.embed.call_count, 2)

    def test_missing_metadata_on_readback_fails_and_cleans_up(self):
        def get(**kwargs):
            rows = self.store.get(**kwargs)
            if kwargs.get("ids"):
                rows.pop("metadatas")
            return rows
        self.collection.get.side_effect = get
        with self.assertRaises(self.rag.IndexingError):
            self.index()
        self.assertEqual(self.store.count(), 0)

    def test_changed_chunk_metadata_cannot_satisfy_duplicate(self):
        first = self.index()
        list(self.store.rows.values())[0]["metadata"]["chunk_number"] = 7
        second = self.index()
        self.assertNotEqual(first.index_id, second.index_id)
        self.assertEqual(self.embed.call_count, 4)

    def test_unfiltered_vector_fake_exposes_foreign_and_partial_records(self):
        self.store.add(ids=["foreign"], documents=["foreign text"], embeddings=[[0.1]],
                       metadatas=[{"user_id": USER_B}])
        self.assertEqual(self.store.get()["ids"], ["foreign"])
        self.assertEqual(self.store.get(where={"user_id": USER_A})["ids"], [])

    def test_float32_rounding_is_accepted_but_dimension_mismatch_is_not(self):
        self.contract.verify_rows(dict(ids=["id"], documents=["text"], embeddings=[[0.100000001]]),
                                  ["id"], ["text"], [[0.1]])
        with self.assertRaises(self.rag.IndexingError):
            self.contract.verify_rows(dict(ids=["id"], documents=["text"], embeddings=[[0.1, 0.2]]),
                                      ["id"], ["text"], [[0.1]])


class EphemeralIndexContracts(OfflineCase):
    def setUp(self):
        super().setUp()
        self.router = self.app("src.core.pipeline_router")
        self.store = MemoryCollection()
        self.collection = Mock(wraps=self.store)
        self.client = Mock()
        self.client.create_collection.return_value = self.collection
        self.stack.enter_context(patch.object(self.router.chromadb, "EphemeralClient", return_value=self.client))
        splitter = Mock()
        splitter.split_text.return_value = ["first", "second"]
        self.splitter = splitter
        self.stack.enter_context(patch.object(self.router, "RecursiveCharacterTextSplitter", return_value=splitter))
        self.stack.enter_context(patch.object(self.router, "CHAR_LIMIT_FOR_DIRECT", 5))
        self.embed = self.stack.enter_context(patch.object(self.router, "get_gemini_embedding", return_value=[0.1, 0.2]))
        self.model = Mock(return_value=(True, "notes", "synthetic"))
        self.error = self.app("src.core.indexing").IndexingError

    def run_route(self):
        return self.router.route_and_process("synthetic long source", "question", None, self.model,
                                             comprehensive=False)

    def test_complete_index_reaches_model_and_is_removed(self):
        result = self.run_route()
        self.assertIs(result[0], True)
        self.assertIn("first", self.model.call_args.args[0])
        self.assertIn("second", self.model.call_args.args[0])
        self.client.delete_collection.assert_called_once_with(
            name=self.client.create_collection.call_args.kwargs["name"])

    def test_one_failed_embedding_cannot_reach_model(self):
        self.embed.side_effect = [[0.1, 0.2], RuntimeError("synthetic embedding failure")]
        with self.assertRaises(self.error):
            self.run_route()
        self.model.assert_not_called()
        self.collection.add.assert_not_called()

    def test_zero_chunks_cannot_reach_model(self):
        self.splitter.split_text.return_value = [" "]
        with self.assertRaises(self.error):
            self.run_route()
        self.model.assert_not_called()
        self.client.create_collection.assert_not_called()

    def test_partial_insert_cannot_reach_model(self):
        self.store.write_limit = 1
        with self.assertRaises(self.error):
            self.run_route()
        self.model.assert_not_called()
        self.client.delete_collection.assert_called_once()

    def test_insert_exception_cannot_reach_model(self):
        self.store.add_error = RuntimeError("private insertion detail")
        with self.assertRaises(self.error):
            self.run_route()
        self.model.assert_not_called()
        self.client.delete_collection.assert_called_once()

    def test_query_failure_cannot_generate_ungrounded_notes(self):
        self.collection.query.side_effect = RuntimeError("synthetic query error")
        with self.assertRaises(RuntimeError):
            self.run_route()
        self.model.assert_not_called()
        self.client.delete_collection.assert_called_once()

    def test_empty_or_unknown_context_cannot_reach_model(self):
        for documents in ([], [[]], [[" "]], [["not an indexed chunk"]]):
            with self.subTest(documents=documents):
                self.collection.query.return_value = {"documents": documents}
                with self.assertRaises(self.error):
                    self.run_route()
        self.model.assert_not_called()

    def test_query_vector_dimension_mismatch_cannot_reach_model(self):
        self.embed.side_effect = [[0.1, 0.2], [0.1, 0.2], [0.1]]
        with self.assertRaises(self.error):
            self.run_route()
        self.collection.query.assert_not_called()
        self.model.assert_not_called()
