"""Batch 6B-2: deterministic source delivery, not mocked factual-accuracy proof."""
from dataclasses import replace
import html
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from offline.fake_database import USER_A, SESSION_A
from offline.support import OfflineCase
from offline.test_extraction import UploadUIFixtures, upload


def source_records(prompt):
    if "\nSOURCE_RECORDS\n" not in prompt:
        return []
    return json.loads(prompt.split("\nSOURCE_RECORDS\n", 1)[1].split("\nEND_SOURCE_RECORDS\n", 1)[0])


class ManifestContracts(OfflineCase):
    def setUp(self):
        super().setUp()
        self.records = self.app("src.utils.source_manifest")

    def test_every_character_and_unicode_boundary_is_accounted_for(self):
        source = "  FIRST\n" + "α🧪<&>\t" * 500 + "\nMIDDLE\n" + "z" * 1300 + "\nFINAL  "
        manifest = self.records.build_manifest(source)
        self.assertEqual("".join(source[part.start:part.end] for part in manifest.spans), source)
        self.assertEqual(manifest.byte_length, len(source.encode()))
        self.assertEqual(manifest.spans[0].start, 0)
        self.assertEqual(manifest.spans[-1].end, len(source))
        manifest.validate(source)

    def test_stable_ids_hashes_and_offsets_are_deterministic(self):
        source = "repeated content\n" * 300
        self.assertEqual(self.records.build_manifest(source), self.records.build_manifest(source))
        manifest = self.records.build_manifest(source)
        self.assertEqual(len({part.source_id for part in manifest.spans}), len(manifest.spans))
        self.assertNotEqual(manifest.source_hash, self.records.build_manifest(source + "changed").source_hash)

    def test_whitespace_is_retained_but_whitespace_only_units_are_not_required(self):
        source = "FIRST\n" + " \t\n" * 1500 + "FINAL"
        manifest = self.records.build_manifest(source)
        self.assertTrue(any(not item.required for item in manifest.spans))
        self.assertEqual(sum(item.end-item.start for item in manifest.spans), len(source))
        self.assertTrue(all(source[item.start:item.end].replace("\ufeff", "").strip()
                            for item in manifest.spans if item.required))

    def test_equal_source_passages_remain_distinct_occurrences(self):
        source = "same fact " * 1000
        manifest = self.records.build_manifest(source)
        self.assertGreater(len(manifest.required_ids), 1)
        self.assertEqual(len(manifest.required_ids), len(set(manifest.required_ids)))

    def test_empty_whitespace_and_invalid_encoding_fail(self):
        for source in ("", " \n\t", "\ufeff", "\ud800"):
            with self.subTest(value_type=type(source).__name__), self.assertRaises(ValueError):
                self.records.build_manifest(source)

    def test_missing_duplicate_reordered_or_altered_spans_fail(self):
        source = "valid source " * 200
        manifest = self.records.build_manifest(source)
        variants = (manifest.spans[:-1], manifest.spans + (manifest.spans[-1],),
                    tuple(reversed(manifest.spans)),
                    (replace(manifest.spans[0], end=manifest.spans[0].end-1),) + manifest.spans[1:])
        for spans in variants:
            with self.subTest(span_count=len(spans)), self.assertRaises(ValueError):
                replace(manifest, spans=spans).validate(source)

    def test_source_span_hard_limit_fails_without_skipping_tail(self):
        with patch.object(self.records, "MAX_SOURCE_SPANS", 2), self.assertRaises(ValueError):
            self.records.build_manifest("x" * 2000)


