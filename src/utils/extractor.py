import io
import docx
import pptx
from pypdf import PdfReader

def extract_universal_text(uploaded_file):
    """
    Extracts text from uploaded files universally supporting PDF, DOCX, PPTX, TXT, and MD.
    Expects a Streamlit UploadedFile or file-like object with a `.name` attribute.
    """
    try:
        filename = uploaded_file.name.lower()
        
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)
            
        if filename.endswith(".pdf"):
            reader = PdfReader(uploaded_file)
            text = ""
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            return text
            
        elif filename.endswith(".docx"):
            doc = docx.Document(uploaded_file)
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
            return text
            
        elif filename.endswith(".pptx"):
            prs = pptx.Presentation(uploaded_file)
            text = ""
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "has_text_frame") and shape.has_text_frame:
                        text += shape.text + "\n"
            return text
            
        elif filename.endswith(".txt") or filename.endswith(".md"):
            content = uploaded_file.read()
            if isinstance(content, bytes):
                return content.decode("utf-8", errors="replace")
            return str(content)
            
        else:
            return ""
            
    except Exception as e:
        print(f"Extraction error: {e}")
        return ""
