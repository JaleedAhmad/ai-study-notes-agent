"""Batches 5A/5B-1/5B-2: real processing code with synthetic dependency outputs.

Parser/renderer fakes do not validate file formats or improve source coverage.
Ordinary failing assertions preserve scheduled, unresolved correctness contracts.
"""

from contextlib import nullcontext, redirect_stdout, redirect_stderr
import io
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from offline.fake_database import USER_A, SESSION_A
from offline.support import OfflineCase
from offline.fake_vectors import MemoryCollection


def upload(name, data=b"synthetic fixture"):
    value = io.BytesIO(data)
    value.name = name
    return value


class ImageFixture:
    """Not a real image/codec. Only interface operations used by production OCR."""

    def __init__(self, text="synthetic image text", mode="RGB"):
        self.text, self.mode = text, mode

    def convert(self, mode):
        return ImageFixture(self.text, mode)

    def save(self, buffer, format):
        buffer.write(b"synthetic-image-not-a-real-jpeg")


class ExtractionFixtures(OfflineCase):
    def setUp(self):
        super().setUp()
        self.extractor = self.app("src.utils.extractor")
        self.vision = self.app("src.core.vision_client")

    def pdf(self, texts, images=None):
        pages = [SimpleNamespace(extract_text=Mock(side_effect=value) if isinstance(value, Exception)
                                 else Mock(return_value=value)) for value in texts]
        reader = self.stack.enter_context(patch.object(
            self.extractor, "PdfReader", return_value=SimpleNamespace(pages=pages)))
        images = images if images is not None else [ImageFixture() for _ in texts]

        def render(data, **kwargs):
            # Honor requested page ranges without selecting/fixing missing pages
            # on behalf of production. No Poppler process or real rasterization.
            start = kwargs.get("first_page", 1) - 1
            stop = kwargs.get("last_page", len(images))
            return images[start:stop]

        renderer = self.stack.enter_context(patch.object(
            self.extractor, "convert_from_bytes", side_effect=render))
        return reader, renderer

    def ocr_text(self):
        return self.stack.enter_context(patch.object(
            self.extractor, "extract_text_from_image", side_effect=lambda image: image.text))

    def providers(self, gemini=None, groq="synthetic fallback OCR"):
        if gemini is None:
            gemini = RuntimeError("synthetic Gemini outage")
        primary = Mock(side_effect=gemini) if isinstance(gemini, Exception) else Mock(
            return_value=SimpleNamespace(text=gemini))
        secondary = Mock(side_effect=groq) if isinstance(groq, Exception) else Mock(
            return_value=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=groq))]))
        self.stack.enter_context(patch.object(self.vision.gemini_client.models,
                                              "generate_content", primary))
        self.stack.enter_context(patch.object(self.vision.groq_client.chat.completions,
                                              "create", secondary))
        return primary, secondary


