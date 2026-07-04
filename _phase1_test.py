# -*- coding: utf-8 -*-
"""
Phase 1 smoke-test: extract helpers from app.py and exercise the
Sample-source pipeline end-to-end (no Streamlit, no Gemini API needed).
"""
import sys
import json
import ast
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Placeholder declarations for static code analysis / IDE linters
    PRIORITY_ORDER: list = []
    SAMPLE_FILE: Path = Path()
    def _normalize_engine_thread(t: dict) -> dict: ...
    def _normalize_sample_thread(t: dict) -> dict: ...
    def _local_triage_sample(threads: list) -> list: ...
    def _load_sample_threads() -> list: ...
    def _actionable_count(triaged: list) -> int: ...
    def _priority_class(priority: str) -> str: ...

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# Load app.py source, extract the helper function definitions only
src = (HERE / "app.py").read_text(encoding="utf-8")
tree = ast.parse(src)
helper_names = {
    "_normalize_engine_thread",
    "_normalize_sample_thread",
    "_local_triage_sample",
    "_load_sample_threads",
    "_actionable_count",
    "_priority_class",
}
needed_consts = {"PRIORITY_ORDER", "SAMPLE_FILE"}
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in helper_names:
        exec(ast.unparse(node), globals())
    elif isinstance(node, ast.Assign):
        # Pull PRIORITY_ORDER + SAMPLE_FILE constants
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id in needed_consts:
                exec(ast.unparse(node), globals())

# ---- Test 1: load + triage sample threads ------------------------------
threads = _load_sample_threads()
print(f"[1] Loaded {len(threads)} sample threads")
assert len(threads) == 5, f"expected 5 sample threads, got {len(threads)}"
for t in threads:
    assert t["id"], f"missing id: {t}"
    assert t["subject"], f"missing subject: {t}"
    assert t["messages"], f"missing messages: {t}"
    for m in t["messages"]:
        assert m["from"] and m["date"] and m["body"], f"bad message: {m}"

triaged = _local_triage_sample(threads)
print(f"[2] Triaged {len(triaged)} threads (sorted by priority)")
by_pri = {}
for t in triaged:
    by_pri.setdefault(t["priority"], []).append(t["subject"])
for prio in ["URGENT", "NEEDS-REPLY", "FYI", "IGNORE"]:
    if prio in by_pri:
        print(f"    {prio:13s} ({len(by_pri[prio])})")
        for s in by_pri[prio]:
            print(f"      - {s[:75]}")

# Verify priority sort
priorities = [t["priority"] for t in triaged]
assert priorities == sorted(priorities, key=lambda p: PRIORITY_ORDER.index(p)), \
    "triaged list is not sorted by PRIORITY_ORDER"
print("[3] Sort order: OK")

# Verify actionable count = URGENT + NEEDS-REPLY
actionable = _actionable_count(triaged)
expected_actionable = len(by_pri.get("URGENT", [])) + len(by_pri.get("NEEDS-REPLY", []))
assert actionable == expected_actionable, \
    f"actionable={actionable} but expected {expected_actionable}"
print(f"[4] Actionable count: {actionable}")

# ---- Test 2: engine-shape normalization -------------------------------
fake_engine = [{
    "thread_id":   "abc123",
    "sender":      "alice@example.com",
    "subject":     "Test thread",
    "snippet":     "Hello world snippet",
    "date":        "2026-06-27 10:00 AM",
}]
normalized = _normalize_engine_thread(fake_engine[0])
print(f"[5] Engine->pipeline normalize: {json.dumps(normalized, indent=2)}")
assert normalized["id"]      == "abc123"
assert normalized["subject"] == "Test thread"
assert normalized["messages"][0]["from"] == "alice@example.com"
assert normalized["messages"][0]["body"] == "Hello world snippet"
assert normalized["messages"][0]["date"] == "2026-06-27 10:00 AM"

# ---- Test 3: missing 'date' field -> sensible default ------------------
no_date = {"thread_id": "x", "sender": "y", "subject": "z", "snippet": "s"}
nd = _normalize_engine_thread(no_date)
assert nd["messages"][0]["date"]  # must be non-empty
print(f"[6] Missing-date fallback: '{nd['messages'][0]['date']}'")

# ---- Test 4: priority class mapping -----------------------------------
assert _priority_class("URGENT")      == "urgent"
assert _priority_class("NEEDS-REPLY") == "reply"
assert _priority_class("FYI")         == "fyi"
assert _priority_class("IGNORE")      == "ignore"
print("[7] Priority class mapping: OK")

print()
print("=" * 60)
print("ALL PHASE-1 PIPELINE TESTS PASSED")
print("=" * 60)