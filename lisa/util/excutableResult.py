from typing import Optional


class ExecutableResult:
    def __init__(self, stdout: str, stderr: str, exitCode: Optional[int]) -> None:
        self.stdout = stdout.strip("\r\n")
        self.stderr = stderr.strip("\r\n")
        self.exitCode = exitCode