class ExtractorContracts(ExtractionFixtures):
    def test_short_documents_preserve_valid_text(self):
        self.assertEqual(self.extractor.extract_universal_text(upload("one.txt", b"A")), "A")
        with patch.object(self.extractor.docx, "Document", return_value=SimpleNamespace(
                paragraphs=[SimpleNamespace(text="B")])):
            self.assertEqual(self.extractor.extract_universal_text(upload("one.docx")), "B\n")
        slide = SimpleNamespace(shapes=[SimpleNamespace(has_text_frame=True, text="C")])
        with patch.object(self.extractor.pptx, "Presentation", return_value=SimpleNamespace(slides=[slide])):
            self.assertEqual(self.extractor.extract_universal_text(upload("one.pptx")), "C\n")

    def test_short_ocr_page_has_real_newlines_and_valid_content(self):
        self.pdf([None], [ImageFixture("A")])
        self.ocr_text()
        text = self.extractor.extract_universal_text(upload("one.pdf"))
        self.assertIn("\n--- Page 1 ---\nA\n", text)
        self.assertNotIn("\\n", text)

    def test_text_stream_is_preserved_and_nontext_read_is_rejected(self):
        source = io.StringIO("short stream")
        source.name = "stream.txt"
        self.assertEqual(self.extractor.extract_universal_text(source), "short stream")
        validation = self.app("src.utils.extraction_validation")
        source = SimpleNamespace(name="bad.txt", read=lambda: None)
        with self.assertRaises(validation.ExtractionError):
            self.extractor.extract_universal_text(source)

    def test_parser_details_are_private_but_cause_is_preserved(self):
        validation = self.app("src.utils.extraction_validation")
        cause = ValueError("synthetic-private-parser-detail")
        with patch.object(self.extractor, "PdfReader", side_effect=cause):
            with self.assertRaises(validation.ExtractionError) as caught:
                self.extractor.extract_universal_text(upload("bad.pdf"))
        self.assertNotIn("synthetic-private-parser-detail", str(caught.exception))
        self.assertIs(caught.exception.__cause__, cause)

    def test_valid_utf8_text_and_cursor_rewind(self):
        source = upload("synthetic.TXT", "Synthetic equations: α + β".encode())
        source.seek(10)
        self.assertEqual(self.extractor.extract_universal_text(source), "Synthetic equations: α + β")

    def test_valid_markdown_is_preserved(self):
        self.assertEqual(self.extractor.extract_universal_text(
            upload("synthetic.md", b"# Topic\n\nSynthetic details")), "# Topic\n\nSynthetic details")

    def test_valid_text_can_contain_error_messages(self):
        text = "Lecture about handling errors: [Error: Vision extraction failed.]"
        self.assertEqual(self.extractor.extract_universal_text(
            upload("errors.txt", text.encode())), text)

    def test_valid_native_pdf_does_not_require_ocr(self):
        text = "Synthetic native PDF study content. " * 4
        _, renderer = self.pdf([text])
        self.assertIn(text, self.extractor.extract_universal_text(upload("native.pdf")))
        renderer.assert_not_called()

    def test_image_only_pdf_uses_requested_ocr_pages(self):
        _, renderer = self.pdf([None, None], [ImageFixture("first page"), ImageFixture("second page")])
        ocr = self.ocr_text()
        text = self.extractor.extract_universal_text(upload("scan.pdf"))
        self.assertIn("first page", text)
        self.assertIn("second page", text)
        self.assertEqual(ocr.call_count, 2)
        self.assertEqual(renderer.call_count, 2)
        self.assertEqual([(call.kwargs["first_page"], call.kwargs["last_page"])
                          for call in renderer.call_args_list], [(1, 1), (2, 2)])

    def test_valid_docx_paragraphs_are_preserved(self):
        with patch.object(self.extractor.docx, "Document", return_value=SimpleNamespace(
                paragraphs=[SimpleNamespace(text="Synthetic DOCX paragraph")])):
            self.assertIn("Synthetic DOCX paragraph", self.extractor.extract_universal_text(upload("a.docx")))

    def test_valid_pptx_text_frames_are_preserved(self):
        slide = SimpleNamespace(shapes=[SimpleNamespace(has_text_frame=True, text="Synthetic slide")])
        with patch.object(self.extractor.pptx, "Presentation", return_value=SimpleNamespace(slides=[slide])):
            self.assertIn("Synthetic slide", self.extractor.extract_universal_text(upload("a.pptx")))

    def test_valid_image_is_converted_and_sent_to_ocr(self):
        with patch.object(self.extractor.Image, "open", return_value=ImageFixture("handwritten sample", "L")):
            ocr = self.ocr_text()
            self.assertEqual(self.extractor.extract_universal_text(upload("a.jpeg")), "handwritten sample")
        self.assertEqual(ocr.call_args.args[0].mode, "RGB")

    def test_zero_page_pdf_is_explicitly_rejected(self):
        self.pdf([])
        with self.assertRaises(ValueError, msg="EXTRACT-01: zero-page PDF returned success-shaped empty text"):
            self.extractor.extract_universal_text(upload("zero.pdf"))

    def test_empty_text_is_explicitly_rejected(self):
        with self.assertRaises(ValueError, msg="EXTRACT-02: empty text has no failure signal"):
            self.extractor.extract_universal_text(upload("empty.txt", b""))

    def test_whitespace_text_is_explicitly_rejected(self):
        with self.assertRaises(ValueError, msg="EXTRACT-03: whitespace is not study material"):
            self.extractor.extract_universal_text(upload("blank.txt", b" \t\r\n "))

    def test_unsupported_file_is_explicitly_rejected(self):
        with self.assertRaises(ValueError, msg="EXTRACT-04: unsupported suffix silently returned empty text"):
            self.extractor.extract_universal_text(upload("unsupported.bin"))

    def test_malformed_pdf_error_reaches_caller(self):
        with patch.object(self.extractor, "PdfReader", side_effect=ValueError("synthetic corrupt PDF")):
            with self.assertRaises(ValueError, msg="EXTRACT-05: PDF parser error was swallowed"):
                self.extractor.extract_universal_text(upload("bad.pdf"))

    def test_malformed_docx_error_reaches_caller(self):
        with patch.object(self.extractor.docx, "Document", side_effect=ValueError("synthetic bad DOCX")):
            with self.assertRaises(ValueError, msg="EXTRACT-06: DOCX parser error was swallowed"):
                self.extractor.extract_universal_text(upload("bad.docx"))

    def test_malformed_pptx_error_reaches_caller(self):
        with patch.object(self.extractor.pptx, "Presentation", side_effect=ValueError("synthetic bad PPTX")):
            with self.assertRaises(ValueError, msg="EXTRACT-07: PPTX parser error was swallowed"):
                self.extractor.extract_universal_text(upload("bad.pptx"))

    def test_malformed_image_error_reaches_caller(self):
        with patch.object(self.extractor.Image, "open", side_effect=ValueError("synthetic bad image")):
            with self.assertRaises(ValueError, msg="EXTRACT-08: image parser error was swallowed"):
                self.extractor.extract_universal_text(upload("bad.png"))

    def test_whitespace_pdf_and_no_rendered_pages_is_rejected(self):
        self.pdf([" \t\n"], [])
        with self.assertRaises(ValueError, msg="EXTRACT-09: unsuccessful PDF fallback looked successful"):
            self.extractor.extract_universal_text(upload("blank.pdf"))

    def test_table_only_docx_cannot_silently_succeed_empty(self):
        document = SimpleNamespace(paragraphs=[], tables=[SimpleNamespace(
            rows=[SimpleNamespace(cells=[SimpleNamespace(text="Synthetic table content")])])])
        with patch.object(self.extractor.docx, "Document", return_value=document):
            with self.assertRaises(ValueError, msg="EXTRACT-10: unsupported table-only content became empty success"):
                self.extractor.extract_universal_text(upload("table.docx"))

    def test_blank_pptx_is_explicitly_rejected(self):
        with patch.object(self.extractor.pptx, "Presentation", return_value=SimpleNamespace(slides=[])):
            with self.assertRaises(ValueError, msg="EXTRACT-11: blank slides have no failure signal"):
                self.extractor.extract_universal_text(upload("blank.pptx"))

    def test_invalid_utf8_is_not_silently_replaced(self):
        with self.assertRaises(ValueError, msg="EXTRACT-12: invalid UTF-8 was silently replaced"):
            self.extractor.extract_universal_text(upload("encoding.txt", b"synthetic \xff\xfe"))

    def test_binary_nul_text_is_not_valid_study_content(self):
        with self.assertRaises(ValueError, msg="EXTRACT-13: binary-looking text accepted by suffix alone"):
            self.extractor.extract_universal_text(upload("binary.txt", b"\x00\x01\x00synthetic"))

    def test_mixed_pdf_does_not_skip_image_page_due_to_average(self):
        native = "Native study material. " * 8
        self.pdf([native, None], [ImageFixture(native), ImageFixture("missing scanned page")])
        self.ocr_text()
        text = self.extractor.extract_universal_text(upload("mixed.pdf"))
        self.assertIn(native, text)
        self.assertIn("missing scanned page", text, "EXTRACT-14: whole-document average hid a scanned page")

    def test_partial_pdf_parser_failure_is_not_empty_success(self):
        self.pdf(["Valid first page " * 8, ValueError("synthetic second-page parser error")])
        with self.assertRaises(ValueError, msg="EXTRACT-15: partial PDF failure discarded text silently"):
            self.extractor.extract_universal_text(upload("partial.pdf"))

    def test_missing_rendered_page_is_not_complete_success(self):
        self.pdf([None, None], [ImageFixture("only first page")])
        self.ocr_text()
        with self.assertRaises(ValueError, msg="EXTRACT-16: renderer page-count mismatch was ignored"):
            self.extractor.extract_universal_text(upload("short-render.pdf"))

    def test_pdf_with_one_ocr_failure_is_not_complete_success(self):
        self.pdf([None, None], [ImageFixture(), ImageFixture()])
        primary, secondary = self.providers(groq=RuntimeError("synthetic Groq outage"))
        primary.side_effect = [SimpleNamespace(text="valid first page"), RuntimeError("synthetic second page outage")]
        with self.assertRaises(ValueError, msg="EXTRACT-17: failed OCR page became document text"):
            self.extractor.extract_universal_text(upload("partial-ocr.pdf"))


