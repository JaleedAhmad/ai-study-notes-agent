"""Batch 6B-1: actual validation/adapters/eligibility with synthetic responses."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from offline.fake_database import SESSION_A
from offline.support import OfflineCase
from offline.test_extraction import UploadUIFixtures, upload


def gemini(text="valid notes", finish="STOP", **fields):
    return SimpleNamespace(text=text, candidates=[SimpleNamespace(finish_reason=finish)], **fields)


def compatible(text="valid notes", finish="stop", **fields):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text),
                                                    finish_reason=finish)], **fields)


class GenerationValidationContracts(OfflineCase):
    def setUp(self):
        super().setUp()
        self.contract = self.app("src.utils.generation_validation")

    def test_import_does_not_initialize_providers_or_ui(self):
        sys.modules["google.genai"].Client.assert_not_called()
        sys.modules["openai"].OpenAI.assert_not_called()

    def test_none_empty_whitespace_binary_and_structures_are_rejected(self):
        for value in (None, "", " \t\n", "\ufeff", "\x00text", {}, [], 1, True):
            with self.subTest(value=value), self.assertRaises(self.contract.GenerationError):
                self.contract.validate_generation_text(value)

    def test_valid_short_unicode_and_error_discussion_remain_usable(self):
        for text in ("A", "α + β", "Study error handling: [Error: sample]", '{"topic":"errors"}'):
            with self.subTest(text=text):
                result = self.contract.validate_generation_text(text)
                self.assertEqual(result, text)
                self.assertEqual(result.completion_status, self.contract.UNKNOWN)

    def test_reserved_error_envelopes_are_not_notes(self):
        for text in ('[Error: quota exhausted]', '{"error":{"message":"failure"}}',
                     'All LLM generation endpoints are currently unreachable. Please try again later.'):
            with self.subTest(text=text), self.assertRaises(self.contract.GenerationError):
                self.contract.validate_generation_text(text)

    def test_missing_metadata_is_explicitly_unknown_not_reported_finished(self):
        result = self.contract.gemini_text(SimpleNamespace(text="valid notes"))
        self.assertEqual(result, "valid notes")
        self.assertEqual(result.completion_status, self.contract.UNKNOWN)
        other = self.contract.openai_text(SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="other notes"))]))
        self.assertEqual(other.completion_status, self.contract.UNKNOWN)

    def test_finish_enum_and_string_forms_are_recognized_without_length_guessing(self):
        for reason in ("STOP", "stop", "FinishReason.STOP", SimpleNamespace(name="STOP", value=1)):
            with self.subTest(reason=reason):
                result = self.contract.validate_generation_text("A", reason)
                self.assertEqual(result.completion_status, self.contract.REPORTED_FINISHED)
        self.assertEqual(self.contract.validate_generation_text("x" * 10000).completion_status,
                         self.contract.UNKNOWN)

    def test_explicit_incomplete_blocked_or_unknown_nonempty_reasons_fail_closed(self):
        for reason in ("MAX_TOKENS", "length", "SAFETY", "content_filter", "tool_calls", "OTHER", "new_status"):
            with self.subTest(reason=reason), self.assertRaises(self.contract.GenerationError):
                self.contract.validate_generation_text("nonempty text", reason)

    def test_invalid_completion_annotation_cannot_bypass_validation(self):
        value = self.contract.GenerationText("nonempty", "incomplete")
        with self.assertRaises(self.contract.GenerationError):
            self.contract.validate_generation_text(value)

    def test_json_round_trip_keeps_notes_and_loses_completion_certainty(self):
        value = self.contract.validate_generation_text("valid notes", "STOP")
        decoded = json.loads(json.dumps(value))
        self.assertEqual(decoded, "valid notes")
        self.assertEqual(self.contract.validate_generation_text(decoded).completion_status, self.contract.UNKNOWN)

    def test_gemini_error_block_or_malformed_candidates_fail(self):
        responses = [None, {"text":"not a response"}, gemini(error={"message":"private"}),
                     gemini(prompt_feedback=SimpleNamespace(block_reason="SAFETY")),
                     SimpleNamespace(text="notes", candidates=[]),
                     SimpleNamespace(text="notes", candidates=[object(), object()])]
        for response in responses:
            with self.subTest(response=type(response).__name__), self.assertRaises(self.contract.GenerationError):
                self.contract.gemini_text(response)

    def test_openai_error_status_refusal_or_invalid_choices_fail(self):
        refused = compatible()
        refused.choices[0].message.refusal = "private refusal"
        responses = [compatible(error={"message":"private"}), compatible(status="incomplete"),
                     compatible(status="in_progress"), refused,
                     SimpleNamespace(choices=[]), SimpleNamespace(choices="not choices")]
        for response in responses:
            with self.subTest(response=type(response).__name__), self.assertRaises(self.contract.GenerationError):
                self.contract.openai_text(response)

    def test_total_prompt_and_instruction_are_included_in_byte_budget(self):
        budget = self.contract.MAX_COMPREHENSIVE_PROMPT_BYTES
        overhead = len(self.contract.full_source_prompt("A", "q").encode()) - 1
        self.assertEqual(len(self.contract.comprehensive_prompt("a" * (budget-overhead), "q").encode()), budget)
        with self.assertRaises(self.contract.GenerationError):
            self.contract.comprehensive_prompt("a" * (budget-overhead+1), "q")
        with self.assertRaises(self.contract.GenerationError):
            self.contract.comprehensive_prompt("A", "q" * budget)

    def test_multibyte_source_cannot_bypass_byte_budget_using_small_character_count(self):
        text = "🧪" * (self.contract.MAX_COMPREHENSIVE_PROMPT_BYTES // 4)
        self.assertLess(len(text), self.contract.MAX_COMPREHENSIVE_PROMPT_BYTES)
        with self.assertRaises(self.contract.GenerationError):
            self.contract.comprehensive_prompt(text, "q")

    def test_invalid_source_instruction_and_encoding_have_safe_failures(self):
        for source, query in ((None,"q"), (" ","q"), ("valid",None), ("valid","\x00"), ("\ud800","q")):
            with self.subTest(source_type=type(source).__name__), self.assertRaises(self.contract.GenerationError):
                self.contract.comprehensive_prompt(source, query)


class ProviderValidationContracts(OfflineCase):
    def setUp(self):
        super().setUp()
        self.llm = self.app("src.core.llm_client")
        self.contract = self.app("src.utils.generation_validation")
        self.clients = [Mock(), Mock(), Mock()]
        for name, client in zip(("gemini_client","groq_client","hf_client"), self.clients):
            self.stack.enter_context(patch.object(self.llm, name, client))
        self.first = self.clients[0].models.generate_content
        self.second = self.clients[1].chat.completions.create
        self.third = self.clients[2].chat.completions.create
        self.first.side_effect = RuntimeError("synthetic outage")
        self.second.side_effect = RuntimeError("synthetic outage")
        self.third.side_effect = RuntimeError("synthetic outage")
        self.prompt = "source context and instruction"

    def test_error_response_advances_to_existing_fallback_with_exact_context(self):
        self.first.side_effect = None
        self.first.return_value = gemini(error={"message":"private details"})
        self.second.side_effect = None
        self.second.return_value = compatible("valid fallback")
        result = self.llm.generate_content(self.prompt)
        self.assertEqual(result[1], "valid fallback")
        self.assertEqual(result[1].completion_status, self.contract.REPORTED_FINISHED)
        self.assertEqual(self.second.call_args.kwargs["messages"], [{"role":"user","content":self.prompt}])
        self.third.assert_not_called()

    def test_explicit_truncation_falls_through_to_valid_later_provider(self):
        self.first.side_effect = None
        self.first.return_value = gemini("cut off", "MAX_TOKENS")
        self.second.side_effect = None
        self.second.return_value = compatible("valid fallback", "stop")
        self.assertEqual(self.llm.generate_content(self.prompt)[1], "valid fallback")

    def test_metadata_absence_is_not_falsely_promoted_to_verified_completion(self):
        self.first.side_effect = None
        self.first.return_value = SimpleNamespace(text="valid notes")
        result = self.llm.generate_content(self.prompt)
        self.assertIs(result[0], True)
        self.assertEqual(result[1].completion_status, self.contract.UNKNOWN)
        self.second.assert_not_called()

    def test_generation_caps_are_explicit_for_every_existing_provider(self):
        self.llm.generate_content(self.prompt)
        limit = self.contract.MAX_OUTPUT_TOKENS
        self.assertEqual(self.first.call_args.kwargs["config"], {"max_output_tokens":limit})
        self.assertEqual(self.second.call_args.kwargs["max_tokens"], limit)
        self.assertEqual(self.third.call_args.kwargs["max_tokens"], limit)

    def test_provider_exception_details_do_not_reach_runtime_logs(self):
        for call in (self.first,self.second,self.third):
            call.side_effect = RuntimeError("private-synthetic-detail")
        capture = io.StringIO()
        with redirect_stdout(capture), redirect_stderr(capture):
            self.assertIs(self.llm.generate_content(self.prompt)[0], False)
        self.assertNotIn("private-synthetic-detail", capture.getvalue())


class GenerationUIValidationContracts(UploadUIFixtures):
    def setUp(self):
        super().setUp()
        self.contract = self.app("src.utils.generation_validation")
        self.st.file_uploader.return_value = [upload("valid.txt", b"valid short source")]
        self.st.button.return_value = True
        self.chat = self.stack.enter_context(patch.object(self.ui, "initialize_chat", return_value=object()))
        self.save = self.stack.enter_context(patch.object(self.ui.database, "create_session", return_value=SESSION_A))
        self.router.return_value = (True, "valid notes", "offline", "direct")
        real_router = self.app("src.core.pipeline_router")
        self.router.side_effect = lambda **kwargs: real_router.route_and_process(
            kwargs["raw_text"], kwargs["query"], None,
            lambda prompt: self.router.return_value[:3])

    def test_valid_legacy_string_result_has_visible_unknown_completion_warning(self):
        self.render()
        self.save.assert_called_once()
        records = self.app("src.utils.source_manifest")
        saved_notes = records.load_notes(self.save.call_args.args[3], self.save.call_args.args[2])
        self.assertEqual(saved_notes.completion_status, self.contract.UNKNOWN)
        self.st.warning.assert_called_once()
        self.assertIn("unverified", self.st.warning.call_args.args[0])

    def test_reported_finished_result_remains_usable_without_unknown_warning(self):
        notes = self.contract.validate_generation_text("valid notes", "STOP")
        self.router.return_value = (True,notes,"offline","direct")
        self.render()
        self.save.assert_called_once()
        self.st.warning.assert_not_called()

    def test_success_boolean_cannot_authorize_invalid_payload_or_status(self):
        for value in (None,{},"[Error: synthetic failure]",self.contract.GenerationText("cut off","incomplete")):
            with self.subTest(value_type=type(value).__name__):
                self.router.return_value=(True,value,"offline","direct")
                self.render()
        self.save.assert_not_called()
        self.chat.assert_not_called()
        self.assertIsNone(self.st.session_state.notes)

    def test_truthy_nonboolean_success_is_not_accepted(self):
        self.router.return_value=(1,"valid text","offline","direct")
        self.render()
        self.save.assert_not_called()
        self.assertIsNone(self.st.session_state.notes)

    def test_long_source_without_coverage_is_blocked_even_if_router_claims_success(self):
        self.st.file_uploader.return_value=[upload("large.txt", b"x" * 10000)]
        self.router.side_effect = None
        self.render()
        self.router.assert_called_once()
        self.save.assert_not_called()
        self.chat.assert_not_called()
        self.assertTrue(any("coverage" in call.args[0] for call in self.st.error.call_args_list))

    def test_failed_regeneration_does_not_redisplay_previous_notes_or_exports(self):
        self.st.button.return_value=False
        self.render()
        token=self.st.session_state.ready_source
        self.st.session_state.update(notes="previous notes",notes_source=token,podcast_bytes=b"old",anki_bytes=b"old")
        self.st.button.return_value=True
        self.router.return_value=(False,"private provider message","offline","direct")
        self.render()
        self.assertIsNone(self.st.session_state.notes)
        self.assertIsNone(self.st.session_state.podcast_bytes)
        self.assertIsNone(self.st.session_state.anki_bytes)
        self.save.assert_not_called()
        self.assertNotIn("private provider message",str(self.st.error.call_args_list))
