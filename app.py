# -*- coding: utf-8 -*-
"""
app.py - The Draft Desk
=======================
Unified Streamlit UI for the AI Email Ghostwriter pipeline.

Phases (sidebar navigation):
  1. Inbox & Triage     - fetch threads, classify priorities
  2. Draft Generation   - generate on-brand AI reply drafts
  3. Approval Gate      - human-in-the-loop review: approve/edit/reject
  4. Export Proof       - download proof-of-work bundle (Markdown + HTML)

Run with:
    streamlit run app.py
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
import streamlit as st
from draft_machine import draft_reply
from task_logger import log_action, get_action_log

# ---------------------------------------------------------------------------
# Page config - must be the first Streamlit command in the script
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="The Draft Desk",
    page_icon="\u270D\uFE0F",   # writing hand ✍️
    layout="wide",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HERE            = Path(__file__).parent
load_dotenv(HERE / ".env", override=True)
SAMPLE_FILE     = HERE / "sample_threads.json"
PHASES          = ["Inbox & Triage", "Draft Generation", "Approval Gate", "Export Proof"]
PRIORITY_ORDER  = ["URGENT", "NEEDS-REPLY", "FYI", "IGNORE"]
PRIORITY_EMOJI  = {"URGENT": "\U0001F6A8", "NEEDS-REPLY": "\u21A9\uFE0F",
                   "FYI": "\u2139\uFE0F",  "IGNORE": "\u0001\uFE0F"}
PRIORITY_COLOR  = {"URGENT": "#e94560", "NEEDS-REPLY": "#ffd86b",
                   "FYI": "#8be9fd",   "IGNORE": "#6c757d"}

# ---------------------------------------------------------------------------
# Theme CSS
# ---------------------------------------------------------------------------

st.markdown(
    '''
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

        .stApp { background-color: #1a1a2e; color: #f1f1f1; }
        section[data-testid="stSidebar"] { background-color: #16213e; }

        /* ---- Phase 1: Thread cards ---- */
        .thread-card {
            background-color: #0f3460; border-radius: 8px;
            padding: 14px 18px; margin-bottom: 10px;
            color: #f1f1f1; font-size: 14px; line-height: 1.55;
        }
        .thread-card .meta { color: #8be9fd; font-size: 12px; margin-bottom: 4px; }
        .thread-card .meta b { color: #ffd86b; }
        .thread-card.urgent    { border-left: 4px solid #e94560; }
        .thread-card.reply     { border-left: 4px solid #ffd86b; }
        .thread-card.fyi       { border-left: 4px solid #8be9fd; }
        .thread-card.ignore    { border-left: 4px solid #6c757d; opacity: 0.75; }

        /* ---- Phase headers ---- */
        .phase-header { color: #ffffff; font-size: 28px; font-weight: 700; margin-bottom: 6px; }
        .phase-sub    { color: #8be9fd; font-size: 14px; margin-bottom: 20px; }

        .actionable-badge {
            background-color: #143a1f; border: 1px solid #4ecca3;
            color: #b9f6ca; padding: 8px 14px; border-radius: 8px;
            font-weight: 600; display: inline-block;
        }
        .priority-header {
            color: #ffffff; font-size: 16px; font-weight: 700;
            margin: 18px 0 8px 0; padding-bottom: 4px; border-bottom: 1px solid #333;
        }
        .empty-state {
            background-color: #16213e; border: 1px dashed #4ecca3;
            border-radius: 10px; padding: 30px; color: #8be9fd; text-align: center;
        }

        /* ---- Phase 2: Draft panels ---- */
        .thread-panel {
            background-color: #0f3460; border-left: 4px solid #e94560;
            border-radius: 8px; padding: 14px 18px; min-height: 200px;
            white-space: pre-wrap; color: #eaeaea; font-size: 13px; line-height: 1.6;
        }
        .draft-panel {
            background-color: #0a2540; border: 1px solid #4ecca3;
            border-radius: 10px; padding: 14px 18px; min-height: 200px;
            white-space: pre-wrap; color: #f1f1f1; font-size: 13px; line-height: 1.6;
        }
        .panel-label {
            font-size: 11px; font-weight: 700; letter-spacing: 0.08em;
            text-transform: uppercase; margin-bottom: 8px;
            padding: 3px 8px; border-radius: 4px; display: inline-block;
        }
        .label-thread { background-color: #2d1b3d; color: #e94560; }
        .label-draft  { background-color: #0d2e1e; color: #4ecca3; }

        /* ---- Phase 3: Approval Gate ---- */
        .approval-card {
            background-color: #111827; border: 1px solid #2a2a4a;
            border-radius: 12px; padding: 20px 22px; margin-bottom: 24px;
        }
        .approval-subject { font-size: 17px; font-weight: 700; color: #ffffff; margin-bottom: 4px; }
        .status-pill {
            display: inline-block; padding: 3px 10px; border-radius: 20px;
            font-size: 11px; font-weight: 600; letter-spacing: 0.05em;
        }
        .pill-approved { background: #143a1f; color: #4ecca3; }
        .pill-rejected { background: #3a1414; color: #e94560; }
        .pill-pending  { background: #1e2a3a; color: #ffd86b; }

        /* ---- Streamlit overrides ---- */
        div[data-testid="stMetricValue"] { color: #ffffff; }
        div[data-testid="stMetricLabel"] { color: #8be9fd; }
        .stTextArea textarea {
            background-color: #0a2540 !important;
            color: #f1f1f1 !important;
            border: 1px solid #4ecca3 !important;
            font-size: 13px !important;
            line-height: 1.6 !important;
        }
    </style>
    ''',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Session-state bootstrap
# ---------------------------------------------------------------------------

DEFAULTS = {
    "threads":        [],     # raw fetched threads
    "triaged":        [],     # triage-enriched threads: {..., priority, category, reason}
    "drafts":         {},     # dict[thread_id -> draft text string]
    "approved":       {},     # dict[thread_id -> approved draft text]
    "rejected":       set(),  # set[thread_id]
    "sent_threads":   set(),  # set[thread_id] of sent threads
    "sent_threads_details": {}, # dict[thread_id -> message_id]
    "meetings_info":  {},     # dict[thread_id -> dict]
    "booked_meetings": {},    # dict[thread_id -> dict]
    "booked":         {},     # dict[thread_id -> dict] -- track booked events
    "current_phase":  "Inbox & Triage",
    "source":         "Sample Threads",
    "last_pulled_at": None,
    "generation_counts": {},  # dict[thread_id -> int]
    "error_message":  None,   # error message to show at page top
    "selected_model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
    "pipeline_running": False,
    "pipeline_log": [],
    "max_n_val": 20,
}

for _k, _v in DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

os.environ["GEMINI_MODEL"] = st.session_state["selected_model"]

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

@st.cache_resource
def _get_calendar_engine():
    import calendar_engine
    return calendar_engine

def _normalize_engine_thread(t):
    """Convert gmail_fetch output shape into pipeline shape."""
    thread_id = t.get("thread_id") or t.get("id") or ""
    sender    = t.get("sender") or t.get("from") or "Unknown"
    subject   = t.get("subject", "(no subject)")
    snippet   = t.get("snippet", "") or ""
    date      = t.get("date") or datetime.now().strftime("%Y-%m-%d %I:%M %p")
    return {
        "id":       thread_id,
        "subject":  subject,
        "messages": [{"from": sender, "date": date, "body": snippet}],
    }


def _normalize_sample_thread(t):
    """Sample threads already match pipeline shape; stabilize id."""
    t = dict(t)
    t["id"] = t.get("id") or t.get("thread_id") or ""
    if not t["id"]:
        t["id"] = "sample-" + str(abs(hash(t.get("subject", ""))) % 10**8)
    return t


def _fetch_gmail_threads(max_results=20):
    from engine import fetch_threads
    return fetch_threads(max_results=max_results)


def _triage_gmail_threads(raw_threads):
    from triage import triage_inbox
    triaged = triage_inbox(raw_threads)
    # Normalize categories to meeting-request if they mention meeting/scheduling/calendar
    for t in triaged:
        cat = t.get("category", "").lower()
        subj = t.get("subject", "").lower()
        body = (t["messages"][0]["body"] if t.get("messages") else "").lower()
        text = cat + " " + subj + " " + body
        if "meeting-request" in cat or any(k in text for k in ["schedule meeting", "calendar invitation", "time slot", "calendar invite", "book a time"]):
            t["_category"] = "meeting-request"
            t["category"] = "meeting-request"
        else:
            t["_category"] = t.get("category", "")
    return triaged


def _local_triage_sample(threads):
    """Keyword-based offline triage for Sample mode (no API calls)."""
    urgent_kw      = ["\U0001F6A8", "down", "incident", "p0", "production",
                      "outage", "asap", "urgent", "500s", "500 errors"]
    needs_reply_kw = ["can you", "could you", "let me know", "reply",
                      "respond", "schedule", "review", "send me", "feedback",
                      "renewal", "meeting", "walk through", "time slots",
                      "decide", "approve", "sign", "renew", "quick question",
                      "wondering", "30 min"]
    fyi_kw         = ["standup", "notes", "recap", "fyi", "no action",
                      "digest", "weekly", "summary", "wiki"]
    ignore_kw      = ["unsubscribe", "promotion", "deal ", "sale ", "newsletter"]

    def _classify(t):
        subj = t.get("subject", "").lower()
        body = (t["messages"][0]["body"] if t.get("messages") else "").lower()
        text = subj + " " + body
        is_fyi_marked  = any(k in text for k in fyi_kw) and (
            "no action" in text or "fyi" in text or "standup" in subj
        )
        asks_for_reply = any(k in text for k in needs_reply_kw)
        if is_fyi_marked and not asks_for_reply:
            return {"priority": "FYI",         "category": "Informational", "_category": "Informational",
                    "reason":   "Explicitly marked FYI / no action required."}
        if any(k in text for k in urgent_kw):
            return {"priority": "URGENT",      "category": "Alert", "_category": "Alert",
                    "reason":   "Production-impacting or time-critical."}
        if any(k in text for k in needs_reply_kw):
            is_meet = any(k in text for k in ["meeting", "time slots", "30 min", "schedule", "calendar"])
            category = "meeting-request" if is_meet else "Action Request"
            return {"priority": "NEEDS-REPLY", "category": category, "_category": category,
                    "reason":   "Requires a response within 24-48 hours."}
        if any(k in text for k in fyi_kw):
            return {"priority": "FYI",         "category": "Informational", "_category": "Informational",
                    "reason":   "Informational, no action needed."}
        if any(k in text for k in ignore_kw):
            return {"priority": "IGNORE",      "category": "Promotional", "_category": "Promotional",
                    "reason":   "Low-value, can be archived."}
        return {"priority": "NEEDS-REPLY",     "category": "Unclassified", "_category": "Unclassified",
                "reason":   "No keyword match - defaulted to needs-reply."}

    triaged = [{**t, **_classify(t)} for t in threads]
    triaged.sort(key=lambda x: PRIORITY_ORDER.index(x.get("priority", "IGNORE")))
    return triaged


def _load_sample_threads():
    if not SAMPLE_FILE.exists():
        return []
    with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [_normalize_sample_thread(t) for t in data]


def _save_approved_draft(record):
    """Append approved draft record to approved_drafts.json."""
    approved_file = HERE / "approved_drafts.json"
    if approved_file.exists():
        with open(approved_file, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                if not isinstance(data, list):
                    data = []
            except Exception:
                data = []
    else:
        data = []

    # Remove existing record for the same thread if any, to avoid duplicates
    data = [r for r in data if r.get("thread_id") != record.get("thread_id")]
    data.append(record)

    with open(approved_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _mark_draft_as_sent_in_file(thread_id, message_id):
    """Update sent timestamp and message_id for a record in approved_drafts.json."""
    approved_file = HERE / "approved_drafts.json"
    if approved_file.exists():
        try:
            with open(approved_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            updated = False
            for r in data:
                if r.get("thread_id") == thread_id:
                    r["sent_at"] = datetime.now().isoformat(timespec="seconds")
                    r["message_id"] = message_id
                    updated = True
            if updated:
                with open(approved_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


def _actionable_count(triaged):
    return sum(1 for t in triaged if t.get("priority") in ("URGENT", "NEEDS-REPLY"))


def _get_actionable_threads():
    return [t for t in st.session_state.triaged
            if t.get("priority") in ("URGENT", "NEEDS-REPLY")]


def _priority_class(priority):
    return {"URGENT": "urgent", "NEEDS-REPLY": "reply",
            "FYI": "fyi",      "IGNORE": "ignore"}.get(priority, "ignore")


def _format_thread_for_display(thread):
    """Render a thread dict as a plain-text string for display panels."""
    lines = [f"Subject: {thread.get('subject', '(no subject)')}"]
    lines.append("")
    for idx, msg in enumerate(thread.get("messages", []), start=1):
        lines.append(f"--- Message #{idx} ---")
        lines.append(f"From: {msg.get('from', 'Unknown')}")
        lines.append(f"Date: {msg.get('date', 'Unknown')}")
        lines.append("")
        lines.append(msg.get("body", "").strip())
        lines.append("")
    return "\n".join(lines)


def run_full_pipeline():
    """Run the complete pipeline from fetch to draft, returning log strings."""
    logs = []
    logs.append(f"Starting full pipeline...")
    
    src = st.session_state.get("source", "Sample Threads")
    logs.append(f"Source selected: {src}")
    
    # 1. Fetch & Triage
    try:
        if src == "Gmail Threads":
            logs.append("Fetching Gmail threads...")
            max_n = int(st.session_state.get("max_n_val", 20))
            raw = _fetch_gmail_threads(max_results=max_n)
            pipeline_threads = [_normalize_engine_thread(t) for t in raw]
            logs.append("Triaging Gmail threads...")
            triaged_engine = _triage_gmail_threads(raw)
            by_id = {t.get("thread_id"): t for t in triaged_engine}
            triaged = []
            for pt in pipeline_threads:
                cls = by_id.get(pt["id"], {})
                triaged.append({**pt, **{
                    "priority": cls.get("priority", "FYI"),
                    "category": cls.get("category", "Unknown"),
                    "reason":   cls.get("reason",   "Not classified"),
                }})
            triaged.sort(key=lambda x: PRIORITY_ORDER.index(x.get("priority", "IGNORE")))
            st.session_state.threads = pipeline_threads
            st.session_state.triaged = triaged
        else:
            logs.append("Loading sample threads...")
            sample = _load_sample_threads()
            logs.append("Triaging sample threads...")
            triaged = _local_triage_sample(sample)
            st.session_state.threads = sample
            st.session_state.triaged = triaged
            
        st.session_state.last_pulled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logs.append(f"Successfully triaged {len(st.session_state.triaged)} threads.")
    except Exception as e:
        logs.append(f"ERROR during fetch/triage: {e}")
        return logs

    # 2. Reset Downstream State
    logs.append("Resetting downstream state...")
    st.session_state.drafts = {}
    st.session_state.approved = {}
    st.session_state.rejected = set()
    st.session_state.sent_threads = set()
    st.session_state.sent_threads_details = {}
    st.session_state.booked = {}
    st.session_state.generation_counts = {}

    # 3. Draft Generation
    actionable = [t for t in st.session_state.triaged if t.get("priority") in ("URGENT", "NEEDS-REPLY")]
    logs.append(f"Found {len(actionable)} actionable threads to draft.")
    
    def _get_draft_reply():
        from draft_machine import draft_reply
        return draft_reply
        
    draft_func = _get_draft_reply()
        
    for thread in actionable:
        tid = thread.get("id")
        subject = thread.get("subject", "(no subject)")
        logs.append(f"Generating draft for: {subject[:30]}...")
        try:
            draft_text = draft_func(thread)
            st.session_state.drafts[tid] = draft_text
            logs.append(f"  -> Success: Draft generated for {tid}")
        except Exception as e:
            logs.append(f"  -> ERROR drafting {tid}: {e}")
            
    # 4. Set phase
    logs.append("Moving to Approval Gate phase...")
    st.session_state.current_phase = "Approval Gate"
    
    logs.append("Pipeline run complete.")
    return logs


def _render_pipeline_execution():
    """Execute the full pipeline with live progress UI updates."""
    pipeline_log = []
    
    with st.status("Running full pipeline...", expanded=True) as status:
        src = st.session_state.get("source", "Sample Threads")
        
        # Step 1: Fetch
        status.update(label=f"Fetching threads from {src}...")
        try:
            if src == "Gmail Threads":
                max_n = int(st.session_state.get("max_n_val", 20))
                raw = _fetch_gmail_threads(max_results=max_n)
                pipeline_threads = [_normalize_engine_thread(t) for t in raw]
            else:
                sample = _load_sample_threads()
            st.write("✅ Fetched threads successfully.")
            pipeline_log.append(f"Fetched threads from {src}.")
        except Exception as e:
            st.write(f"❌ Fetch failed: {e}")
            pipeline_log.append(f"ERROR fetch: {e}")
            status.update(label="Pipeline failed.", state="error")
            return

        # Step 2: Triage
        status.update(label="Triaging threads...")
        try:
            if src == "Gmail Threads":
                triaged_engine = _triage_gmail_threads(raw)
                by_id = {t.get("thread_id"): t for t in triaged_engine}
                triaged = []
                for pt in pipeline_threads:
                    cls = by_id.get(pt["id"], {})
                    triaged.append({**pt, **{
                        "priority": cls.get("priority", "FYI"),
                        "category": cls.get("category", "Unknown"),
                        "reason":   cls.get("reason",   "Not classified"),
                    }})
                triaged.sort(key=lambda x: PRIORITY_ORDER.index(x.get("priority", "IGNORE")))
                st.session_state.threads = pipeline_threads
                st.session_state.triaged = triaged
            else:
                triaged = _local_triage_sample(sample)
                st.session_state.threads = sample
                st.session_state.triaged = triaged
                
            st.session_state.last_pulled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.write(f"✅ Triaged {len(st.session_state.triaged)} threads successfully.")
            pipeline_log.append(f"Successfully triaged {len(st.session_state.triaged)} threads.")
        except Exception as e:
            st.write(f"❌ Triage failed: {e}")
            pipeline_log.append(f"ERROR triage: {e}")
            status.update(label="Pipeline failed.", state="error")
            return

        # Reset downstream states
        st.session_state.drafts = {}
        st.session_state.approved = {}
        st.session_state.rejected = set()
        st.session_state.sent_threads = set()
        st.session_state.sent_threads_details = {}
        st.session_state.booked = {}
        st.session_state.generation_counts = {}

        # Step 3: Draft Generation Loop
        actionable = [t for t in st.session_state.triaged if t.get("priority") in ("URGENT", "NEEDS-REPLY")]
        if not actionable:
            st.write("✅ No actionable threads require drafting.")
            pipeline_log.append("No actionable threads.")
            status.update(label="Pipeline complete.", state="complete")
        else:
            status.update(label=f"Generating {len(actionable)} drafts...")
            
            def _get_draft_reply():
                from draft_machine import draft_reply
                return draft_reply
                
            draft_func = _get_draft_reply()
            
            for thread in actionable:
                tid = thread.get("id")
                subject = thread.get("subject", "(no subject)")
                try:
                    draft_text = draft_func(thread)
                    st.session_state.drafts[tid] = draft_text
                    st.write(f"✅ Drafted: {subject[:40]}")
                    pipeline_log.append(f"Success drafting {tid}: {subject}")
                except Exception as e:
                    st.write(f"❌ Failed to draft: {subject[:40]} - {e}")
                    pipeline_log.append(f"ERROR drafting {tid}: {e}")
            
            status.update(label="Pipeline complete.", state="complete")
            
    # Outside the status block:
    st.session_state.pipeline_log = pipeline_log
    st.session_state.current_phase = "Approval Gate"
    st.session_state.pipeline_running = False
    st.rerun()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## \u270D\uFE0F The Draft Desk")
    st.caption("Chief Of Staff - Draft Worflow")
    st.markdown("---")
    
    if st.button("🚀 Run Full Pipeline", type="primary", use_container_width=True):
        st.session_state.pipeline_running = True
        st.rerun()
    st.caption("Fetches, triages, and drafts -- stops at Approval Gate.")

    st.markdown("---")

    st.markdown("**Source**")
    source = st.radio(
        "Email source",
        options=["Sample Threads", "Gmail Threads"],
        index=0 if st.session_state.source == "Sample Threads" else 1,
        label_visibility="collapsed",
    )
    st.session_state.source = source

    st.markdown("---")
    st.markdown("**Navigation**")
    for phase in PHASES:
        is_current = st.session_state.current_phase == phase
        label = ("\u25B8 " if is_current else "") + phase
        if st.button(
            label,
            key="nav_" + phase,
            use_container_width=True,
            type="primary" if is_current else "secondary",
        ):
            st.session_state.current_phase = phase
            st.rerun()

    st.markdown("---")
    if st.session_state.triaged:
        st.markdown("**Session summary**")
        st.caption("Threads: " + str(len(st.session_state.triaged)))
        st.caption("Actionable: " + str(_actionable_count(st.session_state.triaged)))
        if st.session_state.drafts:
            st.caption("Drafts: " + str(len(st.session_state.drafts)))
        if st.session_state.approved:
            st.caption("Approved: " + str(len(st.session_state.approved)))
        if st.session_state.last_pulled_at:
            st.caption("Last pull: " + str(st.session_state.last_pulled_at))

# ---------------------------------------------------------------------------
# PHASE 1 — Inbox & Triage
# ---------------------------------------------------------------------------

def render_phase_inbox_triage():
    st.markdown(
        '<div class="phase-header">\U0001F4E5 Inbox &amp; Triage</div>'
        '<div class="phase-sub">Pull threads from your source and let Gemini classify them.</div>',
        unsafe_allow_html=True,
    )

    src = st.session_state.source
    button_label = "\U0001F504 Pull & Triage Threads  (" + src + ")"

    if src == "Gmail Threads":
        c1, c2 = st.columns([1, 3])
        def _update_max_n():
            st.session_state.max_n_val = st.session_state.max_n_widget

        with c1:
            max_n = st.number_input(
                "Threads to pull", min_value=1, max_value=50, step=5,
                value=st.session_state.max_n_val,
                help="How many recent Gmail threads to fetch.",
                key="max_n_widget",
                on_change=_update_max_n
            )
        with c2:
            st.caption(
                "Requires `token.json` (Gmail OAuth) and `GEMINI_API_KEY` in `.env`. "
                "Switch to **Sample** for a key-free demo."
            )
    else:
        max_n = None
        st.caption(
            "Loading the bundled `sample_threads.json` (5 realistic demo threads). "
            "Triage uses a local keyword classifier — no API calls."
        )

    pull_clicked = st.button(button_label, type="primary", use_container_width=False)

    if pull_clicked:
        try:
            with st.spinner("Pulling & triaging threads from " + src + "\u2026"):
                if src == "Gmail Threads":
                    raw = _fetch_gmail_threads(max_results=int(max_n))
                    pipeline_threads = [_normalize_engine_thread(t) for t in raw]
                    triaged_engine   = _triage_gmail_threads(raw)
                    by_id = {t.get("thread_id"): t for t in triaged_engine}
                    triaged = []
                    for pt in pipeline_threads:
                        cls = by_id.get(pt["id"], {})
                        triaged.append({**pt, **{
                            "priority": cls.get("priority", "FYI"),
                            "category": cls.get("category", "Unknown"),
                            "reason":   cls.get("reason",   "Not classified"),
                        }})
                    triaged.sort(key=lambda x: PRIORITY_ORDER.index(x.get("priority", "IGNORE")))
                    st.session_state.threads = pipeline_threads
                    st.session_state.triaged = triaged
                else:
                    sample  = _load_sample_threads()
                    triaged = _local_triage_sample(sample)
                    st.session_state.threads = sample
                    st.session_state.triaged = triaged

                st.session_state.last_pulled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.session_state.drafts   = {}
                st.session_state.approved = {}
                st.session_state.rejected = set()
                st.session_state.generation_counts = {}
                st.session_state.error_message = None

            st.success("\u2705 Pulled & triaged " + str(len(st.session_state.triaged)) + " threads.")
        except FileNotFoundError as e:
            st.error("\u274C " + str(e))
        except Exception as e:
            st.error("\u274C Failed to pull threads: " + str(e))

    st.markdown("---")

    triaged = st.session_state.triaged
    if not triaged:
        st.markdown(
            '<div class="empty-state">\U0001F4ED No threads loaded yet.<br/>'
            'Click <b>Pull &amp; Triage Threads</b> above to get started.</div>',
            unsafe_allow_html=True,
        )
        return

    # ---- Metrics row -------------------------------------------------------
    urgent_n   = sum(1 for t in triaged if t.get("priority") == "URGENT")
    reply_n    = sum(1 for t in triaged if t.get("priority") == "NEEDS-REPLY")
    fyi_n      = sum(1 for t in triaged if t.get("priority") == "FYI")
    ignore_n   = sum(1 for t in triaged if t.get("priority") == "IGNORE")
    actionable = urgent_n + reply_n

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total",                  len(triaged))
    m2.metric("\U0001F6A8 Urgent",          urgent_n)
    m3.metric("\u21A9\uFE0F Needs Reply",   reply_n)
    m4.metric("\u2139\uFE0F FYI",           fyi_n)
    m5.metric("\U0001F5D1\uFE0F Ignore",    ignore_n)

    st.markdown(
        '<span class="actionable-badge">\u26A1 ' + str(actionable) +
        ' actionable thread(s) — urgent + needs-reply</span>',
        unsafe_allow_html=True,
    )
    st.markdown("")

    # ---- Group by priority -------------------------------------------------
    for priority in PRIORITY_ORDER:
        group = [t for t in triaged if t.get("priority") == priority]
        if not group:
            continue

        emoji = PRIORITY_EMOJI[priority]
        color = PRIORITY_COLOR[priority]
        st.markdown(
            '<div class="priority-header">' + emoji + " " + priority +
            ' <span style="color:' + color + ';">- ' + str(len(group)) +
            ' thread(s)</span></div>',
            unsafe_allow_html=True,
        )

        for t in group:
            tid      = t.get("id", "")
            subject  = t.get("subject", "(no subject)")
            category = t.get("category", "")
            reason   = t.get("reason", "")
            messages = t.get("messages", []) or [{}]
            first    = messages[0]
            sender   = first.get("from", "Unknown")
            date     = first.get("date", "")
            body     = first.get("body", "")
            cls      = _priority_class(priority)
            label    = subject + "  -  " + sender

            with st.expander(label, expanded=(priority == "URGENT")):
                card_html = (
                    '<div class="thread-card ' + cls + '">'
                    '<div class="meta">'
                    '<b>From:</b> ' + sender +
                    ' &nbsp;-&nbsp; <b>Date:</b> ' + date +
                    ' &nbsp;-&nbsp; <b>Category:</b> ' + category +
                    ' &nbsp;-&nbsp; <b>ID:</b> <code>' + tid + '</code>'
                    '</div>'
                    '<div style="margin-top:6px;">'
                    '<span style="background-color:' + color + '22; color:' + color + ';'
                    ' padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600;">' +
                    priority + '</span>'
                    '&nbsp;<span style="color:#bbbbbb; font-size:12px;">' + reason + '</span>'
                    '</div>'
                    '<hr style="border-color:#333; margin:10px 0;"/>'
                    '<div style="white-space: pre-wrap; color:#eaeaea;">' + body + '</div>'
                    '</div>'
                )
                st.markdown(card_html, unsafe_allow_html=True)

    if actionable > 0:
        st.markdown("---")
        st.info(
            "\u2728 **" + str(actionable) + " actionable thread(s) ready.** "
            "Head to **Draft Generation** in the sidebar to generate replies.",
            icon="\u2709\uFE0F",
        )


# ---------------------------------------------------------------------------
# PHASE 2 — Draft Generation
# ---------------------------------------------------------------------------

def render_phase_draft_generation():
    st.markdown(
        '<div class="phase-header">\u270F\uFE0F Draft Generation</div>'
        '<div class="phase-sub">Generate on-brand reply drafts for every actionable thread using Gemini.</div>',
        unsafe_allow_html=True,
    )

    if "error_message" in st.session_state and st.session_state.error_message:
        st.error(st.session_state.error_message)

    actionable = _get_actionable_threads()

    if not st.session_state.triaged:
        st.markdown(
            '<div class="empty-state">\U0001F4ED No threads loaded yet.<br/>'
            'Go to <b>Inbox &amp; Triage</b> first to pull threads.</div>',
            unsafe_allow_html=True,
        )
        return

    if not actionable:
        st.markdown(
            '<div class="empty-state">\u2705 No actionable threads found.<br/>'
            'All threads are FYI or IGNORE — no replies needed.</div>',
            unsafe_allow_html=True,
        )
        return

    # ---- Summary metrics ---------------------------------------------------
    n_total   = len(actionable)
    n_drafted = sum(1 for t in actionable if t.get("id") in st.session_state.drafts)
    n_pending = n_total - n_drafted

    c1, c2, c3 = st.columns(3)
    c1.metric("Actionable Threads", n_total)
    c2.metric("Drafts Generated",   n_drafted)
    c3.metric("Pending",            n_pending)

    st.markdown("---")

    # ---- Generate All button -----------------------------------------------
    btn_label = (
        "\U0001F916 Generate All Drafts (" + str(n_pending) + " remaining)"
        if n_pending > 0 else "\u2705 All Drafts Generated"
    )
    gen_btn = st.button(
        btn_label,
        type="primary",
        disabled=(n_pending == 0),
        use_container_width=False,
    )

    if gen_btn:
        st.session_state.error_message = None  # Clear previous error

        remaining    = [t for t in actionable if t.get("id") not in st.session_state.drafts]
        progress_bar = st.progress(0, text="Initialising Gemini…")
        status_text  = st.empty()

        has_error = False
        quota_exhausted_model = None
        for i, thread in enumerate(remaining):
            tid     = thread.get("id", "")
            subject = thread.get("subject", "(no subject)")
            status_text.markdown(
                "**Drafting reply for:** `" + subject + "` &nbsp; (" + str(i + 1) + "/" + str(len(remaining)) + ")",
                unsafe_allow_html=True,
            )
            try:
                draft_text = draft_reply(thread)
                st.session_state.drafts[tid] = draft_text
            except RuntimeError as exc:
                err_str = str(exc)
                # Check if it's a quota error
                if "quota" in err_str.lower() or "429" in err_str:
                    current_model = st.session_state.get("selected_model", "gemini-2.5-flash")
                    if current_model != "gemini-2.0-flash" and not quota_exhausted_model:
                        # Try fallback to gemini-2.0-flash
                        status_text.markdown(
                            f"⚠️ **{current_model} quota exhausted. Switching to gemini-2.0-flash (1500 RPD free tier)...**",
                            unsafe_allow_html=True,
                        )
                        try:
                            import os
                            os.environ["GEMINI_MODEL"] = "gemini-2.0-flash"
                            quota_exhausted_model = current_model
                            draft_text = draft_reply(thread, model_name="gemini-2.0-flash")
                            st.session_state.drafts[tid] = draft_text
                            # Continue with the fallback model for remaining threads
                        except Exception as fallback_exc:
                            st.session_state.error_message = (
                                f"🔴 Both {current_model} and gemini-2.0-flash quota exhausted. "
                                "Please wait for limits to reset or upgrade your API tier."
                            )
                            has_error = True
                            break
                    else:
                        st.session_state.error_message = (
                            f"🔴 {str(exc)}"
                        )
                        has_error = True
                        break
                else:
                    st.session_state.error_message = (
                        f"🔴 {str(exc)}"
                    )
                    has_error = True
                    break
            except (SystemExit, ValueError) as exc:
                st.session_state.error_message = (
                    f"🔴 {str(exc)}"
                )
                has_error = True
                break
            except Exception as exc:
                st.session_state.drafts[tid] = "[Draft failed: " + str(exc) + "]"

            progress_bar.progress(
                (i + 1) / len(remaining),
                text="\u2705 " + str(i + 1) + "/" + str(len(remaining)) + " complete",
            )

        if not has_error:
            status_text.markdown("\u2728 **Done!** All drafts generated.")
            if quota_exhausted_model:
                st.info(
                    f"ℹ️ Note: Switched from {quota_exhausted_model} to gemini-2.0-flash due to quota limits. "
                    "All drafts were successfully generated."
                )
        st.rerun()

    st.markdown("---")

    # ---- Side-by-side preview ----------------------------------------------
    if not st.session_state.drafts:
        st.markdown(
            '<div class="empty-state">\u23F3 Click <b>Generate All Drafts</b> above to start.</div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown("### \U0001F4CB Generated Drafts")

    for thread in actionable:
        tid      = thread.get("id", "")
        subject  = thread.get("subject", "(no subject)")
        priority = thread.get("priority", "NEEDS-REPLY")
        emoji    = PRIORITY_EMOJI.get(priority, "")

        if tid not in st.session_state.drafts:
            continue

        draft_text = st.session_state.drafts[tid]

        with st.expander(emoji + " " + subject, expanded=True):
            col_left, col_right = st.columns(2, gap="medium")

            with col_left:
                st.markdown(
                    '<span class="panel-label label-thread">\U0001F4E8 Original Thread</span>',
                    unsafe_allow_html=True,
                )
                latest_msg   = thread.get("messages", [{}])[-1]
                body_preview = latest_msg.get("body", "")
                sender       = latest_msg.get("from", "Unknown")
                date         = latest_msg.get("date", "")
                st.markdown(
                    '<div class="thread-panel">'
                    '<span style="color:#8be9fd;font-size:11px;">'
                    'From: <b style="color:#ffd86b">' + sender + '</b>'
                    ' &nbsp;|&nbsp; ' + date +
                    '</span><br/><br/>' + body_preview + '</div>',
                    unsafe_allow_html=True,
                )

            with col_right:
                st.markdown(
                    '<span class="panel-label label-draft">\u270D\uFE0F AI Draft</span>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    '<div class="draft-panel">' + draft_text.replace("\n", "<br/>") + '</div>',
                    unsafe_allow_html=True,
                )

    st.markdown("---")
    st.info(
        "\u2728 Drafts ready. Head to **Approval Gate** in the sidebar to review, "
        "edit, approve, or reject each draft before exporting.",
        icon="\U0001F6E1\uFE0F",
    )


# ---------------------------------------------------------------------------
# PHASE 3 — Approval Gate
# ---------------------------------------------------------------------------

def render_phase_approval_gate():
    st.markdown(
        '<div class="phase-header">\U0001F6E1\uFE0F Approval Gate</div>'
        '<div class="phase-sub">Review, edit, approve, or reject each AI-generated draft.</div>',
        unsafe_allow_html=True,
    )

    pipeline_log = st.session_state.get("pipeline_log", [])
    if pipeline_log:
        with st.expander("Pipeline Execution Log"):
            for entry in pipeline_log:
                if "ERROR" in entry or "FAILED" in entry:
                    st.write(f"❌ {entry}")
                else:
                    st.write(f"✅ {entry}")
            if st.button("Clear log"):
                st.session_state.pipeline_log = []
                st.rerun()
        st.markdown("---")

    actionable = _get_actionable_threads()

    if not st.session_state.triaged:
        st.markdown(
            '<div class="empty-state">\U0001F4ED No threads loaded.<br/>'
            'Complete Phase 1 (Inbox &amp; Triage) first.</div>',
            unsafe_allow_html=True,
        )
        return

    if not st.session_state.drafts:
        st.markdown(
            '<div class="empty-state">\u270F\uFE0F No drafts generated yet.<br/>'
            'Complete Phase 2 (Draft Generation) first.</div>',
            unsafe_allow_html=True,
        )
        return

    # ---- Running count header ----------------------------------------------
    n_approved = len(st.session_state.approved)
    n_rejected = len(st.session_state.rejected)
    n_pending  = sum(
        1 for t in actionable
        if t.get("id") in st.session_state.drafts
        and t.get("id") not in st.session_state.approved
        and t.get("id") not in st.session_state.rejected
    )

    ca, cr, cp = st.columns(3)
    ca.metric("\u2705 Approved", n_approved)
    cr.metric("\u274C Rejected", n_rejected)
    cp.metric("\u23F3 Pending",  n_pending)

    # ---- All-reviewed celebration ------------------------------------------
    if n_pending == 0 and (n_approved + n_rejected) > 0:
        st.balloons()
        st.success(
            "\U0001F389 All drafts reviewed! "
            + str(n_approved) + " approved, "
            + str(n_rejected) + " rejected. "
            "Head to **Export Proof** to download your bundle."
        )

    st.markdown("---")

    # ---- Per-draft review cards --------------------------------------------
    from draft_machine import draft_reply

    for thread in actionable:
        tid      = thread.get("id", "")
        subject  = thread.get("subject", "(no subject)")
        priority = thread.get("priority", "NEEDS-REPLY")
        emoji    = PRIORITY_EMOJI.get(priority, "")
        color    = PRIORITY_COLOR.get(priority, "#8be9fd")

        if tid not in st.session_state.drafts:
            continue

        # Already approved / sent
        if tid in st.session_state.approved:
            if tid in st.session_state.get("sent_threads", set()):
                sent_id = st.session_state.sent_threads_details.get(tid, "Success")
                st.markdown(
                    f'<div style="padding:10px 16px; margin-bottom:12px; background:#1b3b2b;'
                    f' border-radius:8px; border-left:3px solid #4ecca3;">'
                    f'<span class="status-pill pill-approved">🚀 SENT</span>'
                    f'&nbsp;&nbsp;<span style="color:#aaa;">{subject} (ID: {sent_id})</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                category = thread.get("category") or thread.get("_category") or ""
                category_lower = category.lower().strip()
                is_meeting = (category_lower in ["meeting-request", "meeting request"])
                
                if is_meeting:
                    c_app, c_snd, c_book = st.columns([3, 1, 1])
                    with c_app:
                        st.markdown(
                            '<div style="padding:10px 16px; margin-bottom:12px; background:#0d2e1e;'
                            ' border-radius:8px; border-left:3px solid #4ecca3;">'
                            '<span class="status-pill pill-approved">\u2705 APPROVED</span>'
                            '&nbsp;&nbsp;<span style="color:#aaa;">' + subject + '</span>'
                            '</div>',
                            unsafe_allow_html=True,
                        )
                    with c_snd:
                        if st.button("🚀 Send", key="send_" + tid, type="primary"):
                            if st.session_state.source == "Sample Threads":
                                import time
                                time.sleep(0.5)
                                mock_id = "mock-msg-" + str(abs(hash(subject)) % 10**8)
                                st.session_state.setdefault("sent_threads", set()).add(tid)
                                st.session_state.setdefault("sent_threads_details", {})[tid] = mock_id
                                st.success(f"Sent (Mock)! ID: {mock_id}")
                                st.rerun()
                            else:
                                recipient = thread.get("messages", [{}])[-1].get("from", "Unknown")
                                if '<' in recipient and '>' in recipient:
                                    recipient = recipient.split('<')[1].split('>')[0]
                                try:
                                    from engine import send_reply
                                    result = send_reply(
                                        thread_id=tid,
                                        to=recipient,
                                        subject=subject,
                                        body=st.session_state.approved[tid],
                                        message_id=thread.get("message_id")
                                    )
                                    real_id = result.get("id") or result.get("message_id") or "Success"
                                    st.session_state.setdefault("sent_threads", set()).add(tid)
                                    st.session_state.setdefault("sent_threads_details", {})[tid] = real_id
                                    _mark_draft_as_sent_in_file(tid, real_id)
                                    log_action(
                                        action_type="sent",
                                        thread_subject=thread.get("subject", ""),
                                        detail=recipient,
                                        action_id=real_id,
                                    )
                                    st.success(f"Sent! ID: {real_id}")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed to send email: {e}")
                    with c_book:
                        if tid in st.session_state.booked:
                            evt = st.session_state.booked[tid]
                            link = evt.get("htmlLink") or "https://calendar.google.com"
                            st.markdown(f"[📅 View Calendar]({link})")
                        else:
                            if st.button("📅 Book Meeting", key="book_btn_" + tid, type="secondary"):
                                try:
                                    with st.spinner("Parsing meeting request..."):
                                        engine_mod = _get_calendar_engine()
                                        details = engine_mod.parse_meeting_request(thread)
                                        
                                    if "parsing_error" in details:
                                        st.error(f"Failed to parse meeting details: {details['parsing_error']}")
                                    else:
                                        with st.spinner("Finding free slot..."):
                                            if st.session_state.source == "Sample Threads":
                                                proposed = details.get("proposed_times", [])
                                                if proposed:
                                                    free_slot = proposed[0]
                                                else:
                                                    free_slot = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT14:00:00Z")
                                            else:
                                                free_slot = engine_mod.find_free_slot(
                                                    details.get("proposed_times", []),
                                                    details.get("duration_minutes", 30)
                                                )
                                                
                                        if not free_slot:
                                            st.error("No free slot available among proposed times.")
                                        else:
                                            with st.spinner("Creating calendar event..."):
                                                if st.session_state.source == "Sample Threads":
                                                    import time
                                                    time.sleep(0.5)
                                                    mock_evt = {
                                                        "id": "mock-event-" + str(abs(hash(subject)) % 10**8),
                                                        "htmlLink": "https://calendar.google.com",
                                                        "summary": details.get("topic", subject),
                                                        "start": {"dateTime": free_slot},
                                                        "end": {"dateTime": free_slot},
                                                        "attendees": [{"email": a} for a in details.get("attendees", [])]
                                                    }
                                                    st.session_state.booked[tid] = mock_evt
                                                    st.rerun()
                                                else:
                                                    evt = engine_mod.create_event(
                                                        summary=details.get("topic", subject),
                                                        start_time=free_slot,
                                                        duration_minutes=details.get("duration_minutes", 30),
                                                        attendees=details.get("attendees", []),
                                                        description=f"Automated booking for thread: {subject}"
                                                    )
                                                    st.session_state.booked[tid] = evt
                                                    if "id" in evt:
                                                        log_action(
                                                            action_type="booked",
                                                            thread_subject=thread.get("subject", ""),
                                                            detail=details.get("topic", thread.get("subject", "")),
                                                            action_id=evt["id"],
                                                        )
                                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed to book meeting: {e}")
                    
                    if tid in st.session_state.booked:
                        evt = st.session_state.booked[tid]
                        link = evt.get("htmlLink") or "https://calendar.google.com"
                        attendees_list = ", ".join(a.get("email") for a in evt.get("attendees", [])) if evt.get("attendees") else "None"
                        st.success(
                            f"✅ **Meeting Booked Successfully!**\n\n"
                            f"* **Title**: {evt.get('summary', 'Meeting')}\n"
                            f"* **Time**: {evt.get('start', {}).get('dateTime', '')}\n"
                            f"* **Attendees**: {attendees_list}\n"
                            f"* **Link**: [View in Google Calendar]({link})"
                        )
                else:
                    c_app, c_snd = st.columns([4, 1])
                    with c_app:
                        st.markdown(
                            '<div style="padding:10px 16px; margin-bottom:12px; background:#0d2e1e;'
                            ' border-radius:8px; border-left:3px solid #4ecca3;">'
                            '<span class="status-pill pill-approved">\u2705 APPROVED</span>'
                            '&nbsp;&nbsp;<span style="color:#aaa;">' + subject + '</span>'
                            '</div>',
                            unsafe_allow_html=True,
                        )
                    with c_snd:
                        if st.button("🚀 Send", key="send_" + tid, type="primary"):
                            if st.session_state.source == "Sample Threads":
                                import time
                                time.sleep(0.5)
                                mock_id = "mock-msg-" + str(abs(hash(subject)) % 10**8)
                                st.session_state.setdefault("sent_threads", set()).add(tid)
                                st.session_state.setdefault("sent_threads_details", {})[tid] = mock_id
                                st.success(f"Sent (Mock)! ID: {mock_id}")
                                st.rerun()
                            else:
                                recipient = thread.get("messages", [{}])[-1].get("from", "Unknown")
                                if '<' in recipient and '>' in recipient:
                                    recipient = recipient.split('<')[1].split('>')[0]
                                try:
                                    from engine import send_reply
                                    result = send_reply(
                                        thread_id=tid,
                                        to=recipient,
                                        subject=subject,
                                        body=st.session_state.approved[tid],
                                        message_id=thread.get("message_id")
                                    )
                                    real_id = result.get("id") or result.get("message_id") or "Success"
                                    st.session_state.setdefault("sent_threads", set()).add(tid)
                                    st.session_state.setdefault("sent_threads_details", {})[tid] = real_id
                                    _mark_draft_as_sent_in_file(tid, real_id)
                                    log_action(
                                        action_type="sent",
                                        thread_subject=thread.get("subject", ""),
                                        detail=recipient,
                                        action_id=real_id,
                                    )
                                    st.success(f"Sent! ID: {real_id}")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed to send email: {e}")
            continue

        # Already rejected
        if tid in st.session_state.rejected:
            st.markdown(
                '<div style="padding:10px 16px; margin-bottom:12px; background:#2e0d0d;'
                ' border-radius:8px; border-left:3px solid #e94560;">'
                '<span class="status-pill pill-rejected">\u274C REJECTED</span>'
                '&nbsp;&nbsp;<span style="color:#aaa;">' + subject + '</span>'
                '</div>',
                unsafe_allow_html=True,
            )
            continue

        # ---- Pending review ------------------------------------------------
        st.markdown(
            '<div class="approval-card">'
            '<div class="approval-subject">' + emoji + ' ' + subject + '</div>'
            '<span class="status-pill" style="color:' + color + ';'
            ' background:' + color + '22; border:1px solid ' + color + '44;">'
            + priority + '</span>'
            '</div>',
            unsafe_allow_html=True,
        )

        col_left, col_right = st.columns(2, gap="medium")

        with col_left:
            st.markdown("**\U0001F4E8 Original Thread**")
            thread_display = _format_thread_for_display(thread)
            st.markdown(
                '<div class="thread-panel">' +
                thread_display.replace("\n", "<br/>") +
                '</div>',
                unsafe_allow_html=True,
            )

        gen_count = st.session_state.generation_counts.get(tid, 0)
        with col_right:
            st.markdown("**\u270D\uFE0F Edit Draft**")
            edited_draft = st.text_area(
                label="draft_" + tid,
                value=st.session_state.drafts[tid],
                height=300,
                label_visibility="collapsed",
                key=f"edit_{tid}_{gen_count}",
            )

        # ---- Action buttons ------------------------------------------------
        b1, b2, b3, _ = st.columns([1, 1, 1, 3])

        with b1:
            if st.button("\u2705 Approve", key="approve_" + tid, type="primary"):
                st.session_state.approved[tid] = edited_draft
                
                # Build record payload
                first_msg = thread.get("messages", [{}])[0]
                sender = first_msg.get("from", "Unknown")
                
                record = {
                    "thread_id":       tid,
                    "recipient_email": sender,
                    "thread_subject":  subject,
                    "reply_to":        sender,
                    "model":           st.session_state.get("selected_model", "gemini-2.5-flash-lite"),
                    "edited":          (edited_draft != st.session_state.drafts[tid]),
                    "confidence":      None,
                    "draft":           edited_draft,
                    "approved_at":     datetime.now().isoformat(timespec="seconds"),
                    "message_id":      thread.get("message_id")
                }
                try:
                    _save_approved_draft(record)
                except Exception as e:
                    st.warning(f"Could not persist approved draft to file: {e}")
                    
                st.rerun()

        with b2:
            if st.button("\U0001F504 Regenerate", key="regen_" + tid):
                regen_error = None
                with st.spinner("Regenerating draft\u2026"):
                    try:
                        new_draft = draft_reply(thread)
                        st.session_state.drafts[tid] = new_draft
                        # Increment generation count for this thread to force widget recreation
                        st.session_state.generation_counts[tid] = st.session_state.generation_counts.get(tid, 0) + 1
                    except RuntimeError as exc:
                        err_str = str(exc)
                        # Check if it's a quota error and the current model is not the fallback
                        if "quota" in err_str.lower() or "429" in err_str:
                            current_model = st.session_state.get("selected_model", "gemini-2.5-flash")
                            if current_model != "gemini-2.0-flash":
                                try:
                                    # Try fallback to gemini-2.0-flash which has higher limits
                                    import os
                                    os.environ["GEMINI_MODEL"] = "gemini-2.0-flash"
                                    new_draft = draft_reply(thread, model_name="gemini-2.0-flash")
                                    st.session_state.drafts[tid] = new_draft
                                    st.session_state.generation_counts[tid] = st.session_state.generation_counts.get(tid, 0) + 1
                                    st.warning(f"⚠️ {current_model} quota exhausted. Successfully regenerated using gemini-2.0-flash (1500 RPD free tier).")
                                    # Restore the original model setting
                                    os.environ["GEMINI_MODEL"] = current_model
                                except Exception as fallback_exc:
                                    regen_error = f"Both {current_model} and fallback model failed. {str(fallback_exc)}"
                                    # Restore the original model setting
                                    os.environ["GEMINI_MODEL"] = current_model
                            else:
                                regen_error = str(exc)
                        else:
                            regen_error = str(exc)
                    except Exception as exc:
                        regen_error = str(exc)
                if regen_error:
                    st.error("Regeneration failed: " + regen_error)
                else:
                    st.rerun()

        with b3:
            if st.button("\u274C Reject", key="reject_" + tid):
                st.session_state.rejected.add(tid)
                st.rerun()

        st.markdown("---")


# ---------------------------------------------------------------------------
# PHASE 4 — Export Proof
# ---------------------------------------------------------------------------

def generate_proof_markdown():
    """Build a Markdown proof-of-work document for all approved drafts."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    thread_lookup = {t.get("id"): t for t in st.session_state.triaged}

    lines = [
        "# The Draft Desk — Proof of Work",
        "",
        f"**Generated:** {now}",
        f"**Approved drafts:** {len(st.session_state.approved)}",
        "",
        "---",
        "",
    ]

    for tid, approved_text in st.session_state.approved.items():
        thread   = thread_lookup.get(tid, {})
        subject  = thread.get("subject", "(no subject)")
        priority = thread.get("priority", "")

        lines += [
            f"## {subject}",
            "",
            f"**Priority:** {priority}",
            "",
            "### Original Thread",
            "",
        ]
        for idx, msg in enumerate(thread.get("messages", []), start=1):
            lines += [
                f"**Message #{idx}**",
                f"- **From:** {msg.get('from', 'Unknown')}",
                f"- **Date:** {msg.get('date', 'Unknown')}",
                "",
                "> " + msg.get("body", "").strip().replace("\n", "\n> "),
                "",
            ]
        lines += [
            "### Draft Reply",
            "",
            "```",
            approved_text.strip(),
            "```",
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


def generate_proof_html():
    """Build a styled dark-theme HTML proof-of-work document."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    thread_lookup = {t.get("id"): t for t in st.session_state.triaged}

    cards_html = ""
    for tid, approved_text in st.session_state.approved.items():
        thread   = thread_lookup.get(tid, {})
        subject  = thread.get("subject", "(no subject)")
        priority = thread.get("priority", "")
        emoji    = PRIORITY_EMOJI.get(priority, "")
        color    = PRIORITY_COLOR.get(priority, "#8be9fd")

        msgs_html = ""
        for idx, msg in enumerate(thread.get("messages", []), start=1):
            msgs_html += (
                '<div style="margin-bottom:12px;">'
                '<div style="font-size:11px; color:#8be9fd; margin-bottom:4px;">'
                '<b style="color:#ffd86b">From:</b> ' + msg.get("from", "Unknown") +
                ' &nbsp;|&nbsp; '
                '<b style="color:#ffd86b">Date:</b> ' + msg.get("date", "Unknown") +
                '</div>'
                '<div style="color:#ddd; font-size:13px; line-height:1.6; white-space:pre-wrap;">' +
                msg.get("body", "").strip() +
                '</div></div>'
            )

        cards_html += (
            '<div class="card">'
            '<div class="card-header">'
            '<span class="priority-badge" style="background:' + color + '22; color:' + color + '; border:1px solid ' + color + '44;">'
            + emoji + " " + priority +
            '</span>'
            '<h2>' + subject + '</h2>'
            '</div>'
            '<div class="grid">'
            '<div class="panel thread-panel">'
            '<div class="panel-label" style="color:#e94560;">\U0001F4E8 Original Thread</div>'
            + msgs_html +
            '</div>'
            '<div class="panel draft-panel">'
            '<div class="panel-label" style="color:#4ecca3;">\u270D\uFE0F Approved Draft</div>'
            '<div style="white-space:pre-wrap; font-size:13px; line-height:1.7; color:#f0f0f0;">' +
            approved_text.strip() +
            '</div></div></div></div>'
        )
    action_log = get_action_log()
    log_html = ""
    if action_log:
        log_html = '<div style="margin-top: 40px; border-top: 1px solid #2a2a4a; padding-top: 30px;">'
        log_html += '<h2 style="color:#fff; margin-bottom:16px;">\U0001F4CB Action Log</h2>'
        log_html += '<table style="width:100%; text-align:left; border-collapse: collapse; margin-top: 16px; font-size: 14px;">'
        log_html += '<tr style="border-bottom: 1px solid #2a2a4a; color:#8be9fd;">'
        log_html += '<th style="padding: 12px 8px;">Action</th><th style="padding: 12px 8px;">Subject</th><th style="padding: 12px 8px;">Details</th><th style="padding: 12px 8px;">Timestamp</th></tr>'
        for entry in action_log:
            atype = entry.get("action_type", "").upper()
            icon = "📤" if atype == "SENT" else "📅" if atype == "BOOKED" else ""
            ts = entry.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                ts = dt.strftime("%b %d %I:%M %p")
            except ValueError:
                pass
            log_html += '<tr style="border-bottom: 1px solid #2a2a4a;">'
            log_html += f'<td style="padding: 12px 8px;">{icon} {atype}</td>'
            log_html += f'<td style="padding: 12px 8px;"><b>{entry.get("thread_subject", "")}</b></td>'
            log_html += f'<td style="padding: 12px 8px; color:#4ecca3;"><code>{entry.get("detail", "")}</code></td>'
            log_html += f'<td style="padding: 12px 8px; color:#aaa;">{ts}</td>'
            log_html += '</tr>'
        log_html += '</table></div>'

    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '  <meta charset="UTF-8"/>\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>\n'
        '  <title>The Draft Desk — Proof of Work</title>\n'
        '  <style>\n'
        '    @import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap");\n'
        '    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\n'
        '    body { background: #1a1a2e; color: #f1f1f1; font-family: "Inter", sans-serif;\n'
        '           padding: 40px 24px; min-height: 100vh; }\n'
        '    .header { text-align: center; margin-bottom: 48px; }\n'
        '    .header h1 { font-size: 36px; font-weight: 700;\n'
        '      background: linear-gradient(135deg, #4ecca3, #ffd86b);\n'
        '      -webkit-background-clip: text; -webkit-text-fill-color: transparent;\n'
        '      background-clip: text; margin-bottom: 8px; }\n'
        '    .header .meta { color: #8be9fd; font-size: 14px; }\n'
        '    .card { background: #111827; border: 1px solid #2a2a4a; border-radius: 16px;\n'
        '            padding: 28px; margin-bottom: 32px;\n'
        '            box-shadow: 0 4px 24px rgba(0,0,0,0.4); }\n'
        '    .card-header { margin-bottom: 20px; }\n'
        '    .card-header h2 { font-size: 20px; font-weight: 700; color: #fff; margin-top: 8px; }\n'
        '    .priority-badge { display: inline-block; padding: 3px 10px; border-radius: 20px;\n'
        '                      font-size: 12px; font-weight: 600; letter-spacing: 0.04em; }\n'
        '    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }\n'
        '    @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }\n'
        '    .panel { border-radius: 10px; padding: 18px 20px; min-height: 160px; }\n'
        '    .thread-panel { background: #0f3460; border-left: 4px solid #e94560; }\n'
        '    .draft-panel  { background: #0a2e1e; border-left: 4px solid #4ecca3; }\n'
        '    .panel-label { font-size: 11px; font-weight: 700; letter-spacing: 0.08em;\n'
        '                   text-transform: uppercase; margin-bottom: 14px; display: block; }\n'
        '    .footer { text-align: center; margin-top: 48px; color: #555; font-size: 12px; }\n'
        '  </style>\n'
        '</head>\n'
        '<body>\n'
        '  <div class="header">\n'
        '    <h1>\u270D\uFE0F The Draft Desk — Proof of Work</h1>\n'
        '    <div class="meta">Generated: ' + now + ' &nbsp;|&nbsp; '
        + str(len(st.session_state.approved)) + ' approved draft(s)</div>\n'
        '  </div>\n'
        + cards_html +
        log_html +
        '  <div class="footer">Generated by The Draft Desk — AI Email Ghostwriter</div>\n'
        '</body>\n'
        '</html>'
    )


def render_phase_export_proof():
    st.markdown(
        '<div class="phase-header">\U0001F4E6 Export Proof</div>'
        '<div class="phase-sub">Download your approved drafts as a shareable proof-of-work bundle.</div>',
        unsafe_allow_html=True,
    )

    if not st.session_state.approved:
        st.markdown(
            '<div class="empty-state">\U0001F6E1\uFE0F No approved drafts yet.<br/>'
            'Complete Phase 3 (Approval Gate) first.</div>',
            unsafe_allow_html=True,
        )
        return

    n_approved = len(st.session_state.approved)
    n_rejected = len(st.session_state.rejected)

    s1, s2, s3 = st.columns(3)
    s1.metric("\u2705 Approved Drafts", n_approved)
    s2.metric("\u274C Rejected",        n_rejected)
    s3.metric("\U0001F4C5 Generated",   datetime.now().strftime("%b %d, %Y"))

    st.markdown("---")

    # ---- Download buttons --------------------------------------------------
    md_content   = generate_proof_markdown()
    html_content = generate_proof_html()
    ts = datetime.now().strftime("%Y%m%d_%H%M")

    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            label="\u2B07\uFE0F Download Proof (Markdown)",
            data=md_content.encode("utf-8"),
            file_name="draft_desk_proof_" + ts + ".md",
            mime="text/markdown",
            use_container_width=True,
            type="primary",
        )
    with dl2:
        st.download_button(
            label="\U0001F310 Download Proof (HTML)",
            data=html_content.encode("utf-8"),
            file_name="draft_desk_proof_" + ts + ".html",
            mime="text/html",
            use_container_width=True,
        )

    st.markdown("---")
    st.markdown("### \U0001F4CB Approved Drafts Preview")

    thread_lookup = {t.get("id"): t for t in st.session_state.triaged}

    for tid, approved_text in st.session_state.approved.items():
        thread   = thread_lookup.get(tid, {})
        subject  = thread.get("subject", "(no subject)")
        priority = thread.get("priority", "NEEDS-REPLY")
        emoji    = PRIORITY_EMOJI.get(priority, "")

        with st.expander(emoji + " " + subject, expanded=True):
            col_left, col_right = st.columns(2, gap="medium")

            with col_left:
                st.markdown(
                    '<span class="panel-label label-thread">\U0001F4E8 Original Thread</span>',
                    unsafe_allow_html=True,
                )
                thread_display = _format_thread_for_display(thread)
                st.markdown(
                    '<div class="thread-panel">' +
                    thread_display.replace("\n", "<br/>") +
                    '</div>',
                    unsafe_allow_html=True,
                )

            with col_right:
                st.markdown(
                    '<span class="panel-label label-draft">\u270D\uFE0F Approved Draft</span>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    '<div style="background:#0a2e1e; border-left:3px solid #4ecca3;'
                    ' padding:14px 18px; border-radius:8px; white-space:pre-wrap;'
                    ' font-size:13px; line-height:1.7; color:#f0f0f0;">' +
                    approved_text.replace("\n", "<br/>") +
                    '</div>',
                    unsafe_allow_html=True,
                )

    st.markdown("---")
    st.markdown("### Action Log")
    log_entries = get_action_log()
    if not log_entries:
        st.info("No actions logged yet.")
    else:
        for entry in log_entries:
            c1, c2, c3, c4 = st.columns([1.5, 3, 3, 2])
            with c1:
                atype = entry.get("action_type", "").upper()
                icon = "📤" if atype == "SENT" else "📅"
                st.markdown(f"{icon} {atype}")
            with c2:
                st.markdown(f"**{entry.get('thread_subject', '')}**")
            with c3:
                st.markdown(f"`{entry.get('detail', '')}`")
            with c4:
                try:
                    dt = datetime.fromisoformat(entry.get("timestamp", "").replace("Z", "+00:00"))
                    st.caption(dt.strftime("%b %d %I:%M %p"))
                except ValueError:
                    st.caption(entry.get("timestamp", ""))


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

if st.session_state.pipeline_running:
    _render_pipeline_execution()
else:
    phase = st.session_state.current_phase

    if phase == "Inbox & Triage":
        render_phase_inbox_triage()
    elif phase == "Draft Generation":
        render_phase_draft_generation()
    elif phase == "Approval Gate":
        render_phase_approval_gate()
    elif phase == "Export Proof":
        render_phase_export_proof()