class PDFCoverageContracts(ExtractionFixtures):
    """Real per-page orchestration; synthetic parser, renderer and OCR outputs."""

    def structure(self, reader, index, *, contents=None, resources=None, annotations=None):
        page = reader.return_value.pages[index]
        page.get_contents = Mock(return_value=contents)
        metadata = {"/Resources": resources or {}, "/Annots": annotations}
        page.get = lambda key, default=None: metadata.get(key, default)
        return page

    def test_short_native_pages_do_not_trigger_ocr(self):
        _, renderer = self.pdf(["A", "Second short page"])
        ocr = self.ocr_text()
        result = self.extractor.extract_universal_text(upload("short.pdf"))
        self.assertLess(result.index("A"), result.index("Second short page"))
        renderer.assert_not_called()
        ocr.assert_not_called()

    def test_alternating_native_and_ocr_preserves_page_order(self):
        _, renderer = self.pdf(["native one", None, "native three", None],
                               [ImageFixture("unused"), ImageFixture("scan two"),
                                ImageFixture("unused"), ImageFixture("scan four")])
        ocr = self.ocr_text()
        result = self.extractor.extract_universal_text(upload("mixed.pdf"))
        offsets = [result.index(value) for value in ("native one", "scan two", "native three", "scan four")]
        self.assertEqual(offsets, sorted(offsets))
        self.assertNotIn("unused", result)
        self.assertEqual(ocr.call_count, 2)
        self.assertEqual([call.kwargs["first_page"] for call in renderer.call_args_list], [2, 4])

    def test_same_page_native_and_image_are_both_retained_without_exact_duplicate(self):
        reader, _ = self.pdf(["native line"], [ImageFixture("native line\nimage caption")])
        self.structure(reader, 0, contents=SimpleNamespace(operations=[]),
                       resources={"/XObject": {"/Im0": object()}})
        self.ocr_text()
        result = self.extractor.extract_universal_text(upload("mixed-page.pdf"))
        self.assertEqual(result.count("native line"), 1)
        self.assertIn("image caption", result)

    def test_native_text_is_not_replaced_by_differing_ocr(self):
        reader, _ = self.pdf(["Reliable native equation"], [ImageFixture("Image diagram transcription")])
        self.structure(reader, 0, annotations=[object()])
        self.ocr_text()
        result = self.extractor.extract_universal_text(upload("annotated.pdf"))
        self.assertIn("Reliable native equation", result)
        self.assertIn("Image diagram transcription", result)

    def test_inline_image_and_form_invocations_require_ocr(self):
        for operator in (b"INLINE IMAGE", b"Do", b"sh"):
            with self.subTest(operator=operator):
                reader, renderer = self.pdf(["native"], [ImageFixture("visual material")])
                self.structure(reader, 0, contents=SimpleNamespace(operations=[([], operator)]))
                ocr = self.ocr_text()
                result = self.extractor.extract_universal_text(upload("inline.pdf"))
                self.assertIn("visual material", result)
                renderer.assert_called_once()
                ocr.assert_called_once()

    def test_structurally_blank_pages_skip_ocr_and_keep_original_numbering(self):
        reader, renderer = self.pdf(["first", None, "third"])
        self.structure(reader, 1)
        ocr = self.ocr_text()
        result = self.extractor.extract_universal_text(upload("blank-between.pdf"))
        self.assertIn("--- Page 1 ---", result)
        self.assertIn("--- Page 3 ---", result)
        self.assertNotIn("--- Page 2 ---", result)
        renderer.assert_not_called()
        ocr.assert_not_called()

    def test_empty_operation_stream_is_structurally_blank(self):
        reader, renderer = self.pdf(["study", " "])
        self.structure(reader, 1, contents=SimpleNamespace(operations=[]))
        self.assertIn("study", self.extractor.extract_universal_text(upload("blank.pdf")))
        renderer.assert_not_called()

    def test_no_content_stream_with_image_resource_is_not_assumed_blank(self):
        reader, renderer = self.pdf([None], [ImageFixture("image text")])
        self.structure(reader, 0, resources={"/XObject": {"/Im0": object()}})
        self.ocr_text()
        self.assertIn("image text", self.extractor.extract_universal_text(upload("resource.pdf")))
        renderer.assert_called_once()

    def test_duplicate_ocr_does_not_remove_native_or_repeat_it(self):
        reader, _ = self.pdf(["first native line\nsecond native line"],
                             [ImageFixture("first native line\nsecond native line")])
        self.structure(reader, 0, annotations=[object()])
        self.ocr_text()
        result = self.extractor.extract_universal_text(upload("duplicate.pdf"))
        self.assertEqual(result.count("first native line"), 1)
        self.assertEqual(result.count("second native line"), 1)

    def test_all_structurally_blank_pages_rejected_as_no_study_content(self):
        reader, renderer = self.pdf([None, " "])
        self.structure(reader, 0)
        self.structure(reader, 1)
        with self.assertRaises(self.extractor.ExtractionError):
            self.extractor.extract_universal_text(upload("blank.pdf"))
        renderer.assert_not_called()

    def test_unknown_structure_is_not_assumed_blank(self):
        self.pdf([None], [ImageFixture(" ")])
        self.ocr_text()
        with self.assertRaises(self.extractor.ExtractionError):
            self.extractor.extract_universal_text(upload("unknown.pdf"))

    def test_painted_but_textless_page_requires_valid_ocr(self):
        reader, _ = self.pdf([None], [ImageFixture(" ")])
        self.structure(reader, 0, contents=SimpleNamespace(operations=[([], b"f")]))
        self.ocr_text()
        with self.assertRaises(self.extractor.ExtractionError):
            self.extractor.extract_universal_text(upload("painted.pdf"))

    def test_extra_render_is_rejected_not_appended(self):
        self.pdf([None])
        with patch.object(self.extractor, "convert_from_bytes", return_value=[ImageFixture(), ImageFixture()]):
            with self.assertRaises(self.extractor.ExtractionError):
                self.extractor.extract_universal_text(upload("extra-render.pdf"))

    def test_missing_image_page_does_not_return_prior_native_text_as_complete(self):
        self.pdf(["native first", None], [ImageFixture()])
        self.ocr_text()
        with self.assertRaises(self.extractor.ExtractionError):
            self.extractor.extract_universal_text(upload("missing.pdf"))

    def test_render_timeout_is_safe_page_failure(self):
        self.pdf(["native first", None])
        with patch.object(self.extractor, "convert_from_bytes", side_effect=RuntimeError("private-timeout-detail")):
            with self.assertRaises(self.extractor.ExtractionError) as caught:
                self.extractor.extract_universal_text(upload("timeout.pdf"))
        self.assertIn("page 2", str(caught.exception))
        self.assertNotIn("private-timeout-detail", str(caught.exception))

    def test_mixed_page_ocr_failure_rejects_even_with_native_text(self):
        reader, _ = self.pdf(["native text"], [ImageFixture(" ")])
        self.structure(reader, 0, resources={"/XObject": {"/Form": object()}})
        self.ocr_text()
        with self.assertRaises(self.extractor.ExtractionError):
            self.extractor.extract_universal_text(upload("partial.pdf"))

    def test_later_ocr_exception_rejects_document_and_closes_images(self):
        images = [ImageFixture(), ImageFixture()]
        for image in images:
            image.close = Mock()
        self.pdf([None, None], images)
        with patch.object(self.extractor, "extract_text_from_image", side_effect=["valid page", RuntimeError("private-ocr")]):
            with self.assertRaises(self.extractor.ExtractionError) as caught:
                self.extractor.extract_universal_text(upload("partial.pdf"))
        self.assertIn("page 2", str(caught.exception))
        self.assertNotIn("private-ocr", str(caught.exception))
        for image in images:
            image.close.assert_called_once()

    def test_render_bounds_and_release_apply_to_each_page(self):
        images = [ImageFixture("scan one"), ImageFixture("scan two")]
        for image in images:
            image.close = Mock()
        _, renderer = self.pdf([None, None], images)
        self.ocr_text()
        self.extractor.extract_universal_text(upload("bounded.pdf"))
        self.assertEqual(renderer.call_count, 2)
        for number, call in enumerate(renderer.call_args_list, 1):
            self.assertEqual(call.kwargs, dict(first_page=number, last_page=number,
                                             size=1600, thread_count=1, timeout=60))
            images[number - 1].close.assert_called_once()

    def test_invalid_native_response_fails_closed(self):
        self.pdf([{"not": "text"}])
        with self.assertRaises(self.extractor.ExtractionError):
            self.extractor.extract_universal_text(upload("invalid.pdf"))

    def test_structure_parser_failure_is_not_blank_success(self):
        reader, _ = self.pdf(["native"])
        page = self.structure(reader, 0)
        page.get_contents.side_effect = RuntimeError("private-structure-detail")
        with self.assertRaises(self.extractor.ExtractionError) as caught:
            self.extractor.extract_universal_text(upload("structure.pdf"))
        self.assertNotIn("private-structure-detail", str(caught.exception))


