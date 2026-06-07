import streamlit as st
from datetime import datetime
from ..database import database
from ..core.agent import initialize_chat

def render_sidebar():
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
        
        return use_web_search, tone, focus, length
