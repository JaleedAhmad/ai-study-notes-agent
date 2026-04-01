import streamlit as st
import database
import oauth

st.set_page_config(page_title="AI Study Notes Agent", page_icon="📚")

if "user_id" not in st.session_state:
    st.session_state.user_id = None

# --- OAUTH CALLBACK HANDLER ---
query_params = st.query_params
if "code" in query_params and "state" in query_params and st.session_state.user_id is None:
    code = query_params["code"]
    state = query_params["state"]
    st.write(f"Authenticating with {state.capitalize()}...")
    
    if state == "google":
        email = oauth.get_google_user(code)
    elif state == "github":
        email = oauth.get_github_user(code)
    else:
        email = None
        
    if email:
        success, uid = database.authenticate_oauth_user(email, state)
        if success:
            st.session_state.user_id = uid
            st.query_params.clear()
            st.rerun()
    else:
        st.error(f"Failed to authenticate with {state.capitalize()}")
        st.query_params.clear()

# --- AUTHENTICATION LAYER ---
if st.session_state.user_id is None:
    st.title("AI Study Notes Agent 📚")
    st.write("Please log in or sign up to continue.")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f'<a href="{oauth.get_google_auth_url()}" target="_self"><button style="width:100%; padding:10px; background-color:#4285F4; color:white; border:none; border-radius:5px; cursor:pointer;">🔵 Continue with Google</button></a>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<a href="{oauth.get_github_auth_url()}" target="_self"><button style="width:100%; padding:10px; background-color:#333; color:white; border:none; border-radius:5px; cursor:pointer;">⚫ Continue with GitHub</button></a>', unsafe_allow_html=True)
    
    st.divider()
    st.write("Or use Email and Password:")
    tab1, tab2 = st.tabs(["Login", "Sign Up"])
    with tab1:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                success, result = database.authenticate_user(username, password)
                if success:
                    st.session_state.user_id = result
                    st.rerun()
                else:
                    st.error(result)
                    
    with tab2:
        with st.form("signup_form"):
            new_username = st.text_input("New Username")
            new_password = st.text_input("New Password", type="password")
            if st.form_submit_button("Sign Up"):
                if len(new_username) < 3 or len(new_password) < 6:
                    st.error("Username must be at least 3 characters and password at least 6 characters.")
                else:
                    success, result = database.create_user(new_username, new_password)
                    if success:
                        st.success("Account created successfully! Please switch to the Login tab.")
                    else:
                        st.error(result)
    st.stop()
# --- END AUTHENTICATION LAYER ---

from pdf_reader import extract_text_from_pdf
from agent import generate_study_notes, initialize_chat, send_chat_message
from pdf_exporter import generate_pdf
from datetime import datetime