class VisionContracts(ExtractionFixtures):
    def test_ocr_transcription_can_discuss_an_error_envelope(self):
        text = "[Error: sample]\nStudy note: handle the failure with [retry]"
        _, secondary = self.providers(gemini=text)
        self.assertEqual(self.vision.extract_text_from_image(ImageFixture()), text)
        secondary.assert_not_called()

    def test_malformed_primary_structure_uses_valid_fallback(self):
        primary, secondary = self.providers(gemini="unused")
        primary.return_value = {"error": "synthetic provider error"}
        self.assertEqual(self.vision.extract_text_from_image(ImageFixture()), "synthetic fallback OCR")
        secondary.assert_called_once()

    def test_empty_secondary_choices_raise_typed_failure(self):
        validation = self.app("src.utils.extraction_validation")
        _, secondary = self.providers()
        secondary.return_value = SimpleNamespace(choices=[])
        with self.assertRaises(validation.ExtractionError):
            self.vision.extract_text_from_image(ImageFixture())

    def test_primary_whitespace_and_error_envelope_use_fallback(self):
        for value in (" \n\t ", "[Error: synthetic provider failure]", "\x00binary"):
            with self.subTest(value=value):
                _, secondary = self.providers(gemini=value)
                self.assertEqual(self.vision.extract_text_from_image(ImageFixture()), "synthetic fallback OCR")
                secondary.assert_called_once()

    def test_invalid_secondary_content_is_not_source(self):
        validation = self.app("src.utils.extraction_validation")
        for value in (None, 17, {}, [], "[Error: synthetic provider failure]"):
            with self.subTest(value=value):
                self.providers(groq=value)
                with self.assertRaises(validation.ExtractionError):
                    self.vision.extract_text_from_image(ImageFixture())

    def test_missing_provider_clients_raise_typed_failure(self):
        validation = self.app("src.utils.extraction_validation")
        with patch.object(self.vision, "gemini_client", None), patch.object(self.vision, "groq_client", None):
            with self.assertRaises(validation.ExtractionError):
                self.vision.extract_text_from_image(ImageFixture())

    def test_provider_exception_details_are_not_logged_or_returned(self):
        validation = self.app("src.utils.extraction_validation")
        self.providers(gemini=RuntimeError("synthetic-private-provider-detail"),
                       groq=RuntimeError("synthetic-private-provider-detail"))
        captured = io.StringIO()
        with redirect_stdout(captured), redirect_stderr(captured):
            with self.assertRaises(validation.ExtractionError) as caught:
                self.vision.extract_text_from_image(ImageFixture())
        self.assertNotIn("synthetic-private-provider-detail", captured.getvalue())
        self.assertNotIn("synthetic-private-provider-detail", str(caught.exception))

    def test_valid_gemini_ocr_stops_fallback(self):
        primary, secondary = self.providers(gemini="synthetic handwritten formula")
        self.assertEqual(self.vision.extract_text_from_image(ImageFixture()), "synthetic handwritten formula")
        primary.assert_called_once()
        secondary.assert_not_called()

    def test_gemini_exception_falls_back_to_valid_groq(self):
        primary, secondary = self.providers()
        self.assertEqual(self.vision.extract_text_from_image(ImageFixture()), "synthetic fallback OCR")
        self.assertEqual(primary.call_count, 1)
        self.assertEqual(secondary.call_count, 1)

    def test_total_ocr_failure_raises_instead_of_returning_source(self):
        self.providers(groq=RuntimeError("synthetic Groq outage"))
        with self.assertRaises(ValueError, msg="EXTRACT-18: total OCR failure returned an error string"):
            self.vision.extract_text_from_image(ImageFixture())

    def test_empty_primary_ocr_uses_valid_fallback(self):
        self.providers(gemini="")
        self.assertEqual(self.vision.extract_text_from_image(ImageFixture()), "synthetic fallback OCR",
                         "EXTRACT-19: empty primary response stopped fallback")

    def test_nonstring_primary_ocr_uses_valid_fallback(self):
        self.providers(gemini=17)
        self.assertEqual(self.vision.extract_text_from_image(ImageFixture()), "synthetic fallback OCR",
                         "EXTRACT-20: non-text primary response stopped fallback")

    def test_blank_fallback_ocr_is_rejected(self):
        self.providers(groq=" \n\t ")
        with self.assertRaises(ValueError, msg="EXTRACT-21: blank fallback response accepted"):
            self.vision.extract_text_from_image(ImageFixture())

    def test_image_extractor_does_not_return_ocr_error_as_content(self):
        self.providers(groq=RuntimeError("synthetic Groq outage"))
        with patch.object(self.extractor.Image, "open", return_value=ImageFixture()):
            with self.assertRaises(ValueError, msg="EXTRACT-22: OCR failure propagated as source text"):
                self.extractor.extract_universal_text(upload("handwritten.png"))


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class Stopped(BaseException):
    """Streamlit's stop/rerun control flow must escape ordinary except Exception."""


