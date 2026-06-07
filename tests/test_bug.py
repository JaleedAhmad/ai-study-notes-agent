from io import BytesIO
from pdf_reader import extract_text_from_pdf

# Mock Streamlit UploadedFile behavior
with open("test.pdf", "rb") as f:
    mock_uploaded_file = BytesIO(f.read())

print("First extraction:")
text1 = extract_text_from_pdf(mock_uploaded_file)
print(f"Length of text1: {len(text1)}")

print("\nSecond extraction (simulating Streamlit rerun on button click):")
text2 = extract_text_from_pdf(mock_uploaded_file)
print(f"Length of text2: {len(text2)}")
