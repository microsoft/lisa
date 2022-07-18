# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from enum import Enum

from lisa.feature import Feature

FEATURE_NAME_STARTSTOP = "StartStop"


class StopState(str, Enum):
    Hibernate = "hibernate"
    Shutdown = "shutdown"


class StartStop(Feature):
    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_STARTSTOP

    @classmethod
    def can_disable(cls) -> bool:
        # no reason to disable it, it can not be used
        return False

    def _stop(self, wait: bool = True, state: StopState = StopState.Shutdown) -> None:
        raise NotImplementedError()

    def _start(self, wait: bool = True) -> None:
        raise NotImplementedError()

    def _restart(self, wait: bool = True) -> None:
        raise NotImplementedError()

    def enabled(self) -> bool:
        # most platform support shutdown
        return True

    def stop(self, wait: bool = True, state: StopState = StopState.Shutdown) -> None:
        self._log.info("stopping")
        self._stop(wait=wait, state=state)
        self._node.close()

    def start(self, wait: bool = True) -> None:
        self._log.info("starting")
        self._start(wait=wait)

    def restart(self, wait: bool = True) -> None:
        self._log.info("restarting")
        self._restart(wait=wait)
        self._node.close()

    def status(self, resource_group_name: str, name: str) -> str:
        raise NotImplementedError()
