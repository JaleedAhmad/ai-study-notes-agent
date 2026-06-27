import time
import sys
import base64
from io import BytesIO
import traceback
from PIL import Image
from .llm_client import gemini_client, groq_client

def extract_text_from_image(image: Image.Image) -> str:
    """
    Extracts text, handwriting, and structural info from an image using a cascading fallback strategy.
    Tier 1: Google Gemini 2.5 Flash
    Tier 2: Groq Llama 3.2 11B Vision
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
            elapsed = time.time() - start_time
            print(f"LOG: [Vision Client] -> Completed in {elapsed:.2f}s (Gemini)")
            return response.text if response.text else ""
        except Exception as e:
            print(f"[Tier 1 Vision Error] Gemini failed: {e}", file=sys.stderr)
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
            elapsed = time.time() - start_time
            print(f"LOG: [Vision Client] -> Completed in {elapsed:.2f}s (Groq)")
            return response.choices[0].message.content
        except Exception as e:
            print(f"[Tier 2 Vision Error] Groq failed: {e}", file=sys.stderr)
    else:
        print("[Tier 2 Vision Warning] Groq API Key missing.", file=sys.stderr)

    # Total Failure
    print("[CRITICAL Vision] All Vision endpoints failed.", file=sys.stderr)
    elapsed = time.time() - start_time
    print(f"LOG: [Vision Client] -> Completed in {elapsed:.2f}s (Failed)")
    return "[Error: Vision extraction failed. All OCR endpoints are currently unreachable.]"
