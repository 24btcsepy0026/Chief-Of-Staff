import os
import base64
import html
import json
from pathlib import Path
from datetime import datetime
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

HERE = Path(__file__).parent
TOKEN_PATH = str(HERE / "token.json")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar"
]

from google.auth.transport.requests import Request
# pyrefly: ignore [missing-import]
from google_auth_oauthlib.flow import InstalledAppFlow

def _get_credentials():
    creds = None
    if os.path.exists(TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
            # Explicit scope check: if loaded creds don't cover all required scopes, force re-auth
            if creds and (not creds.scopes or not all(s in creds.scopes for s in SCOPES)):
                creds = None
                try:
                    os.remove(TOKEN_PATH)
                except Exception:
                    pass
        except Exception as e:
            # If the token scope doesn't match or parsing fails, we run the flow
            creds = None
            try:
                os.remove(TOKEN_PATH)
            except Exception:
                pass

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds:
            client_secrets_path = HERE / "gmail-mcp-server" / "gcp-oauth.keys.json"
            if not client_secrets_path.exists():
                raise FileNotFoundError(f"Missing client secrets file at {client_secrets_path}")
            
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secrets_path), SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return creds

def get_gmail_service():
    return build("gmail", "v1", credentials=_get_credentials())

def get_calendar_service():
    return build("calendar", "v3", credentials=_get_credentials())

def fetch_threads(max_results: int = 20) -> list[dict]:
    """Returns last N threads as: thread_id, sender, subject, snippet, message_id"""
    service = get_gmail_service()
    
    # Default to pulling threads from the last 2 days (stretch goal)
    results = service.users().threads().list(userId="me", maxResults=max_results, q="newer_than:2d").execute()
    threads = results.get('threads', [])
    
    # Dynamic fallback: if we got fewer threads than requested, expand timeframe to 7 days
    if len(threads) < max_results:
        results = service.users().threads().list(userId="me", maxResults=max_results, q="newer_than:7d").execute()
        threads = results.get('threads', [])
    
    result_list = []
    for t in threads:
        thread_id = t['id']
        tdata = service.users().threads().get(userId='me', id=thread_id).execute()
        
        messages = tdata.get('messages', [])
        if not messages:
            continue
            
        first_msg = messages[0]
        snippet = first_msg.get('snippet', '')
        
        headers = first_msg['payload'].get('headers', [])
        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '(No Subject)')
        sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown')
        
        if '<' in sender and '>' in sender:
            sender = sender.split('<')[1].split('>')[0]
            
        # Extract Message-ID of the latest message for In-Reply-To
        last_msg = messages[-1]
        last_headers = last_msg.get('payload', {}).get('headers', [])
        message_id = next((h['value'] for h in last_headers if h['name'].lower() == 'message-id'), None)
            
        result_list.append({
            'thread_id': thread_id,
            'sender': html.unescape(sender),
            'from': html.unescape(sender),
            'subject': html.unescape(subject),
            'snippet': html.unescape(snippet),
            'message_id': message_id
        })
        
    return result_list

def send_reply(thread_id: str, to: str, subject: str, body: str, message_id: str = None) -> dict:
    """Send a reply to a thread using the Gmail API, setting appropriate threading headers."""
    service = get_gmail_service()
    
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to
    
    # Prefix subject with Re: if not already present
    if not subject.lower().startswith("re:"):
        msg["Subject"] = "Re: " + subject
    else:
        msg["Subject"] = subject
        
    if message_id:
        msg["In-Reply-To"] = message_id
        msg["References"] = message_id
        
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = service.users().messages().send(
        userId="me",
        body={"raw": raw, "threadId": thread_id}
    ).execute()
    
    # Ensure message_id is populated in result dictionary
    if sent and "id" in sent:
        sent["message_id"] = sent["id"]
        
    return sent

def send_approved_drafts():
    """Reads approved_drafts.json, sends each unsent draft, and updates the file."""
    approved_file = HERE / "approved_drafts.json"
    if not approved_file.exists():
        print("No approved_drafts.json file found.")
        return

    try:
        with open(approved_file, "r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception as e:
        print(f"Error reading approved drafts: {e}")
        return

    if not isinstance(records, list):
        print("Invalid format in approved_drafts.json")
        return

    unsent_records = [r for r in records if not r.get("sent_at")]
    if not unsent_records:
        print("No unsent approved drafts found.")
        return

    print(f"Found {len(unsent_records)} unsent draft(s). Sending...")
    
    updated = False
    for r in records:
        if not r.get("sent_at"):
            thread_id = r.get("thread_id")
            to = r.get("recipient_email") or r.get("reply_to")
            subject = r.get("thread_subject")
            body = r.get("draft")
            message_id = r.get("message_id")

            if not thread_id or not to or not body:
                print(f"Missing required fields for draft: {r.get('thread_subject', 'No Subject')}")
                continue

            try:
                print(f"Sending reply to {to} for thread '{subject}'...")
                sent = send_reply(
                    thread_id=thread_id,
                    to=to,
                    subject=subject,
                    body=body,
                    message_id=message_id
                )
                r["sent_at"] = datetime.now().isoformat(timespec="seconds")
                r["message_id"] = sent.get("id") or sent.get("message_id")
                updated = True
                print(f"✓ Sent successfully! Message ID: {r['message_id']}")
            except Exception as e:
                print(f"❌ Failed to send reply to {to}: {e}")

    if updated:
        with open(approved_file, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        print("Updated approved_drafts.json with sent timestamps.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "send":
        send_approved_drafts()
    else:
        # Default behavior: fetch threads and print them
        print("📬 Fetching recent threads...")
        try:
            threads = fetch_threads(max_results=5)
            for t in threads:
                print(f"- {t['subject']} (from: {t['sender']}, ID: {t['thread_id']})")
        except Exception as e:
            print(f"Error fetching threads: {e}")

