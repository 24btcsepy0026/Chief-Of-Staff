import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google import genai
from google.genai import types

HERE = Path(__file__).parent
TOKEN_PATH = str(HERE / "token.json")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar"
]

def _build_calendar_service():
    """Build a Google Calendar v3 service using shared credentials."""
    from engine import _get_credentials
    creds = _get_credentials()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)

def parse_meeting_request(thread: dict) -> dict:
    """Use Gemini to extract structured meeting request details from the email thread with model fallbacks."""
    import time
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"parsing_error": "GEMINI_API_KEY not found in environment", "raw": ""}

    # Format the thread messages
    messages = thread.get("messages", [])
    history_text = f"Subject: {thread.get('subject', 'No Subject')}\n\n"
    for m in messages:
        history_text += f"From: {m.get('from', 'Unknown')}\n"
        history_text += f"Date: {m.get('date', 'Unknown')}\n"
        history_text += f"Body: {m.get('body', '')}\n"
        history_text += "-"*20 + "\n"

    today_str = datetime.now().strftime("%Y-%m-%d")
    prompt = (
        f"Today's date is: {today_str}.\n"
        "Read the following email thread history and extract details about the requested meeting.\n"
        "Return ONLY a valid JSON object. Do not include any explanation or markdown formatting. The JSON must match this structure:\n"
        "{\n"
        "  \"proposed_times\": [\"YYYY-MM-DDTHH:MM:SSZ\"],  // List of proposed start date/times in ISO-8601 format. Resolve relative terms like 'tomorrow', 'this Wednesday', 'next Friday at 2pm' using today's date.\n"
        "  \"attendees\": [\"email@example.com\"],  // List of email addresses of attendees mentioned in the thread.\n"
        "  \"topic\": \"Summary Topic\",  // A short one-line summary of the meeting.\n"
        "  \"duration_minutes\": 30  // The meeting duration in minutes (default to 30 if not specified).\n"
        "}\n\n"
        f"EMAIL THREAD:\n{history_text}"
    )

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash"
    ]

    client = genai.Client(api_key=api_key)
    last_error = None
    
    for model in models_to_try:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction="You are a precise scheduling assistant. You only output valid JSON matching the requested schema.",
                        temperature=0.1
                    )
                )
                
                text = response.text.strip()
                
                # Strip markdown code fences if present (e.g. ```json ... ```)
                if text.startswith("```"):
                    lines = text.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    text = "\n".join(lines).strip()
                    
                data = json.loads(text)
                return {
                    "proposed_times": data.get("proposed_times", []),
                    "attendees": data.get("attendees", []),
                    "topic": data.get("topic", thread.get("subject", "Meeting")),
                    "duration_minutes": int(data.get("duration_minutes", 30))
                }
            except Exception as e:
                last_error = e
                # Check for transient rate limit or service unavailable codes
                err_str = str(e).lower()
                if "503" in err_str or "429" in err_str or "unavailable" in err_str or "demand" in err_str:
                    time.sleep(1.0 * (attempt + 1))
                else:
                    break

    return {
        "parsing_error": f"All models failed. Last error: {last_error}",
        "raw": response.text if 'response' in locals() else ""
    }

def check_availability(time_min: str, time_max: str) -> bool:
    """Check if a time window on primary calendar is free using FreeBusy query."""
    try:
        service = _build_calendar_service()
        
        # Append "Z" to times that lack timezone info
        if not time_min.endswith("Z") and "+" not in time_min and "-" not in time_min[10:]:
            time_min += "Z"
        if not time_max.endswith("Z") and "+" not in time_max and "-" not in time_max[10:]:
            time_max += "Z"
            
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": "primary"}]
        }
        
        res = service.freebusy().query(body=body).execute()
        calendars = res.get("calendars", {})
        primary = calendars.get("primary", {})
        busy = primary.get("busy", [])
        
        return len(busy) == 0
    except Exception as e:
        print(f"Error checking availability: {e}")
        return False

def find_free_slot(proposed_times: list, duration_minutes: int) -> str | None:
    """Find the first available time slot from the proposed times list."""
    from datetime import timezone
    for pt in proposed_times:
        try:
            pt_norm = pt
            if not pt_norm.endswith("Z") and "+" not in pt_norm and "-" not in pt_norm[10:]:
                pt_norm += "Z"
                
            dt_str = pt_norm.replace("Z", "+00:00")
            start_dt = datetime.fromisoformat(dt_str)
            end_dt = start_dt + timedelta(minutes=duration_minutes)
            
            # Normalize to UTC
            start_utc = start_dt.astimezone(timezone.utc)
            end_utc = end_dt.astimezone(timezone.utc)
            
            time_min = start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            time_max = end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            
            if check_availability(time_min, time_max):
                return pt
        except Exception as e:
            print(f"Skipped malformed proposed time '{pt}': {e}")
            continue
    return None

def create_event(summary: str, start_time: str, duration_minutes: int, attendees: list, description: str = "") -> dict:
    """Create a Google Calendar event on primary calendar."""
    from datetime import timezone
    service = _build_calendar_service()
    
    start_norm = start_time
    if not start_norm.endswith("Z") and "+" not in start_norm and "-" not in start_norm[10:]:
        start_norm += "Z"
        
    dt_str = start_norm.replace("Z", "+00:00")
    start_dt = datetime.fromisoformat(dt_str)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    
    # Normalize to UTC
    start_utc = start_dt.astimezone(timezone.utc)
    end_utc = end_dt.astimezone(timezone.utc)
    
    # Filter attendees with valid email addresses containing '@'
    valid_attendees = [{"email": a.strip()} for a in attendees if isinstance(a, str) and "@" in a]
    
    event_body = {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timeZone": "UTC"
        },
        "end": {
            "dateTime": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timeZone": "UTC"
        },
        "attendees": valid_attendees
    }
    
    res = service.events().insert(
        calendarId="primary",
        body=event_body,
        sendUpdates="all"
    ).execute()
    
    return res
