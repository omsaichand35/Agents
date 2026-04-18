"""
Recovery Guardian Agent — OLLAMA DEMO
=====================================
Model  : qwen2.5:7b
Pattern: ReAct (tool-use loop)

Runs a single cycle of the Recovery Guardian agent using the local Ollama LLM.
"""

import os
import json
from openai import OpenAI
from datetime import datetime
from recovery_store import RecoveryStore
from tools import TOOL_DEFINITIONS, execute_tool

MODEL = "qwen2.5:7b"

# Convert tool definitions to OpenAI/Ollama format
OLLAMA_TOOLS = []
for tool in TOOL_DEFINITIONS:
    func = {"type": "function", "function": {"name": tool["name"], "description": tool["description"]}}
    if tool.get("input_schema", {}).get("properties"):
        func["function"]["parameters"] = tool["input_schema"]
    OLLAMA_TOOLS.append(func)

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

def main():
    client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    store = RecoveryStore()

    print("="*60)
    print("  RECOVERY GUARDIAN AGENT — OLLAMA DEMO")
    print(f"Model  : {MODEL}")
    print("Pattern: ReAct (tool-use loop)")
    print("="*60)

    chat = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Recovery Guardian cycle 1 starting now. Current time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ". Assess all discharged patients in home recovery and take appropriate action."}
        ],
        tools=OLLAMA_TOOLS,
        tool_choice="auto",
        temperature=0.0,
        stream=True,
    )

    for chunk in chat:
        if chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
        if chunk.choices[0].delta.tool_calls:
            for call in chunk.choices[0].delta.tool_calls:
                args = json.loads(call.function.arguments)
                print(f"\n[Tool call] {call.function.name}({json.dumps(args, indent=2)})")
                result = execute_tool(call.function.name, args, store)
                print(f"[Tool result] {json.dumps(result, indent=2)}")

if __name__ == "__main__":
    main()
