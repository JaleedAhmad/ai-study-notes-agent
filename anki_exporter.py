import tempfile
import os
import uuid
import genanki
import random
from google import genai

def generate_anki_deck(notes_text):
    client = genai.Client()
    
    # Advanced logic prompt to strictly force the AI to return parseable data arrays
    extraction_prompt = f"""
    You are an expert educational assistant designed to extract spaced-repetition flashcards from study notes.
    Extract key facts, concepts, and definitions from the provided study notes.
    Format your response STRICTLY as a list of Question and Answer pairs.
    You MUST separate the question and the answer with ':::' and place each pair on a new line.
    DO NOT include any markdown formatting, numbers, bullet points, explanations, or introductory text.
    
    Example correct format:
    What is the powerhouse of the cell?:::The mitochondria.
    Who wrote Hamlet?:::William Shakespeare.
    
    Here are the study notes to extract flashcards from:
    {notes_text}
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=extraction_prompt
        )
        
        raw_output = response.text.strip()
        
        # Parse the output robustly
        cards = []
        for line in raw_output.split('\n'):
            if ':::' in line:
                parts = line.split(':::')
                if len(parts) == 2:
                    q = parts[0].strip().replace('*', '').replace('#', '')
                    a = parts[1].strip().replace('*', '').replace('#', '')
                    if q and a:
                        cards.append((q, a))
                        
        if not cards:
            return None
            
        # Genanki IDs must be unique numerical identifiers
        deck_id = random.randrange(1 << 30, 1 << 31)
        model_id = random.randrange(1 << 30, 1 << 31)
        
        # Create the Anki Model (Note Type HTML Structure)
        anki_model = genanki.Model(
            model_id,
            'Simple QA Model',
            fields=[
                {'name': 'Question'},
                {'name': 'Answer'},
            ],
            templates=[
                {
                    'name': 'Card 1',
                    'qfmt': '<h3 style="text-align:center; color:#333;">{{Question}}</h3>',
                    'afmt': '{{FrontSide}}<hr id="answer"><div style="text-align:center; font-style:italic;">{{Answer}}</div>',
                },
            ])
            
        # Create the active Deck
        deck = genanki.Deck(deck_id, "AI Study Notes Flashcards")
        
        # Hydrate the deck with cards
        for q, a in cards:
            note = genanki.Note(
                model=anki_model,
                fields=[q, a]
            )
            deck.add_note(note)
            
        # Serialize and Compile the SQLite .apkg file
        temp_filename = f"temp_deck_{uuid.uuid4().hex}.apkg"
        genanki.Package(deck).write_to_file(temp_filename)
        
        # Extract binary bytes back to streamlit memory
        with open(temp_filename, "rb") as f:
            deck_bytes = f.read()
            
        # Clean up temp file immediately to save disk
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
            
        return deck_bytes
    except Exception as e:
        print(f"Anki generation pipeline failed: {e}")
        return None
