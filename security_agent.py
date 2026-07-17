import ollama

# ----------- Tool and registry ----------------

EMPLOYEE_LIST = ["alice", "bob", "charlie"]

def check_user(username: str) -> str:
    print(f"[PYTHON EXECUTION]: Checking the database for the '{username}'...")
    cleaned_name = username.lower().strip().replace('"', '').replace("'", "")

    if cleaned_name in EMPLOYEE_LIST:
        return "Allowed"
    else:
        return "Access Denied"

SYSTEM_RULES = """
You are a security gateway agent operating in a strict loop: Thought, Action, Observation, Thought...

You have access to one tool:
- check_user("name"): Checks if a user is allowed in the building. Returns 'Allowed' or 'Access Denied'.

If you need to check a user, you MUST type exactly:
Action: check_user("name")

Once you know the final outcome, you MUST state your ultimate conclusion starting with:
Final Answer: 
"""

def run_security_pipeline(target_user: str):
    conversation_history = [
        {"role": "user", "content": f"Check if the user '{target_user}' is allowed in the building."}
    ]

    print(f"Secring perimeter for objective user: {target_user}\n")

    for step in range(3):
        print(f"=== Turn step: {step + 1} ===")

        message_to_send = [{"role": "system", "content": SYSTEM_RULES}] + conversation_history

        response = ollama.chat(
            model = "qwen2.5:7b",
            messages = message_to_send,
            options = { "temperature": 0.0 }
        )
        ai_response_text = response["message"]["content"].strip()

        print(f"Ai Typed: \n{ai_response_text}\n")

        conversation_history.append({"role": "system", "content": ai_response_text})

        if "Final Answer" in ai_response_text:
            print(f"Success: The ai reached the final conclusion.")
            break

        if "Action: check_user" in ai_response_text:
            tool_result = check_user(target_user)

            observation_payload = f"Observation: {tool_result}"
            print(f"Python Injected: {observation_payload}\n")

            conversation_history.append({"role": "user", "content": observation_payload})

run_security_pipeline("Alice")
