"""
demo_ollama.py
==============
Runs the Discharge Negotiator Agent locally via Ollama.
Uses the OpenAI-compatible endpoint that Ollama exposes on port 11434.

Usage:
    ollama pull qwen2.5:7b
    python demo_ollama.py

No API key required — runs fully locally.
"""

import json
from datetime import datetime
from openai import OpenAI

from discharge_store import DischargeStore
from discharge_tools import TOOL_DEFINITIONS, execute_tool
from discharge_agent import SYSTEM_PROMPT

# ── Model ──────────────────────────────────────────────────────────────────
OLLAMA_MODEL = "qwen2.5:7b"

# Convert to OpenAI tool format
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        },
    }
    for tool in TOOL_DEFINITIONS
]


def run_discharge_cycle_ollama(client: OpenAI, store: DischargeStore, cycle: int) -> None:
    print(f"\n{'='*60}")
    print(f"  DISCHARGE NEGOTIATOR CYCLE {cycle} [Ollama: {OLLAMA_MODEL}]  |  {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Discharge negotiator cycle {cycle} starting now. "
                f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
                "Please assess all admitted patients for discharge readiness, "
                "identify and resolve all blockers, and get ready patients home."
            ),
        },
    ]

    while True:
        response = client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=messages,
            tools=OPENAI_TOOLS,
            temperature=0.0,
        )

        message = response.choices[0].message
        messages.append(message)

        if message.content:
            print(f"\n[Agent reasoning]\n{message.content}")

        if not message.tool_calls:
            print("\n[Agent] Cycle complete.\n")
            break

        for tool_call in message.tool_calls:
            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                args = {}

            print(f"\n[Tool call] {tool_call.function.name}({json.dumps(args, indent=2)})")
            result = execute_tool(tool_call.function.name, args, store)
            print(f"[Tool result] {json.dumps(result, indent=2)}")

            messages.append({
                "role":         "tool",
                "tool_call_id": tool_call.id,
                "name":         tool_call.function.name,
                "content":      json.dumps(result),
            })


def demo_ollama():
    client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    store  = DischargeStore()

    print("=" * 60)
    print("  DISCHARGE NEGOTIATOR AGENT — OLLAMA DEMO")
    print(f"  Model  : {OLLAMA_MODEL}")
    print(f"  Pattern: ReAct (tool-use loop)")
    print("=" * 60)

    run_discharge_cycle_ollama(client, store, cycle=1)

    # Audit
    actions  = store.get_action_log()
    sms_log  = store.get_sms_log()
    messages = store.get_agent_messages()
    blocker_resolves = [a for a in actions if a["action"] == "resolve_blocker"]
    eta_updates      = [a for a in actions if a["action"] == "update_eta"]

    print("\n" + "=" * 60)
    print("  AUDIT SUMMARY")
    print("=" * 60)
    print(f"\nBlockers resolved  : {len(blocker_resolves)}")
    print(f"ETA updates        : {len(eta_updates)}")
    print(f"SMS sent           : {len(sms_log)}")
    print(f"Agent messages     : {len(messages)}")

    for s in sms_log:
        print(f"  -> {s['recipient']} ({s['phone']}): {s['message'][:80]}")


if __name__ == "__main__":
    demo_ollama()