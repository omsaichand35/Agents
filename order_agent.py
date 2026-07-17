from typing import Annotated, TypedDict
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode


# ---------------- The state definition ---------------------
class OrderState(TypedDict):
    messages: Annotated[list, add_messages]

# --------------- Tools -------------------
INVENTORY = {
    "laptop" : 5,
    "phone" : 0,
    "headphones" : 12
}

@tool
def check_inventory(item: str) -> str:
    """Checks the local warehouse database for product stock"""
    print(f"[TOOLS]: Quering the warehouse for the {item} inventory.")
    stock = INVENTORY.get(item.lower().strip(), 0)
    return "IN STOCK" if stock > 0 else "OUT OF STOCK"

@tool
def calculate_tax(base_price: float) -> float:
    """Calculates the final bill of the product"""
    print(f"[TOOLS]: Calculating the 10% sales tax matrx for base price: {base_price}")
    return round(base_price * 0.10, 2)

tools_list = [check_inventory, calculate_tax]
tools_node = ToolNode(tools_list)

# --------------- Agent Core ------------------
SYSTEM_RULES = """
You are an autonomous E-Commerce Order Fullfillment Agent operating in a strict Thought, Action, Observation loop.

Your processing sequence:
1. Always check inventory first for the requested item using check_inventory("item_name").
2. If the observation returns 'OUT_OF_STOCK', stop instantly and tell the user we cannot fulfill it.
3. If 'IN_STOCK', use calculate_tax(base_price) with the price provided in the prompt to find the final invoice amount.
4. Once you have the final tax calculations, give the final summary starting with 'Final Answer:'.
"""

model = ChatOllama(
    model = "qwen2.5:7b",
    temperature = 0.0
).bind_tools(tools_list)

def call_router(state: OrderState):
    print("\n[NODE]: Agent is evaluating order parameters...")
    message_with_rule = [{"role": "system", "content": SYSTEM_RULES}] + state["messages"]

    response = model.invoke(message_with_rule)
    return {"messages": [response]}

def should_continue(state: OrderState):
    last_msg = state["messages"][-1]

    if last_msg.tool_calls:
        print(f"[MESSAGE]: Agent task is not done. Routing to the tools")
        return "tools"
    print(f"[MESSAGE]: No more tools to call. Agent has done the work.")
    return END

# ------------ Work Assembly ---------------

workflow = StateGraph(OrderState)

workflow.add_node("agent", call_router)
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

# ---------------- Main Function -----------------
if __name__ == "__main__":
    initial_input = {
        "messages": [("user", "I want to buy a mobile. The listed price is 1000 dollars. Please process my order.")]
    }

    print("🚀 Booting up E-Commerce Order Fulfillment Graph Pipeline...")

    # Run the graph to completion and extract the final assistant message
    final_state = app.invoke(initial_input)
    final_message = final_state["messages"][-1]

    print("\n🏆 [FINAL ORDER STATUS]:")
    # Print the assistant content regardless of its internal flags
    print(final_message.content)