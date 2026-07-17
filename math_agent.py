import ollama
import re

from numpy.f2py.auxfuncs import options


def multiply(num1: int, num2: int) -> int:
    print(f" [PYTHON MATHEMATICS]: Executing real code: {num1} x {num2}")
    return num1 * num2

SYSTEM_RULES = """
You are an advanced mathematical computing agent operating in a strict loop: Thought, Action, Observation, Thought...

You have access to one tool:
- multiply(num1, num2): Multiplies two integers together.

If you need to multiply numbers, you MUST use this exact syntax:
Action: multiply(X, Y)
(Where X and Y are the raw numbers you want to calculate).

Once you have computed the final solution to the user's entire prompt, state your conclusion using this syntax:
Final Answer: your final number or explanation here
"""

def run_pipe_line(user_objective: str):
    conversation_history = [
        {"role": "user", "content": user_objective}
    ]

    print(f"Initializing the math agent with objective: {user_objective}")

    for step in range(3):
        print(f"--- Turn step: {step + 1} ---")

        message_to_send = [{"role": "system", "content": SYSTEM_RULES}] + conversation_history

        response = ollama.chat(
            model = "qwen2.5:7b",
            messages = message_to_send,
            options = {
                "temperature": 0.0,
                "stop": ["Observation:", "observation:"]
            }
        )

        ai_response = response["message"]["content"].strip()

        print(f"AI Typed: \n{ai_response}\n")
        conversation_history.append({"role": "system", "content": ai_response})

        if "Final Answer" in ai_response:
            print("Success: The agent completed the task...")
            break

        action_match = re.search(r"Action: \s*multiply\((\d+),\s*(\d+)\)", ai_response)

        if action_match:

            extract_num1 = int(action_match.group(1))
            extract_num2 = int(action_match.group(2))

            calculation_result = multiply(extract_num1, extract_num2)

            observation_payload = f"Observation: {calculation_result}"
            print(f"PYTHON INJECTED: {observation_payload}\n")

            conversation_history.append({"role": "user", "content": observation_payload})

        else:
            if "Action:" in ai_response:
                error_payload = "Observation: Error - Invalid syntax. Use format exactly like multiply(x1, x2)"
                print("[CORRECTION INJECTED]: MODEL formatted arguments incorrectly.\n")

                conversation_history.append({"role": "user", "content": error_payload})

MATH_TASK = "Calculate 14 multiplied by 7. Once you have that result, add 10 to it and give me the final answer."
run_pipe_line(MATH_TASK)