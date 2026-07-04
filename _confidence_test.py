"""Smoke-test the confidence heuristic without hitting the Gemini API."""
import sys
sys.path.insert(0, r"c:\Users\kamal\OneDrive\Documents\CHIEF_OF_STAFF")
from draft_machine import _compute_heuristic_confidence

good_thread = {"subject": "Q3 Budget Review", "messages": [{"from": "p@x.com", "body": "Can you approve?"}]}
good_draft  = (
    "Hi Priya,\n\n"
    "The $180K split looks reasonable. I'm good to approve once you've confirmed the UX research line.\n\n"
    "Can we lock this in by EOD Friday?\n\n"
    "Best,\nRahul"
)

medium_draft = "Sounds good."

bad_draft = "Yes."

print(f"Good draft    -> {_compute_heuristic_confidence(good_draft, good_thread):.0%}")
print(f"Medium draft  -> {_compute_heuristic_confidence(medium_draft, good_thread):.0%}")
print(f"Bad draft     -> {_compute_heuristic_confidence(bad_draft, good_thread):.0%}")
print(f"Empty draft   -> {_compute_heuristic_confidence('', good_thread):.0%}")
print(f"Filler draft  -> {_compute_heuristic_confidence('I hope this finds you well. Thank you for reaching out.', good_thread):.0%}")