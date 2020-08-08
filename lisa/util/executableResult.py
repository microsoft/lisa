from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutableResult:
    stdout: str
    stderr: str
    exitCode: Optional[int]
