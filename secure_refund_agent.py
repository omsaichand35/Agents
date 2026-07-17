import sqlite3

from typing import Annotated, TypedDict
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite import SqliteSaver


class FinanceState(TypedDict):
    messages: Annotated[list, add_messages]


@tool
def process_monetary_refund(username: str, amount: float) -> str:
    """Executes a real monetary financial refund back to the user's bank card account ledger records."""
    print(f"[CRITICAL EXECUTION TOOL]: Successfully wired {amount} back to account {username}.")
    return f"Success: Refund of amount {amount} to account {username}!"


tool_list = [process_monetary_refund]
tool_node = ToolNode(tool_list)

SYSTEM_RULES = """
You are an AI Billing & Refund Specialist operating in a strict Thought, Action, Observation loop.

If a user requests a refund, verify the username and amount, then immediately execute your financial tool:
Action: process_monetary_refund(username="name", amount=0.00)

Once the tool returns its confirmation observation, provide a professional closing response to the user.
"""

model = ChatOllama(
    model="qwen2.5:7b",
    temperature=0.0
).bind_tools(tool_list)


def call_processor(state: FinanceState):
    print("[Message]: Agent is evaluating the transaction authority data...")
    message_to_send = [{"role": "system", "content": SYSTEM_RULES}] + state["messages"]
    response = model.invoke(message_to_send)
    return {"messages": [response]}


def should_continue(state: FinanceState):
    last_msg = state["messages"][-1]
    if last_msg.tool_calls:
        print("[MESSAGE]: Tool called. Routing to the required tool.")
        return "tools"
    print("[MESSAGE]: No tools are called. Agent has done the work...")
    return END


workflow = StateGraph(FinanceState)

workflow.add_node("agent", call_processor)
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

conn = sqlite3.connect("agent_memory.db", check_same_thread=False)
db_checkpointer = SqliteSaver(conn)

app = workflow.compile(db_checkpointer, interrupt_before=["tools"])

if __name__ == "__main__":
    config = {"configurable": {"thread_id": "finanace_993"}}

    print("Booting up the Finanace Graph pipeline...")

    initial_input = {
        "messages": [
            ("user", "My username is omsai. I was double charged for my subscription. Please refund me 50 dollars!")]
    }

    print("------------ Step 1: Processing User prompt -------------")
    for chunk in app.stream(initial_input, config=config, stream_mode="values"):
        pass

    current_state = app.get_state(config)
    last_msg = current_state.values["messages"][-1]

    print(f"[AI ORIGINAL INTENT]: Wants to run tool with args : {last_msg.tool_calls[0]['args']}")

    print("\n[ADMIN OVERRIDE]: Override the database row and change the refund value to $20...")

    tool_call_id = last_msg.tool_calls[0]["id"]

    from langchain_core.messages import AIMessage
    corrected_msgs = AIMessage(
        content = "",
        tool_calls= [{
            "name": "process_monetary_refund",
            "args": {"username": "omsai", "amount": 20.00},
            "id": tool_call_id
        }]
    )

    app.update_state(config, {"messages": [corrected_msgs]})
    print("✅ Database memory ledger successfully modified on the hard drive.")

    # -----------------------------------------------------------------
    # RESUME GRAPH WITH MODIFIED STATE
    # -----------------------------------------------------------------
    print("\n🏁 Resuming execution track stream using overridden memory states...")
    for chunk in app.stream(None, config=config, stream_mode="values"):
        pass

    final_state = app.get_state(config)
    print(f"\n🏆 [FINAL ORDER METRICS]:\n{final_state.values['messages'][-1].content}\n")