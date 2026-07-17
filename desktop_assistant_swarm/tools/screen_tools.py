from langchain_core.tools import tool
from PIL import ImageGrab
from Agentic_AI.desktop_assistant_swarm.config.settings import SNAPSHOT_DIR

@tool
def capture_active_desktop() -> str:
    """Takes an instant high-resolution screenshot of the active desktop."""
    print("\n[PERCEPTION ENGINE]: Capturing real-time viewport frame...")
    try:
        screenshot = ImageGrab.grab()
        screenshot.save(SNAPSHOT_DIR, "PNG")
        return f"SUCCESS: Viewport saved locally to '{SNAPSHOT_DIR}'. Vision model can analyze the layout grid."
    except Exception as e:
        return f"ERROR: Failed to capture screenshot\n. ERROR message: {str(e)}"