class UploadUIFixtures(ExtractionFixtures):
    def setUp(self):
        super().setUp()
        # Do not import unrelated exporter packages or trigger their dependencies.
        for module_name, function_name in (("src.exporters.pdf_exporter", "generate_pdf"),
                                            ("src.exporters.anki_exporter", "generate_anki_deck")):
            module = ModuleType(module_name)
            setattr(module, function_name, self.sandbox.blocked_call("unexpected export in ingestion test"))
            self.stack.enter_context(patch.dict(sys.modules, {module_name: module}))
        self.ui = self.app("src.ui.main_content")
        self.st = sys.modules["streamlit"]
        self.st.session_state = State(user_id=USER_A, current_file=None, current_session_id=None,
            pdf_text=None, notes=None, chat_session=None, chat_history=[], library_id=None,
            podcast_bytes=None, anki_bytes=None)
        self.st.file_uploader = Mock(return_value=[])
        self.st.button = Mock(return_value=False)
        self.st.spinner = Mock(side_effect=lambda *a, **k: nullcontext())
        self.st.stop = Mock(side_effect=Stopped)
        self.st.rerun = Mock(side_effect=Stopped)
        for name in ("title", "write", "success", "error", "warning", "progress", "empty"):
            setattr(self.st, name, Mock())
        self.vector_store = MemoryCollection()
        self.collection = Mock(wraps=self.vector_store)
        client = Mock()
        client.get_or_create_collection.return_value = self.collection
        self.stack.enter_context(patch.object(self.ui.rag, "get_chroma_client", return_value=client))
        # Transparent split, no implicit empty-content validation. Actual RAG skip
        # conditions and exception swallowing still execute.
        self.stack.enter_context(patch.object(self.ui.rag, "chunk_text", side_effect=lambda text: [text]))
        self.embedding = self.stack.enter_context(patch.object(
            self.ui.rag, "get_gemini_embedding", return_value=[0.1, 0.2]))
        self.index = self.stack.enter_context(patch.object(self.ui.rag, "embed_and_store_document",
                                                         wraps=self.ui.rag.embed_and_store_document))
        self.extract = self.stack.enter_context(patch.object(self.ui, "extract_universal_text",
                                                           wraps=self.extractor.extract_universal_text))
        self.router = self.stack.enter_context(patch.object(self.ui, "route_and_process",
            return_value=(False, "synthetic generation stopped", "offline", "offline")))
        self.real_notes_view = self.ui.render_notes_section
        self.real_podcast_view = self.ui.render_podcast_section
        self.notes_view = self.stack.enter_context(patch.object(self.ui, "render_notes_section"))
        self.stack.enter_context(patch.object(self.ui, "render_podcast_section"))
        self.real_chat_view = self.ui.render_chat_section
        self.stack.enter_context(patch.object(self.ui, "render_chat_section"))

    def render(self):
        try:
            self.ui.render_main_content(False, "Academic", "Summary", "Medium")
        except Stopped:
            pass