class ComprehensiveContracts(OfflineCase):
    def setUp(self):
        super().setUp()
        self.core = self.app("src.core.comprehensive_generation")
        self.validation = self.app("src.utils.generation_validation")
        self.records = self.app("src.utils.source_manifest")
        self.source = "FIRST\n" + "f" * 12000 + "\nMIDDLE\n" + "m" * 12000 + "\nFINAL"
        self.model = Mock(return_value=self.result("compact validated notes"))
        self.query = "Create ordered study notes."

    def result(self, text, status="STOP"):
        return True, self.validation.validate_generation_text(text, status), "synthetic"

    def generate(self, **kwargs):
        return self.core.generate_comprehensive(self.source, self.query, self.model, **kwargs)[0]

    def test_import_has_no_provider_or_ui_initialization(self):
        sys.modules["google.genai"].Client.assert_not_called()
        sys.modules["openai"].OpenAI.assert_not_called()

    def test_ordered_first_middle_final_and_all_required_source_are_delivered_once(self):
        result = self.generate()
        manifest = result.coverage.manifest
        rows = [row for call in self.model.call_args_list for row in source_records(call.args[0])]
        self.assertEqual(tuple(row["id"] for row in rows), manifest.required_ids)
        for row in rows:
            self.assertEqual(row["text"], self.source[row["start"]:row["end"]])
        self.assertEqual("".join(row["text"] for row in rows), self.source)
        self.assertEqual(result.coverage.status, "complete")
        self.assertEqual(result.completion_status, self.validation.REPORTED_FINISHED)
        self.records.validate_coverage(result, self.source)

    def test_every_prompt_and_output_reservation_obeys_the_request_budget(self):
        result = self.generate()
        for call in self.model.call_args_list:
            self.assertLessEqual(len(call.args[0].encode()), result.coverage.prompt_limit)
            self.assertLessEqual(len(call.args[0].encode()) + result.coverage.output_reserve_bytes,
                                 result.coverage.prompt_limit + result.coverage.output_reserve_bytes)
        self.assertEqual(len(result.coverage.requests), self.model.call_count)

    def test_short_source_uses_one_full_source_call_with_reversible_delimiters(self):
        self.source = "Source explains <user_content> and </user_content> plus α < β & γ."
        result = self.generate()
        self.model.assert_called_once()
        prompt = self.model.call_args.args[0]
        body = prompt.split("\n<user_content>\n",1)[1].split("\n</user_content>\n",1)[0]
        self.assertEqual(html.unescape(body), self.source)
        self.assertEqual(result.coverage.requests[0].stage, "direct")

    def test_long_source_uses_no_retrieval_or_embedding_dependencies(self):
        self.generate()
        sys.modules["chromadb"].EphemeralClient.assert_not_called()
        sys.modules["chromadb"].PersistentClient.assert_not_called()
        sys.modules["google.genai"].Client.assert_not_called()
        self.assertGreater(self.model.call_count, 1)

    def test_long_instruction_or_minimum_unit_failure_occurs_before_calls(self):
        self.query = "q" * 9000
        with self.assertRaises(ValueError):
            self.generate()
        self.model.assert_not_called()

    def test_any_required_source_batch_failure_aborts_before_final(self):
        self.model.side_effect = [self.result("first"), (False,"synthetic failure","None")]
        with self.assertRaises(ValueError):
            self.generate()
        self.assertEqual(self.model.call_count, 2)
        self.assertFalse(any(call.args[0].startswith("Produce a cohesive final") for call in self.model.call_args_list))

    def test_invalid_and_truncated_intermediate_output_cannot_complete(self):
        for payload in (None, " ", {}, self.validation.GenerationText("cut off","incomplete")):
            with self.subTest(payload_type=type(payload).__name__):
                self.model.return_value = (True,payload,"synthetic")
                self.model.reset_mock()
                with self.assertRaises(ValueError):
                    self.generate()
                self.model.assert_called_once()

    def test_overlong_intermediate_is_rejected_without_truncation(self):
        self.model.return_value = self.result("x" * 4000)
        with self.assertRaises(ValueError):
            self.generate()
        self.assertEqual(self.model.return_value[1], "x" * 4000)
        self.model.assert_called_once()

    def test_invalid_or_truncated_final_response_aborts(self):
        def call(prompt):
            if prompt.startswith("Produce a cohesive final"):
                return True,self.validation.GenerationText("unfinished","incomplete"),"synthetic"
            return self.result("intermediate notes")
        self.model.side_effect = call
        with self.assertRaises(ValueError):
            self.generate()
        self.assertTrue(self.model.call_args.args[0].startswith("Produce a cohesive final"))

    def test_missing_metadata_is_independent_of_complete_source_delivery(self):
        self.model.return_value = (True,"usable notes","synthetic")
        result = self.generate()
        self.assertEqual(result.completion_status, self.validation.UNKNOWN)
        self.assertEqual(result.coverage.status, "complete")

    def test_unknown_intermediate_cannot_be_upgraded_by_finished_final(self):
        self.model.side_effect = lambda prompt: (self.result("final") if prompt.startswith("Produce a cohesive final")
                                               else (True,"usable intermediate","synthetic"))
        result = self.generate()
        self.assertEqual(result.completion_status, self.validation.UNKNOWN)
        self.assertEqual(result.coverage.requests[-1].completion_status, self.validation.REPORTED_FINISHED)

    def test_hierarchical_synthesis_keeps_all_ancestry_without_dropping_notes(self):
        self.source = "synthetic section " * 9000
        self.model.side_effect = lambda prompt: self.result("final notes" if prompt.startswith("Produce a cohesive final") else "n" * 1500)
        result = self.generate()
        self.assertGreater(result.coverage.synthesis_rounds, 1)
        self.assertLessEqual(result.coverage.synthesis_rounds, 6)
        result.coverage.validate(self.source)
        self.assertLessEqual(result.coverage.provider_call_upper_bound, 384)

    def test_synthesis_round_limit_fails_instead_of_dropping_nodes(self):
        self.source = "synthetic section " * 9000
        self.model.return_value = self.result("n" * 1500)
        with self.assertRaises(ValueError):
            self.generate(limits=replace(self.core.GenerationLimits(), max_synthesis_rounds=1))
        self.assertFalse(any(call.args[0].startswith("Produce a cohesive final") for call in self.model.call_args_list))

    def test_runtime_model_call_limit_blocks_additional_synthesis(self):
        self.source = "synthetic section " * 9000
        self.model.return_value = self.result("n" * 1500)
        full = self.generate()
        source_calls = sum(item.stage == "source" for item in full.coverage.requests)
        self.model.reset_mock()
        limit = source_calls + 1
        with self.assertRaises(ValueError):
            self.generate(limits=replace(self.core.GenerationLimits(), max_model_calls=limit))
        self.assertEqual(self.model.call_count, limit)
        self.assertFalse(self.model.call_args.args[0].startswith("Produce a cohesive final"))

    def test_runtime_provider_budget_reserves_each_cascade_before_invocation(self):
        self.source = "synthetic section " * 9000
        self.model.return_value = self.result("n" * 1500)
        full = self.generate()
        source_calls = sum(item.stage == "source" for item in full.coverage.requests)
        self.model.reset_mock()
        provider_limit = 3 * (source_calls + 1)
        with self.assertRaises(ValueError):
            self.generate(limits=replace(self.core.GenerationLimits(), max_provider_calls=provider_limit))
        self.assertEqual(self.model.call_count * 3, provider_limit)

    def test_whitespace_gaps_are_accounted_without_empty_batch_calls(self):
        self.source = "FIRST\n" + " \t\n" * 6000 + "FINAL"
        result = self.generate()
        rows = [row for call in self.model.call_args_list for row in source_records(call.args[0])]
        self.assertEqual(tuple(row["id"] for row in rows), result.coverage.manifest.required_ids)
        self.assertTrue(all(row["text"].strip() for row in rows))
        self.assertEqual(sum(span.end-span.start for span in result.coverage.manifest.spans),len(self.source))

    def test_minimum_encoded_section_overflow_is_rejected_before_calls(self):
        self.source = "<" * 4000
        with self.assertRaises(ValueError):
            self.generate(limits=replace(self.core.GenerationLimits(), request_bytes=8992))
        self.model.assert_not_called()

    def test_long_literal_delimiters_are_preserved_by_json_transport(self):
        self.source = "<user_content>α & β</user_content>\n" * 500
        result = self.generate()
        rows = [row for call in self.model.call_args_list for row in source_records(call.args[0])]
        self.assertEqual("".join(row["text"] for row in rows), self.source)
        result.coverage.validate(self.source)

    def test_oversized_final_output_is_rejected_despite_normal_finish_status(self):
        self.model.side_effect = lambda prompt: self.result("x" * 9000 if prompt.startswith("Produce a cohesive final") else "notes")
        with self.assertRaises(ValueError):
            self.generate()
        self.assertTrue(self.model.call_args.args[0].startswith("Produce a cohesive final"))

    def test_source_batch_limit_is_checked_before_calls(self):
        with self.assertRaises(ValueError):
            self.generate(limits=replace(self.core.GenerationLimits(), max_source_batches=1))
        self.model.assert_not_called()

    def test_model_and_provider_call_minimum_limits_fail_before_calls(self):
        for limits in (replace(self.core.GenerationLimits(), max_model_calls=1),
                       replace(self.core.GenerationLimits(), max_provider_calls=3)):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                self.generate(limits=limits)
        self.model.assert_not_called()

    def test_hard_limits_cannot_be_raised_by_configuration(self):
        for field,value in (("max_model_calls",129),("max_provider_calls",385),
                            ("max_source_batches",65),("max_synthesis_rounds",7)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.generate(limits=replace(self.core.GenerationLimits(), **{field:value}))
        self.model.assert_not_called()

    def test_request_and_output_byte_limits_cannot_be_raised_by_configuration(self):
        for limits in (replace(self.core.GenerationLimits(),request_bytes=16385),
                       replace(self.core.GenerationLimits(),output_reserve_bytes=8193)):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                self.generate(limits=limits)
        self.model.assert_not_called()

    def test_missing_duplicate_out_of_order_or_changed_intermediates_fail(self):
        nodes = [self.core.Intermediate("one",("S000000",),"first",self.records.digest("first")),
                 self.core.Intermediate("two",("S000001",),"second",self.records.digest("second"))]
        self.core.check_intermediates(nodes,("S000000","S000001"))
        variants = [nodes[:1],nodes+[nodes[0]],list(reversed(nodes)),[replace(nodes[0],text="changed"),nodes[1]]]
        for items in variants:
            with self.subTest(count=len(items)), self.assertRaises(ValueError):
                self.core.check_intermediates(items,("S000000","S000001"))

    def test_coverage_graph_rejects_missing_duplicate_and_reordered_results(self):
        result = self.generate()
        report = result.coverage
        variants = (report.requests[:-1], report.requests+(report.requests[-1],),
                    tuple(reversed(report.requests)))
        for requests in variants:
            with self.subTest(length=len(requests)), self.assertRaises(ValueError):
                replace(report,requests=requests).validate(self.source)

    def test_final_notes_content_is_bound_to_its_validated_output_hash(self):
        result = self.generate()
        altered = self.validation.GenerationText("different final notes",result.completion_status)
        altered.coverage = result.coverage
        with self.assertRaises(ValueError):
            self.records.validate_coverage(altered,self.source)

    def test_versioned_record_round_trip_retains_manifest_and_completion_separately(self):
        result = self.generate()
        encoded = self.records.dump_notes(result,self.source)
        decoded = self.records.load_notes(encoded,self.source)
        self.assertEqual(decoded,result)
        self.assertEqual(decoded.coverage,result.coverage)
        self.assertEqual(decoded.completion_status,result.completion_status)
        self.assertEqual(self.records.load_notes("historical notes",self.source),"historical notes")

    def test_saved_record_rejects_wrong_source_or_incomplete_graph(self):
        result = self.generate()
        encoded = self.records.dump_notes(result,self.source)
        with self.assertRaises(ValueError):
            self.records.load_notes(encoded,self.source+"changed")
        raw = json.loads(encoded[len(self.records.RECORD_PREFIX):])
        raw["coverage"]["requests"].pop()
        with self.assertRaises(ValueError):
            self.records.load_notes(self.records.RECORD_PREFIX+json.dumps(raw),self.source)

    def test_existing_provider_fallback_executes_for_each_required_call(self):
        llm = self.app("src.core.llm_client")
        first,second,third = Mock(),Mock(),Mock()
        first.models.generate_content.side_effect = RuntimeError("synthetic primary outage")
        second.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="valid fallback notes"),finish_reason="stop")])
        with patch.object(llm,"gemini_client",first),patch.object(llm,"groq_client",second),patch.object(llm,"hf_client",third):
            result,_ = self.core.generate_comprehensive(self.source,self.query,llm.generate_content)
        self.assertEqual(first.models.generate_content.call_count,len(result.coverage.requests))
        self.assertEqual(second.chat.completions.create.call_count,len(result.coverage.requests))
        third.chat.completions.create.assert_not_called()
        self.assertLessEqual(first.models.generate_content.call_count+second.chat.completions.create.call_count,
                             result.coverage.provider_call_upper_bound)
        for primary,fallback in zip(first.models.generate_content.call_args_list,second.chat.completions.create.call_args_list):
            self.assertEqual(primary.kwargs["contents"],fallback.kwargs["messages"][0]["content"])


