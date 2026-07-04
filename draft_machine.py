"""
draft_machine.py
----------------
Generates email reply drafts using Gemini (gemini-2.5-flash).

Depends on:
  - context_builder.py  (assemble_context)
  - tone_profile.json
  - past_replies.json
  - .env               (GEMINI_API_KEY)

SDK: google-genai  (pip install google-genai)
"""

import os
import re
import sys
import time
import json
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from context_builder import assemble_context

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
load_dotenv(HERE / ".env", override=True)

MODEL_NAME   = "gemini-2.5-flash-lite"
MAX_RETRIES  = 5
RETRY_DELAY  = 12  # seconds between retries on 503

# Fallback chain: tried in order when a model is quota-exhausted
FALLBACK_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
]


def _get_api_key() -> str:
    """Validate and return the API key."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        err_msg = (
            "GEMINI_API_KEY not found. "
            "Please create a .env file with GEMINI_API_KEY=\"your-key-here\" "
            "or enter an override key in the sidebar."
        )
        print(f"\n[ERROR] {err_msg}\n")
        raise ValueError(err_msg)
    return api_key


# ---------------------------------------------------------------------------
# Drafting rules injected into every prompt
# ---------------------------------------------------------------------------

DRAFTING_RULES = """
---
DRAFTING RULES (non-negotiable):

ONE-ASK RULE
  Every reply contains exactly ONE clear question OR one clear response.
  Never stack multiple questions in the same email.

LENGTH CONTROL
  Match the energy of the incoming thread.
  Hard cap: 5 sentences max (excluding the signature).
  Use a short numbered list only if there are 3+ action items.

NO AI FILLER
  Never write these phrases (or close variants):
    - "I hope this finds you well"
    - "Thank you for reaching out"
    - "Please don't hesitate to reach out"
    - "As per my last email"
    - "I wanted to follow up"
    - "Certainly!" / "Absolutely!" / "Of course!"

STRUCTURE
  1. Acknowledge briefly (1 sentence max, only if needed)
  2. Give the response or answer
  3. ONE clear next step or question -- nothing else
