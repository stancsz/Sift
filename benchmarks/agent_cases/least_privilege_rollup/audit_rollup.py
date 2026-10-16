"""Starter for a deterministic least-privilege grant rollup."""
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DATA=ROOT/"data"
OUTPUT=ROOT/"access_rollup.json"
SUBJECT="alice.chen@stratus.example"
START="2026-07-18"
END="2026-10-16"

def build_report() -> dict:
    # TODO: join the request, effective policy rules, and normal in-window events.
    return {"subject": SUBJECT, "review_window":{"start":START,"end":END},
            "approved":[], "unused":[], "policy_blocked":[]}

def main() -> None:
    OUTPUT.write_text(json.dumps(build_report(),indent=2,sort_keys=True)+"\n",encoding="utf-8")

if __name__=="__main__": main()
