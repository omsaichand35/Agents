from pathlib import Path
import argparse
import re
import sys

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from Agentic_AI.desktop_assistant_swarm.agents.workers import coding_worker
from Agentic_AI.desktop_assistant_swarm.tools.codebase_tools import (
    list_workspace_files,
    search_workspace_text,
    get_python_file_errors,
)


_FILLER_WORDS = {
    "inspect",
    "read",
    "understand",
    "understanding",
    "summarize",
    "summarise",
    "summary",
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "for",
    "what",
    "this",
    "that",
    "new",
    "agent",
    "can",
    "do",
    "files",
    "file",
    "code",
    "coding",
}


def _extract_keywords(prompt_text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9_]+", prompt_text.lower())
    return [word for word in words if len(word) > 2 and word not in _FILLER_WORDS]


def _structured_analysis(prompt_text: str) -> str:
    keywords = _extract_keywords(prompt_text)
    search_terms = keywords[:5]
    matches: list[str] = []

    if search_terms:
        search_query = "|".join(re.escape(term) for term in search_terms)
        matches_text = search_workspace_text.invoke({
            "query": search_query,
            "include_pattern": "Agentic_AI/desktop_assistant_swarm/**/*.py",
            "max_results": 12,
            "regex": True,
        })
        matches = [line for line in matches_text.splitlines() if line.strip()]

    candidate_files: list[str] = []
    if matches:
        for line in matches:
            file_path = line.split(":", 1)[0]
            if file_path not in candidate_files:
                candidate_files.append(file_path)

    python_error_checks: list[str] = []
    for file_path in candidate_files[:5]:
        if file_path.endswith(".py"):
            python_error_checks.append(get_python_file_errors.invoke({"path_text": file_path}))

    repo_listing = list_workspace_files.invoke({"include_pattern": "Agentic_AI/desktop_assistant_swarm/**/*.py"}).splitlines()

    report_lines = [
        "--- Coding Analysis ---",
        f"Request: {prompt_text}",
        "",
        f"Keywords: {', '.join(search_terms) if search_terms else 'none found'}",
        "",
        "Likely related files:",
    ]

    if candidate_files:
        for index, file_path in enumerate(candidate_files[:8], 1):
            report_lines.append(f"{index}. {file_path}")
    else:
        for index, file_path in enumerate(repo_listing[:8], 1):
            report_lines.append(f"{index}. {file_path}")

    report_lines.extend([
        "",
        "Observed signals:",
        *([f"- {line}" for line in matches[:8]] if matches else ["- No direct code matches found for the prompt keywords."]),
        "",
        "Debug checks:",
        *([f"- {line}" for line in python_error_checks] if python_error_checks else ["- No Python files selected for compile checks yet."]),
        "",
        "Suggested next steps:",
        "- Read the listed files, identify the controlling function, and make the smallest localized edit first.",
        "- Re-run the Python file error checks after edits.",
        "- If the request is ambiguous, confirm the target file or behavior before broad refactors.",
    ])

    return "\n".join(report_lines)


def main() -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("prompt", nargs="*", help="Coding request to analyze")
    parser.add_argument("--agent", action="store_true", help="Use the LLM-backed coding worker instead of the deterministic analyzer")
    args = parser.parse_args()

    print("Coding ask mode")
    print("Describe the bug, improvement, or feature. The agent will inspect the repo, suggest fixes, and write code when needed.")

    request_text = " ".join(args.prompt).strip()
    if not request_text:
        request_text = input("Request: ").strip()
    if not request_text:
        print("Nothing to do.")
        return

    if args.agent:
        result = coding_worker.invoke({"messages": [("user", request_text)]})
        messages = result.get("messages", []) if isinstance(result, dict) else []

        if messages:
            final_message = messages[-1]
            final_content = getattr(final_message, "content", str(final_message))
            print("\n--- Final Response ---")
            print(final_content)
        else:
            print("No response was produced by the coding agent.")
    else:
        print(_structured_analysis(request_text))


if __name__ == "__main__":
    main()