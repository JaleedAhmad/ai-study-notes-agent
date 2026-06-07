import streamlit as st
import uuid
import time
import traceback
from ..utils.extractor import extract_universal_text
from ..core.agent import generate_study_notes, initialize_chat, send_chat_message
from ..core.pipeline_router import route_and_process
from ..core.llm_client import generate_content
from ..exporters.pdf_exporter import generate_pdf
from ..exporters.anki_exporter import generate_anki_deck
from ..exporters.audio import generate_audio_from_text
from ..database import database
from ..core import rag

def render_main_content(use_web_search, tone, focus, length):
    st.title("AI Study Notes Agent")

    uploaded_files = st.file_uploader("Upload your study material", type=["pdf", "docx", "pptx", "txt", "md"], accept_multiple_files=True)

    if uploaded_files:
        current_filenames = [f.name for f in uploaded_files]
        if st.session_state.current_file != current_filenames and st.session_state.current_session_id is None:
            st.session_state.current_file = current_filenames
            st.session_state.pdf_text = None
            st.session_state.notes = None
            st.session_state.chat_session = None
            st.session_state.chat_history = []
            st.session_state.podcast_bytes = None
            st.session_state.anki_bytes = None
            st.session_state.library_id = str(uuid.uuid4())

        if st.session_state.pdf_text is None:
            st.write("Extracting and Indexing Library... (This may take a minute for large files)")
            combined_text = ""
            
            with st.spinner("Processing Library into Vector Database..."):
                for f in uploaded_files:
                    print("LOG: [Gateway 2 (Universal Ingestion Engine)] -> Started...")
                    start_ingest = time.time()
                    try:
                        text = extract_universal_text(f)
                        elapsed = time.time() - start_ingest
                        print(f"LOG: [Gateway 2 (Universal Ingestion Engine)] -> Completed in {elapsed:.2f}s | Extracted {len(text)} characters")
                    except Exception as e:
                        print(f"LOG: [Gateway 2 (Universal Ingestion Engine)] -> Exception at {time.time()}: {traceback.format_exc()}")
                        raise e
                    combined_text += f"\n\n--- Document: {f.name} ---\n\n" + text
                    rag.embed_and_store_document(
                        user_id=st.session_state.user_id,
                        document_id=f"{st.session_state.library_id}_{f.name}",
                        pdf_text=text,
                        filename=f.name
                    )
            st.session_state.pdf_text = combined_text
            st.success("Library Indexed Successfully into ChromaDB!")

        if st.button("Generate Study Notes"):
            with st.spinner("Analyzing content..."):
                try:
                    instruction_wrapper = f"""
                    You are an AI Study Notes Agent designed to help students understand study material.
                    Analyze the provided content and convert it into structured learning notes.
                    Please customize the notes strictly according to these preferences:
                    - Tone: {tone}
                    - Focus: {focus}
                    - Length: {length}
                    """
                    
                    success, payload, provider, strategy = route_and_process(
                        raw_text=st.session_state.pdf_text,
                        query=instruction_wrapper,
                        chroma_client=None,
                        llm_orchestrator=generate_content
                    )
                    
                    if success:
                        st.session_state.notes = payload
                        st.session_state.generation_strategy = strategy
                        st.session_state.generation_provider = provider
                    else:
                        raise Exception(payload)

                    st.session_state.chat_session = initialize_chat(st.session_state.pdf_text, use_web_search=use_web_search)
                    st.session_state.chat_history = []
                    st.session_state.podcast_bytes = None
                    st.session_state.anki_bytes = None
                    
                    print("LOG: [Gateway 5 (Session Init)] -> Started...")
                    start_session = time.time()
                    try:
                        st.session_state.current_session_id = database.create_session(
                            st.session_state.user_id,
                            ", ".join(st.session_state.current_file) if isinstance(st.session_state.current_file, list) else st.session_state.current_file, 
                            st.session_state.pdf_text, 
                            st.session_state.notes
                        )
                        elapsed = time.time() - start_session
                        print(f"LOG: [Gateway 5 (Session Init)] -> Completed in {elapsed:.2f}s")
                    except Exception as e:
                        print(f"LOG: [Gateway 5 (Session Init)] -> Exception at {time.time()}: {traceback.format_exc()}")
                        raise e
                    st.rerun()
                except Exception as e:
                    st.error(f"An error occurred while generating notes. Details: {e}")

    if st.session_state.notes:
        render_notes_section()
        render_podcast_section()
        render_chat_section(use_web_search)