---
"""


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def _compute_heuristic_confidence(draft: str, thread: dict) -> float:
    """
    Compute a heuristic confidence score in [0.0, 1.0] for the generated draft.

    Heuristics used (each contributes a small score):
      - length: drafts between 40 and 700 chars score higher
      - sentence count: 2-6 sentences is the sweet spot (matches DRAFTING_RULES)
      - has greeting (Hi/Hey/Hello/...)
      - has sign-off / signature line
      - contains an explicit question OR a clear next-step verb
      - thread has a clear subject
    """
    if not draft:
        return 0.0

    score = 0.0
    body  = draft.strip()
    lower = body.lower()
    length = len(body)

    # 1) Length sweet-spot (40-700 chars)
    if 40 <= length <= 700:
        score += 0.25
    elif 20 <= length < 40 or 700 < length <= 1000:
        score += 0.12

    # 2) Sentence count (2-6)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
    n_sent = len(sentences)
    if 2 <= n_sent <= 6:
        score += 0.20
    elif n_sent == 1 or n_sent == 7:
        score += 0.10

    # 3) Has greeting
    if re.match(r"^\s*(hi|hey|hello|good (morning|afternoon|evening)|dear)\b", lower):
        score += 0.10

    # 4) Has sign-off / signature line (Best,/Thanks,/Regards, + name)
    if re.search(r"\n\s*(best|thanks|regards|cheers|warm regards|kind regards)[,.]?", lower):
        score += 0.10

    # 5) Contains explicit question OR clear next-step verb
    has_question = "?" in body
    next_step_verbs = (
        "let me know", "can we", "could we", "shall we", "i'll", "i will",
        "schedule", "book", "send", "share", "confirm", "reply", "respond",
        "follow up", "loop in", "set up", "set a", "by eod", "by tomorrow",
        "by friday", "by monday",
    )
    has_next_step = any(v in lower for v in next_step_verbs)
    if has_question or has_next_step:
        score += 0.15

    # 6) Thread context quality (has subject + >=1 message with body)
    messages = thread.get("messages", []) if isinstance(thread, dict) else []
    subject  = (thread.get("subject") or "").strip() if isinstance(thread, dict) else ""
    if subject and any((m.get("body") or "").strip() for m in messages):
        score += 0.10

    # 7) No AI-filler phrases (penalty avoidance)
    filler = [
        "i hope this finds you well",
        "thank you for reaching out",
        "please don't hesitate",
        "as per my last email",
        "i wanted to follow up",
    ]
    if not any(f in lower for f in filler):
        score += 0.10

    # Clamp
    return max(0.0, min(1.0, round(score, 2)))


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def draft_reply(
    thread: dict,
    tone_path: str = None,
    replies_path: str = None,
    model_name: str = None,
) -> str:
    """
    Generate a draft email reply for the given thread.

    Args:
        thread:       Thread dict  {"subject": str, "messages": [...]}
        tone_path:    Path to tone_profile.json
        replies_path: Path to past_replies.json
        model_name:   Name of the Gemini model to use

    Returns:
        The raw draft text (no subject line, no explanation).
    """
    if tone_path is None:
        tone_path = str(Path(__file__).parent / "tone_profile.json")
    if replies_path is None:
        replies_path = str(Path(__file__).parent / "past_replies.json")

    api_key = _get_api_key()
    if model_name is None:
        model_name = os.getenv("GEMINI_MODEL", MODEL_NAME)

    # Assemble system + user prompts from context_builder
    context = assemble_context(thread, tone_path=tone_path, replies_path=replies_path)

    system_prompt = context["system"] + "\n" + DRAFTING_RULES
    user_prompt   = context["user"]

    gen_config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.7,
        max_output_tokens=1024,
    )

    # Build the list of models to try: requested model first, then fallbacks
    models_to_try = [model_name]
    for fb in FALLBACK_MODELS:
        if fb != model_name and fb not in models_to_try:
            models_to_try.append(fb)

    last_exc = None
    for current_model in models_to_try:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Create a fresh client for each attempt to avoid "client has been closed" errors
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=current_model,
                    contents=user_prompt,
                    config=gen_config,
                )
                if current_model != model_name:
                    print(f"\n[INFO] Draft generated using fallback model: {current_model}\n")
                return response.text.strip()
            except Exception as exc:
                last_exc = exc
                err_str = str(exc)
                is_503  = "503" in err_str or "UNAVAILABLE" in err_str
                is_429  = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str

                if is_429:
                    # Quota exhausted on this model — skip to next fallback immediately
                    print(f"\n[WARN] Quota exhausted for {current_model}, trying next model...\n")
                    break  # break inner retry loop, move to next model
                elif is_503 and attempt < MAX_RETRIES:
                    print(f"  [retry {attempt}/{MAX_RETRIES}] Model busy (503) for {current_model}, waiting {RETRY_DELAY}s ...")
                    time.sleep(RETRY_DELAY)
                elif is_503:
                    print(f"\n[WARN] {current_model} still unavailable after {MAX_RETRIES} retries, trying next model...\n")
                    break  # move to next fallback
                else:
                    raise  # unexpected error — surface immediately

    # All models exhausted
    raise RuntimeError(
        "All Gemini models have hit their quota limit. "
        "Please wait for your daily quota to reset or add a paid API key."
    ) from last_exc


def draft_reply_with_metadata(
    thread: dict,
    tone_path: str = None,
    replies_path: str = None,
    model_name: str = None,
) -> dict:
    """
    Generate a draft reply and return it alongside useful metadata.

    Returns a dict with:
        draft          - the generated email body
        model          - model name used
        thread_subject - subject line of the thread
        reply_to       - sender of the most recent incoming message
        confidence     - float in [0.0, 1.0] -- model's self-assessed confidence
    """
    if tone_path is None:
        tone_path = str(Path(__file__).parent / "tone_profile.json")
    if replies_path is None:
        replies_path = str(Path(__file__).parent / "past_replies.json")
    if model_name is None:
        model_name = os.getenv("GEMINI_MODEL", MODEL_NAME)

    messages = thread.get("messages", [])
    last_msg = messages[-1] if messages else {}
    reply_to = last_msg.get("from", "Unknown")
    subject  = thread.get("subject", "(no subject)")

    draft = draft_reply(thread, tone_path=tone_path, replies_path=replies_path, model_name=model_name)

    confidence = _compute_heuristic_confidence(draft, thread)

    return {
        "draft":          draft,
        "model":          model_name,
        "thread_subject": subject,
        "reply_to":       reply_to,
        "confidence":     confidence,
    }


# ---------------------------------------------------------------------------
# Sample threads for the UI demo
# ---------------------------------------------------------------------------

SAMPLE_THREADS = [
    {
        "subject": "Q3 Budget Review -- Need Your Sign-off",
        "messages": [
            {
                "from": "priya.sharma@acmecorp.com",
                "date": "2026-06-25 09:15 AM",
                "body": (
                    "Hi Rahul,\n\n"
                    "I've put together the Q3 budget breakdown for the product team. "
                    "Total ask is $180K -- split across contractor costs ($90K), "
                    "tooling ($50K), and a small UX research budget ($40K).\n\n"
                    "We need sign-off by end of week so finance can process it before "
                    "the quarter closes. Can you review and let me know if you're good "
                    "to approve, or if you'd like to discuss anything first?\n\n"
                    "Thanks,\nPriya"
                ),
            }
        ],
    },
    {
        "subject": "Quick question about Q3 Product Roadmap",
        "messages": [
            {
                "from": "sarah.jenkins@acmecorp.com",
                "date": "2026-06-25 10:00 AM",
                "body": (
                    "Hi Rahul,\n\n"
                    "I was wondering if we have finalized the Q3 roadmap? "
                    "I need to communicate the priorities to my team before our "
                    "planning session on Friday.\n\n"
                    "Also -- are the OKRs still the same, or have there been any updates?\n\n"
                    "Thanks,\nSarah"
                ),
            }
        ],
    },
    {
        "subject": "Vendor contract renewal -- Acme Analytics",
        "messages": [
            {
                "from": "contracts@acmevendor.com",
                "date": "2026-06-24 04:42 PM",
                "body": (
                    "Hello,\n\n"
                    "Your annual subscription with Acme Analytics is set to renew on "
                    "July 15, 2026 at the current rate of $24,000/year. Attached is the "
                    "renewal paperwork. Please countersign and return at your earliest "
                    "convenience, or reply if you'd like to negotiate terms.\n\n"
                    "Best,\nAcme Contracts Team"
                ),
            }
        ],
    },
]


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Use the first sample thread for the CLI demo
    sample_thread = SAMPLE_THREADS[0]

    print(f"Generating email draft with {MODEL_NAME} ...\n")

    result = draft_reply_with_metadata(sample_thread)

    sep = "=" * 60
    print(sep)
    print("DRAFT REPLY")
    print(sep)
    print(result["draft"])
    print(sep)
    print("\n[Metadata]")
    print(f"  Model          : {result['model']}")
    print(f"  Thread Subject : {result['thread_subject']}")
    print(f"  Replying to    : {result['reply_to']}")
    print(f"  Confidence     : {result['confidence']:.0%}")