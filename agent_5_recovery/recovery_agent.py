"""
Recovery Guardian Agent
=======================
Model  : gemini-2.0-flash
Pattern: ReAct  (Reason -> Act -> Observe -> loop)

Agent 5 — the final agent in the PatientOS multi-agent system.

Follows the patient HOME after discharge and watches over them until fully recovered.
Runs every morning at 8 AM. Each cycle:
  1. Reads all patients in post-discharge home recovery
  2. For each patient:
     a. Reads full recovery record (medications, check-in history, recovery day)
     b. Checks medication compliance log for missed critical doses silently
     c. Reads latest check-in response and trends
     d. Reasons adaptively about the full picture
     e. Takes the right action — reminder, flag, emergency SMS, or recovery close
"""

import os
import json
import time
from google import genai
from google.genai import types
from datetime import datetime
from recovery_store import RecoveryStore
from tools import TOOL_DEFINITIONS, execute_tool

# Model
MODEL = "gemini-2.0-flash"
MONITOR_INTERVAL_SECONDS = 86400  # 24 hours

# Transform to Gemini format
GEMINI_TOOLS = []
for tool in TOOL_DEFINITIONS:
    func = {"name": tool["name"], "description": tool["description"]}
    if tool.get("input_schema", {}).get("properties"):
        func["parameters"] = tool["input_schema"]
    GEMINI_TOOLS.append(func)


SYSTEM_PROMPT = """
You are the Recovery Guardian Agent for a hospital — Agent 5 in the PatientOS system.
You follow every discharged patient HOME and protect their recovery.
You run every morning. You are their AI companion until they are fully recovered.

YOUR CYCLE PROTOCOL:

STEP 1 — GET ALL PATIENTS
Call read_all_patients to see who is in home recovery today.

STEP 2 — ASSESS EACH PATIENT (one at a time)
For each patient:
  a) Call read_patient_recovery — full medications, check-in history, recovery day.
  b) Call read_compliance_gaps — detect missed critical doses EVEN IF patient says fine.
     A patient can say "I feel better" while silently skipping cardiac meds.
     You catch this here. This is your most important safety check.
  c) Read their latest check-in response and analyse the TREND across all days.

STEP 3 — DECIDE AND ACT

  Check-in "1" (better) + no compliance gap:
    -> send_medication_reminder. Patient is on track. No escalation.

  Check-in "2" (same) for 1 day:
    -> send_medication_reminder. Monitor.

  Check-in "2" (same) for 2+ consecutive days:
    -> send_medication_reminder + notify_doctor (routine flag).

  Check-in "3" (worse) — reason BEFORE acting:
    What is their diagnosis? What recovery day is it?
    Is this expected discomfort or a genuine red flag?
    If unexpected or Day 4+:
      -> send_emergency_sms (calm, specific instruction).
      -> notify_doctor (full clinical context).
      -> book_emergency_appointment (today or tomorrow).

  Critical compliance gap even if check-in says "better":
    -> send_emergency_sms explaining why their specific medication matters.
    -> notify_doctor about the gap.
    Severity: urgent (emergency only if cardiac/anticoagulant missed 3+ days).

  Recovery day >= medication duration AND check-in "1":
    -> mark_patient_recovered with a warm summary.

RULES:
- Always check compliance gaps BEFORE acting on check-in responses.
- Emergency SMS must be CALM and SPECIFIC — tell them what to do, not just that something is wrong.
- Always send medication reminder unless escalating to emergency.
- When in doubt — notify the doctor. A false alarm is better than a missed readmission.
- You are the last safety net between this patient and a preventable hospital return.
"""


def run_recovery_cycle(client: genai.Client, store: RecoveryStore, cycle: int) -> None:
    print(f"\n{'=' * 60}")
    print(f"  RECOVERY GUARDIAN — CYCLE {cycle}  |  {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'=' * 60}")

    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[{"function_declarations": GEMINI_TOOLS}],
            temperature=0.0,
        )
    )

    prompt = (
        f"Recovery Guardian cycle {cycle} starting now. "
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
        "Assess all discharged patients in home recovery and take appropriate action."
    )

    response = chat.send_message(prompt)

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
            clean_args = call.args if isinstance(call.args, dict) else dict(call.args)
            if not isinstance(clean_args, dict):
                clean_args = {}
            for k, v in clean_args.items():
                if hasattr(v, "__len__") and not isinstance(v, str):
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

        response = chat.send_message(tool_parts)


def main():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    client  = genai.Client(api_key=api_key) if api_key else genai.Client()
    store   = RecoveryStore()

    print("Recovery Guardian Agent started.")
    print(f"Model    : {MODEL}")
    print(f"Pattern  : ReAct (tool-use loop)")
    print(f"Interval : every 24 hours (every morning)")
    print(f"Patients : {len(store.get_all_patients())} in post-discharge recovery\n")

    cycle = 0
    while True:
        cycle += 1
        run_recovery_cycle(client, store, cycle)
        print(f"[Monitor] Sleeping until tomorrow morning...")
        time.sleep(MONITOR_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()