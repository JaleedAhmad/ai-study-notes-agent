import streamlit as st
import re
import time
from ..database import database
from ..auth import oauth

def validate_email(email):
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return re.match(pattern, email) is not None

def validate_password_complexity(password):
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"\d", password):
        return False, "Password must contain at least one digit."
    return True, ""

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
    
    # Initialize rate limiting state
    if "login_attempts" not in st.session_state:
        st.session_state.login_attempts = 0
    if "lockout_time" not in st.session_state:
        st.session_state.lockout_time = None

    # Check if locked out
    if st.session_state.lockout_time:
        if time.time() < st.session_state.lockout_time:
            st.error(f"Too many failed attempts. Please try again in {int(st.session_state.lockout_time - time.time())} seconds.")
            return
        else:
            # Reset lockout
            st.session_state.login_attempts = 0
            st.session_state.lockout_time = None

    st.markdown(f'<a href="{oauth.get_github_auth_url()}" target="_self"><button style="width:100%; padding:10px; background-color:#333; color:white; border:none; border-radius:5px; cursor:pointer;">⚫ Continue with GitHub</button></a>', unsafe_allow_html=True)
    
    st.divider()
    st.write("Or use Email and Password:")
    tab1, tab2 = st.tabs(["Login", "Sign Up"])
    with tab1:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                email = email.strip().lower()
                if not email or not password:
                    st.error("Please fill in both fields.")
                else:
                    try:
                        success, result = database.authenticate_user(email, password)
                        if success:
                            st.session_state.login_attempts = 0
                            st.session_state.user_id = result
                            st.rerun()
                        else:
                            st.session_state.login_attempts += 1
                            if st.session_state.login_attempts >= 5:
                                st.session_state.lockout_time = time.time() + 180 # 3 minutes lockout
                                st.error("Too many failed attempts. You have been locked out for 3 minutes.")
                            else:
                                st.error(result)
                    except Exception as e:
                        st.error("Could not reach the database. Please try again.")
                    
    with tab2:
        with st.form("signup_form"):
            new_email = st.text_input("New Email")
            new_password = st.text_input("New Password", type="password")
            if st.form_submit_button("Sign Up"):
                new_email = new_email.strip().lower()
                if not validate_email(new_email):
                    st.error("Please enter a valid email address.")
                else:
                    is_valid, msg = validate_password_complexity(new_password)
                    if not is_valid:
                        st.error(msg)
                    else:
                        try:
                            success, result = database.create_user(new_email, new_password)
                            if success:
                                st.success("Account created successfully! Please switch to the Login tab.")
                            else:
                                st.error(result)
                        except Exception as e:
                            st.error("Could not reach the database. Please try again.")
