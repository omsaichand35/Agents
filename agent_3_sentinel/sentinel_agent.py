"""
sentinel_agent.py
=================
Deterioration Sentinel Agent
=============================
Model  : gemini-2.0-flash
Pattern: ReAct  (Reason -> Act -> Observe -> loop)

Runs every 30 minutes. Watches ALL admitted patients simultaneously.
Detects deterioration by analysing RATE OF CHANGE across vitals —
not just whether a value crossed a threshold.

The key insight:
  Meena's temperature went 37.0 -> 37.4 -> 37.8 -> 38.1 over 12 hours.
  None of these values individually triggers a standard alarm.
  But the consistent upward trend, combined with rising HR and falling BP,
  is a classic early sepsis signature — 4–6 hours before collapse.
  The Sentinel catches this. No human was watching at 2 AM.
"""

import os
import json
import time
from google import genai
from google.genai import types
from datetime import datetime
from sentinel_store import SentinelStore
from sentinel_tools import TOOL_DEFINITIONS, execute_tool

# ── Model ─────────────────────────────────────────────────────────────────
MODEL = "gemini-2.0-flash"
MONITOR_INTERVAL_SECONDS = 1800  # 30 minutes

# Convert tool definitions to Gemini format
GEMINI_TOOLS = []
for tool in TOOL_DEFINITIONS:
    func = {
        "name":        tool["name"],
        "description": tool["description"],
    }
    if tool.get("input_schema", {}).get("properties"):
        func["parameters"] = tool["input_schema"]
    GEMINI_TOOLS.append(func)

# ── System prompt ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are the Deterioration Sentinel Agent for PatientOS — a hospital AI system.
You run every 30 minutes, watching every admitted patient simultaneously.

YOUR CORE MISSION:
Detect patient deterioration EARLY — before any single vital hits a standard
alarm threshold. You catch the PATTERN, not the peak.

YOUR CYCLE PROTOCOL:

STEP 1 — GET THE WATCHLIST
Call read_admitted_patients to see who is admitted right now.

STEP 2 — ASSESS EACH PATIENT (repeat for every patient)
For each patient:
  a) Call read_patient_vitals to get their last 6 readings.
  b) Analyse the RATE OF CHANGE — not just current values.
     Ask yourself: is each vital getting worse across readings?
     Even small consistent changes are significant.
  c) Look for multi-signal patterns (more dangerous than one bad reading):
     • Early sepsis:    Temp ↑ + HR ↑ + BP ↓ + RR ↑ (even mild)
     • Respiratory:     SpO2 declining consistently (even 0.5% per reading)
     • Haemodynamic:    BP systolic falling + HR rising (compensating)
  d) Call check_active_alerts — never create a duplicate alert.
  e) Decide:
     -> If clear deterioration trend: call create_alert with full reasoning.
     -> If no concerning trend: call no_action with brief reason.
     -> If patient is flagged and scheduled for discharge: call message_agent
       with to_agent='discharge_negotiator', message_type='hold_discharge'.

STEP 3 — CONCLUDE
After all patients are assessed, summarise how many were stable,
how many were flagged, and what actions were taken.

SEVERITY RULES:
  low      — 1–2 signals, mild trend, patient looks overall stable
  medium   — 2–3 signals trending, rate of change worth watching
  high     — 3+ signals trending, or any signal moving fast
  critical — multi-signal sepsis pattern OR SpO2 below 93%

WHAT YOUR REASONING MUST INCLUDE (in create_alert):
  • Exact vital values with timestamps
  • Rate of change per signal (e.g. "Temp rose 1.1°C over 12 hours")
  • Which pattern this resembles
  • Why this warrants escalation now
  • Recommended immediate action for the doctor

IMPORTANT:
  - Never alert on a single bad reading if the overall trend is stable.
  - Always call no_action if a patient is stable — never skip a patient.
  - Always check for active alerts before creating a new one.
  - Your reasoning in create_alert is what the doctor reads at 2 AM.
    Be precise. Be complete. Be honest about uncertainty.

You are the only one watching these patients right now.
"""


# ── ReAct loop ─────────────────────────────────────────────────────────────

def run_sentinel_cycle(client: genai.Client, store: SentinelStore, cycle: int) -> None:
    print(f"\n{'='*60}")
    print(f"  DETERIORATION SENTINEL CYCLE {cycle}  |  {datetime.now().strftime('%H:%M:%S')}")
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
        f"Sentinel cycle {cycle} starting now. "
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
        "Please assess all admitted patients for signs of deterioration "
        "and take any necessary actions."
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
    store   = SentinelStore()

    print("Deterioration Sentinel Agent started.")
    print(f"Model    : {MODEL}")
    print(f"Pattern  : ReAct (tool-use loop)")
    print(f"Interval : every {MONITOR_INTERVAL_SECONDS // 60} minutes")
    print(f"Patients : {len(store.get_all_patients())} admitted\n")

    cycle = 0
    while True:
        cycle += 1
        run_sentinel_cycle(client, store, cycle)
        print(f"[Monitor] Sleeping {MONITOR_INTERVAL_SECONDS}s until next cycle...")
        time.sleep(MONITOR_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()