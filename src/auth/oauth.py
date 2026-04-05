import os
import requests
import urllib.parse
from dotenv import load_dotenv

load_dotenv()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")

# Streamlit runs locally on port 8501 by default
REDIRECT_URI = "http://localhost:8501/"

def get_google_auth_url():
    base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
        "state": "google"
    }
    return f"{base_url}?{urllib.parse.urlencode(params)}"

def get_google_user(code):
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    response = requests.post(token_url, data=data)
    if response.status_code != 200:
        return None
    
    access_token = response.json().get("access_token")
    if not access_token:
        return None
        
    userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
    user_resp = requests.get(userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
    if user_resp.status_code != 200:
        return None
    return user_resp.json().get("email")

def get_github_auth_url():
    base_url = "https://github.com/login/oauth/authorize"
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "user:email",
        "state": "github"
    }
    return f"{base_url}?{urllib.parse.urlencode(params)}"

def get_github_user(code):
    token_url = "https://github.com/login/oauth/access_token"
    data = {
        "client_id": GITHUB_CLIENT_ID,
        "client_secret": GITHUB_CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    headers = {"Accept": "application/json"}
    response = requests.post(token_url, data=data, headers=headers)
    if response.status_code != 200:
        return None
        
    access_token = response.json().get("access_token")
    if not access_token:
        return None
        
    user_url = "https://api.github.com/user/emails"
    user_resp = requests.get(user_url, headers={"Authorization": f"token {access_token}"})
    if user_resp.status_code != 200:
        return None
    
    emails = user_resp.json()
    primary_email = next((email["email"] for email in emails if email["primary"]), None)
    return primary_email or (emails[0]["email"] if emails else None)
