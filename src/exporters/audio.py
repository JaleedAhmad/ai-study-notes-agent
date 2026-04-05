import re
import os
import uuid
from gtts import gTTS

def clean_markdown_for_speech(markdown_text):
    """
    Cleans markdown formatting elements from text so that the gTTS 
    robot speaks naturally without reading asterisks or hashes.
    """
    # Remove large markdown headings but keep text and add a period for natural pause
    text = re.sub(r'#+\s*(.*)', r'\1.', markdown_text)
    # Remove asterisks (bold/italics)
    text = re.sub(r'\*', '', text)
    # Remove underscores
    text = re.sub(r'_', '', text)
    # Remove code blocks
    text = re.sub(r'```.*?```', 'Code blocks omitted for audio.', text, flags=re.DOTALL)
    # Remove inline code marks
    text = re.sub(r'`(.*?)`', r'\1', text)
    # Replace newlines with spaces to prevent awkward pauses
    text = text.replace('\n', ' ')
    # Consolidate multiple spaces
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

def generate_audio_from_text(markdown_text):
    clean_text = clean_markdown_for_speech(markdown_text)
    if not clean_text:
        return None
        
    try:
        # Generate speech natively
        tts = gTTS(text=clean_text, lang='en', slow=False)
        
        # Save to temp file
        temp_filename = f"temp_podcast_{uuid.uuid4().hex}.mp3"
        tts.save(temp_filename)
        
        # Read raw bytes to send to streamlit
        with open(temp_filename, "rb") as f:
            audio_bytes = f.read()
            
        # Clean up temp file immediately to save disk
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
            
        return audio_bytes
    except Exception as e:
        print(f"Audio generation failed: {e}")
        return None
