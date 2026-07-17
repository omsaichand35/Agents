import sqlite3
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import AIMessage


class OpsState(TypedDict):
    messages: Annotated[list, add_messages]

@tool
def provision_cloud_server(server_name: str, ram_gb: int) -> str:
    """Provisions a new cloud server infrastructure container instance inside the datacenter cluster."""
    print(f"\n🖥️ [CLUSTER HARDWARE ENTRY]: Successfully provisioned cloud server infrastructure container...")
    return f"SUCCESS: Server '{server_name}' with ram: {ram_gb} GB is allocated..."

tool_list = [provision_cloud_server]
tool_node = ToolNode(tool_list)

SYSTEM_RULES = """
You are an Automated Cloud DevOps Infrastructure Agent operating in a strict Thought, Action, Observation loop.
When a user asks for a server, immediately execute the tool: provision_cloud_server(server_name="name", ram_gb=16)
"""

model = ChatOllama(
    model="qwen2.5:7b",
    temperature=0.0
).bind_tools(tool_list)

def call_processor(state: OpsState):
    print("[NODE]: Agent is reading the cluster resource allocation metrics...")
    # FIXED: Role changed to "system" for proper rule adherence
    message_to_send = [{"role": "system", "content": SYSTEM_RULES}] + state["messages"]
    response = model.invoke(message_to_send)
    return {"messages": [response]}

def should_continue(state: OpsState):
    last_msg = state["messages"][-1]
    if last_msg.tool_calls:
        print("[EDGE]: Deployment tool triggered. Shifting track to toolNode...")
        return "tools"
    print("[NODE]: No tool is called. Agent has finished the work...")
    return END

workflow = StateGraph(OpsState)

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

conn = sqlite3.connect("ops_infra.db", check_same_thread=False)
db_checkpointer = SqliteSaver(conn)

app = workflow.compile(checkpointer=db_checkpointer, interrupt_before=["tools"])

if __name__ == "__main__":
    config = {"configurable": {"thread_id": "server_deployment_3453"}}
    print("🚀 Booting up the Ops Infrastructure Agent...\n")

    current_state = app.get_state(config)

    # FIXED: Added .values to properly evaluate if historical entries exist on disk
    if not current_state.values:
        print("---------- Turn 1: User Submits High-specs Server Request ----------")
        initial_input = {"messages": [("user", "I need a high-performance database server. Call it 'ProdDB' and give it 64 GB of RAM please.")]}

        for chunk in app.stream(initial_input, config=config, stream_mode="values"):
            pass

        print("\n🛑 [INTERRUPT]: Server sizing exceeds automated security tier thresholds!")
        print("State variables have been locked to disk file 'ops_infra.db'.")
        print("Run the script a SECOND time to open the Administrator Control Panel panel.")

    else:
        print("[DATABASE STATUS]: Found a frozen deployment ticket on disk. Opening control panel...")
        last_msg = current_state.values['messages'][-1]
        request_args = last_msg.tool_calls[0]['args']
        tool_call_id = last_msg.tool_calls[0]["id"]

        print(f"\n📋 [PENDING TRANSACTION LOG]:")
        print(f"Target Server Name: {request_args.get('server_name')}")
        print(f"Requested RAM Size: {request_args.get('ram_gb')} GB")

        print("\n🛠️ [ADMIN DESK MENU]:")
        print("1. APPROVE  -> Allow the requested 64 GB layout server to deploy natively.")
        print("2. OVERRIDE -> Use Time Travel database mutation to downsize the order to a safe 16 GB.")
        print("3. REJECT   -> Abort the transaction deployment task line completely.")

        admin_choice = input("\nEnter choice number (1, 2, 3): ").strip()

        if admin_choice == "1":
            print("\n✅ Native approval verified. Resuming server construction...")
            for chunk in app.stream(None, config=config, stream_mode="values"):
                pass
            print(f"\n🏆 [FINAL OUTPUT]:\n{app.get_state(config).values['messages'][-1].content}\n")

        elif admin_choice == "2":
            print("\n🛠️ Mutating database records on disk... Forcing RAM downgrade to 16GB...")

            corrected_message = AIMessage(
                content="",
                tool_calls=[{
                    "name": "provision_cloud_server",
                    "args": {"server_name": request_args.get('server_name'), "ram_gb": 16},  # Downgraded!
                    "id": tool_call_id
                }]
            )
            app.update_state(config, {"messages": [corrected_message]})

            print("✅ Memory table records updated. Resuming system conveyor track layout...")
            for chunk in app.stream(None, config=config, stream_mode="values"):
                pass
            print(f"\n🏆 [FINAL OUTPUT]:\n{app.get_state(config).values['messages'][-1].content}\n")

        else:
            print("\n❌ Transaction denied by engineering supervisor. Ticket cleared safely from pipeline.")