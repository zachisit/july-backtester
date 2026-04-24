"""
Autoresearch scoring script.
Runs main.py with AUTORESEARCH=1, finds the latest iteration JSON,
and prints the score for autoresearch to parse.
"""

import json
import os
import glob

# Find the latest iteration file
files = sorted(glob.glob("autoresearch_runs/iteration_*.json"))
if not files:
    print("SCORE: 0")
    exit(1)

latest = files[-1]
with open(latest) as f:
    data = json.load(f)

# Score = total return percentage
ec = data.get("equity_curve", [])
if len(ec) > 1:
    start_val = ec[0]["value"]
    end_val = ec[-1]["value"]
    score = round(((end_val / start_val) - 1) * 100, 2)
else:
    score = 0

print(f"SCORE: {score}")