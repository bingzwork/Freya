from pathlib import Path


def replace_in_file(path, old_text, new_text):
    path = Path(path)

    if not path.exists():
        return "File not found."

    content = path.read_text(encoding="utf-8")

    if old_text not in content:
        return "Text not found."

    content = content.replace(old_text, new_text)

    path.write_text(content, encoding="utf-8")

    return "File updated."
    