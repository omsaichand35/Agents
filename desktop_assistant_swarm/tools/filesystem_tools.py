from pathlib import Path

from langchain_core.tools import tool


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


def _normalize_hint(value: str) -> str:
    return value.strip().lower()


def _find_folder_candidates(folder_hint: str, search_root: str = "") -> list[Path]:
    root = Path(search_root).expanduser().resolve() if search_root else WORKSPACE_ROOT
    hint = _normalize_hint(folder_hint)
    candidates: list[Path] = []

    if root.exists() and root.is_dir():
        for candidate in root.rglob("*"):
            if candidate.is_dir() and hint in candidate.name.lower():
                candidates.append(candidate)

    candidates.sort(key=lambda path: (len(path.parts), str(path).lower()))
    return candidates


def _render_candidates(candidates: list[Path]) -> str:
    return "\n".join(f"{index + 1}. {candidate}" for index, candidate in enumerate(candidates))


def _build_file_path(target_dir: Path, item_name: str, file_extension: str) -> Path:
    cleaned_name = item_name.strip()
    extension = file_extension.strip()

    if extension and not extension.startswith("."):
        extension = f".{extension}"

    if extension and not cleaned_name.lower().endswith(extension.lower()):
        cleaned_name = f"{cleaned_name}{extension}"

    return target_dir / cleaned_name


@tool
def locate_matching_folders(folder_hint: str, search_root: str = "") -> str:
    """Searches for folders whose names contain the provided hint and returns the matching paths."""
    candidates = _find_folder_candidates(folder_hint, search_root)

    if not candidates:
        root = Path(search_root).expanduser().resolve() if search_root else WORKSPACE_ROOT
        return f"NO_MATCH: No folder matching '{folder_hint}' was found under '{root}'."

    if len(candidates) == 1:
        return f"MATCH: {candidates[0]}"

    return f"AMBIGUOUS: multiple folders matched '{folder_hint}':\n{_render_candidates(candidates)}"


@tool
def create_item_in_matching_folder(
    folder_hint: str,
    item_name: str,
    item_kind: str = "file",
    file_extension: str = "",
    content: str = "",
    search_root: str = "",
) -> str:
    """Finds a matching folder and creates a folder or file inside it."""
    candidates = _find_folder_candidates(folder_hint, search_root)
    root = Path(search_root).expanduser().resolve() if search_root else WORKSPACE_ROOT

    if not candidates:
        return f"NO_MATCH: No folder matching '{folder_hint}' was found under '{root}'."

    if len(candidates) > 1:
        return f"AMBIGUOUS: multiple folders matched '{folder_hint}':\n{_render_candidates(candidates)}"

    target_dir = candidates[0]
    kind = item_kind.strip().lower()

    if kind == "folder":
        target_path = target_dir / item_name.strip()
        target_path.mkdir(parents=True, exist_ok=True)
        return f"SUCCESS: Folder created at '{target_path}'."

    target_path = _build_file_path(target_dir, item_name, file_extension)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return f"SUCCESS: File created at '{target_path}'."