class ComprehensivePersistenceContracts(UploadUIFixtures):
    def setUp(self):
        super().setUp()
        self.records = self.app("src.utils.source_manifest")
        self.validation = self.app("src.utils.generation_validation")
        self.router.side_effect = self.app("src.core.pipeline_router").route_and_process
        self.model = self.stack.enter_context(patch.object(self.ui,"generate_content",
            return_value=(True,self.validation.validate_generation_text("valid generated notes","STOP"),"synthetic")))
        self.stack.enter_context(patch.object(self.ui,"initialize_chat",return_value=object()))
        self.save = self.stack.enter_context(patch.object(self.ui.database,"create_session",return_value=SESSION_A))
        self.st.file_uploader.return_value = [upload("long.txt",b"meaningful selected source " * 1000)]
        self.st.button.return_value = True

    def test_complete_guide_is_saved_with_recoverable_source_manifest(self):
        self.render()
        self.save.assert_called_once()
        source = self.save.call_args.args[2]
        notes = self.records.load_notes(self.save.call_args.args[3],source)
        self.assertEqual(notes.coverage.status,"complete")
        notes.coverage.validate(source)
        state = self.app("src.utils.document_state")
        state.restore_saved_session(self.st.session_state,dict(user_id=USER_A,id=SESSION_A,
            filename="long.txt",pdf_text=source,notes=self.save.call_args.args[3],chat_history=[]),USER_A)
        self.assertEqual(self.st.session_state.notes,"valid generated notes")
        self.assertEqual(self.st.session_state.notes.coverage,notes.coverage)

    def test_partial_batch_failure_is_not_saved_or_displayed_as_complete_notes(self):
        self.model.side_effect=[(True,"first intermediate","synthetic"),(False,"synthetic failure","None")]
        self.render()
        self.save.assert_not_called()
        self.assertIsNone(self.st.session_state.notes)
        self.st.error.assert_called()

    def test_success_shaped_text_without_coverage_cannot_be_saved(self):
        self.router.side_effect = None
        self.router.return_value = (True,"plausible but unverified notes","synthetic","batch")
        self.render()
        self.save.assert_not_called()
        self.assertIsNone(self.st.session_state.notes)

    def test_wrong_source_coverage_cannot_authorize_persistence(self):
        core = self.app("src.core.comprehensive_generation")
        other,_ = core.generate_comprehensive("another source","notes",lambda prompt:(True,"notes","synthetic"))
        self.router.side_effect = None
        self.router.return_value = (True,other,"synthetic","direct")
        self.render()
        self.save.assert_not_called()
        self.assertIsNone(self.st.session_state.notes)
