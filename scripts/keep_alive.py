import os
import sys
import requests
from supabase import create_client, Client
from dotenv import load_dotenv

def main():
    # Force environment reload safely
    load_dotenv()
    
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
    HF_SPACE_URL = os.environ.get("HF_SPACE_URL")
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("CRITICAL: Missing SUPABASE_URL or SUPABASE_KEY.")
        print("Please ensure these environment variables or GitHub secrets are set.")
        sys.exit(1)
        
    print(f"Connecting to Supabase at: {SUPABASE_URL}")
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Query a single row from the 'users' table to simulate database activity
        # This keeps the Supabase project awake preventing the 7-day inactivity pause
        res = supabase.table("users").select("id").limit(1).execute()
        
        print("Successfully queried the Supabase database.")
    except Exception as e:
        print(f"Failed to connect or query the database: {e}")
        sys.exit(1)
        
    if not HF_SPACE_URL:
        print("WARNING: Missing HF_SPACE_URL. Skipping Hugging Face Space ping.")
        print("Please ensure HF_SPACE_URL is set in environment variables or GitHub variables.")
    else:
        print(f"Pinging Hugging Face Space at: {HF_SPACE_URL}")
        try:
            # Add a small timeout so the action doesn't hang indefinitely
            response = requests.get(HF_SPACE_URL, timeout=15)
            response.raise_for_status()
            print(f"Successfully pinged Hugging Face Space (Status Code: {response.status_code}).")
        except Exception as e:
            print(f"Failed to ping Hugging Face Space: {e}")
            sys.exit(1)

    print("Keep-alive tasks completed successfully.")

if __name__ == "__main__":
    main()
