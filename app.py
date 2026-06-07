import streamlit as st
import time
import traceback
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
print("LOG: [Gateway 1 (Authentication Check)] -> Started...")
start_auth = time.time()
try:
    handle_oauth_callback()
    elapsed = time.time() - start_auth
    print(f"LOG: [Gateway 1 (Authentication Check)] -> Completed in {elapsed:.2f}s")
except Exception as e:
    print(f"LOG: [Gateway 1 (Authentication Check)] -> Exception at {time.time()}: {traceback.format_exc()}")
    raise e

# Authentication check
if st.session_state.user_id is None:
    render_login_signup_form()
    st.stop()

# Render Sidebar and get user preferences
use_web_search, tone, focus, length = render_sidebar()

# Render Main Content
render_main_content(use_web_search, tone, focus, length)
