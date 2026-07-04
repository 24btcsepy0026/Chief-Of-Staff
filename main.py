import sys
import io
import re

# We need to set standard output encoding to utf-8 so emojis print correctly on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from engine import fetch_threads
from triage import triage_inbox
from digest import format_digest, export_html

def main():
    print("📬 Fetching your last 35 threads...")
    threads = fetch_threads(max_results=35)
    print(f"✓ Got {len(threads)} threads.\n")
    
    print("🧠 Classifying with Gemini (this may take a few minutes)...")
    results = triage_inbox(threads)
    print("✓ Classification complete.\n")
    
    digest = format_digest(results)
    print(digest)
    
    # Save the digest to a file
    with open("digest_output.txt", "w", encoding="utf-8") as f:
        # Write an uncolored version for the text file by stripping ansi
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        uncolored = ansi_escape.sub('', digest)
        f.write(uncolored)
        
    export_html(results, "digest.html")
    print("\nSaved digest to digest_output.txt and digest.html")

if __name__ == "__main__":
    main()
