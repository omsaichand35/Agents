import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from Agentic_AI.desktop_assistant_swarm.config.settings import DB_FILE

def get_db_checkpointer() -> SqliteSaver:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return SqliteSaver(conn)
