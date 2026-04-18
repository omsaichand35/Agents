"""
care_agent.py
=============
Care Continuity Agent
=====================
Model  : gemini-2.0-flash  (Gemini 2.0 Flash)
Pattern: ReAct  (Reason → Act → Observe → loop)

Runs every 30 minutes. Detects gaps in patient care plans.
Classifies severity. Finds resolutions. Gets minimal human approval.
Executes and updates all downstream records.

The signature scenario:
  10:00 AM  Doctor prescribes Amoxicillin-Clavulanate
  04:00 PM  Pharmacy never dispensed it — out of stock
             Nurse never administered it
             No human flagged anything

  Agent cycle at 04:00 PM:
    → Detects the gap (medication_not_dispensed, 6h, critical)
    → Queries pharmacy → out of stock
    → Searches drug DB → Co-Amoxiclav 625mg available
    → Sends doctor a one-tap approval request
    → Doctor approves
    → Updates prescription
    → Notifies pharmacy with new order
    → Updates nurse's medication sheet with new drug + time
    → Resolves the gap
    All without any human initiating it.
"""

import os
import json
import time
from google import genai
from google.genai import types
from datetime import datetime
from care_store import CareStore
from care_tools import TOOL_DEFINITIONS, execute_tool

# ── Model ─────────────────────────────────────────────────────────────────
MODEL = "gemini-2.0-flash"  # Gemini 2.0 Flash
MONITOR_INTERVAL_SECONDS = 1800  # 30 minutes

# Transform Anthropic tools to Gemini tools
GEMINI_TOOLS = []
for tool in TOOL_DEFINITIONS:
    func = {
        "name": tool["name"],
        "description": tool["description"],
    }
    if "input_schema" in tool and tool.get("input_schema", {}).get("properties"):
        func["parameters"] = tool["input_schema"]
    GEMINI_TOOLS.append(func)

# ── System prompt ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are the Care Continuity Agent for a hospital. You run every 30 minutes.
Your job: own every patient's care plan, detect gaps, and close them — without being asked.

Your cycle protocol:

STEP 1 — SCAN
Call scan_care_gaps to get all current care gaps across all patients.
If no gaps: state the queue is clean and end the cycle.

STEP 2 — TRIAGE EACH GAP
For each gap, call read_patient_record to get full context.
Classify the gap:
  - CRITICAL: antibiotics, anticoagulants, cardiac drugs, insulin — act immediately
  - MODERATE: analgesics, antipyretics — act within the cycle
  - LOW: vitamins, supplements — log and monitor

STEP 3 — INVESTIGATE ROOT CAUSE
For 'medication_not_dispensed' gaps:
  → Call query_pharmacy to check stock.
  → If out of stock, call drug_substitution_search to find a therapeutically equivalent alternative.

For 'administration_overdue' gaps:
  → Check if drug was dispensed.
  → If yes: notify the nurse urgently.
  → If no: treat as a dispensing gap first.

STEP 4 — RESOLVE
For drug substitutions:
  → Call escalate_to_human with a clear description and suggested_action for the doctor.
  → Once approved (approval status will be 'approved' in the response), call write_action with action='update_prescription'.
  → Call write_action with action='update_nurse_sheet' to reschedule administration.
  → Call send_notification to inform pharmacy, nurse, and doctor of changes.

For administration delays:
  → Call send_notification to nurse with urgent reminder.

STEP 5 — CLOSE
After all actions, summarise what gaps were found, what was done, and what approvals were obtained.

Rules:
- Never skip escalate_to_human for drug substitutions. Always get doctor approval first.
- Always notify every affected party (doctor, nurse, pharmacy) after a change.
- Reason step-by-step before each tool call. Explain WHY.
- You are not a human. But you act with clinical precision.
"""


# ── ReAct loop ─────────────────────────────────────────────────────────────
def run_care_cycle(client: genai.Client, store: CareStore, cycle: int) -> None:
    print(f"\n{'=' * 60}")
    print(f"  CARE CONTINUITY CYCLE {cycle}  |  {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'=' * 60}")

    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[{"function_declarations": GEMINI_TOOLS}],
            temperature=0.0
        )
    )

    prompt = (
        f"Care continuity cycle {cycle} starting now. "
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
        "Please scan all patient care plans, detect any gaps, and resolve them."
    )

    response = chat.send_message(prompt)

    # ── ReAct turn loop ────────────────────────────────────────────────────
    while True:
        parts = response.candidates[0].content.parts if response.candidates else []
        for part in parts:
            if part.text:
                print(f"\n[Agent reasoning]\n{part.text}")

        function_calls = [part.function_call for part in parts if part.function_call]

        if not function_calls:
            print("\n[Agent] Cycle complete.\n")
            break

        tool_parts = []
        for call in function_calls:
            # Convert args to native python dict
            clean_args = call.args if isinstance(call.args, dict) else dict(call.args)
            if not isinstance(clean_args, dict):
                clean_args = {}
            for k, v in clean_args.items():
                if hasattr(v, '__len__') and not isinstance(v, str):
                    clean_args[k] = list(v)

            print(f"\n[Tool call] {call.name}({json.dumps(clean_args, indent=2)})")
            result = execute_tool(call.name, clean_args, store)
            print(f"[Tool result] {json.dumps(result, indent=2)}")

            tool_parts.append(
                types.Part.from_function_response(
                    name=call.name,
                    response={"result": result}
                )
            )

        if tool_parts:
            response = chat.send_message(tool_parts)
        else:
            break


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key) if api_key else genai.Client()
    store = CareStore()

    print("Care Continuity Agent started.")
    print(f"Model    : {MODEL}")
    print(f"Pattern  : ReAct (tool-use loop)")
    print(f"Interval : every {MONITOR_INTERVAL_SECONDS // 60} minutes")

    cycle = 0
    while True:
        cycle += 1
        run_care_cycle(client, store, cycle)
        print(f"[Monitor] Sleeping {MONITOR_INTERVAL_SECONDS}s until next cycle...")
        time.sleep(MONITOR_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()