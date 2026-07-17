from langgraph.prebuilt import create_react_agent
from Agentic_AI.desktop_assistant_swarm.config.settings import TEXT_ROUTER_MODEL, VISION_EYE_MODEL
from Agentic_AI.desktop_assistant_swarm.config.prompts import ADMIN_PROMPT, VISION_PROMPT, WEB_PROMPT, CODING_PROMPT, PERSONAL_PROMPT
from Agentic_AI.desktop_assistant_swarm.tools.web_tools import open_google_search, open_youtube_search, play_youtube_video
from Agentic_AI.desktop_assistant_swarm.tools.filesystem_tools import create_item_in_matching_folder, locate_matching_folders
from Agentic_AI.desktop_assistant_swarm.tools.codebase_tools import (
    list_workspace_files,
    read_workspace_file,
    search_workspace_text,
    get_python_file_errors,
    write_workspace_file,
    replace_text_in_file,
)
from Agentic_AI.desktop_assistant_swarm.tools.screen_tools import capture_active_desktop
from Agentic_AI.desktop_assistant_swarm.tools.os_automation import launch_local_application, launch_notepad_and_type, execute_interface_click

os_admin_worker = create_react_agent(
    model = TEXT_ROUTER_MODEL,
    tools = [launch_local_application, launch_notepad_and_type, execute_interface_click, locate_matching_folders, create_item_in_matching_folder],
    name = "os_admin_worker",
    prompt=ADMIN_PROMPT
)

vision_eye_worker = create_react_agent(
    model = VISION_EYE_MODEL,
    tools = [capture_active_desktop],
    name = "vision_eye_worker",
    prompt = VISION_PROMPT
)

browser_worker = create_react_agent(
    model = TEXT_ROUTER_MODEL,
    tools = [open_google_search, open_youtube_search, play_youtube_video],
    name = "browser_worker",
    prompt = WEB_PROMPT
)

coding_worker = create_react_agent(
    model = TEXT_ROUTER_MODEL,
    tools = [
        list_workspace_files,
        read_workspace_file,
        search_workspace_text,
        get_python_file_errors,
        write_workspace_file,
        replace_text_in_file,
    ],
    name = "coding_worker",
    prompt = CODING_PROMPT
)

personal_worker = create_react_agent(
    model = TEXT_ROUTER_MODEL,
    tools = [
        launch_local_application,
        launch_notepad_and_type,
        execute_interface_click,
        locate_matching_folders,
        create_item_in_matching_folder,
        open_google_search,
        open_youtube_search,
        play_youtube_video,
        list_workspace_files,
        read_workspace_file,
        search_workspace_text,
        get_python_file_errors,
        write_workspace_file,
        replace_text_in_file,
        capture_active_desktop,
    ],
    name = "personal_worker",
    prompt = PERSONAL_PROMPT
)