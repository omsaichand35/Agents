from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_core.messages import AIMessage
from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma

COMPANY_POLICY_DOCUMENTS = [
    Document(page_content="Policy ID 101: The corporate return window for electronic items bought during major promotional sales (like Black Friday) is strictly 45 days from the date of delivery."),
    Document(page_content="Policy ID 102: Standard tier accounts are charged a flat $15 international processing handling fee for overseas server provisioning requests."),
    Document(page_content="Policy ID 103: Premium and VIP tier accounts receive completely free, unlimited global shipping and zero server configuration overhead costs.")
]

print("Initializing local vector database storage rows...")

embeddings_engine = OllamaEmbeddings(model="qwen3-embedding")

vector_store = Chroma.from_documents(
    documents=COMPANY_POLICY_DOCUMENTS,
    embedding=embeddings_engine
)
retriever = vector_store.as_retriever(search_kwargs={"k": 1})

@tool
def search_company_knowledge_base(query: str) -> str:
    """Searched the private corporate policy manually to find verified answers for the queries"""
    print(f"[RAG TOOL]: Executing semantic vector search for: {query}")
    matching_docs = retriever.invoke(query)
    if not matching_docs:
        return "No specific corporate policy clause found for this query...."
    return matching_docs[0].page_content

tool_list = [search_company_knowledge_base]
tool_node = ToolNode(tool_list)

class RAGState(TypedDict):
    messages: Annotated[list, add_messages]

SYSTEM_RULES = """
You are an expert Corporate Customer Support Specialist operating in a strict Thought, Action, Observation loop.

You have access to a private internal knowledge base tool: search_company_knowledge_base(query="search term")
If the user asks about corporate rules, return policies, or tier fees, you must search the database tool first to find the factual answer. Do not guess.
"""

model = ChatOllama(
    model="qwen2.5:7b",
    temperature=0.0
).bind_tools(tool_list)

def call_agent(state: RAGState):
    print("[NODE]: Agent is analysing the request parameters... ")
    message_to_send = [{"role": "user", "content": SYSTEM_RULES}] + state["messages"]
    response = model.invoke(message_to_send)
    return {"messages": response}

def should_continue(state: RAGState):
    last_msg = state["messages"][-1]
    if last_msg.tool_calls:
        print("[EDGE]: Agent requested document retrieval. Routing to the corresponding tool.")
        return "tools"
    print("[EDGE]: No tool is called. Agent has done the work...")
    return END

workflow = StateGraph(RAGState)
workflow.add_node("agent", call_agent)
workflow.add_node("tools", tool_node)
workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
workflow.add_edge("tools", "agent")

app = workflow.compile()


if __name__ == "__main__":
        print("\n🚀 Booting up the Agentic RAG Knowledge Base Pipeline...")

        # Test Question: Something explicitly written inside our secret company document vector array
        user_input = {
            "messages": [("user", "What is the return window for a laptop I bought during the Black Friday sale?")]}

        final_chunk = {}
        for chunk in app.stream(user_input, stream_mode="values"):
            final_chunk = chunk

        if "messages" in final_chunk:
            print(f"\n🏆 [FINAL ANSWER FROM VERIFIED KNOWLEDGE BASE]:\n{final_chunk['messages'][-1].content}\n")