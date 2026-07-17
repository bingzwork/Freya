"""Run a bounded, structured project verification command."""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    command: list[str]
    stdout: str
    stderr: str
    return_code: int


class VerificationRunner:
    def __init__(self, workspace, timeout_seconds=120):
        self.workspace = Path(workspace).resolve()
        self.timeout_seconds = timeout_seconds

    def run_tests(self):
        return self.run([sys.executable, "-m", "pytest", "-q"])

    def lint(self) -> VerificationResult:
        """Run a fast syntax check on all .py files using py_compile."""
        errors = []
        for py_file in self.workspace.rglob("*.py"):
            # Skip __pycache__ directories
            if any(part == "__pycache__" for part in py_file.parts):
                continue
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(py_file)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                errors.append(f"{py_file}: {result.stderr.strip()}")
        if errors:
            return VerificationResult(
                False,
                [sys.executable, "-m", "py_compile", "<multiple>"],
                "\n".join(errors),
                "",
                1,
            )
        else:
            return VerificationResult(
                True,
                [sys.executable, "-m", "py_compile", "<all>"],
                "",
                "",
                0,
            )

    def dry_run_verify(self) -> VerificationResult:
        """Run verification (tests + lint) without applying any changes."""
        test_result = self.run_tests()
        lint_result = self.lint()
        success = test_result.success and lint_result.success
        combined_out = (test_result.stdout + "\n" + lint_result.stdout).strip()
        combined_err = (test_result.stderr + "\n" + lint_result.stderr).strip()
        return VerificationResult(
            success,
            ["verify", "tests+lint"],
            combined_out,
            combined_err,
            0 if success else 1,
        )

    def run(self, command):
        if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
            raise ValueError("Verification commands must be a list of strings.")
        try:
            completed = subprocess.run(
                command,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            return VerificationResult(
                False,
                command,
                error.stdout or "",
                f"Verification timed out after {self.timeout_seconds} seconds.",
                -1,
            )
        return VerificationResult(
            completed.returncode == 0,
            command,
            completed.stdout,
            completed.stderr,
            completed.returncode,
        )
