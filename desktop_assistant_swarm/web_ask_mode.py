from pathlib import Path
import sys

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from Agentic_AI.desktop_assistant_swarm.tools.web_parser import parse_web_request
from Agentic_AI.desktop_assistant_swarm.tools.web_tools import open_google_search, open_youtube_search, play_youtube_video, research_web_query


def main() -> None:
    print("Web ask mode")
    print("Type a question for a terminal-only research summary, or a YouTube request like 'find the latest filmymoji video and play it'.")

    request_text = input("Request: ").strip()
    parsed = parse_web_request(request_text)

    if parsed.action == "unknown" or not parsed.query:
        print("Nothing was parsed from the request.")
        return

    if parsed.action == "open_google_search":
        result = research_web_query.invoke({"query": parsed.query})
    elif parsed.action == "open_youtube_search":
        result = open_youtube_search.invoke({"query": parsed.query})
    elif parsed.action == "play_youtube_video":
        invoke_args = {"query": parsed.query}
        if parsed.youtube_filter:
            invoke_args["youtube_filter"] = parsed.youtube_filter
        result = play_youtube_video.invoke(invoke_args)
    elif parsed.action == "research_web":
        result = research_web_query.invoke({"query": parsed.query})
    else:
        print(f"Unknown action parsed from request: {parsed.action}")
        return

    print(f"Parsed action: {parsed.action}")
    print(f"Parsed query: {parsed.query}")
    if parsed.youtube_filter:
        print(f"Parsed youtube filter: {parsed.youtube_filter}")
    print(f"\n{result}")


if __name__ == "__main__":
    main()