"""
context_builder.py
------------------
Assembles the full prompt context (system + user) for an email reply drafting agent.

Schema expectations
-------------------
tone_profile.json  →  name, role, company, tone, voice_description,
                       traits[], do[], dont[], signature,
                       preferred_greetings[], preferred_signoffs[]

past_replies.json  →  list of { id, context, incoming_subject, reply }
"""

import json


# ---------------------------------------------------------------------------
# 1. Loaders
# ---------------------------------------------------------------------------

def load_tone_profile(path: str = "tone_profile.json") -> dict:
    """Read and return the tone profile dict from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_past_replies(path: str = "past_replies.json") -> list:
    """Read and return the list of past reply examples from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 2. Thread formatter
# ---------------------------------------------------------------------------

def format_thread_history(thread: dict) -> str:
    """
    Format a thread dict into a readable string.

    Expected shape:
        {
            "subject": str,
            "messages": [{"from": str, "date": str, "body": str}, ...]
        }
    """
    lines = [f"Subject: {thread.get('subject', '(no subject)')}"]
    lines.append("")

    for idx, msg in enumerate(thread.get("messages", []), start=1):
        lines.append(f"--- Message #{idx} ---")
        lines.append(f"From: {msg.get('from', 'Unknown')}")
        lines.append(f"Date: {msg.get('date', 'Unknown')}")
        lines.append("")
        lines.append(msg.get("body", "").strip())
        lines.append("")

    lines.append("--- END OF EMAIL THREAD ---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. Prompt builders
# ---------------------------------------------------------------------------

def build_system_prompt(tone_profile: dict, past_replies: list) -> str:
    """
    Build the system prompt from the rich tone profile and past reply examples.

    Uses: name, role, company, tone, voice_description, traits,
          do, dont, signature, preferred_greetings, preferred_signoffs
    """
    name        = tone_profile.get("name", "the user")
    role        = tone_profile.get("role", "professional")
    company     = tone_profile.get("company", "")
    tone        = tone_profile.get("tone", "neutral")
    voice_desc  = tone_profile.get("voice_description", "")
    traits      = tone_profile.get("traits", [])
    dos         = tone_profile.get("do", [])
    donts       = tone_profile.get("dont", [])
    signature   = tone_profile.get("signature", f"Best,\n{name}")
    greetings   = tone_profile.get("preferred_greetings", [f"Hi {{name}},"])
    signoffs    = tone_profile.get("preferred_signoffs", ["Best,"])

    lines = []

    # --- Identity ---
    lines += [
        f"You are an AI assistant drafting email replies on behalf of {name}.",
        f"{name} is a {role}{' at ' + company if company else ''}.",
        "",
    ]

    # --- Voice description ---
    if voice_desc:
        lines += [
            "Voice & Personality:",
            f"  {voice_desc}",
            "",
        ]

    # --- Tone & traits ---
    lines += [
        "Persona:",
        f"  - Name      : {name}",
        f"  - Role      : {role}",
        f"  - Company   : {company}" if company else "",
        f"  - Tone      : {tone}",
    ]
    lines = [l for l in lines if l != ""]  # strip blank placeholder lines

    if traits:
        lines.append("  - Traits    : " + ", ".join(traits))

    lines.append("")

    # --- DO rules ---
    if dos:
        lines.append("Always do:")
        for rule in dos:
            lines.append(f"  [DO]  {rule}")
        lines.append("")

    # --- DON'T rules ---
    if donts:
        lines.append("Never do:")
        for rule in donts:
            lines.append(f"  [NOT] {rule}")
        lines.append("")

    # --- Preferred greetings ---
    if greetings:
        lines.append("Preferred greetings (pick the most appropriate one):")
        for g in greetings:
            lines.append(f"  • {g}")
        lines.append("")

    # --- Preferred sign-offs ---
    if signoffs:
        lines.append("Preferred sign-offs (pick the most appropriate one):")
        for s in signoffs:
            lines.append(f"  • {s}")
        lines.append("")

    # --- Signature ---
    lines += [
        "Always end with this exact signature block:",
        signature,
        "",
    ]

    # --- Past reply examples (up to 3) ---
    examples = past_replies[:3]
    if examples:
        lines += [
            "-" * 60,
            f"Here's how {name} writes -- use these as style references:",
            "-" * 60,
            "",
        ]
        for reply in examples:
            ctx     = reply.get("context", "")
            subj    = reply.get("incoming_subject", "")
            body    = reply.get("reply", "").strip()
            eid     = reply.get("id", "")

            lines.append(f"Example {eid}:")
            if ctx:
                lines.append(f"  Situation : {ctx}")
            if subj:
                lines.append(f"  Subject   : {subj}")
            lines.append("")
            lines.append(body)
            lines.append("")
            lines.append("-" * 40)
            lines.append("")

    # --- Final instruction ---
    lines += [
        "When drafting the reply:",
        "  1. Match the tone, length, and structure shown in the examples above.",
        "  2. Follow every 'Always do' rule and avoid every 'Never do' rule.",
        "  3. Close with the exact signature block provided.",
        "  4. Return only the email body — no commentary, no preamble.",
    ]

    return "\n".join(lines)


def build_user_prompt(thread_formatted: str) -> str:
    """Build the user-facing message that asks the agent for a reply draft."""
    return (
        "Here is the email thread that needs a reply:\n\n"
        f"{thread_formatted}\n\n"
        "Draft a concise, on-brand reply in Rahul's voice as described in your instructions. "
        "Return only the email body — no extra commentary."
    )


# ---------------------------------------------------------------------------
# 4. Main assembler
# ---------------------------------------------------------------------------

def assemble_context(
    thread: dict,
    tone_path: str = "tone_profile.json",
    replies_path: str = "past_replies.json",
) -> dict:
    """
    Load tone profile and past replies, then build the full prompt context.

    Returns:
        {"system": <system_prompt_str>, "user": <user_prompt_str>}
    """
    tone_profile = load_tone_profile(tone_path)
    past_replies = load_past_replies(replies_path)

    thread_formatted = format_thread_history(thread)
    system_prompt    = build_system_prompt(tone_profile, past_replies)
    user_prompt      = build_user_prompt(thread_formatted)

    return {
        "system": system_prompt,
        "user": user_prompt,
    }


# ---------------------------------------------------------------------------
# 5. Demo / smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample_thread = {
        "subject": "Question about Q3 Product Roadmap",
        "messages": [
            {
                "from": "sarah.jenkins@acmecorp.com",
                "date": "2026-06-25 10:00 AM",
                "body": (
                    "Hi Rahul,\n\n"
                    "I was wondering if we have finalized the Q3 roadmap? "
                    "I need to communicate the priorities to my team before our "
                    "planning session on Friday.\n\n"
                    "Also — are the OKRs still the same, or have there been any updates?\n\n"
                    "Thanks,\nSarah"
                ),
            }
        ],
    }

    print("Assembling context using tone_profile.json and past_replies.json ...\n")
    context = assemble_context(sample_thread)

    sep = "=" * 60
    print(f"\n{sep}")
    print("SYSTEM PROMPT")
    print(sep)
    print(context["system"])

    print(f"\n{sep}")
    print("USER PROMPT")
    print(sep)
    print(context["user"])
    print(sep)
