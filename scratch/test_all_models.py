import os
import sys
from dotenv import load_dotenv
from google import genai

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("Error: GEMINI_API_KEY not found in .env")
    sys.exit(1)

client = genai.Client(api_key=api_key)
models = [
    'gemini-2.0-flash',
    'gemini-3.5-flash',
    'gemini-2.5-flash',
    'gemini-2.5-pro',
    'gemini-flash-latest',
    'gemini-1.5-flash',
    'gemini-1.5-pro'
]

print(f"API Key: {api_key[:8]}...{api_key[-4:] if len(api_key) > 8 else ''}")
print("Testing models:")
for m in models:
    try:
        response = client.models.generate_content(model=m, contents="Hello")
        print(f"  {m}: SUCCESS")
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
            print(f"  {m}: FAILED (429 Quota Exhausted)")
        else:
            print(f"  {m}: FAILED ({type(e).__name__}: {err_msg[:80]})")
