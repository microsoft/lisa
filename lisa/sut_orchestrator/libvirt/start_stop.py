# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any

from lisa import features

from .context import get_node_context
from .platform_interface import IBaseLibvirtPlatform


# Implements the StartStop feature.
class StartStop(features.StartStop):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)

    def _stop(
        self, wait: bool = True, state: features.StopState = features.StopState.Shutdown
    ) -> None:
        if state == features.StopState.Hibernate:
            raise NotImplementedError(
                "libvirt orchestrator does not support hibernate stop"
            )

        node_context = get_node_context(self._node)
        domain = node_context.domain
        assert domain

        if not domain.isActive():
            # VM is already shutdown.
            return

        if wait:
            domain.destroy()

        else:
            domain.shutdown()

    def _start(self, wait: bool = True) -> None:
        assert isinstance(self._platform, IBaseLibvirtPlatform)
        self._platform.restart_domain_and_attach_logger(self._node)

    def _restart(self, wait: bool = True) -> None:
        node_context = get_node_context(self._node)
        domain = node_context.domain
        assert domain

        if wait:
            if domain.isActive():
                # Shutdown VM.
                domain.destroy()

            # Boot up VM and ensure console logger reattaches.
            assert isinstance(self._platform, IBaseLibvirtPlatform)
            self._platform.restart_domain_and_attach_logger(self._node)

        else:
            if domain.isActive():
                # On a clean reboot, QEMU process is not torn down.
                # So, no need to reattach the console logger.
                domain.reboot()

            else:
                # Boot up VM and ensure console logger reattaches.
                assert isinstance(self._platform, IBaseLibvirtPlatform)
                self._platform.restart_domain_and_attach_logger(self._node)
