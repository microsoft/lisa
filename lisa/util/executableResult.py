from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutableResult:
    stdout: str
    stderr: str
    exit_code: Optional[int]
    elapsed: float

    def __str__(self) -> str:
        return self.stdout
