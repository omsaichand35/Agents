import ollama
import json
import re

# ============ Tools Layer ============

def calculate_length(text: str) -> int:
    cleaned = text.strip("'").strip('"')
    print(f"[Tool Execution]: Running calculate_length on {cleaned}")
    return len(cleaned)

TOOL_REGISTRY = {
    "calculate_length": calculate_length
}

# ============ Agent System Prompt ===============

system_prompt = """
    You are an autonomous Agentic AI operating in a strict loop: Thought, Action, Observation, Thought...

    You have access to exactly ONE tool:
    - calculate_length(text): Returns the integer count of characters in a text string.
    
    To use this tool, you MUST use the exact syntax below. Do not output anything else on the line when making an action.
    Action: calculate_length("your text here")
    
    Example Flow:
    User: Find the length of 'cat' and add 5.
    Thought: I need to find the length of the string 'cat' first. I will use my tool.
    Action: calculate_length("cat")
    Observation: 3
    Thought: The length is 3. Now I need to add 5. 3 + 5 is 8. I have the final answer.
    Final Answer: The final result is 8.
    
    CRITICAL: 
    1. Only make ONE action per turn. 
    2. When you output an 'Action: ', you MUST immediately stop generating text and wait for the Observation.
    3. If you have the ultimate conclusion, you MUST start your line with 'Final Answer:'.
"""

# ========= Autonomus Routing loop ===============

def run_autonomous_agent(user_prompt: str):
    print(f"Initilizing Agent with objective: '{user_prompt}'")

    conversation_history = [
        {"role": "system", "context": system_prompt},
        {"role": "user", "context": user_prompt},
    ]

    MAX_STEPS = 5

    for step in range(MAX_STEPS):
        print(f"-------- Agent Execution step {step + 1} ---------------")

        response = ollama.chat(
            model = "qwen2.5:7b",
            messages= conversation_history,
            options={
                "temperature": 0.0
            }
        )

        agent_output = response['message']['content'].strip()
        print(agent_output)

        conversation_history.append({"role": "assistant", "context": agent_output})

        if "Final Answer" in agent_output:
            print(f"\n Objective reached successfully by Agent.")
            return

        action_match = re.search(r"Action:\s*(\w+)\(\"(.*?)\"\)", agent_output)

        if action_match:
            tool_name = action_match.group(1)
            tool_arguments = action_match.group(2)

            if tool_name in TOOL_REGISTRY:
                tool_function = TOOL_REGISTRY[tool_name]
                result = tool_function(tool_arguments)

                observation_str = f"Observation {result}"
                print(f"[SYSTEM INJECTION]: {observation_str}\n")
                conversation_history.append({"role": "system", "context": observation_str})

            else:
                error_msg = f"Observation : Error - Tool '{tool_name}' not recognized.'"
                print(f"[SYSTEM ERROR]: {error_msg}\n")
                conversation_history.append({"role": "system", "context": error_msg})


        else:
            error_msg = "Observation: Error - You must call an action using syntax: Action: tool_name(\"arg\") or provide a Final Answer."
            print(f"⚠️ [SYNTAX WARNING]: Injection correction sent to model.")
            conversation_history.append({"role": "user", "content": error_msg})

    print("\n❌ Execution halted: Maximum step safety limit exceeded.")

# --- EXECUTION ---

OBJECTIVE = "Take the phrase 'OmniSpace Technology' and calculate its character length. Then, multiply that number by 2 and give me the final answer."

run_autonomous_agent(OBJECTIVE)