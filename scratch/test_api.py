import os
import traceback
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

try:
    print("Testing with gemini-flash-latest...")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents="Hello",
    )
    print("Success! Response:")
    print(response.text)
except Exception as e:
    print("Failed:")
    traceback.print_exc()
