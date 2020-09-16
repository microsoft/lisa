from timeit import default_timer as timer
from typing import Optional


class Timer:
    def __init__(self) -> None:
        self.start = timer()
        self._elapsed: Optional[float] = None

    def elapsed(self, stop: bool = True) -> float:
        """
        stop: True uses for onetime timer. it returns stored elapsed. Following calls
                returns the stored value.
              False uses for continual counting. it returns current elapsed, but also
                store it.
        """
        if self._elapsed is None or not stop:
            self._elapsed = timer() - self.start
        return self._elapsed

    def elapsed_text(self, stop: bool = True) -> str:
        return f"{self.elapsed(stop):.3f} sec"

    def __str__(self) -> str:
        return self.elapsed_text()


def create_timer() -> Timer:
    return Timer()
