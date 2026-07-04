import colorama
from colorama import Fore, Style

colorama.init(autoreset=True)

ICONS = {"urgent": "🔴", "needs-reply": "🟡", "fyi": "🟢", "ignore": "⚪"}
COLORS = {
    "urgent": Fore.RED,
    "needs-reply": Fore.YELLOW,
    "fyi": Fore.GREEN,
    "ignore": Fore.LIGHTBLACK_EX
}

def format_digest(results: list) -> str:
    counts = {}
    for r in results:
        counts[r["priority"]] = counts.get(r["priority"], 0) + 1
        
    lines = []
    lines.append("="*60)
    lines.append(" YOUR INBOX DIGEST")
    lines.append(f" {len(results)} threads · generated now")
    lines.append("="*60)
    
    # Stretch goal: add an executive summary line
    urgent_count = counts.get("URGENT", 0)
    lines.append(f"\nYou have {urgent_count} urgent items needing attention today.")
    
    current_priority = None
    for r in results:
        priority = r.get("priority", "IGNORE")
        
        if priority != current_priority:
            current_priority = priority
            p_key = priority.lower()
            icon = ICONS.get(p_key, "⚪")
            color = COLORS.get(p_key, Fore.WHITE)
            count = counts.get(priority, 0)
            lines.append(f"\n{color}{icon} {priority} ({count}){Style.RESET_ALL}")
            
        p_key = priority.lower()
        color = COLORS.get(p_key, Fore.WHITE)
        
        lines.append(f" {color}▸ {r.get('subject', 'No Subject')}{Style.RESET_ALL}")
        lines.append(f"   {r.get('from', 'Unknown Sender')}")
        lines.append(f"   → {r.get('reason', '')}")
        
    return "\n".join(lines)

def export_html(results: list, filename="digest.html"):
    counts = {}
    for r in results:
        counts[r["priority"]] = counts.get(r["priority"], 0) + 1
    
    html = ["<html><head><style>body { font-family: sans-serif; background: #111; color: #eee; } h1, h2 { color: #fff; } .gray { color: #888; } .reason { color: #aaa; font-style: italic; }</style></head><body>"]
    html.append("<h1>Your Inbox Digest</h1>")
    html.append(f"<p><strong>{len(results)} threads</strong></p>")
    html.append(f"<p>You have {counts.get('URGENT', 0)} urgent items needing attention today.</p>")
    
    current_priority = None
    for r in results:
        priority = r.get("priority", "IGNORE")
        if priority != current_priority:
            current_priority = priority
            p_key = priority.lower()
            icon = ICONS.get(p_key, "⚪")
            count = counts.get(priority, 0)
            html.append(f"<h2>{icon} {priority} ({count})</h2>")
            
        html.append(f"<div style='margin-left: 20px; margin-bottom: 15px;'>")
        html.append(f"<strong>▸ {r.get('subject', 'No Subject')}</strong><br/>")
        html.append(f"<span class='gray'>{r.get('from', 'Unknown Sender')}</span><br/>")
        html.append(f"<span class='reason'>→ {r.get('reason', '')}</span>")
        html.append("</div>")
        
    html.append("</body></html>")
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("\n".join(html))
