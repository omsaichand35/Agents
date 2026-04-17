"""
Triage Orchestrator Agent
=========================
Model  : claude-sonnet-4-20250514  (Claude Sonnet 4 via Anthropic API)
Pattern: ReAct  (Reason → Act → Observe → loop)

The agent runs a continuous monitoring loop every 5 minutes.
Each cycle it:
  1. Reads all patient records from the waiting queue
  2. Reasons about acuity vs token order
  3. Reshuffles the queue if priority is wrong
  4. Sends SMS to affected patients
  5. Notifies the on-duty doctor if a high-acuity patient was moved
"""

import os
import json
import time
from google import genai
from google.genai import types
from datetime import datetime
from patient_store import PatientStore
from tools import TOOL_DEFINITIONS, execute_tool

# ── Model ──────────────────────────────────────────────────────────────────
MODEL = "gemini-2.5-flash"          # Gemini 2.5 Flash
MONITOR_INTERVAL_SECONDS = 300              # 5 minutes

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

# ── System prompt ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are the Triage Orchestrator Agent for a hospital emergency department.
You run continuously, monitoring the patient waiting queue every 5 minutes.

Your job:
1. Call read_queue to get all current patients and their token order.
2. For each patient, call read_patient_record to get their chief complaint, age, and vitals.
3. Score every patient on acuity (1-10):
   - 9-10: Life-threatening (chest pain + diaphoresis, stroke symptoms, severe trauma)
   - 7-8 : Urgent (high fever + altered consciousness, severe abdominal pain)
   - 5-6 : Moderate (moderate fever, fractures, moderate pain)
   - 1-4 : Low (minor lacerations, sprains, mild headache)
4. Compare your acuity ranking with the current token order.
5. If the token order does not match clinical priority:
   a. Call write_action with action="reshuffle_queue" and the correct ordered list.
   b. For each patient whose position changed, call send_sms to notify them.
   c. If any patient scored >= 8 was moved up, call notify_doctor with a clinical summary.
6. If no reshuffle is needed, log that the queue is optimal and wait for the next cycle.

Always reason step-by-step before calling a tool.
Always explain WHY you are reshuffling — cite the specific complaint and risk profile.
You are the decision-maker. No human approves your queue changes.
"""

# ── ReAct loop ─────────────────────────────────────────────────────────────
def run_triage_cycle(client: genai.Client, store: PatientStore, cycle: int) -> None:
    print(f"\n{'='*60}")
    print(f"  TRIAGE CYCLE {cycle}  |  {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[{"function_declarations": GEMINI_TOOLS}],
            temperature=0.0
        )
    )

    prompt = (f"Triage cycle {cycle} starting now. "
              f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
              f"Please assess the waiting queue and take any necessary actions.")

    response = chat.send_message(prompt)

    # ── ReAct turn loop ────────────────────────────────────────────────────
    while True:
        for part in response.candidates[0].content.parts:
            if part.text:
                print(f"\n[Agent reasoning]\n{part.text}")

        function_calls = [part.function_call for part in response.candidates[0].content.parts if part.function_call]

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

        response = chat.send_message(tool_parts)


# ── Main entry point ───────────────────────────────────────────────────────
def main():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key) if api_key else genai.Client()
    store = PatientStore()

    print("Triage Orchestrator Agent started.")
    print(f"Model     : {MODEL}")
    print(f"Pattern   : ReAct (tool-use loop)")
    print(f"Interval  : every {MONITOR_INTERVAL_SECONDS // 60} minutes")
    print(f"Patients  : {len(store.get_queue())} in queue\n")

    cycle = 0
    while True:
        cycle += 1
        run_triage_cycle(client, store, cycle)

        print(f"[Monitor] Sleeping {MONITOR_INTERVAL_SECONDS}s until next cycle...")
        time.sleep(MONITOR_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()