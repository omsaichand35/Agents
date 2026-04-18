import json
from datetime import datetime
from openai import OpenAI

from care_store import CareStore
from care_tools import TOOL_DEFINITIONS, execute_tool

# Import the existing system prompt without touching any agent files
from care_agent import SYSTEM_PROMPT

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

def run_care_cycle_ollama(client: OpenAI, store: CareStore, cycle: int) -> None:
    """A separate cycle loop specifically for the OpenAI module and Ollama API behavior."""
    print(f"\n{'='*60}")
    print(f"  CARE CONTINUITY CYCLE {cycle} [Ollama: {OLLAMA_MODEL}] |  {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Care continuity cycle {cycle} starting now. "
                f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
                "Please scan all patient care plans, detect any gaps, and resolve them."
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
    store = CareStore()

    print("=" * 60)
    print("  CARE CONTINUITY AGENT — OLLAMA DEMO")
    print(f"  Model  : {OLLAMA_MODEL}")
    print(f"  Pattern: ReAct (tool-use loop)")
    print("=" * 60)

    # ── Cycle 1: critical antibiotic gap ──────────────────────────────────
    print("\n[Demo] Cycle 1:")
    print("  Meena P. — Amoxicillin-Clavulanate prescribed 6h ago,")
    print("  never dispensed (pharmacy out of stock), never administered.")
    print("  Agent should: detect gap → query pharmacy → find substitute")
    print("  → get doctor approval → update prescription → notify all.\n")
    run_care_cycle_ollama(client, store, cycle=1)

    # ── Cycle 2: administration overdue ───────────────────────────────────
    print("\n[Demo] Cycle 2:")
    print("  Arjun K. — Metoprolol dispensed but nurse has not confirmed")
    print("  administration (1h overdue). Agent should: detect gap → notify nurse.\n")
    run_care_cycle_ollama(client, store, cycle=2)

    # ── Audit summary ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  AUDIT SUMMARY")
    print("=" * 60)

    actions = store.get_action_log()
    sms     = store.get_sms_log()
    gaps    = store.get_open_gaps()

    print(f"\nActions logged      : {len(actions)}")
    print(f"Notifications sent  : {len(sms)}")
    print(f"Remaining open gaps : {len(gaps)}")

    print("\n── Action log ──")
    for a in actions:
        print(f"  [{a['timestamp']}] {a['action_type']}: {str(a['detail'])[:80]}")

    print("\n── Notifications ──")
    for s in sms:
        print(f"  → {s['recipient']} ({s['phone']}): {s['message'][:80]}")

    print("\n── Open gaps ──")
    if not gaps:
        print("  None — all gaps resolved.")
    for g in gaps:
        print(f"  {g.gap_id} | {g.severity} | {g.description[:70]}")

if __name__ == "__main__":
    demo_ollama()