"""Plain-text consumer boundaries with synthetic codec/model/speech operations."""
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from offline.fake_database import USER_A, SESSION_A
from offline.support import OfflineCase
from offline.test_extraction import UploadUIFixtures, Stopped


def records_for(case):
    core=case.app("src.core.comprehensive_generation")
    records=case.app("src.utils.source_manifest")
    source="Synthetic definitions and equations."
    notes,_=core.generate_comprehensive(source,"notes",lambda prompt:(True,"Plain study notes.","synthetic"))
    v2=records.dump_notes(notes,source)
    raw=json.loads(v2[len(records.RECORD_PREFIX):])
    raw["version"]=1
    raw["coverage"].pop("reference_contract")
    for request in raw["coverage"]["requests"]:
        request.pop("reference_ids")
    v1=records.RECORD_PREFIX_V1+json.dumps(raw)
    return records,source,("Plain study notes.",v1,v2)


class UIConsumerContracts(UploadUIFixtures):
    def setUp(self):
        super().setUp()
        self.records,self.source,self.values=records_for(self)
        self.state=self.app("src.utils.document_state")
        self.st.columns=Mock(side_effect=lambda count:tuple(nullcontext() for _ in range(count)))
        for name in ("caption","info","subheader","divider","write","download_button","audio"):
            setattr(self.st,name,Mock())
        self.pdf=self.stack.enter_context(patch.object(self.ui,"generate_pdf",return_value=b"synthetic pdf"))
        self.anki=self.stack.enter_context(patch.object(self.ui,"generate_anki_deck",return_value=b"synthetic deck"))
        self.audio=self.stack.enter_context(patch.object(self.ui,"generate_audio_from_text",return_value=b"synthetic audio"))
        self.st.button.side_effect=lambda label,**kwargs:label=="Generate Anki"

    def select(self,value):
        self.state.restore_saved_session(self.st.session_state,dict(user_id=USER_A,id=SESSION_A,
            filename="synthetic.txt",pdf_text=self.source,notes=value,chat_history=[]),USER_A)
        # Simulate a raw serialized cache value at the consumer boundary. The
        # consumer must decode it itself, not rely on the sidebar fixture.
        self.st.session_state.notes=value

    def invoke(self,view):
        try:
            view()
        except Stopped:
            pass

    def test_view_markdown_pdf_and_flashcard_consumers_receive_only_plain_text(self):
        for value in self.values:
            with self.subTest(format=value[:30]):
                self.select(value)
                for mock in (self.pdf,self.anki,self.st.download_button,self.st.write):
                    mock.reset_mock()
                self.invoke(self.real_notes_view)
                self.pdf.assert_called_once()
                self.anki.assert_called_once()
                self.assertEqual(self.pdf.call_args.args[0],"Plain study notes.")
                self.assertEqual(self.anki.call_args.args[0],"Plain study notes.")
                markdown=next(call for call in self.st.download_button.call_args_list
                              if call.kwargs.get("label")=="Download Markdown")
                self.assertEqual(markdown.kwargs["data"],"Plain study notes.")
                self.assertNotIn(self.records.RECORD_FAMILY,str(self.st.write.call_args_list))

    def test_audio_and_podcast_receive_only_decoded_text(self):
        self.st.button.side_effect=lambda label,**kwargs:label=="Generate Audio Podcast"
        for value in self.values:
            with self.subTest(format=value[:30]):
                self.select(value)
                self.audio.reset_mock()
                self.invoke(self.real_podcast_view)
                self.audio.assert_called_once_with("Plain study notes.")

    def test_unsupported_or_corrupt_envelope_is_never_rendered_or_exported(self):
        for value in ("AI_STUDY_NOTES_GENERATION_V3\n{}",self.records.RECORD_PREFIX+"broken"):
            self.select(self.values[0])
            self.st.session_state.notes=value
            self.invoke(self.real_notes_view)
            self.invoke(self.real_podcast_view)
        self.pdf.assert_not_called()
        self.anki.assert_not_called()
        self.audio.assert_not_called()
        self.assertNotIn(self.records.RECORD_FAMILY,str(self.st.write.call_args_list))

    def test_wrong_source_envelope_is_not_reused_for_exports(self):
        self.select(self.values[0])
        core=self.app("src.core.comprehensive_generation")
        other,_=core.generate_comprehensive("other source","notes",lambda prompt:(True,"Other notes.","synthetic"))
        self.st.session_state.notes=self.records.dump_notes(other,"other source")
        self.invoke(self.real_notes_view)
        self.pdf.assert_not_called()
        self.anki.assert_not_called()

    def test_stale_note_binding_blocks_all_consumer_calls(self):
        self.select(self.values[-1])
        self.st.session_state.notes_source="stale-source"
        self.invoke(self.real_notes_view)
        self.invoke(self.real_podcast_view)
        self.pdf.assert_not_called()
        self.anki.assert_not_called()
        self.audio.assert_not_called()


