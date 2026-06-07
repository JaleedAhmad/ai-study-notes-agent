import sys
import os
from unittest.mock import patch, MagicMock

# Add parent to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core import llm_client

def test_full_cascade():
    print("--- Testing Full Cascade to Failure ---")
    
    # Mock all clients to throw exceptions
    with patch.object(llm_client, 'gemini_client') as mock_gemini, \
         patch.object(llm_client, 'groq_client') as mock_groq, \
         patch.object(llm_client, 'hf_client') as mock_hf:
        
        mock_gemini.models.generate_content.side_effect = Exception("Simulated Gemini Outage")
        mock_groq.chat.completions.create.side_effect = Exception("Simulated Groq Outage")
        mock_hf.chat.completions.create.side_effect = Exception("Simulated HF Outage")
        
        success, payload, provider = llm_client.generate_content("Hello, world!")
        print(f"Result: Success={success}, Provider={provider}")
        assert not success
        assert provider == "None"

def test_tier_2_fallback():
    print("\n--- Testing Tier 2 Fallback (Groq) ---")
    
    with patch.object(llm_client, 'gemini_client') as mock_gemini, \
         patch.object(llm_client, 'groq_client') as mock_groq:
        
        mock_gemini.models.generate_content.side_effect = Exception("Simulated Gemini Outage")
        
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Groq response"
        mock_groq.chat.completions.create.return_value = mock_response
        
        success, payload, provider = llm_client.generate_content("Hello, world!")
        print(f"Result: Success={success}, Provider={provider}")
        assert success
        assert provider == "Groq"
        assert payload == "Groq response"

def test_tier_3_fallback():
    print("\n--- Testing Tier 3 Fallback (HF) ---")
    
    with patch.object(llm_client, 'gemini_client') as mock_gemini, \
         patch.object(llm_client, 'groq_client') as mock_groq, \
         patch.object(llm_client, 'hf_client') as mock_hf:
        
        mock_gemini.models.generate_content.side_effect = Exception("Simulated Gemini Outage")
        mock_groq.chat.completions.create.side_effect = Exception("Simulated Groq Outage")
        
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "HF response"
        mock_hf.chat.completions.create.return_value = mock_response
        
        success, payload, provider = llm_client.generate_content("Hello, world!")
        print(f"Result: Success={success}, Provider={provider}")
        assert success
        assert provider == "Hugging Face"
        assert payload == "HF response"

if __name__ == "__main__":
    test_full_cascade()
    test_tier_2_fallback()
    test_tier_3_fallback()
    print("\nAll cascade logic paths verified!")
