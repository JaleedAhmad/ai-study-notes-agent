import time
import sys
import base64
import re
from io import BytesIO
import traceback
from PIL import Image
from .llm_client import gemini_client, groq_client
from ..utils.extraction_validation import ExtractionError, validate_extracted_text


def _validated_ocr_text(text):
    text = validate_extracted_text(text)
    # An error envelope is not a successful provider transcription. Do not
    # blacklist ordinary study text merely because it discusses errors.
    stripped = text.strip()
    if re.fullmatch(r"\[error:[^\[\]]*\]", stripped, re.IGNORECASE | re.DOTALL):
        raise ExtractionError("Image text extraction failed. Please try again.")
    return text

def extract_text_from_image(image: Image.Image) -> str:
    """
    Extracts text, handwriting, and structural info from an image using a cascading fallback strategy.
    Tier 1: Google Gemini 2.5 Flash
    Tier 2: Groq Llama 3.2 11B Vision
    Returns validated text or raises ExtractionError after both tiers fail.
    """
    prompt = "Extract all text, handwriting, and structural information from this image perfectly as markdown. Ignore non-informational background elements or formatting artifacts. Render all mathematical formulas strictly using LaTeX."
    
    print("LOG: [Vision Client] -> Started...")
    start_time = time.time()
    
    # Tier 1: Gemini 2.5 Flash
    if gemini_client:
        try:
            print("Attempting Tier 1 Vision (Google Gemini 2.5 Flash)...")
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[image, prompt]
            )
            text = _validated_ocr_text(response.text)
            elapsed = time.time() - start_time
            print(f"LOG: [Vision Client] -> Completed in {elapsed:.2f}s (Gemini)")
            return text
        except Exception:
            print("[Tier 1 Vision Error] Gemini returned no usable result.", file=sys.stderr)
    else:
        print("[Tier 1 Vision Warning] Gemini API Key missing.", file=sys.stderr)

    # Tier 2: Groq Llama Vision Fallback
    if groq_client:
        try:
            print("Attempting Tier 2 Vision (Groq llama-3.2-11b-vision-preview)...")
            # Convert PIL image to base64
            buffered = BytesIO()
            if image.mode != "RGB":
                image = image.convert("RGB")
            image.save(buffered, format="JPEG")
            base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')
            
            response = groq_client.chat.completions.create(
                model="llama-3.2-11b-vision-preview",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ]
            )
            text = _validated_ocr_text(response.choices[0].message.content)
            elapsed = time.time() - start_time
            print(f"LOG: [Vision Client] -> Completed in {elapsed:.2f}s (Groq)")
            return text
        except Exception:
            print("[Tier 2 Vision Error] Groq returned no usable result.", file=sys.stderr)
    else:
        print("[Tier 2 Vision Warning] Groq API Key missing.", file=sys.stderr)

    # Total Failure
    print("[CRITICAL Vision] All Vision endpoints failed.", file=sys.stderr)
    elapsed = time.time() - start_time
    print(f"LOG: [Vision Client] -> Completed in {elapsed:.2f}s (Failed)")
    raise ExtractionError("Image text extraction failed. Please try again.")
