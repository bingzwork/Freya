"""Bounced retry orchestration for approved code changes."""


class RepairLoop:
    def __init__(self, patch_engine, tools, verifier, max_attempts=2):
        self.patch_engine = patch_engine
        self.tools = tools
        self.verifier = verifier
        self.max_attempts = max_attempts

    def run(self, propose):
        """Try proposals until one verifies; failed attempts are rolled back."""
        attempts = []
        feedback = ""
        for number in range(1, self.max_attempts + 1):
            operations = propose(feedback)
            # First, run a dry run (tests + lint) to catch obvious errors before touching files.
            dry_run = self.verifier.dry_run_verify()
            if not dry_run.success:
                # Do not modify anything; just return the verification failure.
                result = {
                    "changes": [],
                    "verification": dry_run,
                    "rolled_back": False,
                }
            else:
                result = self.patch_engine.apply_and_verify(
                    self.tools, operations, self.verifier
                )
            attempts.append(result)
            if result["verification"].success:
                return {"success": True, "attempts": attempts}
            feedback = self._feedback(result["verification"])
        return {"success": False, "attempts": attempts}

    @staticmethod
    def _feedback(verification):
        output = (verification.stdout + "\n" + verification.stderr).strip()
        return f"Previous verification failed (exit {verification.return_code}):\n{output}"
