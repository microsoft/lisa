from typing import Optional


class ExecutableResult:
    def __init__(self, stdout: str, stderr: str, exitCode: Optional[int]) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.exitCode = exitCode
