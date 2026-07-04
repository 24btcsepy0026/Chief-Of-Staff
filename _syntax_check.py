import ast
import sys

files = [
    r"c:\Users\kamal\OneDrive\Documents\CHIEF_OF_STAFF\app.py",
    r"c:\Users\kamal\OneDrive\Documents\CHIEF_OF_STAFF\triage.py",
    r"c:\Users\kamal\OneDrive\Documents\CHIEF_OF_STAFF\draft_machine.py",
    r"c:\Users\kamal\OneDrive\Documents\CHIEF_OF_STAFF\engine.py",
    r"c:\Users\kamal\OneDrive\Documents\CHIEF_OF_STAFF\calendar_engine.py",
]

ok = True
for path in files:
    try:
        ast.parse(open(path, encoding="utf-8").read())
        print(f"[OK]   {path}")
    except SyntaxError as e:
        ok = False
        print(f"[FAIL] {path}: {e}")

sys.exit(0 if ok else 1)