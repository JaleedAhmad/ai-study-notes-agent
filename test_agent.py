from agent import generate_study_notes

try:
    print("Testing API call...")
    notes = generate_study_notes("This is a test of the study notes generator.")
    print("Success! Output snippet:")
    print(notes[:100])
except Exception as e:
    print(f"Error occurred: {e}")