use_web_search = False
# Sidebar Configuration
with st.sidebar:
    st.title("🌐 AI Capabilities")
    use_web_search = st.toggle("Enable Live Web Search", value=False, help="Allows the AI to intelligently search Google to supplement your textbook notes with up-to-date real-world context.")
    st.divider()
    
    st.write("🔒 Secure Session")
    if st.button("🚪 Logout", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
        
    st.divider()
    st.title("📚 Chat History")
    if st.button("➕ Start New Session", use_container_width=True):
        st.session_state.current_session_id = None
        st.session_state.notes = None
        st.session_state.pdf_text = None
        st.session_state.chat_session = None
        st.session_state.chat_history = []
        st.session_state.current_file = None
        st.session_state.podcast_bytes = None
        st.session_state.anki_bytes = None
        st.rerun()

    st.divider()
    
    sessions = database.get_all_sessions(st.session_state.user_id)
    for session in sessions:
        try:
            date_str = datetime.fromisoformat(session["timestamp"]).strftime("%b %d, %H:%M")
        except:
            date_str = "Unknown Date"
            
        col1, col2 = st.columns([4, 1])
        btn_label = f"📄 {session['filename'][:15]}... ({date_str})" if len(session['filename']) > 15 else f"📄 {session['filename']} ({date_str})"
        
        with col1:
            if st.button(btn_label, key=f"load_{session['id']}"):
                st.session_state.current_session_id = session["id"]
                st.session_state.pdf_text = session["pdf_text"]
                st.session_state.notes = session["notes"]
                st.session_state.chat_history = session["chat_history"]
                st.session_state.chat_session = initialize_chat(session["pdf_text"], session["chat_history"], use_web_search=use_web_search)
                st.session_state.current_file = session["filename"]
                st.session_state.podcast_bytes = None
                st.session_state.anki_bytes = None
                st.rerun()
        
        with col2:
            if st.button("🗑️", key=f"del_{session['id']}"):
                database.delete_session(session["id"])
                if st.session_state.current_session_id == session["id"]:
                    st.session_state.current_session_id = None
                    st.session_state.notes = None
                    st.session_state.pdf_text = None
                    st.session_state.chat_session = None
                    st.session_state.chat_history = []
                    st.session_state.current_file = None
                    st.session_state.podcast_bytes = None
                    st.session_state.anki_bytes = None
                st.rerun()

    st.divider()
    st.title("🛠️ Customization")
    st.write("Tweak the output of your study notes!")
    tone = st.selectbox("Tone", ["Academic", "Simple/Beginner", "Conversational"])
    focus = st.selectbox("Focus area", ["General Summary", "Flashcards", "Code/Technical Examples", "Exam Prep Questions"])
    length = st.select_slider("Length", options=["Short", "Medium", "Detailed"], value="Medium")

st.title("AI Study Notes Agent")

if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None
if "notes" not in st.session_state:
    st.session_state.notes = None
if "pdf_text" not in st.session_state:
    st.session_state.pdf_text = None
if "chat_session" not in st.session_state:
    st.session_state.chat_session = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "current_file" not in st.session_state:
    st.session_state.current_file = None
if "podcast_bytes" not in st.session_state:
    st.session_state.podcast_bytes = None
if "anki_bytes" not in st.session_state:
    st.session_state.anki_bytes = None

if "library_id" not in st.session_state:
    st.session_state.library_id = None

uploaded_files = st.file_uploader("Upload your study material (PDFs)", type="pdf", accept_multiple_files=True)

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
        import uuid
        st.session_state.library_id = str(uuid.uuid4())

    if st.session_state.pdf_text is None:
        st.write("Extracting and Indexing Library... (This may take a minute for large files)")
        combined_text = ""
        import rag
        
        with st.spinner("Processing Library into Vector Database..."):
            for f in uploaded_files:
                text = extract_text_from_pdf(f)
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
                st.session_state.notes = generate_study_notes(st.session_state.pdf_text, tone, focus, length, use_web_search=use_web_search)
                st.session_state.chat_session = initialize_chat(st.session_state.pdf_text, use_web_search=use_web_search)
                st.session_state.chat_history = []
                st.session_state.podcast_bytes = None
                st.session_state.anki_bytes = None
                st.session_state.current_session_id = database.create_session(
                    st.session_state.user_id,
                    ", ".join(st.session_state.current_file) if isinstance(st.session_state.current_file, list) else st.session_state.current_file, 
                    st.session_state.pdf_text, 
                    st.session_state.notes
                )
                st.rerun()
            except Exception as e:
                st.error(f"An error occurred while generating notes. Please check your API key or quota.\n\nDetails: {e}")

if st.session_state.notes:
    if st.session_state.current_session_id:
        st.caption(f"Viewing session: {st.session_state.current_file}")
    
    st.subheader("Generated Study Notes")
    st.write(st.session_state.notes)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button(
            label="Download as Markdown",
            data=st.session_state.notes,
            file_name="study_notes.md",
            mime="text/markdown"
        )
    with col2:
        try:
            pdf_bytes = generate_pdf(st.session_state.notes)
            st.download_button(
                label="Download as PDF",
                data=pdf_bytes,
                file_name="study_notes.pdf",
                mime="application/pdf"
            )
        except Exception as e:
            st.error(f"Could not prepare PDF download: {e}")
            
    with col3:
        if not st.session_state.get("anki_bytes"):
            if st.button("Generate Anki Flashcards"):
                with st.spinner("Extracting strictly formatted Flashcards..."):
                    from anki_exporter import generate_anki_deck
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

    # --- Podcast Mode Section ---
    st.divider()
    st.subheader("🎧 Podcast Mode")
    st.write("Turn your notes into a spoken podcast to listen on the go!")
    
    if not st.session_state.get("podcast_bytes"):
        if st.button("Generate Audio Podcast"):
            with st.spinner("Recording podcast... (this usually takes 10 to 30 seconds depending on note length)"):
                from audio import generate_audio_from_text
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
            label="Download Podcast (.mp3)",
            data=st.session_state.podcast_bytes,
            file_name="study_podcast.mp3",
            mime="audio/mp3"
        )

    # --- Interactive Q&A Section ---
    st.divider()
    st.subheader("Interactive Q&A")
    st.write("Ask any questions about the study material!")

    if st.session_state.chat_session is None and st.session_state.pdf_text is not None:
        st.session_state.chat_session = initialize_chat(st.session_state.pdf_text, st.session_state.chat_history)

    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if user_question := st.chat_input("Ask a question about your notes..."):
        with st.chat_message("user"):
            st.markdown(user_question)
        
        st.session_state.chat_history.append({"role": "user", "content": user_question})
        database.update_chat_history(st.session_state.current_session_id, "user", user_question)
        
        with st.chat_message("assistant"):
            with st.spinner("Searching Digital Library & Thinking..."):
                try:
                    import rag
                    
                    relevant_context = rag.query_relevant_chunks(st.session_state.user_id, user_question)
                    
                    if relevant_context:
                        rag_prompt = f"Target RAG Context Retrieved from Library:\n{relevant_context}\n\nUser Question: {user_question}"
                    else:
                        rag_prompt = user_question
                        
                    answer = send_chat_message(st.session_state.chat_session, rag_prompt)
                    st.markdown(answer)
                    st.session_state.chat_history.append({"role": "assistant", "content": answer})
                    database.update_chat_history(st.session_state.current_session_id, "assistant", answer)
                except Exception as e:
                    st.error(f"Error answering question: {e}")
