from pathlib import Path
import sys
import warnings

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from Agentic_AI.desktop_assistant_swarm.agents.supervisor import app
from Agentic_AI.desktop_assistant_swarm.config.settings import SWARM_THREAD_ID
from Agentic_AI.desktop_assistant_swarm.tools.os_automation import launch_notepad_and_type

warnings.filterwarnings("ignore", category=UserWarning)

if __name__ == "__main__":
    config = {"configurable": {"thread_id": SWARM_THREAD_ID}}
    print("Connecting to Assistant Security & Compliance Authorization Desk...")

    current_state = app.get_state(config)

    if not current_state.values:
        print("ERROR: No pending or frozen automation loops found in memory rows.")
        exit()

    print("\n⚠️  [PENDING OS ACTION]: An agent is requesting access to execute local system updates or click events.")
    print("1. APPROVE -> Release the lock and allow the system worker to run actions live.")
    print("2. TERMINATE -> Wipe state context and abort deployment.")

    choice = input("\nEnter confirmation code index (1 or 2): ").strip()

    if choice == "1":
        print("\n✅ Verification granted. Resuming execution track stream over OS systems...")
        result = launch_notepad_and_type.invoke({
            "input_text": "India is a diverse country with a rich history, culture, and geography."
        })
        print(f"\n🏆 [FINAL EXECUTIVE SUMMARY EXECUTED]:\n{result}\n")
    else:
        print("\n❌ Action rejected. Execution track aborted safely.")
