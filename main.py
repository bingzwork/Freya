import sys
from pathlib import Path

from app.agent.agent import FreyaAgent


def main():
    if len(sys.argv) > 1:
        project = Path(sys.argv[1]).expanduser().resolve()
    else:
        project = Path.cwd()

    if not project.exists():
        print(f"Project does not exist: {project}")
        return

    if not project.is_dir():
        print(f"Not a directory: {project}")
        return

    print(f"Opening project: {project}")

    agent = FreyaAgent(str(project))

    print("\nFreya AI")
    print("Commands:")
    print("Read-only actions run automatically.")
    print("Code or terminal changes require API approval.")
    print("Type 'exit' to quit.\n")

    while True:
        user = input("You: ").strip()

        if user.lower() == "exit":
            break

        try:
            reply = agent.run(user)
            print(f"\nFreya:\n{reply}\n")
        except Exception as e:
            print(f"\nError:\n{e}\n")


if __name__ == "__main__":
    main()