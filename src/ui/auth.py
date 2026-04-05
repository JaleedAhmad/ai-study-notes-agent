import streamlit as st
from ..database import database
from ..auth import oauth

def handle_oauth_callback():
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

def render_login_signup_form():
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
            email = st.text_input("Email/Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                success, result = database.authenticate_user(email, password)
                if success:
                    st.session_state.user_id = result
                    st.rerun()
                else:
                    st.error(result)
                    
    with tab2:
        with st.form("signup_form"):
            new_email = st.text_input("New Email")
            new_password = st.text_input("New Password", type="password")
            if st.form_submit_button("Sign Up"):
                if len(new_email) < 3 or len(new_password) < 6:
                    st.error("Email must be at least 3 characters and password at least 6 characters.")
                else:
                    success, result = database.create_user(new_email, new_password)
                    if success:
                        st.success("Account created successfully! Please switch to the Login tab.")
                    else:
                        st.error(result)
