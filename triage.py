import os
import time
import re
import json
from pathlib import Path
from google import genai
from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env", override=True)

def _get_api_key():
    """Get and validate the API key."""
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables")
    return api_key

MODEL = "gemini-2.5-flash-lite"  # Default model

# Fallback chain: tried in order when a model is quota-exhausted
FALLBACK_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
]

CACHE_FILE = str(HERE / "triage_cache.json")

# ──────────────────────────────────────────────
# Cache helpers — saves API calls across runs
# ──────────────────────────────────────────────

def load_cache() -> dict:
    """Load previously classified thread_ids from disk."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache: dict):
    """Persist the cache to disk."""
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

# ──────────────────────────────────────────────
# Batch prompt
# ──────────────────────────────────────────────

BATCH_PROMPT_TEMPLATE = """
You are an expert email triage assistant.
Classify each of the {count} email threads below.

For each email use EXACTLY one of these priorities:
  URGENT      — needs action today, time-sensitive
  NEEDS-REPLY — requires a response within 24-48 hours
  FYI         — informational, no action needed
  IGNORE      — no value, can be archived

Also provide a short Category (e.g. Newsletter, Client Request, Alert)
and a one-sentence Reason for your classification.

Return ONLY this exact block for every email — no extra text:

Email <N>:
Priority: <priority>
Category: <category>
Reason: <reason>

---EMAILS---
{emails}
"""

def _build_email_block(threads: list) -> str:
    parts = []
    for i, t in enumerate(threads, 1):
        parts.append(
            f"Email {i}:\n"
            f"Sender: {t.get('from', 'Unknown')}\n"
            f"Subject: {t.get('subject', '(no subject)')}\n"
            f"Snippet: {t.get('snippet', '')}"
        )
    return "\n\n".join(parts)

def _parse_batch_response(text: str, count: int) -> list:
    """Parse the batch response into an ordered list of classification dicts."""
    pattern = r'Email\s+(\d+)\s*:\s*\n(.*?)(?=Email\s+\d+\s*:|$)'
    matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)

    parsed = {}
    for num_str, block in matches:
        num = int(num_str)
        entry = {"priority": "IGNORE", "category": "Unknown", "reason": "Failed to parse"}
        for line in block.strip().split('\n'):
            line = line.strip()
            if line.lower().startswith("priority:"):
                entry["priority"] = line.split(":", 1)[1].strip().upper()
            elif line.lower().startswith("category:"):
                entry["category"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("reason:"):
                entry["reason"] = line.split(":", 1)[1].strip()
        entry["priority"] = _normalize_priority(entry["priority"])
        parsed[num] = entry

    return [parsed.get(i, {"priority": "IGNORE", "category": "Unknown", "reason": "Not classified"})
            for i in range(1, count + 1)]

def _normalize_priority(p: str) -> str:
    if p in ("URGENT", "NEEDS-REPLY", "FYI", "IGNORE"):
        return p
    if "URGENT" in p:        return "URGENT"
    if "NEEDS-REPLY" in p:   return "NEEDS-REPLY"
    if "FYI" in p:           return "FYI"
    return "IGNORE"

# ──────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────

PRIORITY_ORDER = {"URGENT": 0, "NEEDS-REPLY": 1, "FYI": 2, "IGNORE": 3}

def triage_inbox(threads: list) -> list:
    """
    Classify threads using a local cache + one batch API call for new threads.
    Threads already seen today are served from cache — zero API calls.
    """
    cache = load_cache()
    cached_results = []
    new_threads = []

    for t in threads:
        tid = t.get("thread_id", "")
        if tid and tid in cache:
            # Restore from cache
            cached_results.append({**t, **cache[tid]})
        else:
            new_threads.append(t)

    cached_count = len(cached_results)
    new_count = len(new_threads)

    if cached_count:
        print(f"  [CACHE] {cached_count} thread(s) loaded from cache (no API call needed).")
    if new_count == 0:
        print("  [OK] All threads served from cache!")
        return _sort(cached_results)

    print(f"  [GEMINI] Sending {new_count} new thread(s) in one batch call...")

    classifications = _batch_classify(new_threads)

    # Merge, cache, and combine
    for t, cls in zip(new_threads, classifications):
        tid = t.get("thread_id", "")
        if tid:
            # Only cache if it's a successful classification, not an API error
            if cls.get("category") != "Error" and not str(cls.get("reason", "")).startswith("API error"):
                cache[tid] = cls
        cached_results.append({**t, **cls})

    save_cache(cache)
    print(f"  [DONE] {new_count} classified, {cached_count} from cache.")
    return _sort(cached_results)


def _sort(results: list) -> list:
    return sorted(results, key=lambda x: PRIORITY_ORDER.get(x.get("priority", "IGNORE"), 3))


def _batch_classify(threads: list) -> list:
    """Send all threads in one prompt; retry with backoff on transient errors; fall back model chain."""
    email_block = _build_email_block(threads)
    prompt = BATCH_PROMPT_TEMPLATE.format(count=len(threads), emails=email_block)

    model_name = os.getenv("GEMINI_MODEL", MODEL)
    api_key = _get_api_key()

    # Build fallback chain
    models_to_try = [model_name]
    for fb in FALLBACK_MODELS:
        if fb != model_name and fb not in models_to_try:
            models_to_try.append(fb)

    for current_model in models_to_try:
        max_retries = 3
        delay = 15
        for attempt in range(max_retries):
            try:
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(model=current_model, contents=prompt)
                if current_model != model_name:
                    print(f"  [INFO] Batch triage used fallback model: {current_model}")
                return _parse_batch_response(response.text, len(threads))
            except Exception as e:
                err = str(e)
                is_429 = "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err
                is_503 = "503" in err or "UNAVAILABLE" in err
                if is_429:
                    print(f"  [WARN] Quota exhausted for {current_model}, trying next model...")
                    break  # move to next model
                elif is_503 and attempt < max_retries - 1:
                    print(f"  [WAIT] {current_model} busy, waiting {delay}s (attempt {attempt+1}/{max_retries})...")
                    time.sleep(delay)
                    delay *= 2
                else:
                    print(f"  [WARN] Batch failed for {current_model} ({err[:60]}), trying one-by-one...")
                    return _individual_classify(threads)

    # All models quota-exhausted — fall back to individual (which has its own chain)
    return _individual_classify(threads)


def _individual_classify(threads: list) -> list:
    """Last-resort: one API call per thread, walking the fallback model chain."""
    results = []
    model_name = os.getenv("GEMINI_MODEL", MODEL)
    api_key = _get_api_key()

    # Build fallback chain
    models_to_try = [model_name]
    for fb in FALLBACK_MODELS:
        if fb != model_name and fb not in models_to_try:
            models_to_try.append(fb)

    for i, t in enumerate(threads):
        if i > 0:
            time.sleep(4)
        prompt = (
            "Classify this email. Return ONLY:\nPriority: <p>\nCategory: <c>\nReason: <r>\n\n"
            f"Sender: {t.get('from','')}\nSubject: {t.get('subject','')}\nSnippet: {t.get('snippet','')}"
        )
        classified = False
        for current_model in models_to_try:
            try:
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(model=current_model, contents=prompt)
                results.append(_parse_single(response.text.strip()))
                classified = True
                break
            except Exception as e:
                err = str(e)
                is_429 = "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower()
                if is_429:
                    print(f"  [WARN] Quota exhausted for {current_model}, trying next model...")
                    continue  # try next model
                else:
                    print(f"  [WARN] {current_model} failed: {err[:60]}")
                    break
        if not classified:
            results.append({"priority": "IGNORE", "category": "Error", "reason": "All models quota exhausted"})
    return results


def _parse_single(text: str) -> dict:
    result = {"priority": "IGNORE", "category": "Unknown", "reason": "Failed to parse"}
    for line in text.split('\n'):
        line = line.strip()
        if line.lower().startswith("priority:"):
            result["priority"] = _normalize_priority(line.split(":", 1)[1].strip().upper())
        elif line.lower().startswith("category:"):
            result["category"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("reason:"):
            result["reason"] = line.split(":", 1)[1].strip()
    return result


def parse_triage_response(text: str) -> dict:
    """Parses 'Priority: / Category: / Reason:' lines from Gemini's response."""
    return _parse_single(text)


