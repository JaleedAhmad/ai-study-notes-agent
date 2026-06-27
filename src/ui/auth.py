import streamlit as st
from ..database import database
from ..auth import oauth

def handle_oauth_callback():
    query_params = st.query_params
    if "code" in query_params and "state" in query_params and st.session_state.user_id is None:
        code = query_params["code"]
        state = query_params["state"]
        st.write(f"Authenticating with {state.capitalize()}...")
        
        if state == "github":
            email = oauth.get_github_user(code)
        else:
            email = None
            
        if email:
            try:
                success, uid = database.authenticate_oauth_user(email, state)
                if success:
                    st.session_state.user_id = uid
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error("Failed to authenticate with provider.")
                    st.query_params.clear()
            except Exception as e:
                st.error("Database connection failed. Please try again.")
                st.query_params.clear()
        else:
            st.error(f"Failed to authenticate with {state.capitalize()}")
            st.query_params.clear()

def render_login_signup_form():
    st.title("AI Study Notes Agent 📚")
    st.write("Please log in or sign up to continue.")
    
    st.markdown(f'<a href="{oauth.get_github_auth_url()}" target="_self"><button style="width:100%; padding:10px; background-color:#333; color:white; border:none; border-radius:5px; cursor:pointer;">⚫ Continue with GitHub</button></a>', unsafe_allow_html=True)
    
    st.divider()
    st.write("Or use Email and Password:")
    tab1, tab2 = st.tabs(["Login", "Sign Up"])
    with tab1:
        with st.form("login_form"):
            email = st.text_input("Email/Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                try:
                    success, result = database.authenticate_user(email, password)
                    if success:
                        st.session_state.user_id = result
                        st.rerun()
                    else:
                        st.error(result)
                except Exception as e:
                    st.error("Could not reach the database. Please try again.")
                    
    with tab2:
        with st.form("signup_form"):
            new_email = st.text_input("New Email")
            new_password = st.text_input("New Password", type="password")
            if st.form_submit_button("Sign Up"):
                if len(new_email) < 3 or len(new_password) < 6:
                    st.error("Email must be at least 3 characters and password at least 6 characters.")
                else:
                    try:
                        success, result = database.create_user(new_email, new_password)
                        if success:
                            st.success("Account created successfully! Please switch to the Login tab.")
                        else:
                            st.error(result)
                    except Exception as e:
                        st.error("Could not reach the database. Please try again.")
