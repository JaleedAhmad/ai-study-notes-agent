import os
import sys
import time
import traceback
from dotenv import load_dotenv
from google import genai
from openai import OpenAI
from ..utils.generation_validation import gemini_text, openai_text, MAX_OUTPUT_TOKENS, FAILURE_MESSAGE

load_dotenv()

# Initialize Tier 1 Client (Google Gemini)
try:
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
except Exception as e:
    gemini_client = None
    print(f"Failed to initialize Gemini client: {e}", file=sys.stderr)

# Initialize Tier 2 Client (Groq)
groq_api_key = os.getenv("GROQ_API_KEY")
groq_client = OpenAI(api_key=groq_api_key, base_url="https://api.groq.com/openai/v1") if groq_api_key else None

# Initialize Tier 3 Client (Hugging Face)
hf_api_key = os.getenv("HUGGINGFACE_API_KEY")
hf_client = OpenAI(api_key=hf_api_key, base_url="https://api-inference.huggingface.co/v1") if hf_api_key else None

def generate_content(prompt):
    """
    Cascading generation with validated payloads and explicit completion evidence.
    Returns: (success: bool, text_payload: str, provider: str).
    Success means usable text, not certified completeness or accuracy. The
    string-compatible payload carries reported_finished or unknown metadata.
    """
    print("LOG: [Gateway 4 (LLM Client Generation Hub)] -> Started...")
    start_llm = time.time()
    try:
        # Tier 1: Google Gemini 2.5 Flash
        if gemini_client:
            try:
                print("Attempting Tier 1 (Google Gemini 2.5 Flash)...")
                response = gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config={"max_output_tokens": MAX_OUTPUT_TOKENS}
                )
                payload = gemini_text(response)
                elapsed = time.time() - start_llm
                print(f"LOG: [Gateway 4 (LLM Client Generation Hub)] -> Completed in {elapsed:.2f}s")
                return True, payload, "Google Gemini"
            except Exception as e:
                print("[Tier 1 Error] Gemini did not return a usable finished response.", file=sys.stderr)
        else:
            print("[Tier 1 Warning] Gemini API Key missing.", file=sys.stderr)

        # Tier 2: Groq - Llama-3-70b
        if groq_client:
            try:
                print("Attempting Tier 2 (Groq llama-3.3-70b-versatile)...")
                response = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=MAX_OUTPUT_TOKENS
                )
                payload = openai_text(response)
                elapsed = time.time() - start_llm
                print(f"LOG: [Gateway 4 (LLM Client Generation Hub)] -> Completed in {elapsed:.2f}s")
                return True, payload, "Groq"
            except Exception as e:
                print("[Tier 2 Error] Groq did not return a usable finished response.", file=sys.stderr)
        else:
            print("[Tier 2 Warning] Groq API Key missing.", file=sys.stderr)

        # Tier 3: Hugging Face - Meta-Llama-3
        if hf_client:
            try:
                print("Attempting Tier 3 (Hugging Face meta-llama/Meta-Llama-3-70B-Instruct)...")
                response = hf_client.chat.completions.create(
                    model="meta-llama/Meta-Llama-3-70B-Instruct",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=MAX_OUTPUT_TOKENS
                )
                payload = openai_text(response)
                elapsed = time.time() - start_llm
                print(f"LOG: [Gateway 4 (LLM Client Generation Hub)] -> Completed in {elapsed:.2f}s")
                return True, payload, "Hugging Face"
            except Exception as e:
                print("[Tier 3 Error] Hugging Face did not return a usable finished response.", file=sys.stderr)
        else:
            print("[Tier 3 Warning] Hugging Face API Key missing.", file=sys.stderr)

        # Total Failure
        print("[CRITICAL] All LLM endpoints failed.", file=sys.stderr)
        elapsed = time.time() - start_llm
        print(f"LOG: [Gateway 4 (LLM Client Generation Hub)] -> Completed in {elapsed:.2f}s")
        return False, FAILURE_MESSAGE, "None"
    except Exception as e:
        print(f"LOG: [Gateway 4 (LLM Client Generation Hub)] -> Exception at {time.time()}: {traceback.format_exc()}")
        raise e