class ExporterBoundaryContracts(OfflineCase):
    def setUp(self):
        super().setUp()
        self.records,self.source,self.values=records_for(self)
        fpdf,markdown,genanki=ModuleType("fpdf"),ModuleType("markdown"),ModuleType("genanki")
        self.pdf_object=Mock()
        self.pdf_object.output.return_value=b"synthetic pdf"
        fpdf.FPDF=Mock(return_value=self.pdf_object)
        markdown.markdown=Mock(return_value="<p>Plain study notes.</p>")
        self.markdown=markdown.markdown
        for name in ("Model","Deck","Note"):
            setattr(genanki,name,Mock())
        package=Mock()
        package.write_to_file.side_effect=lambda path:Path(path).write_bytes(b"synthetic deck")
        genanki.Package=Mock(return_value=package)
        self.stack.enter_context(patch.dict(sys.modules,{"fpdf":fpdf,"markdown":markdown,"genanki":genanki}))
        self.pdf=self.app("src.exporters.pdf_exporter")
        self.anki=self.app("src.exporters.anki_exporter")
        self.audio=self.app("src.exporters.audio")
        self.client=Mock()
        self.client.models.generate_content.return_value=SimpleNamespace(text="Question?:::Answer.")
        self.factory=self.stack.enter_context(patch.object(self.anki.genai,"Client",return_value=self.client))
        tts=Mock()
        tts.save.side_effect=lambda path:Path(path).write_bytes(b"synthetic speech")
        self.tts=self.stack.enter_context(patch.object(self.audio,"gTTS",return_value=tts))

    def test_actual_pdf_path_uses_decoded_markdown(self):
        for value in self.values:
            notes=self.records.load_notes(value,self.source)
            self.assertEqual(self.pdf.generate_pdf(notes),b"synthetic pdf")
            self.assertEqual(self.markdown.call_args.args[0],"Plain study notes.")

    def test_actual_flashcard_path_excludes_envelope_from_model_prompt_and_cleans_temp(self):
        for value in self.values:
            notes=self.records.load_notes(value,self.source)
            self.assertEqual(self.anki.generate_anki_deck(notes),b"synthetic deck")
            prompt=self.client.models.generate_content.call_args.kwargs["contents"]
            self.assertIn("Plain study notes.",prompt)
            self.assertNotIn(self.records.RECORD_FAMILY,prompt)
        self.assertEqual(list(self.workdir.glob("temp_deck_*.apkg")),[])

    def test_actual_audio_path_excludes_metadata_and_cleans_temp(self):
        for value in self.values:
            notes=self.records.load_notes(value,self.source)
            self.assertEqual(self.audio.generate_audio_from_text(notes),b"synthetic speech")
            self.assertEqual(self.tts.call_args.kwargs["text"],"Plain study notes.")
        self.assertEqual(list(self.workdir.glob("temp_podcast_*.mp3")),[])

    def test_raw_wrappers_are_rejected_before_codec_or_provider_calls(self):
        for value in self.values[1:]:
            for consumer in (self.pdf.generate_pdf,self.anki.generate_anki_deck,self.audio.generate_audio_from_text):
                with self.subTest(consumer=consumer.__name__),self.assertRaises(ValueError):
                    consumer(value)
        self.factory.assert_not_called()
        self.markdown.assert_not_called()
        self.tts.assert_not_called()
