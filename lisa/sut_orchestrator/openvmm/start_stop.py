# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast

from lisa import features


class StartStop(features.StartStop):
    def _stop(
        self,
        wait: bool = True,
        state: features.StopState = features.StopState.Shutdown,
    ) -> None:
        if state == features.StopState.Hibernate:
            raise NotImplementedError("openvmm orchestrator does not support hibernate")

        node = cast(Any, self._node)
        node._openvmm_stop(wait=wait)

    def _start(self, wait: bool = True) -> None:
        node = cast(Any, self._node)
        node._openvmm_start(wait=wait)

    def _restart(self, wait: bool = True) -> None:
        node = cast(Any, self._node)
        node._openvmm_restart(wait=wait)
