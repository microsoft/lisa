from timeit import default_timer as timer
from typing import Optional


class Timer:
    def __init__(self) -> None:
        self.start = timer()
        self._elapsed: Optional[float] = None

    def elapsed(self, stop: bool = True) -> float:
        if self._elapsed is None or not stop:
            self._elapsed = timer() - self.start
        return self._elapsed

    def __str__(self) -> str:
        return f"{self.elapsed():.3f} sec"


def create_timer() -> Timer:
    return Timer()
