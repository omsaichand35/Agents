from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_ollama import ChatOllama
from langchain_core.tools import tool


# ----- THE STATE ------
class TicketState(TypedDict):
    messages: Annotated[list, add_messages]


# ------- The Account Database (FIXED: All lowercase keys) -----------
ACCOUNT_DATABASE = {
    "omsai": "VIP",
    "alice": "Standard",
    "bob": "Standard"
}

@tool
def lookup_account_tier(username: str) -> str:
    """Looks up the account subscription tier for a given username. Returns 'VIP' or 'Standard'."""
    print(f"🔧 [TOOL]: Looking up database records for user: '{username}'...")
    cleaned_name = username.lower().strip()
    return ACCOUNT_DATABASE.get(cleaned_name, "Standard")


tool_list = [lookup_account_tier]
tool_node = ToolNode(tool_list)

# ------ The system rule and Node -----------
SYSTEM_RULES = """
You are an automated Customer Support Escalation Agent operating in a strict Thought, Action, Observation loop.

Your absolute first step is ALWAYS to look up the user's account tier using your tool.
Action: lookup_account_tier("username")

Routing Policy after you get the Observation:
1. If the observation is 'VIP', output exactly: "Final Answer: Escalating directly to a Human Manager."
2. If the observation is 'Standard', write a helpful closing reply to their problem yourself.
"""

model = ChatOllama(
    model="qwen2.5:7b",
    temperature=0.0
).bind_tools(tool_list)


def call_router(state: TicketState):
    print("[NODE]: Agent is reading the ticket context...")
    message_with_rules = [{"role": "system", "content": SYSTEM_RULES}] + state["messages"]

    response = model.invoke(message_with_rules)
    return {"messages": [response]}


def should_continue(state: TicketState):
    last_message = state["messages"][-1]

    if last_message.tool_calls:
        print("[EDGE]: Tool call requested. Routing to the ToolNode...")
        return "tools"

    print("[EDGE]: No Tool call requested. Closing the ticket pipeline...")
    return END


# ------ Workflow pipelining ---------

workflow = StateGraph(TicketState)

workflow.add_node("agent", call_router)
workflow.add_node("tools", tool_node)

workflow.add_edge(START, "agent")
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "tools": "tools",
        END: END
    }
)
workflow.add_edge("tools", "agent")

memory_checkpointer = MemorySaver()

app = workflow.compile(checkpointer=memory_checkpointer)

# ---------------- Main Function -----------------
if __name__ == "__main__":
     config = {"configurable": {"thread_id" : "omsai_session_999"}}
     print("Booting up Memory persistent state Graph pipeline...")

     print("\n -------------- Turn 1 ----------------")
     turn_1_input = {"messages": [("user", "Hello, my username is omsai.")]}

     state_after_turn_1 = app.invoke(turn_1_input, config=config)

     print("\n--- TURN 2: User Asks a Follow-up Without Repeating Their Name ---")
     turn_2_input = {"messages": [("user", "I still can't log in. Can you process my help request now?")]}

     state_after_turn_2 = app.invoke(turn_2_input, config=config)
     print(f"🤖 Agent Response: {state_after_turn_2['messages'][-1].content}")