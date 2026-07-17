from pathlib import Path


def read_file(path):
    path = Path(path)

    if not path.exists():
        return "File not found."

    return path.read_text(encoding="utf-8")


def write_file(path, content):
    path = Path(path)
    path.write_text(content, encoding="utf-8")
    return "File saved."


def list_files(folder):
    folder = Path(folder)

    if not folder.exists():
        return []

    return [str(x) for x in folder.iterdir()]