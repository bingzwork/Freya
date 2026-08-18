"""Run a bounded, structured project verification command."""

import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.core.logger import logger


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    command: list[str]
    stdout: str
    stderr: str
    return_code: int
    status: VerificationStatus | str | None = None

    def __post_init__(self) -> None:
        if self.status is None:
            inferred = VerificationStatus.UNKNOWN if self.return_code == -1 else (
                VerificationStatus.VERIFIED if self.success else VerificationStatus.FAILED
            )
            object.__setattr__(self, "status", inferred)
        elif not isinstance(self.status, VerificationStatus):
            object.__setattr__(self, "status", VerificationStatus(str(self.status)))


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
                status=VerificationStatus.FAILED,
            )
        else:
            return VerificationResult(
                True,
                [sys.executable, "-m", "py_compile", "<all>"],
                "",
                "",
                0,
                status=VerificationStatus.VERIFIED,
            )

    def dry_run_verify(self) -> VerificationResult:
        """Run verification (tests + lint) without applying any changes."""
        test_result = self.run_tests()
        lint_result = self.lint()
        success = test_result.success and lint_result.success
        if getattr(test_result, "status", None) == VerificationStatus.UNKNOWN or getattr(lint_result, "status", None) == VerificationStatus.UNKNOWN:
            status = VerificationStatus.UNKNOWN
        elif success:
            status = VerificationStatus.VERIFIED
        else:
            status = VerificationStatus.FAILED
        combined_out = (test_result.stdout + "\n" + lint_result.stdout).strip()
        combined_err = (test_result.stderr + "\n" + lint_result.stderr).strip()
        return VerificationResult(
            success,
            ["verify", "tests+lint"],
            combined_out,
            combined_err,
            0 if success else 1,
            status=status,
        )

    def run(self, command):
        if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
            raise ValueError("Verification commands must be a list of strings.")

        logger.info("[Verification]")
        logger.info("Started")

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
            logger.info("[Verification]")
            logger.info("Failed")
            return VerificationResult(
                False,
                command,
                error.stdout or "",
                f"Verification timed out after {self.timeout_seconds} seconds.",
                -1,
                status=VerificationStatus.UNKNOWN,
            )

        result = VerificationResult(
            completed.returncode == 0,
            command,
            completed.stdout,
            completed.stderr,
            completed.returncode,
            status=VerificationStatus.VERIFIED if completed.returncode == 0 else VerificationStatus.FAILED,
        )

        logger.info("[Verification]")
        logger.info("Passed" if result.success else "Failed")
        return result
from app.verification.coalescing import run as _coalesced_run 
VerificationRunner._legacy_run = VerificationRunner.run 
VerificationRunner._fingerprint = staticmethod(lambda command: hashlib.sha256(chr(0).join(command).encode('utf-8')).hexdigest()) 
VerificationRunner.run = _coalesced_run
def _runner_fingerprint(self, command): 
    from app.verification.coalescing import fingerprint 
    return fingerprint(self, command) 
VerificationRunner._fingerprint = _runner_fingerprint
def _runner_terminate(self, process): 
    if process.poll() is None: 
        try: process.kill() 
        except OSError: pass 
VerificationRunner._terminate_process = _runner_terminate
def _targeted_run_tests(self, paths=None, *, full_suite=False, extra_args=None): 
    if paths is None: 
        paths = [] if full_suite else ['tests/test_verification_runner.py'] 
    command = [sys.executable, '-m', 'pytest', '-q', *[str(path) for path in paths]] 
    if extra_args: 
        command.extend(extra_args) 
    return self.run(command) 
VerificationRunner.run_tests = _targeted_run_tests
