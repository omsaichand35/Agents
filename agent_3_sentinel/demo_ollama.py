import json
from datetime import datetime
from openai import OpenAI

from sentinel_store import SentinelStore
from sentinel_tools import TOOL_DEFINITIONS, execute_tool

# Import the existing system prompt without touching any agent files
from sentinel_agent import SYSTEM_PROMPT

# ── Model ──────────────────────────────────────────────────────────────────
OLLAMA_MODEL = "qwen2.5:7b"

# Convert Anthropic's 'input_schema' JSON schema format to OpenAI's tool format
OPENAI_TOOLS = []
for tool in TOOL_DEFINITIONS:
    OPENAI_TOOLS.append({
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}})
        }
    })

def run_sentinel_cycle_ollama(client: OpenAI, store: SentinelStore, cycle: int) -> None:
    """A separate cycle loop specifically for the OpenAI module and Ollama API behavior."""
    print(f"\n{'='*60}")
    print(f"  DETERIORATION SENTINEL CYCLE {cycle} [Ollama: {OLLAMA_MODEL}] |  {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Sentinel cycle {cycle} starting now. "
                f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
                "Please assess all admitted patients for signs of deterioration "
                "and take any necessary actions."
            )
        }
    ]

    # ReAct Loop
    while True:
        response = client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=messages,
            tools=OPENAI_TOOLS,
            temperature=0.0
        )

        message = response.choices[0].message
        
        # Add the assistant's message out back to the history to form the chain
        messages.append(message)
        
        if message.content:
            print(f"\n[Agent reasoning]\n{message.content}")

        # If it does not call any tools, cycle completes
        if not message.tool_calls:
            print("\n[Agent] Cycle complete.\n")
            break
            
        # Process each tool
        for tool_call in message.tool_calls:
            # Parse arguments
            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                args = {}
            
            print(f"\n[Tool call] {tool_call.function.name}({json.dumps(args, indent=2)})")
            
            # Execute tool safely against the generic backend
            result = execute_tool(tool_call.function.name, args, store)
            print(f"[Tool result] {json.dumps(result, indent=2)}")
            
            # Send the tool result backward to the LLM context
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": json.dumps(result)
            })

def demo_ollama():
    """Start point of the Ollama-specific demo."""
    # Connect to the local Ollama instance's OpenAI compatible port
    client = OpenAI(
        base_url='http://localhost:11434/v1',
        api_key='ollama', 
    )
    store = SentinelStore()

    print("=" * 60)
    print("  DETERIORATION SENTINEL AGENT — OLLAMA DEMO")
    print(f"  Model  : {OLLAMA_MODEL}")
    print(f"  Pattern: ReAct (tool-use loop)")
    print("=" * 60)

    print("\n[Demo] 3 admitted patients in the store:")
    print("  CGH-001 — Meena Krishnan, 58F, Ward 3")
    print("            Temp 37.0→37.4→37.8→38.1 | HR 78→85→94→103 | BP 118→112→104→96")
    print("            → Classic early sepsis pattern (agent should flag HIGH)")
    print()
    print("  CGH-002 — Ravi Shankar, 45M, Ward 3")
    print("            Declining into infection but scheduled for discharge")
    print("            → Agent should flag MEDIUM/HIGH AND message_agent to hold_discharge")
    print()
    print("  CGH-003 — Priya Nair, 32F, ICU")
    print("            SpO2 97.0→96.2→95.1→94.0 — consistent decline over 12 hours")
    print("            → Agent should flag MEDIUM (respiratory concern)")
    print()

    # ── Run the sentinel cycle ─────────────────────────────────────────────
    run_sentinel_cycle_ollama(client, store, cycle=1)

    # ── Audit summary ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  AUDIT SUMMARY")
    print("=" * 60)

    alerts   = store.get_alert_log()
    messages = store.get_message_log()
    actions  = store.get_action_log()

    print(f"\nAlerts fired         : {len(alerts)}")
    print(f"Agent messages sent  : {len(messages)}")
    print(f"Actions logged       : {len(actions)}")

    print("\n── Alerts ──")
    if not alerts:
        print("  None fired.")
    for a in alerts:
        patient = store.get_patient(a.patient_id)
        name    = patient.name if patient else a.patient_id
        print(f"\n  [{a.severity.upper()}] {name} ({a.patient_id})")
        print(f"  Alert ID  : {a.alert_id}")
        print(f"  Triggered : {a.triggered_at}")
        print(f"  Reasoning : {a.reasoning[:250]}...")

    print("\n── Agent messages ──")
    if not messages:
        print("  None sent.")
    for m in messages:
        print(f"  → {m.to_agent} | {m.message_type} | {m.content[:80]}")

    print()

if __name__ == "__main__":
    demo_ollama()