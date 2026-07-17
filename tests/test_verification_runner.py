from pathlib import Path

from app.verification.runner import VerificationRunner


def test_verification_runner_runs_a_safe_argument_list(tmp_path: Path) -> None:
    runner = VerificationRunner(tmp_path)

    result = runner.run(["cmd", "/c", "exit", "0"])

    assert result.success
    assert result.return_code == 0


def test_verification_runner_reports_a_failed_command(tmp_path: Path) -> None:
    runner = VerificationRunner(tmp_path)

    result = runner.run(["cmd", "/c", "exit", "3"])

    assert not result.success
    assert result.return_code == 3