class UploadUIContracts(UploadUIFixtures):
    def test_header_only_extractor_output_is_rejected_before_indexing(self):
        self.st.file_uploader.return_value = [upload("fake.txt")]
        self.extract.return_value = "\n--- Document: fake.txt ---\n--- Page 1 ---\n"
        self.render()
        self.st.error.assert_called_once()
        self.index.assert_not_called()
        self.router.assert_not_called()
        self.st.success.assert_not_called()

    def test_cached_header_only_source_cannot_enable_generation(self):
        self.st.session_state.update(current_file=["same.txt"],
            pdf_text="\n--- Document: same.txt ---\n", library_id="cached")
        self.st.file_uploader.return_value = [upload("same.txt", b"synthetic replacement")]
        self.st.button.return_value = True
        self.render()
        # Unbound legacy cache is discarded; fresh valid bytes may be accepted.
        self.extract.assert_called_once()
        self.assertIn("synthetic replacement", self.router.call_args.kwargs["raw_text"])
        self.assertNotEqual(self.router.call_args.kwargs["raw_text"].strip(), "--- Document: same.txt ---")

    def test_parser_details_do_not_reach_ui_or_ingestion_logs(self):
        self.st.file_uploader.return_value = [upload("bad.pdf")]
        captured = io.StringIO()
        with patch.object(self.extractor, "PdfReader", side_effect=ValueError("synthetic-private-document-detail")), \
                redirect_stdout(captured), redirect_stderr(captured):
            self.render()
        self.st.error.assert_called_once()
        self.assertNotIn("synthetic-private-document-detail", str(self.st.error.call_args_list))
        self.assertNotIn("synthetic-private-document-detail", captured.getvalue())
        self.index.assert_not_called()

    def test_incomplete_pdf_shows_safe_page_failure_without_index_or_generation(self):
        self.pdf(["native first", None], [ImageFixture()])
        self.ocr_text()
        self.st.file_uploader.return_value = [upload("incomplete.pdf")]
        self.st.button.return_value = True
        self.render()
        self.st.error.assert_called_once()
        self.assertIn("PDF page 2", self.st.error.call_args.args[0])
        self.index.assert_not_called()
        self.router.assert_not_called()
        self.st.success.assert_not_called()
        self.assertIsNone(self.st.session_state.pdf_text)

    def test_complete_mixed_pdf_reaches_existing_index_boundary(self):
        self.pdf(["native first", None], [ImageFixture("unused"), ImageFixture("scan second")])
        self.ocr_text()
        self.st.file_uploader.return_value = [upload("complete.pdf")]
        self.render()
        self.index.assert_called_once()
        source = self.index.call_args.kwargs["pdf_text"]
        self.assertIn("native first", source)
        self.assertIn("scan second", source)
        self.assertLess(source.index("native first"), source.index("scan second"))
        self.st.error.assert_not_called()

    def test_valid_upload_extracts_indexes_and_reports_success(self):
        self.st.file_uploader.return_value = [upload("valid.txt", b"synthetic valid source")]
        self.render()
        self.assertIn("synthetic valid source", self.st.session_state.pdf_text)
        self.index.assert_called_once()
        self.collection.add.assert_called_once()
        self.st.success.assert_called_once()
        self.st.error.assert_not_called()

    def test_truly_raised_extraction_error_stops_existing_ui(self):
        self.st.file_uploader.return_value = [upload("bad.pdf")]
        self.extract.side_effect = ValueError("synthetic explicit extraction error")
        self.render()
        self.st.error.assert_called_once()
        self.index.assert_not_called()
        self.st.success.assert_not_called()
        self.router.assert_not_called()

    def test_empty_extraction_never_reaches_indexing(self):
        self.st.file_uploader.return_value = [upload("empty.txt", b"")]
        self.render()
        self.index.assert_not_called()  # EXTRACT-23

    def test_blank_extraction_does_not_report_library_success(self):
        self.st.file_uploader.return_value = [upload("blank.txt", b" \n\t")]
        self.render()
        self.collection.add.assert_not_called()  # Real RAG skips whitespace.
        self.st.success.assert_not_called()  # EXTRACT-24

    def test_failed_extraction_does_not_enable_generation(self):
        self.st.file_uploader.return_value = [upload("empty.txt", b"")]
        self.st.button.return_value = True
        self.render()
        self.router.assert_not_called()  # EXTRACT-25: filename headers are not source.

    def test_real_ocr_failure_does_not_become_an_indexed_document(self):
        self.providers(groq=RuntimeError("synthetic Groq outage"))
        self.st.file_uploader.return_value = [upload("scan.png")]
        with patch.object(self.extractor.Image, "open", return_value=ImageFixture()):
            self.render()
        self.collection.add.assert_not_called()  # EXTRACT-26: provider error is currently stored.

    def test_partially_extracted_upload_batch_is_not_reported_complete(self):
        self.st.file_uploader.return_value = [upload("good.txt", b"synthetic valid first file"), upload("bad.pdf")]
        with patch.object(self.extractor, "PdfReader", side_effect=ValueError("synthetic corrupt second file")):
            self.render()
        self.st.success.assert_not_called()  # EXTRACT-27

    def test_total_embedding_failure_is_not_reported_complete(self):
        self.st.file_uploader.return_value = [upload("valid.txt", b"synthetic valid source")]
        self.embedding.side_effect = RuntimeError("synthetic embedding outage")
        self.render()
        self.collection.add.assert_not_called()
        self.st.success.assert_not_called()  # EXTRACT-28: index receipt is missing.

    def test_index_failure_blocks_generation_and_leaves_source_unaccepted(self):
        self.st.file_uploader.return_value = [upload("valid.txt", b"synthetic valid source")]
        self.st.button.return_value = True
        self.embedding.side_effect = RuntimeError("synthetic provider failure")
        self.render()
        self.st.error.assert_called_once()
        self.assertIsNone(self.st.session_state.pdf_text)
        self.router.assert_not_called()
        self.st.success.assert_not_called()

    def test_index_receipt_is_required_before_success(self):
        self.st.file_uploader.return_value = [upload("valid.txt", b"synthetic valid source")]
        self.index.return_value = None
        self.st.button.return_value = True
        self.render()
        self.st.error.assert_called_once()
        self.router.assert_not_called()
        self.st.success.assert_not_called()
        self.assertIsNone(self.st.session_state.pdf_text)

    def test_receipt_for_different_document_cannot_enable_generation(self):
        self.st.file_uploader.return_value = [upload("valid.txt", b"synthetic valid source")]
        self.index.return_value = self.ui.rag.IndexReceipt(USER_A, "another-document", "revision", 1)
        self.st.button.return_value = True
        self.render()
        self.st.error.assert_called_once()
        self.router.assert_not_called()
        self.st.success.assert_not_called()
        self.assertIsNone(self.st.session_state.pdf_text)

    def test_silent_partial_index_write_blocks_generation(self):
        self.st.file_uploader.return_value = [upload("valid.txt", b"synthetic valid source")]
        self.st.button.return_value = True
        self.vector_store.write_limit = 1
        with patch.object(self.ui.rag, "chunk_text", return_value=["first", "second"]):
            self.render()
        self.assertEqual(self.vector_store.count(), 0)
        self.router.assert_not_called()
        self.st.success.assert_not_called()
        self.st.error.assert_called_once()

    def test_multi_file_retry_reuses_verified_first_index_and_finishes_second(self):
        self.st.file_uploader.return_value = [upload("first.txt", b"first source"),
                                               upload("second.txt", b"second source")]
        self.embedding.side_effect = [[0.1, 0.2], RuntimeError("synthetic second-file failure")]
        self.render()
        self.assertEqual(self.vector_store.count(), 1)
        self.assertIsNone(self.st.session_state.pdf_text)
        self.st.success.assert_not_called()
        self.embedding.side_effect = None
        self.embedding.reset_mock()
        self.render()
        self.embedding.assert_called_once_with("second source")
        self.assertEqual(self.vector_store.count(), 2)
        self.assertIn("first source", self.st.session_state.pdf_text)
        self.assertIn("second source", self.st.session_state.pdf_text)
        self.st.success.assert_called_once()

    def test_same_filename_replacement_does_not_reuse_stale_text(self):
        self.st.session_state.update(current_file=["same.txt"], pdf_text="synthetic old source", library_id="old")
        self.st.file_uploader.return_value = [upload("same.txt", b"synthetic replacement source")]
        self.render()
        self.assertIn("synthetic replacement source", self.st.session_state.pdf_text,
                      "EXTRACT-29: filename equality incorrectly reused old extraction")

    def test_changed_filename_without_saved_session_reextracts(self):
        self.st.session_state.update(current_file=["old.txt"], pdf_text="synthetic old source", notes="old notes")
        self.st.file_uploader.return_value = [upload("new.txt", b"synthetic new source")]
        self.render()
        self.extract.assert_called_once()
        self.assertIn("synthetic new source", self.st.session_state.pdf_text)
        self.assertIsNone(self.st.session_state.notes)

    def test_loaded_session_cannot_generate_old_source_for_different_upload(self):
        self.st.session_state.update(current_file="saved.txt", current_session_id=SESSION_A,
                                     pdf_text="synthetic saved source", notes="saved notes")
        self.st.file_uploader.return_value = [upload("new.txt", b"synthetic new source")]
        self.st.button.return_value = True
        self.render()
        if self.router.call_args_list:
            for call in self.router.call_args_list:
                self.assertIn("synthetic new source", call.kwargs["raw_text"],
                              "EXTRACT-30: generated saved source for a different upload")
                self.assertNotIn("synthetic saved source", call.kwargs["raw_text"])
        else:
            self.assertTrue(self.st.error.called or self.st.warning.called or self.st.stop.called,
                            "Changed upload must reprocess or explicitly explain blocking")

    def test_saved_notes_remain_viewable_without_upload(self):
        state = self.app("src.utils.document_state")
        state.restore_saved_session(self.st.session_state, dict(id=SESSION_A, user_id=USER_A,
            filename="saved.txt", pdf_text="synthetic saved source", notes="saved notes", chat_history=[]), USER_A)
        self.render()
        self.notes_view.assert_called_once()
        self.extract.assert_not_called()
        self.router.assert_not_called()

    def test_empty_source_cannot_reach_note_persistence(self):
        self.st.file_uploader.return_value = [upload("empty.txt", b"")]
        self.st.button.return_value = True
        router = self.app("src.core.pipeline_router")
        self.router.side_effect = router.route_and_process
        with patch.object(self.ui, "generate_content", return_value=(True, "synthetic notes", "offline")), \
                patch.object(self.ui, "initialize_chat", return_value=object()), \
                patch.object(self.ui.database, "create_session", return_value=SESSION_A) as save:
            self.render()
        save.assert_not_called()  # EXTRACT-31: real router accepts header-only input.


