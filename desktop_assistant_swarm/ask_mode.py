from pathlib import Path
import sys

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from Agentic_AI.desktop_assistant_swarm.tools.filesystem_tools import (
    create_item_in_matching_folder,
    locate_matching_folders,
)


def main() -> None:
    print("Filesystem ask mode")

    folder_hint = input("Target folder name or hint: ").strip()
    search_root = input("Search root path (blank for workspace root): ").strip()

    matches = locate_matching_folders.invoke({"folder_hint": folder_hint, "search_root": search_root})
    print(f"\n{matches}")

    if matches.startswith("NO_MATCH"):
        print("\nNo folder was found. Nothing was created.")
        return

    if matches.startswith("AMBIGUOUS"):
        chosen_path = input("Enter the exact folder path to use: ").strip()
        target_folder = Path(chosen_path)
        if not target_folder.exists() or not target_folder.is_dir():
            print("\nThat folder path does not exist. Nothing was created.")
            return
        exact_target_folder = target_folder
    else:
        exact_target_folder = None
        resolved_root = search_root

    item_kind = input("Create a folder or file? [folder/file]: ").strip().lower() or "file"
    item_name = input("Item name: ").strip()
    file_extension = ""
    content = ""

    if item_kind == "file":
        file_extension = input("File extension (blank to keep name as-is): ").strip()
        content = input("File content (blank for empty file): ")

    if exact_target_folder is not None:
        if item_kind == "folder":
            target_path = exact_target_folder / item_name
            target_path.mkdir(parents=True, exist_ok=True)
            print(f"\nSUCCESS: Folder created at '{target_path}'.")
            return

        final_name = item_name
        if file_extension and not file_extension.startswith("."):
            file_extension = f".{file_extension}"
        if file_extension and not final_name.lower().endswith(file_extension.lower()):
            final_name = f"{final_name}{file_extension}"
        target_path = exact_target_folder / final_name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        print(f"\nSUCCESS: File created at '{target_path}'.")
        return

    result = create_item_in_matching_folder.invoke(
        {
            "folder_hint": folder_hint,
            "item_name": item_name,
            "item_kind": item_kind,
            "file_extension": file_extension,
            "content": content,
            "search_root": resolved_root,
        }
    )
    print(f"\n{result}")


if __name__ == "__main__":
    main()