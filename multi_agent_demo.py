import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path
from openai import OpenAI  # <-- For Ollama support

# ── Path injection (Fixes import errors for agent subdirectories) ─────────
root = Path(__file__).parent.absolute()
sys.path.extend([
    str(root / "agent_1_triage"),
    str(root / "agent_2_caretaker"),
    str(root / "agent_3_sentinel"),
    str(root / "agent_4_discharge"),
])

# ── Imports ───────────────────────────────────────────────────────────────
from sentinel_store   import SentinelStore
from care_store       import CareStore
from discharge_store  import DischargeStore
from patient_store    import PatientStore

import sentinel_tools
import care_tools
import discharge_tools
import tools as triage_tools

from shared_bus import bus

# ── Model ─────────────────────────────────────────────────────────────────
OLLAMA_MODEL = "qwen2.5:7b"

# ── Tool Mapping (OpenAI Format) ──────────────────────────────────────────

def convert_to_openai_tools(tool_definitions):
    """Converts Anthropic-style tool definitions to OpenAI-compatible format."""
    openai_tools = []
    for tool in tool_definitions:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}})
            }
        })
    return openai_tools

# ── ReAct Loop for Ollama ─────────────────────────────────────────────────

def run_agent_cycle_ollama(client: OpenAI, name: str, prompt: str, system_prompt: str, tools, execute_fn, store, cycle: int):
    print(f"\n{'='*60}")
    print(f"  {name.upper()} - CYCLE {cycle}  |  {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]

    openai_tools = convert_to_openai_tools(tools)

    while True:
        response = client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=messages,
            tools=openai_tools,
            temperature=0.0
        )

        message = response.choices[0].message
        messages.append(message)

        if message.content:
            print(f"\n[Agent reasoning]\n{message.content}")

        if not message.tool_calls:
            print(f"\n[{name}] Cycle complete.\n")
            break

        for tool_call in message.tool_calls:
            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                args = {}

            print(f"\n[Tool call] {tool_call.function.name}({json.dumps(args, indent=2)})")
            result = execute_fn(tool_call.function.name, args, store)
            print(f"[Tool result] {json.dumps(result, indent=2)}")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": json.dumps(result)
            })

# ── System prompts (concise versions for demo) ─────────────────────────────
# (Prompts remain the same as they were in the previous version)

SENTINEL_PROMPT = """
You are the Deterioration Sentinel Agent. 
Assess patients for signs of physiological decline (Sepsis, Respiratory failure, etc).
If a patient is deteriorating AND scheduled for discharge, call message_agent(hold_discharge).
If deterioration severity is HIGH, also call message_agent(check_medication_gaps) to care_continuity.
"""

CARE_PROMPT = """
You are the Care Continuity Agent. 
Scan for care gaps (missed meds, overdue tasks).
Process your inbox for check_medication_gaps requests from the Sentinel.
If you resolve a critical gap, notify other agents.
"""

DISCHARGE_PROMPT = """
You are the Discharge Negotiator Agent.
Scan for patients ready for discharge and resolve their blockers.
READ YOUR INBOX: If you see a 'hold_discharge' message for a patient, you MUST block their discharge.
Once a patient is discharged, notify Triage that a bed is available.
"""

def main():
    print("\n[!] Initializing multi-agent workflow using OLLAMA (Model: qwen2.5:7b)")
    
    client = OpenAI(
        base_url='http://localhost:11434/v1',
        api_key='ollama',
    )

    sentinel_store  = SentinelStore()
    care_store      = CareStore()
    discharge_store = DischargeStore()
    
    # Header
    print("=" * 60)
    print("  PATIENTOS - MULTI-AGENT WORKFLOW DEMO")
    print(f"  Model: {OLLAMA_MODEL} (Ollama)  |  Bus: shared_bus.py")
    print("=" * 60)

    print("\nScenario:")
    print("  Meena (CGH-001) - early sepsis + scheduled for discharge")
    print("  Ravi  (CGH-002) - stable + 4 discharge blockers")
    print("  Priya (CGH-003) - SpO2 declining (ICU)")

    # 1. Sentinel Cycle
    run_agent_cycle_ollama(
        client        = client,
        name          = "Deterioration Sentinel",
        prompt        = "Assess all admitted patients and take action.",
        system_prompt = SENTINEL_PROMPT,
        tools         = sentinel_tools.TOOL_DEFINITIONS,
        execute_fn    = sentinel_tools.execute_tool,
        store         = sentinel_store,
        cycle         = 1,
    )

    print("\n[Orchestrator] Sentinel done. Giving Care Continuity agent its turn...")

    # 2. Care Continuity Cycle
    run_agent_cycle_ollama(
        client        = client,
        name          = "Care Continuity",
        prompt        = "Process your inbox and scan for care gaps.",
        system_prompt = CARE_PROMPT,
        tools         = care_tools.TOOL_DEFINITIONS,
        execute_fn    = care_tools.execute_tool,
        store         = care_store,
        cycle         = 1,
    )

    print("\n[Orchestrator] Care done. Discharge Negotiator goes last...")

    # 3. Discharge Negotiator Cycle
    run_agent_cycle_ollama(
        client        = client,
        name          = "Discharge Negotiator",
        prompt        = "Check for discharge candidates and resolve blockers.",
        system_prompt = DISCHARGE_PROMPT,
        tools         = discharge_tools.TOOL_DEFINITIONS,
        execute_fn    = discharge_tools.execute_tool,
        store         = discharge_store,
        cycle         = 1,
    )

    # Final Bus Summary
    print("\n" + "=" * 60)
    print("  SHARED BUS AUDIT")
    print("=" * 60)
    
    summary = bus.summary()
    print(f"\nTotal messages  : {summary['total_messages']}")
    print(f"Unread messages : {summary['unread_messages']}")
    
    print("\nBy message type:")
    for mtype, n in summary["by_message_type"].items():
        print(f"  {mtype:30} : {n}")
        
    print("\nBy sending agent:")
    for a, n in summary["by_sending_agent"].items():
        print(f"  {a:30} : {n}")

    print("\n-- All bus messages --")
    for m in bus.get_all_messages():
        status = "v" if m.processed else "o"
        print(
            f"  {status} [{m.priority.upper():8}] {m.from_agent:25} -> {m.to_agent:25} "
            f"| {m.message_type:28} | patient={m.patient_id}"
        )
        print(f"      {m.content[:90]}")
        if m.response:
            print(f"      L> {m.response[:80]}")

    print()

if __name__ == "__main__":
    main()