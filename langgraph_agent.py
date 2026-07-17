from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_ollama import ChatOllama
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool


# ------------ State Definition ----------------
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


# ---------------- Multi-Tool Layer ---------------
@tool
def multiply(a: int, b: int) -> int:
    """Multiplies two integers together. Use this whenever you need to compute mathematical multiplication products."""
    print(f"🔧 [LANGGRAPH TOOL]: Computing {a} x {b}")
    return a * b

@tool
def subtract(a: int, b: int) -> int:
    """Subtracts the second integer (b) from the first integer (a). Use this for subtraction operations."""
    print(f"🔧 [LANGGRAPH TOOL]: Computing {a} - {b}")
    return a - b


tools_list = [multiply, subtract]
tools_node = ToolNode(tools_list)

# ------------- Node Architecture --------------
model = ChatOllama(
    model="qwen2.5:7b",
    temperature=0.0
).bind_tools(tools_list)


def call_model(state: AgentState):
    print(f"\n[NODE]: Agent is analyzing state data...")
    response = model.invoke(state['messages'])
    return {"messages": [response]}


def should_continue(state: AgentState):
    last_message = state['messages'][-1]
    if last_message.tool_calls:
        print(f"[CONDITIONAL EDGE]: Tool call detected! Routing to the tool.")
        return "tools"
    print("[CONDITIONAL EDGE]: No more tool calls required. Task Completed.")
    return END


# ------------- Assembling the complete workflow graph -------------------
workflow = StateGraph(AgentState)

workflow.add_node("agent", call_model)
workflow.add_node("tools", tools_node)

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

app = workflow.compile()

# -------- Main function --------------
if __name__ == "__main__":
    initial_input = {
        "messages": [("user", "Multiply 13 by 34. Take the result and subtract it by the result of 12 multiplied by 3")]
    }
    # To run this, you must first run: pip install pygraphviz OR pip install grandalf
    print("Booting up the official LangGraph local Runtime Pipeline")

    for chunk in app.stream(initial_input, stream_mode="values"):
        if "messages" in chunk:
            last_message = chunk["messages"][-1]
            print(f"[MESSAGE] Type: {last_message.type.upper()} | Content Snippet: {str(last_message.content)}")