def render_notes_section():
    if st.session_state.current_session_id:
        st.caption(f"Viewing session: {st.session_state.current_file}")
        
    if st.session_state.get("generation_strategy"):
        st.info(f"Strategy Selected: {st.session_state.generation_strategy} (Powered by {st.session_state.generation_provider})")
    
    st.subheader("Generated Study Notes")
    st.write(st.session_state.notes)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button(
            label="Download Markdown",
            data=st.session_state.notes,
            file_name="study_notes.md",
            mime="text/markdown"
        )
    with col2:
        try:
            pdf_bytes = generate_pdf(st.session_state.notes)
            st.download_button(
                label="Download PDF",
                data=pdf_bytes,
                file_name="study_notes.pdf",
                mime="application/pdf"
            )
        except Exception as e:
            st.error(f"Could not prepare PDF: {e}")
            
    with col3:
        if not st.session_state.get("anki_bytes"):
            if st.button("Generate Anki"):
                with st.spinner("Extracting Flashcards..."):
                    ab = generate_anki_deck(st.session_state.notes)
                    if ab is not None:
                        st.session_state.anki_bytes = ab
                        st.rerun()
                    else:
                        st.error("Failed to extract flashcards.")
        else:
            st.download_button(
                label="Download Anki (.apkg)",
                data=st.session_state.anki_bytes,
                file_name="study_flashcards.apkg",
                mime="application/octet-stream"
            )

def render_podcast_section():
    st.divider()
    st.subheader("🎧 Podcast Mode")
    st.write("Turn your notes into a spoken podcast!")
    
    if not st.session_state.get("podcast_bytes"):
        if st.button("Generate Audio Podcast"):
            with st.spinner("Recording podcast..."):
                audio = generate_audio_from_text(st.session_state.notes)
                if audio:
                    st.session_state.podcast_bytes = audio
                    st.rerun()
                else:
                    st.error("Failed to generate audio.")
                    
    if st.session_state.get("podcast_bytes"):
        st.success("Podcast ready!")
        st.audio(st.session_state.podcast_bytes, format="audio/mp3")
        st.download_button(
            label="Download MP3",
            data=st.session_state.podcast_bytes,
            file_name="study_podcast.mp3",
            mime="audio/mp3"
        )

def render_chat_section(use_web_search):
    st.divider()
    st.subheader("Interactive Q&A")
    st.write("Ask any questions about the study material!")

    if st.session_state.chat_session is None and st.session_state.pdf_text is not None:
        st.session_state.chat_session = initialize_chat(st.session_state.pdf_text, st.session_state.chat_history, use_web_search=use_web_search)

    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if user_question := st.chat_input("Ask a question about your notes..."):
        with st.chat_message("user"):
            st.markdown(user_question)
        
        st.session_state.chat_history.append({"role": "user", "content": user_question})
        
        print("LOG: [Gateway 5 (Chat Append)] -> Started...")
        start_append = time.time()
        try:
            database.save_chat_message(st.session_state.current_session_id, "user", user_question)
            print(f"LOG: [Gateway 5 (Chat Append)] -> Completed in {time.time() - start_append:.2f}s")
        except Exception as e:
            print(f"LOG: [Gateway 5 (Chat Append)] -> Exception at {time.time()}: {traceback.format_exc()}")
        
        with st.chat_message("assistant"):
            with st.spinner("Searching Library & Thinking..."):
                try:
                    relevant_context = rag.query_relevant_chunks(st.session_state.user_id, user_question)
                    
                    if relevant_context:
                        rag_prompt = f"Target RAG Context Retrieved from Library:\n{relevant_context}\n\nUser Question: {user_question}"
                    else:
                        rag_prompt = user_question
                        
                    answer = send_chat_message(st.session_state.chat_session, rag_prompt)
                    st.markdown(answer)
                    st.session_state.chat_history.append({"role": "assistant", "content": answer})
                    
                    print("LOG: [Gateway 5 (Chat Append)] -> Started...")
                    start_append = time.time()
                    try:
                        database.save_chat_message(st.session_state.current_session_id, "assistant", answer)
                        print(f"LOG: [Gateway 5 (Chat Append)] -> Completed in {time.time() - start_append:.2f}s")
                    except Exception as e:
                        print(f"LOG: [Gateway 5 (Chat Append)] -> Exception at {time.time()}: {traceback.format_exc()}")
                except Exception as e:
                    st.error(f"Error answering question: {e}")
