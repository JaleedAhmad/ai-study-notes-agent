import os
import sys
import time
import traceback
from dotenv import load_dotenv
from google import genai
from openai import OpenAI

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
    Cascading generation hub providing absolute downtime insurance.
    Returns: (success: bool, text_payload: str, provider: str)
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
                    contents=prompt
                )
                elapsed = time.time() - start_llm
                print(f"LOG: [Gateway 4 (LLM Client Generation Hub)] -> Completed in {elapsed:.2f}s")
                return True, response.text, "Google Gemini"
            except Exception as e:
                print(f"[Tier 1 Error] Gemini failed: {e}", file=sys.stderr)
        else:
            print("[Tier 1 Warning] Gemini API Key missing.", file=sys.stderr)

        # Tier 2: Groq - Llama-3-70b
        if groq_client:
            try:
                print("Attempting Tier 2 (Groq llama-3.3-70b-versatile)...")
                response = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}]
                )
                elapsed = time.time() - start_llm
                print(f"LOG: [Gateway 4 (LLM Client Generation Hub)] -> Completed in {elapsed:.2f}s")
                return True, response.choices[0].message.content, "Groq"
            except Exception as e:
                print(f"[Tier 2 Error] Groq failed: {e}", file=sys.stderr)
        else:
            print("[Tier 2 Warning] Groq API Key missing.", file=sys.stderr)

        # Tier 3: Hugging Face - Meta-Llama-3
        if hf_client:
            try:
                print("Attempting Tier 3 (Hugging Face meta-llama/Meta-Llama-3-70B-Instruct)...")
                response = hf_client.chat.completions.create(
                    model="meta-llama/Meta-Llama-3-70B-Instruct",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=2048 # Explicit tokens added for HF compatibility just in case
                )
                elapsed = time.time() - start_llm
                print(f"LOG: [Gateway 4 (LLM Client Generation Hub)] -> Completed in {elapsed:.2f}s")
                return True, response.choices[0].message.content, "Hugging Face"
            except Exception as e:
                print(f"[Tier 3 Error] Hugging Face failed: {e}", file=sys.stderr)
        else:
            print("[Tier 3 Warning] Hugging Face API Key missing.", file=sys.stderr)

        # Total Failure
        print("[CRITICAL] All LLM endpoints failed.", file=sys.stderr)
        elapsed = time.time() - start_llm
        print(f"LOG: [Gateway 4 (LLM Client Generation Hub)] -> Completed in {elapsed:.2f}s")
        return False, "All LLM generation endpoints are currently unreachable. Please try again later.", "None"
    except Exception as e:
        print(f"LOG: [Gateway 4 (LLM Client Generation Hub)] -> Exception at {time.time()}: {traceback.format_exc()}")
        raise e
