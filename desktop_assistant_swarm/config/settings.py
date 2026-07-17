import os
from langchain_ollama import ChatOllama

TEXT_ROUTER_MODEL = ChatOllama(model="qwen2.5:7b", temperature=0.0)
VISION_EYE_MODEL = ChatOllama(model="qwen3.5:latest", temperature=0.0)

DB_FILE = "desktop_vault.db"
SNAPSHOT_DIR = os.path.abspath("live_desktop_viewport.png")
SWARM_THREAD_ID = "assistant_runtime_session_3274_v2"

MAX_LOOP_BREAKOUT = 5
WINDOW_HYDRATION_SLEEP = 5