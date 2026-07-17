from pathlib import Path
import sys
import warnings

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from Agentic_AI.desktop_assistant_swarm.agents.supervisor import app
from Agentic_AI.desktop_assistant_swarm.config.settings import SWARM_THREAD_ID

warnings.filterwarnings("ignore", category=UserWarning)

if __name__ == "__main__":
    config = {"configurable": {"thread_id": SWARM_THREAD_ID}}
    print("Booting up the Local Assistant Swarm...")

    user_request = {
        "messages": [("user", "Launch Notepad on my computer and make sure it had initialized properly. Once it initialized write about India in it.")]
    }

    for chunk in app.stream(user_request, config=config, stream_mode="values", subgraphs=True):
        pass

    print("\n🛑 [OS CORE INTERRUPT TRIPPED]: Safety Boundary Reached.")
    print("The system has prepared the application commands and committed state metrics to 'desktop_vault.db'.")
    print("Run 'security_desk.py' to approve and execute these actions live on your machine.")