class GenerationEligibilityContracts(OfflineCase):
    def assert_invalid_source_does_not_reach_model(self, source, contract):
        router = self.app("src.core.pipeline_router")
        model = Mock(return_value=(True, "synthetic notes", "offline"))
        try:
            result = router.route_and_process(source, "summarize", None, model)
        except ValueError:
            # Only the explicitly proposed validation error counts as denial.
            # Other exception types surface; any provider invocation fails below.
            result = (False, None, None, None)
        model.assert_not_called()  # Current production calls it: ordinary failure.
        self.assertIs(result[0], False, contract)

    def test_valid_source_reaches_model(self):
        router = self.app("src.core.pipeline_router")
        model = Mock(return_value=(True, "synthetic notes", "offline"))
        result = router.route_and_process("synthetic valid source", "summarize", None, model)
        self.assertIs(result[0], True)
        self.assertIn("synthetic valid source", model.call_args.args[0])

    def test_empty_source_does_not_reach_model(self):
        self.assert_invalid_source_does_not_reach_model("", "EXTRACT-32")

    def test_whitespace_source_does_not_reach_model(self):
        self.assert_invalid_source_does_not_reach_model(" \t\n", "EXTRACT-33")

    def test_metadata_only_source_does_not_reach_model(self):
        self.assert_invalid_source_does_not_reach_model("\n--- Document: a.txt ---\n--- Page 1 ---\n", "metadata-only")


