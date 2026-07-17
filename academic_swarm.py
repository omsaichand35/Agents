from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from langgraph_supervisor import create_supervisor


@tool
def fetch_population_data(country: str) -> str:
    """Looks at the given population database and gives the results accordingly."""
    print(f"[RESEARCH AGENT EXECUTING]: Fetching core metrics for '{country}'...")
    db = {
        "india": "1440000000",
        "usa":   "244400000",
        "canada":"122343444"
    }
    return db.get(country.strip().lower(), "DATA UNLISTED...")

@tool
def calculate_growth_forecast(base_population: str, rate: float) -> str:
    """Calculates the growth forecast for the given population."""
    print(f"[MATH AGENT EXECUTING]: Computing growth forecast for '{base_population}'...")
    base = int(base_population)
    forecast = int((1+rate)*base)
    return f"Calculated project total: {forecast}"

model = ChatOllama(
    model="qwen2.5:7b",
    temperature=0.0
)

research_worker = create_react_agent(
    model = model,
    tools = [fetch_population_data],
    name = "research_expert",
    prompt = "You are a data retrieval assistant. Use fetch_population_data to lookup numbers. Do not do math."
)

math_worker = create_react_agent(
    model=model,
    tools=[calculate_growth_forecast],
    name="math_expert",
    prompt="You are a calculation specialist. Use calculate_growth_forecast for forecasting equations. Do not lookup data."
)

SUPERVISOR_PROMPT = """
You are an Academic Director supervising 'research_expert' and 'math_expert'.
Your task is to answer multi-step student questions by routing to the appropriate agent.

Routing Rules:
1. First, send the query to 'research_expert' to find the country's population data.
2. Once the research expert returns the number, pass that population value to 'math_expert' along with the requested rate to compute the forecast.
3. When both agents finish, summarize the final prediction to the user.
"""

workflow = create_supervisor(
    agents = [research_worker, math_worker],
    model=model,
    prompt=SUPERVISOR_PROMPT,
    output_mode="full_history"
)

memory = MemorySaver()

app = workflow.compile(checkpointer=memory)

if __name__ == "__main__":
    config = {"configurable": {"thread_id": "multi_agent_3894"}}
    print("Booting up the Multi-Agent system...")

    user_prompt = {
        "messages": [("user", "What will the population of India be if it grows by 10% (0.10) next year? Let the experts work together!")]
    }

    final_chunk = {}
    for chunk in app.stream(user_prompt, stream_mode="values", subgraphs=True, config=config):
        final_chunk = chunk

    print("\n🏆 [FINAL CONSOLIDATED RESULTS]:")

    # Check if the final chunk is wrapped in the supervisor state tracking dictionary
    if isinstance(final_chunk, dict) and "messages" in final_chunk:
        print(final_chunk["messages"][-1].content)
    else:
        # Fallback: Pull the absolute final state directly from the compiled app state database
        state_snapshot = app.get_state(config)
        if state_snapshot.values and "messages" in state_snapshot.values:
            print(state_snapshot.values["messages"][-1].content)
        else:
            print("Execution completed successfully! Check historical thread logs for message details.")