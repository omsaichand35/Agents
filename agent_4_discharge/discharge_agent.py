"""
discharge_agent.py
==================
Discharge Negotiator Agent
===========================
Model  : gemini-2.5-flash
Pattern: ReAct  (Reason → Act → Observe → loop)

Runs every 30 minutes. Actively works to get every medically-ready patient
home. Identifies every blocker and resolves it without being asked.

The signature scenario:
  Ravi is medically ready for discharge. Vitals stable 48h. Doctor cleared him.
  But no one has:
    - Written the discharge summary
    - Submitted insurance pre-auth
    - Told pharmacy to prepare take-home medications
    - Arranged transport or contacted family

  Discharge Negotiator cycle:
    → Detects Ravi is clinically ready
    → Scans all 4 blockers
    → Drafts discharge summary → sends to doctor for e-signature
    → Submits insurance pre-auth with correct ICD-10 codes → approved
    → Messages pharmacy_agent to expedite 2 pending medications
    → SMS family asking about transport needs
    → Sets ETA: "You can expect to leave by 3:30 PM"
    → Loops every 30 min to track resolution and update ETA
    All without any human initiating it.
"""

import os
import json
import time
from google import genai
from google.genai import types
from datetime import datetime
from discharge_store import DischargeStore
from discharge_tools import TOOL_DEFINITIONS, execute_tool

# ── Model ─────────────────────────────────────────────────────────────────
MODEL = "gemini-2.5-flash"
MONITOR_INTERVAL_SECONDS = 1800   # 30 minutes

# ── Convert tool definitions to Gemini format ──────────────────────────────
GEMINI_TOOLS = []
for tool in TOOL_DEFINITIONS:
    func = {"name": tool["name"], "description": tool["description"]}
    if tool.get("input_schema", {}).get("properties"):
        func["parameters"] = tool["input_schema"]
    GEMINI_TOOLS.append(func)

# ── System prompt ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are the Discharge Negotiator Agent for PatientOS — a hospital AI system.
You are a project manager for every patient's departure from the hospital.
You run every 30 minutes. You work to get medically-ready patients home.

YOUR CYCLE PROTOCOL:

STEP 1 — BUILD YOUR WORKLIST
Call get_discharge_candidates to see all admitted patients and their readiness.
Separate them into:
  A) Ready + has blockers  → work on these now
  B) Ready + no blockers   → confirm discharge, SMS patient
  C) Not clinically ready  → call no_action, explain why, skip

STEP 2 — FOR EACH READY PATIENT: MAP ALL BLOCKERS
Call read_patient_record to get full context.
Call check_blocker_status to see every open blocker and its type.
Prioritise: summary → insurance → pharmacy → transport

STEP 3 — RESOLVE EACH BLOCKER ACTIVELY
Do not just list blockers. Act on each one:

  summary blocker:
    → Call draft_discharge_summary with clinical notes from the patient record.
    → Call resolve_blocker with the summary_id as resolution.

  insurance blocker:
    → Call submit_insurance_preauth with a clinical reason.
    → Call resolve_blocker with the auth_number as resolution.

  pharmacy blocker:
    → Call message_agent(to_agent='pharmacy_agent', message_type='expedite_medications')
      with the specific drug names and urgency.
    → Call resolve_blocker noting pharmacy has been messaged (update when confirmed).

  transport blocker:
    → Call send_sms(recipient='family') asking about transport needs and ETA.
    → Call resolve_blocker noting family has been contacted.

STEP 4 — SET / UPDATE ETA
After resolving blockers, call update_discharge_eta with a realistic time estimate.
Then call send_sms(recipient='patient') with "You can expect to leave by X:XX PM" message.

STEP 5 — COORDINATE WITH OTHER AGENTS
After discharge blockers are resolved:
  → message_agent(to_agent='deterioration_sentinel', message_type='patient_discharged')
    so they stop monitoring the patient.
  → message_agent(to_agent='triage_orchestrator', message_type='bed_available')
    so the bed can be prepared for the next patient.

STEP 6 — CONCLUDE
Summarise: how many patients assessed, how many were ready, how many blockers resolved,
what ETA was set, what agents were notified.

RULES:
- Always call no_action for patients who are not clinically ready.
- Always call resolve_blocker after completing each action — don't leave it pending.
- Always SMS the patient after updating ETA.
- Always message pharmacy before transport — medications take longer.
- Reason step-by-step before every tool call. Explain WHY.
- You are the project manager. You own this patient's discharge.
"""


# ── ReAct loop ─────────────────────────────────────────────────────────────
def run_discharge_cycle(client: genai.Client, store: DischargeStore, cycle: int) -> None:
    print(f"\n{'='*60}")
    print(f"  DISCHARGE NEGOTIATOR CYCLE {cycle}  |  {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[{"function_declarations": GEMINI_TOOLS}],
            temperature=0.0,
        ),
    )

    prompt = (
        f"Discharge negotiator cycle {cycle} starting now. "
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
        "Please assess all admitted patients for discharge readiness, "
        "identify and resolve all blockers, and get ready patients home."
    )

    response = chat.send_message(prompt)

    # ── ReAct turn loop ────────────────────────────────────────────────────
    while True:
        parts = response.candidates[0].content.parts if response.candidates else []

        for part in parts:
            if part.text:
                print(f"\n[Agent reasoning]\n{part.text}")

        function_calls = [p.function_call for p in parts if p.function_call]

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
                    response={"result": result},
                )
            )

        if tool_parts:
            response = chat.send_message(tool_parts)
        else:
            break


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    client  = genai.Client(api_key=api_key) if api_key else genai.Client()
    store   = DischargeStore()

    print("Discharge Negotiator Agent started.")
    print(f"Model    : {MODEL}")
    print(f"Pattern  : ReAct (tool-use loop)")
    print(f"Interval : every {MONITOR_INTERVAL_SECONDS // 60} minutes")
    print(f"Patients : {len(store.get_all_patients())} admitted\n")

    cycle = 0
    while True:
        cycle += 1
        run_discharge_cycle(client, store, cycle)
        print(f"[Monitor] Sleeping {MONITOR_INTERVAL_SECONDS}s until next cycle...")
        time.sleep(MONITOR_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()