class ContentValidationContracts(OfflineCase):
    def test_short_text_and_error_discussion_are_preserved(self):
        validation = self.app("src.utils.extraction_validation")
        for text in ("A", "1", "α", "\ufeffA", "  short\n", "Error handling: [Error: synthetic failure]", "# Title",
                     "Study note: [Error: Vision extraction failed. All OCR endpoints are currently unreachable.]"):
            self.assertEqual(validation.validate_extracted_text(text), text)

    def test_invalid_values_raise_typed_safe_errors(self):
        validation = self.app("src.utils.extraction_validation")
        for value in (None, 17, {}, [], True, "", " \n\t", "\ufeff", " \ufeff\t", "\x00binary"):
            with self.subTest(value=value), self.assertRaises(validation.ExtractionError):
                validation.validate_extracted_text(value)

    def test_generated_headers_alone_fail_but_headers_with_text_remain_unchanged(self):
        validation = self.app("src.utils.extraction_validation")
        for value in ("--- Document: a.txt ---", "\n--- Page 1 ---\n",
                      "\\n--- Page 1 ---\\n", "--- Document: a.txt ---\n--- Page 1 ---\n"):
            with self.subTest(value=value), self.assertRaises(validation.ExtractionError):
                validation.validate_extracted_text(value)
        value = "--- Document: a.txt ---\nA"
        self.assertEqual(validation.validate_extracted_text(value), value)

    def test_retired_ocr_failure_sentinel_is_not_accepted(self):
        validation = self.app("src.utils.extraction_validation")
        sentinel = "[Error: Vision extraction failed. All OCR endpoints are currently unreachable.]"
        for text in (sentinel, "--- Document: scan.pdf ---\n" + sentinel,
                     "\\n--- Page 1 ---\\n" + sentinel + "\\n"):
            with self.assertRaises(validation.ExtractionError):
                validation.validate_extracted_text(text)

    def test_validation_import_has_no_ui_or_provider_initialization(self):
        validation = self.app("src.utils.extraction_validation")
        self.assertEqual(validation.validate_extracted_text("A"), "A")
        for name in ("src.core.llm_client", "src.core.vision_client", "src.utils.extractor"):
            self.assertNotIn(name, sys.modules)
        sys.modules["google.genai"].Client.assert_not_called()
        sys.modules["supabase"].create_client.assert_not_called()
