import streamlit as st
from src.ui.auth import handle_oauth_callback, render_login_signup_form
from src.ui.sidebar import render_sidebar
from src.ui.main_content import render_main_content

st.set_page_config(page_title="AI Study Notes Agent", page_icon="📚")

# Initialize session state
if "user_id" not in st.session_state:
    st.session_state.user_id = None
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

# Handle OAuth callback
handle_oauth_callback()

# Authentication check
if st.session_state.user_id is None:
    render_login_signup_form()
    st.stop()

# Render Sidebar and get user preferences
use_web_search, tone, focus, length = render_sidebar()

# Render Main Content
render_main_content(use_web_search, tone, focus, length)
