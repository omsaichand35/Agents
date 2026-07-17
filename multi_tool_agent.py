import ollama
import re

# ------------ Tools Registry --------------

def fetch_server_status(server_name: str) -> str:
    print(f"[MONITORING TOOL]: Pinging '{server_name}'...'")
    if "alpha" in server_name.lower():
        return "CRITICALL_ERROR_OVERHEATING"
    return "HEALTHY"

def restart_server(server_name: str) -> str:
    print(f"[SYS-ADMIN TOOL]: Sending cold reboot signal to '{server_name}'...'")
    return "REBOOT_SUCCESS_STATUS_200"

SYSTEM_RULES = """
You are a brilliant automated Systems Site Reliability Engineer (SRE) Agent operating in a strict loop: Thought, Action, Observation, Thought...

You have access to EXACTLY TWO tools to manage infrastructure:
1. fetch_server_status("server_name"): Checks if a server is healthy. Returns 'CRITICAL_ERROR_OVERHEATING' or 'HEALTHY_ONLINE'.
2. restart_server("server_name"): Reboots a server. Returns 'REBOOT_SUCCESS_STATUS_200'.

Rules for Tool Selection:
- If you need to check a server's health metrics, use your exact syntax:
  Action: fetch_server_status("server_name")

- If you find out a server has an error or is overheating, you must fix it immediately using this exact syntax:
  Action: restart_server("server_name")

- Once the system is completely safe or fixed, communicate your wrap-up solution starting exactly with:
  Final Answer:
"""

def run_ser_pipeline(target_server: str):

    conversation_history = [
        {"role": "user", "content": f"Check the status of the '{target_server}' server. "}
    ]

    print(f"Starting automated SRE tracking for: {target_server}\n")

    for step in range(4):
        print(f"============ SRE Diagnosis step: {step + 1} ===============")

        message_to_send = [{"role": "system", "content": SYSTEM_RULES}] + conversation_history

        response = ollama.chat(
            model = "qwen2.5:7b",
            messages = message_to_send,
            options = {
                "temperature": 0.0,
                "stop": ["Observation:", "observation:"]
            }
        )

        ai_response = response["message"]["content"]
        print(f"AI Thought/Action process: \n{ai_response}\n")

        conversation_history.append({"role": "assistant", "content": ai_response})

        if "Final Answer" in ai_response:
            print(f"Alert Resolution complete: Closing SRE pipeline window.")
            break

        status_match = re.search(r"Action:\s*fetch_server_status\(\"(.*?)\"\)", ai_response)
        restart_match = re.search(r"Action:\s*restart_server\(\"(.*?)\"\)", ai_response)

        if status_match:
            extracted_server = status_match.group(1)
            tool_output =  fetch_server_status(extracted_server)

            observation_payload = f"Observation: {tool_output}"
            print(f"[PYTHON INJECTED]: {observation_payload}\n")
            conversation_history.append({"role": "assistant", "content": observation_payload})

        elif restart_match:
            extracted_server = restart_match.group(1)
            tool_output = restart_server(extracted_server)

            observation_payload = f"Observation: {tool_output}"
            print(f"[PYTHON INJECTED]: {observation_payload}\n")
            conversation_history.append({"role": "assistant", "content": observation_payload})
        else:
            if "Action:" in ai_response:
                error_payload = f"Observation: Error - Invalid syntax or unknown tool name. Use Exactly: Action: fetch_server_status(\"name\") OR Action restart_server(\"name\")"
                print(f"[PYTHON INJECTED]: {error_payload}\n")
                conversation_history.append({"role": "assistant", "content": error_payload})


run_ser_pipeline("Production_server_alpha")

