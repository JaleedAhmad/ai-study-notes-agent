import os
from supabase import create_client, Client
import bcrypt
from dotenv import load_dotenv

# Force environment reload safely
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("CRITICAL: Missing SUPABASE_URL or SUPABASE_KEY inside the .env file! Phase 7 requires this constraint.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def create_user(email, password=None, provider="email"):
    user = get_user_by_email(email)
    if user:
        return False, "Email already registered."
        
    password_hash = None
    if password:
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    try:
        res = supabase.table("users").insert({
            "email": email.lower(),
            "password_hash": password_hash,
            "provider": provider
        }).execute()
        
        if provider != "email":
            return res.data[0]["id"]
        return True, "Account successfully created! Please log in."
    except Exception as e:
        if provider != "email": return None
        return False, f"Database error: {e}"

def authenticate_user(email, password):
    user = get_user_by_email(email)
    if not user:
        return False, "User not found."
        
    stored_hash = user.get("password_hash")
    if stored_hash:
        if bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
            return True, user["id"]
        else:
            return False, "Incorrect password."
    else:
        return False, f"Account uses OAuth. Please login with {user.get('provider')}."

def get_user_by_email(email):
    res = supabase.table("users").select("*").eq("email", email.lower()).execute()
    if res.data and len(res.data) > 0:
        return res.data[0]
    return None

def get_user_by_id(user_id):
    res = supabase.table("users").select("*").eq("id", user_id).execute()
    if res.data and len(res.data) > 0:
        return res.data[0]
    return None

def authenticate_oauth_user(email, provider):
    user = get_user_by_email(email)
    if user:
        return True, user["id"]
    
    # create_user returns (True, Msg) or (False, Msg) or raw ID if not email.
    # Actually create_user returns ID directly if provider != "email":
    # Let's cleanly orchestrate the ID return:
    uid = create_user(email, provider=provider)
    if uid:
        return True, uid
    return False, "Failed to authenticate with provider."

def create_session(user_id, filename, pdf_text, notes):
    payload = {
        "user_id": user_id,
        "filename": filename,
        "pdf_text": pdf_text,
        "notes": notes,
        "chat_history": []
    }
    res = supabase.table("sessions").insert(payload).execute()
    return res.data[0]["id"]

def get_all_sessions(user_id):
    # Retrieve all columns inherently required by `app.py` list map loops
    res = supabase.table("sessions").select("*").eq("user_id", user_id).order("timestamp", desc=True).execute()
    return res.data if res.data else []

def get_session(session_id):
    res = supabase.table("sessions").select("*").eq("id", session_id).execute()
    if res.data and len(res.data) > 0:
        return res.data[0]
    return None

def save_chat_message(session_id, role, content):
    session_data = get_session(session_id)
    if session_data:
        chat_history = session_data.get("chat_history", [])
        chat_history.append({"role": role, "content": content})
        supabase.table("sessions").update({"chat_history": chat_history}).eq("id", session_id).execute()

def delete_session(session_id):
    supabase.table("sessions").delete().eq("id", session_id).execute()
