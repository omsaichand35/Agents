from langgraph_supervisor import create_supervisor
from Agentic_AI.desktop_assistant_swarm.config.settings import TEXT_ROUTER_MODEL
from Agentic_AI.desktop_assistant_swarm.config.prompts import SUPERVISOR_PROMPT
from Agentic_AI.desktop_assistant_swarm.agents.workers import os_admin_worker, vision_eye_worker, browser_worker, coding_worker
from Agentic_AI.desktop_assistant_swarm.database.connection import get_db_checkpointer

workflow = create_supervisor(
    agents = [os_admin_worker, vision_eye_worker, browser_worker, coding_worker],
    model = TEXT_ROUTER_MODEL,
    prompt = SUPERVISOR_PROMPT,
    output_mode = "full_history"
)

checkpointer = get_db_checkpointer()

app = workflow.compile(checkpointer=checkpointer, interrupt_before=["os_admin_worker", "browser_worker"])
