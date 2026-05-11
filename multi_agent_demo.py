import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path
from openai import OpenAI  # <-- For Ollama support
import httpx

# ── Path injection (Fixes import errors for agent subdirectories) ─────────
root = Path(__file__).parent.absolute()
sys.path.extend([
    str(root / "agent_1_triage"),
    str(root / "agent_2_caretaker"),
    str(root / "agent_3_sentinel"),
    str(root / "agent_4_discharge"),
    str(root / "agent_5_recovery"),
])

# ── Imports ───────────────────────────────────────────────────────────────
from agent_3_sentinel.sentinel_store import SentinelStore
from agent_2_caretaker.care_store import CareStore
from agent_4_discharge.discharge_store import DischargeStore
from agent_1_triage.patient_store import PatientStore

from agent_3_sentinel import sentinel_tools
from agent_2_caretaker import care_tools
from agent_4_discharge import discharge_tools
from agent_1_triage import tools as triage_tools

from shared_bus import bus
from shared_state import OperationalEvent, ops
from patient_registry import get_patient_record

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
        try:
            response = client.chat.completions.create(
                model=OLLAMA_MODEL,
                messages=messages,
                tools=openai_tools,
                temperature=0.0
            )
        except Exception as e:
            print(f"\n[ERROR] Connection to Ollama failed: {e}")
            print(f"[INFO] Retrying in 5 seconds...")
            time.sleep(5)
            try:
                response = client.chat.completions.create(
                    model=OLLAMA_MODEL,
                    messages=messages,
                    tools=openai_tools,
                    temperature=0.0
                )
            except Exception as e2:
                print(f"\n[ERROR] Retry failed: {e2}")
                print(f"[INFO] Skipping this agent cycle.")
                return

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
Your job is to detect deterioration early, remain conservative, and trigger only operationally safe actions.

Before each tool call, give one short sentence describing the decision.
Use tools to:
- inspect patient trends
- publish escalation events
- request discharge holds when risk is present
- notify care continuity about medication gaps when appropriate

Never diagnose. Never prescribe. Never discharge.
Keep reasoning brief and action-focused.
"""

CARE_PROMPT = """
You are the Care Continuity Agent.
Your job is to close care gaps, verify medication readiness, and coordinate follow-up tasks.

Before each tool call, give one short sentence describing the decision.
Use tools to:
- read your inbox
- check medication gaps
- confirm inventory and task completion
- escalate only when a gap cannot be safely resolved

Never prescribe. Never approve clinician decisions.
Keep reasoning brief and operational.
"""

DISCHARGE_PROMPT = """
You are the Discharge Negotiator Agent.
Your job is to resolve discharge blockers, respect any active holds, and coordinate safe release.

Before each tool call, give one short sentence describing the decision.
Use tools to:
- read your inbox
- detect discharge blockers
- hold discharge when sentinel or care flags active risk
- notify triage only after discharge is safe

Never override clinician clearance.
Keep reasoning concise and operational.
"""

def main():
    print("\n[!] Initializing multi-agent workflow using OLLAMA (Model: qwen2.5:7b)")
    
    # Add timeout and retry configuration for Ollama
    import httpx
    client = OpenAI(
        base_url='http://localhost:11434/v1',
        api_key='ollama',
        timeout=httpx.Timeout(300.0),  # 5 minute timeout for GPU model loading
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

    # Seed shared operational state so the workflow has a memory outside the agent stores.
    for canonical_id, workflow_state in [
        ("P-MEENA-001", "DETERIORATION_REVIEW"),
        ("P-RAVI-001", "DISCHARGE_PENDING"),
        ("P-PRIYA-001", "UNDER_MONITORING"),
    ]:
        record = get_patient_record(canonical_id) or {}
        state = ops.get_or_create(canonical_id, record.get("name", ""))
        if state.workflow_state == "ADMITTED":
            ops.transition(
                canonical_id,
                workflow_state,
                reason="demo_seed",
                agent="multi_agent_demo",
            )

    OperationalEvent.emit(
        event="demo.workflow_seeded",
        agent="multi_agent_demo",
        patient_id="MULTI",
        priority="info",
        next_action="start_agent_cycles",
        workflow_state="active",
        detail={"patients": len(ops.all_states())},
    )

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

    print("\n[Orchestrator] Running reaction sweep so inbox events propagate this run...")

    run_agent_cycle_ollama(
        client        = client,
        name          = "Deterioration Sentinel",
        prompt        = "Process inbox first, then reassess only newly flagged patients.",
        system_prompt = SENTINEL_PROMPT,
        tools         = sentinel_tools.TOOL_DEFINITIONS,
        execute_fn    = sentinel_tools.execute_tool,
        store         = sentinel_store,
        cycle         = 2,
    )

    run_agent_cycle_ollama(
        client        = client,
        name          = "Care Continuity",
        prompt        = "Process inbox first, prioritise medication-gap requests, then scan open gaps.",
        system_prompt = CARE_PROMPT,
        tools         = care_tools.TOOL_DEFINITIONS,
        execute_fn    = care_tools.execute_tool,
        store         = care_store,
        cycle         = 2,
    )

    run_agent_cycle_ollama(
        client        = client,
        name          = "Discharge Negotiator",
        prompt        = "Process inbox first, then re-evaluate discharge readiness and holds.",
        system_prompt = DISCHARGE_PROMPT,
        tools         = discharge_tools.TOOL_DEFINITIONS,
        execute_fn    = discharge_tools.execute_tool,
        store         = discharge_store,
        cycle         = 2,
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

    print("\n-- Workflow state snapshot --")
    for state in ops.all_states():
        print(
            f"  {state.patient_id:12} | {state.name:18} | {state.workflow_state:22} "
            f"| hold={str(state.discharge_hold):5} | alerts={len(state.active_alert_ids)}"
        )

    print("\n-- Transition log --")
    for row in ops.get_transition_log():
        print(
            f"  [{row['timestamp']}] {row['patient_id']:12} "
            f"{row['from_state']:20} -> {row['to_state']:20} ({row['agent']})"
        )

    print()

if __name__ == "__main__":
    main()