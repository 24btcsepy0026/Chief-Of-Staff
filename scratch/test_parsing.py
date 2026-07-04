import os
import json
from pathlib import Path
from dotenv import load_dotenv

HERE = Path(__file__).parent.parent
load_dotenv(HERE / ".env", override=True)

import sys
sys.path.insert(0, str(HERE))

from calendar_engine import parse_meeting_request

# Load sample threads
with open(HERE / "sample_threads.json", "r", encoding="utf-8") as f:
    threads = json.load(f)

for t in threads:
    subj = t.get("subject", "")
    if "note" in subj.lower() or "design" in subj.lower():
        print(f"Testing Thread: {subj}")
        res = parse_meeting_request(t)
        print(json.dumps(res, indent=2))
        print("-" * 40)
