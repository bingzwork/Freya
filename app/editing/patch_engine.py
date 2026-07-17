"""
Validate and apply small, explicit multi-file patches.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PatchOperation:
    action: str
    path: str
    old_text: str = ""
    new_text: str = ""


class PatchValidationError(ValueError):
    pass


class PatchEngine:
    SUPPORTED_ACTIONS = {"create", "replace"}

    def parse(self, payload: dict[str, Any]) -> list[PatchOperation]:
        operations = payload.get("operations")
        if not isinstance(operations, list) or not operations:
            raise PatchValidationError("A patch needs a non-empty operations list.")

        parsed = []
        for item in operations:
            if not isinstance(item, dict):
                raise PatchValidationError("Each operation must be an object.")
            operation = PatchOperation(
                action=item.get("action", ""),
                path=item.get("path", ""),
                old_text=item.get("old_text", ""),
                new_text=item.get("new_text", ""),
            )
            self._validate(operation)
            parsed.append(operation)
        return parsed

    def preview(self, operations: list[PatchOperation]) -> str:
        lines = []
        for operation in operations:
            lines.append(f"{operation.action.upper()} {operation.path}")
        return "\n".join(lines)

    def apply(self, tools, operations: list[PatchOperation]) -> list[dict[str, str]]:
        """Apply validated operations through ToolManager's workspace boundary."""
        results = []
        for operation in operations:
            if operation.action == "create":
                result = tools.execute(
                    "create_file", path=operation.path, content=operation.new_text
                )
            else:
                result = tools.execute(
                    "replace_in_file",
                    path=operation.path,
                    old_text=operation.old_text,
                    new_text=operation.new_text,
                )
            if not result.success:
                raise PatchValidationError(f"Could not apply {operation.path}: {result.error}")
            results.append({"path": operation.path, "result": str(result.output)})
        return results

    def apply_and_verify(self, tools, operations, verifier):
        """Apply a patch transactionally and restore all touched files on failure."""
        snapshots = self._snapshot(tools, operations)
        try:
            changes = self.apply(tools, operations)
        except PatchValidationError:
            self._restore(tools, snapshots)
            raise

        verification = verifier.run_tests()
        if not verification.success:
            self._restore(tools, snapshots)
        return {
            "changes": changes,
            "verification": verification,
            "rolled_back": not verification.success,
        }

    def _snapshot(self, tools, operations):
        snapshots = {}
        for operation in operations:
            if operation.path in snapshots:
                continue
            file = tools.safe_path(operation.path)
            snapshots[operation.path] = (
                file.read_text(encoding="utf-8") if file.is_file() else None
            )
        return snapshots

    def _restore(self, tools, snapshots):
        for path, content in snapshots.items():
            if content is None:
                file = tools.safe_path(path)
                if file.is_file():
                    tools.execute("delete_file", path=path)
            else:
                tools.execute("write_file", path=path, content=content)

    def _validate(self, operation: PatchOperation) -> None:
        if operation.action not in self.SUPPORTED_ACTIONS:
            raise PatchValidationError(f"Unsupported patch action: {operation.action}")
        if not isinstance(operation.path, str) or not operation.path.strip():
            raise PatchValidationError("Every operation needs a path.")
        if not isinstance(operation.old_text, str) or not isinstance(operation.new_text, str):
            raise PatchValidationError("Patch text must be strings.")
        if operation.action == "create" and not operation.new_text:
            raise PatchValidationError("A created file cannot be empty.")
        if operation.action == "replace" and not operation.old_text:
            raise PatchValidationError("A replacement needs its exact original text.")
