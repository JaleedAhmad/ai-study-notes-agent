import os
from supabase import create_client, Client
import bcrypt
from dotenv import load_dotenv
from ..auth.identity import require_authenticated_user, validate_user_id

# Force environment reload safely
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("CRITICAL: Missing SUPABASE_URL or SUPABASE_KEY inside the .env file! Phase 7 requires this constraint.")

def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def _identity_result(user):
    try:
        return True, validate_user_id(user.get("id"))
    except (AttributeError, PermissionError):
        return False, "Unable to authenticate account."


def create_user(email, password=None, provider="email"):
    # Every branch returns (success, validated ID or public error message).
    if provider not in ("email", "github"):
        return False, "Unsupported authentication provider."
    user = get_user_by_email(email)
    if user:
        return False, "Email already registered."
        
    password_hash = None
    if password:
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    try:
        res = get_supabase().table("users").insert({
            "email": email.lower(),
            "password_hash": password_hash,
            "provider": provider
        }).execute()
        
        return _identity_result(res.data[0]) if res.data else (False, "Unable to create account.")
    except Exception:
        return False, "Unable to create account. Please try again."

def authenticate_user(email, password):
    user = get_user_by_email(email)
    if not user:
        return False, "User not found."
        
    stored_hash = user.get("password_hash")
    if stored_hash:
        try:
            valid_password = bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
        except (ValueError, TypeError):
            return False, "Unable to authenticate account."
        if valid_password:
            return _identity_result(user)
        else:
            return False, "Incorrect password."
    else:
        return False, f"Account uses OAuth. Please login with {user.get('provider')}."

def get_user_by_email(email):
    res = get_supabase().table("users").select("*").eq("email", email.lower()).execute()
    if res.data and len(res.data) > 0:
        return res.data[0]
    return None

def get_user_by_id(user_id):
    res = get_supabase().table("users").select("*").eq("id", user_id).execute()
    if res.data and len(res.data) > 0:
        return res.data[0]
    return None

def authenticate_oauth_user(email, provider):
    if provider != "github":
        return False, "Unsupported authentication provider."
    user = get_user_by_email(email)
    if user:
        if user.get("provider") != provider or user.get("password_hash"):
            return False, "Use the account's existing sign-in method."
        return _identity_result(user)
    # A concurrent creation may now return failure. It must never become an ID.
    return create_user(email, provider=provider)

def create_session(user_id, filename, pdf_text, notes):
    user_id = require_authenticated_user(user_id)
    payload = {
        "user_id": user_id,
        "filename": filename,
        "pdf_text": pdf_text,
        "notes": notes,
        "chat_history": []
    }
    res = get_supabase().table("sessions").insert(payload).execute()
    if not res.data or res.data[0].get("user_id") != user_id:
        raise PermissionError("Unable to verify saved session.")
    return res.data[0]["id"]

def get_all_sessions(user_id):
    user_id = require_authenticated_user(user_id)
    # Retrieve all columns inherently required by `app.py` list map loops
    res = get_supabase().table("sessions").select("*").eq("user_id", user_id).order("timestamp", desc=True).execute()
    return [row for row in (res.data or []) if row.get("user_id") == user_id]

def get_session(session_id, *, user_id):
    user_id = require_authenticated_user(user_id)
    res = get_supabase().table("sessions").select("*").eq("id", session_id).eq("user_id", user_id).execute()
    if res.data:
        row = res.data[0]
        if row.get("user_id") == user_id and row.get("id") == session_id:
            return row
    return None

def save_chat_message(session_id, role, content, *, user_id):
    user_id = require_authenticated_user(user_id)
    session_data = get_session(session_id, user_id=user_id)
    if session_data is None:
        raise PermissionError("Session unavailable.")
    chat_history = list(session_data.get("chat_history") or [])
    chat_history.append({"role": role, "content": content})
    res = get_supabase().table("sessions").update({"chat_history": chat_history}).eq("id", session_id).eq("user_id", user_id).execute()
    if not res.data or any(row.get("user_id") != user_id or row.get("id") != session_id for row in res.data):
        raise PermissionError("Session unavailable.")

def delete_session(session_id, *, user_id):
    user_id = require_authenticated_user(user_id)
    res = get_supabase().table("sessions").delete().eq("id", session_id).eq("user_id", user_id).execute()
    if not res.data or any(row.get("user_id") != user_id or row.get("id") != session_id for row in res.data):
        raise PermissionError("Session unavailable.")
