from __future__ import annotations

from pathlib import Path
import ast
import py_compile
import re

from langchain_core.tools import tool


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
_IGNORED_DIRECTORIES = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".mypy_cache", ".pytest_cache"}


def _resolve_workspace_path(path_text: str) -> Path:
    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = WORKSPACE_ROOT / candidate

    resolved = candidate.resolve()
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise ValueError(f"Path '{path_text}' is outside the workspace root.") from exc

    return resolved


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(WORKSPACE_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _iter_workspace_files(include_pattern: str) -> list[Path]:
    files: list[Path] = []
    for path in WORKSPACE_ROOT.rglob("*"):
        if not path.is_file():
            continue

        if any(part in _IGNORED_DIRECTORIES for part in path.parts):
            continue

        relative_path = path.relative_to(WORKSPACE_ROOT)
        if include_pattern and include_pattern not in {"**/*", "*"} and not relative_path.match(include_pattern):
            continue

        files.append(path)

    return sorted(files)


@tool
def list_workspace_files(include_pattern: str = "**/*.py") -> str:
    """Lists files in the workspace that match the provided glob pattern."""
    files = _iter_workspace_files(include_pattern)
    if not files:
        return f"No files matched pattern: {include_pattern}"

    return "\n".join(_display_path(path) for path in files[:200])


@tool
def read_workspace_file(path_text: str, start_line: int = 1, end_line: int = 200) -> str:
    """Reads a workspace file and returns numbered lines for targeted inspection."""
    file_path = _resolve_workspace_path(path_text)
    if not file_path.exists():
        return f"File not found: {_display_path(file_path)}"

    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    start_index = max(start_line - 1, 0)
    end_index = min(end_line, len(lines))

    if start_index >= len(lines):
        return f"Requested start line {start_line} is beyond the end of the file."

    output_lines = [f"{index + 1}: {line}" for index, line in enumerate(lines[start_index:end_index], start=start_index)]
    return "\n".join(output_lines)


@tool
def search_workspace_text(query: str, include_pattern: str = "**/*.py", max_results: int = 20, regex: bool = False) -> str:
    """Searches workspace files for matching text and returns file/line hits."""
    if not query.strip():
        return "Search query is empty."

    pattern = re.compile(query, re.IGNORECASE) if regex else None
    results: list[str] = []

    for path in _iter_workspace_files(include_pattern):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue

        for line_number, line in enumerate(lines, start=1):
            matched = bool(pattern.search(line)) if pattern else query.lower() in line.lower()
            if not matched:
                continue

            results.append(f"{_display_path(path)}:{line_number}: {line.strip()}")
            if len(results) >= max_results:
                return "\n".join(results)

    if not results:
        return f"No matches found for: {query}"

    return "\n".join(results)


@tool
def get_python_file_errors(path_text: str) -> str:
    """Checks a Python file for syntax and compile-time errors."""
    file_path = _resolve_workspace_path(path_text)
    if not file_path.exists():
        return f"File not found: {_display_path(file_path)}"

    if file_path.suffix.lower() != ".py":
        return f"Not a Python file: {_display_path(file_path)}"

    source = file_path.read_text(encoding="utf-8", errors="replace")

    try:
        ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        return f"SyntaxError in {_display_path(file_path)} at line {exc.lineno}, column {exc.offset}: {exc.msg}"

    try:
        py_compile.compile(str(file_path), doraise=True)
    except py_compile.PyCompileError as exc:
        return f"CompileError in {_display_path(file_path)}: {exc.msg}"

    return f"No syntax errors found in {_display_path(file_path)}."


@tool
def write_workspace_file(path_text: str, content: str) -> str:
    """Writes content to a workspace file, creating parent folders when needed."""
    file_path = _resolve_workspace_path(path_text)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return f"Wrote file: {_display_path(file_path)}"


@tool
def replace_text_in_file(path_text: str, old_text: str, new_text: str) -> str:
    """Replaces exactly one block of text in a workspace file."""
    file_path = _resolve_workspace_path(path_text)
    if not file_path.exists():
        return f"File not found: {_display_path(file_path)}"

    content = file_path.read_text(encoding="utf-8", errors="replace")
    occurrences = content.count(old_text)
    if occurrences == 0:
        return f"Target text not found in {_display_path(file_path)}"
    if occurrences > 1:
        return f"Target text appears {occurrences} times in {_display_path(file_path)}; refine the replacement text."

    updated_content = content.replace(old_text, new_text, 1)
    file_path.write_text(updated_content, encoding="utf-8")
    return f"Updated file: {_display_path(file_path)}"