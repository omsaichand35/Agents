import time
import subprocess
from pathlib import Path
import pyautogui
from langchain_core.tools import tool
from Agentic_AI.desktop_assistant_swarm.config.settings import WINDOW_HYDRATION_SLEEP


def _process_name_from_command(app_command: str) -> str:
    first_token = app_command.strip().split()[0].strip('"').strip("'")
    process_name = Path(first_token).name
    if not process_name.lower().endswith(".exe"):
        process_name = f"{process_name}.exe"
    return process_name


def _is_process_running(process_name: str) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return process_name.lower() in result.stdout.lower()
    except Exception:
        return False


@tool
def launch_local_application(app_command: str) -> str:
    """Launches an OS application path natively and hold the pipeline until the interface renders..."""
    print(f"[OS KERNAL LINK]: Initiating system launch thread for '{app_command}'.")
    try:
        process_name = _process_name_from_command(app_command)
        if _is_process_running(process_name):
            return f"SUCCESS: {process_name} is already open. Skipping relaunch."

        subprocess.Popen(app_command, shell=True)
        print(f"[ANTI-FAILURE GATING]: Pausing graph for {WINDOW_HYDRATION_SLEEP} seconds for application loading...")
        time.sleep(WINDOW_HYDRATION_SLEEP)
        return f"SUCCESS: Application initialized successfully. Interface layer should be rendered by now."
    except Exception as e:
        return f"ERROR: Application Initialization failed. Error: {str(e)}"


@tool
def launch_notepad_and_type(input_text: str) -> str:
    """Launches Notepad, waits for it to initialize, and types the requested text into it."""
    print("[OS KERNAL LINK]: Initiating system launch thread for 'notepad.exe'.")
    try:
        if not _is_process_running("notepad.exe"):
            subprocess.Popen("notepad.exe", shell=True)
            print(f"[ANTI-FAILURE GATING]: Pausing graph for {WINDOW_HYDRATION_SLEEP} seconds for application loading...")
            time.sleep(WINDOW_HYDRATION_SLEEP)
        else:
            print("[ANTI-FAILURE GATING]: Notepad is already open. Reusing the existing window...")

        pyautogui.write(input_text, interval=0.05)
        return "SUCCESS: Notepad initialized and text entered successfully."
    except Exception as e:
        return f"ERROR: Notepad text entry failed. Error: {str(e)}"
@tool
def execute_interface_click(x_pos: int, y_pos: int, input_text: str) -> str:
    """Executes an interface click on the screenshot."""
    print(f"\n[HARDWARE LINK]: Dispatched click even to coordinate maps X={x_pos}, Y={y_pos}...")
    try:
        pyautogui.moveTo(int(x_pos), int(y_pos), duration=0.4)
        pyautogui.click()

        time.sleep(0.5)

        pyautogui.hotkey('ctrl', 'a')
        pyautogui.hotkey('backspace')
        time.sleep(0.5)

        pyautogui.write(input_text, interval=0.05)

        return f"SUCCESS: Coordinate maps X={x_pos}, Y={y_pos}. Click executed successfully."
    except Exception as e:
        return f"ERROR: Click executed failed. Error: {str(e)}"
