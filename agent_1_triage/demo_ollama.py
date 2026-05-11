import json
from datetime import datetime
from openai import OpenAI

from patient_store import PatientStore, Patient
from tools import TOOL_DEFINITIONS, execute_tool

# Import the existing system prompt without touching any agent files
from triage_agent import SYSTEM_PROMPT

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


def run_triage_cycle_ollama(client: OpenAI, store: PatientStore, cycle: int) -> None:
    """A separate cycle loop specifically for the OpenAI module and Ollama API behavior."""
    print(f"\n{'='*60}")
    print(f"  TRIAGE CYCLE {cycle} [Ollama: {OLLAMA_MODEL}] |  {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Triage cycle {cycle} starting now. "
                f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
                f"Please assess the waiting queue and take any necessary actions."
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
    store = PatientStore()

    print("=" * 60)
    print("  TRIAGE ORCHESTRATOR AGENT — OLLAMA DEMO")
    print(f"  Model  : {OLLAMA_MODEL}")
    print(f"  Pattern: ReAct (tool-use loop)")
    print("=" * 60)

    # ── Cycle 1: baseline queue (token order wrong) ────────────────────────
    print("\n[Demo] Cycle 1 — queue is in token order, acuity is not respected.\n")
    run_triage_cycle_ollama(client, store, cycle=1)

    # ── Simulate a new emergency patient arriving ──────────────────────────
    print("\n[Demo] A new patient just checked in at the front desk...")
    store.add_patient(Patient(
        id="P005",
        name="Kumar R.",
        age=62,
        token="A005",
        chief_complaint="Sudden onset confusion, slurred speech, left-sided facial droop — started 20 min ago",
        arrived_at=datetime.now().strftime("%H:%M"),
        phone="+91-97654-00001",
        vitals={"bp": "185/110", "hr": 88, "spo2": 95, "temp": 98.6},
    ))
    print(f"[Demo] Kumar R. added. Queue now has {len(store.get_queue())} patients.\n")

    # ── Cycle 2: agent detects stroke patient, re-prioritises ──────────────
    print("[Demo] Cycle 2 — agent detects high-acuity stroke patient.\n")
    run_triage_cycle_ollama(client, store, cycle=2)

    # ── Print audit logs ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  AUDIT LOG SUMMARY")
    print("=" * 60)

    print(f"\nReshuffles performed : {len(store.get_action_log())}")
    print(f"SMS messages sent    : {len(store.get_sms_log())}")
    print(f"Doctor notifications : {len(store.get_doctor_log())}")

    print("\n── Final queue order ──")
    for p in store.get_queue():
        print(f"  {p.position}. {p.name:15} | Age {p.age} | {p.chief_complaint[:55]}")

    print("\n── SMS log ──")
    for sms in store.get_sms_log():
        print(f"  -> {sms['phone']}: {sms['message'][:80]}")

    print("\n── Doctor alerts ──")
    for alert in store.get_doctor_log():
        print(f"  [{alert['priority'].upper()}] {alert['message'][:100]}")


if __name__ == "__main__":
    demo_ollama()