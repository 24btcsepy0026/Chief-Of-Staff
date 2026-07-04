import json
import os
from datetime import datetime, timezone

LOG_FILE = "action_log.json"

def get_action_log():
    """Reads action_log.json and returns the full list.
    Returns [] if the file does not exist or is empty.
    """
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except (json.JSONDecodeError, OSError):
        return []

def log_action(action_type, thread_subject, detail, action_id):
    """Appends a record to action_log.json.
    Each record must have: timestamp (ISO format), action_type, thread_subject, detail, id
    action_type is either "sent" or "booked"
    detail is the recipient email (for "sent") or meeting title (for "booked")
    action_id is the Gmail message_id or Google Calendar event_id
    """
    logs = get_action_log()
    
    new_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action_type": action_type,
        "thread_subject": thread_subject,
        "detail": detail,
        "id": action_id
    }
    
    logs.append(new_entry)
    
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2)

def clear_log():
    """Writes an empty list to action_log.json."""
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)