def triage_thread(sender: str, subject: str, snippet: str) -> dict:
    """Classifies a single email thread (sender + subject + snippet) into priority + category + reason."""
    prompt = (
        "You are an expert email triage assistant.\n"
        "Classify the email thread below. Use EXACTLY one of these priorities:\n"
        "  URGENT      — needs action today, time-sensitive\n"
        "  NEEDS-REPLY — requires a response within 24-48 hours\n"
        "  FYI         — informational, no action needed\n"
        "  IGNORE      — no value, can be archived\n\n"
        "Also provide a short Category (e.g. Newsletter, Client Request, Alert) "
        "and a one-sentence Reason for your classification.\n\n"
        "Return ONLY this exact format - no extra text:\n"
        "Priority: <priority>\n"
        "Category: <category>\n"
        "Reason: <reason>\n\n"
        f"Sender: {sender}\nSubject: {subject}\nSnippet: {snippet}"
    )
    model_name = os.getenv("GEMINI_MODEL", MODEL)
    api_key = _get_api_key()

    # Build fallback chain
    models_to_try = [model_name]
    for fb in FALLBACK_MODELS:
        if fb != model_name and fb not in models_to_try:
            models_to_try.append(fb)

    for current_model in models_to_try:
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model=current_model, contents=prompt)
            return parse_triage_response(response.text.strip())
        except Exception as e:
            err = str(e)
            is_429 = "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower()
            if is_429:
                print(f"  [WARN] Quota exhausted for {current_model}, trying next model...")
                continue
            return {"priority": "IGNORE", "category": "Error", "reason": f"API error: {str(e)[:60]}"}

    return {"priority": "IGNORE", "category": "Error", "reason": "All models quota exhausted"}

