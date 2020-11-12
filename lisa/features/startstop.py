from typing import Any

from lisa.feature import Feature

FEATURE_NAME_STARTSTOP = "StartStop"


class StartStop(Feature):
    def __init__(self, node: Any, platform: Any) -> None:
        super().__init__(node, platform)
        self._log = self._node.log

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_STARTSTOP

    @classmethod
    def enabled(cls) -> bool:
        # most platform support shutdown
        return True

    @classmethod
    def can_disable(cls) -> bool:
        # no reason to disable it, it can not be used
        return False

    def _stop(self, wait: bool = True) -> None:
        raise NotImplementedError()

    def _start(self, wait: bool = True) -> None:
        raise NotImplementedError()

    def _restart(self, wait: bool = True) -> None:
        raise NotImplementedError()

    def stop(self, wait: bool = True) -> None:
        self._log.debug("stopping")
        self._stop(wait=wait)
        self._node.close()

    def start(self, wait: bool = True) -> None:
        self._log.debug("starting")
        self._start(wait=wait)

    def restart(self, wait: bool = True) -> None:
        self._log.debug("restarting")
        self._restart(wait=wait)
        self._node.close()
