from google import genai
from google.genai import types
from .prompts import STUDY_AGENT_PROMPT
import os
from dotenv import load_dotenv

# Load API key from .env
load_dotenv()

# We initialize the Gemini client. It expects GEMINI_API_KEY to be present in the environment
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def generate_study_notes(text, tone="Academic", focus="General Summary", length="Medium", use_web_search=False):
    prompt = f"""
    You are an AI Study Notes Agent designed to help students understand study material.

    Analyze the provided content and convert it into structured learning notes.
    Please customize the notes strictly according to these preferences:
    - Tone: {tone}
    - Focus: {focus}  (Make sure the entire structure highlights this focus area)
    - Length: {length}

    Content to analyze:
    {text}
    """
    
    config = types.GenerateContentConfig()
    if use_web_search:
        config.tools = [{"google_search": {}}]

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=config
    )

    return response.text

def initialize_chat(pdf_text, chat_history=None, use_web_search=False):
    from google.genai import types
    history_content = []
    if chat_history:
        for msg in chat_history:
            role = "user" if msg["role"] == "user" else "model"
            history_content.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))
            
    config = types.GenerateContentConfig(
        system_instruction=f"You are a helpful AI study tutor. Answer the student's questions based primarily on the following study material context.\n\nContext:\n{pdf_text}",
        temperature=0.3
    )
    
    if use_web_search:
        config.tools = [{"google_search": {}}]
            
    chat = client.chats.create(
        model="gemini-2.5-flash",
        history=history_content if chat_history else None,
        config=config
    )
    return chat

def send_chat_message(chat_session, user_message):
    response = chat_session.send_message(user_message)
    return response.text
