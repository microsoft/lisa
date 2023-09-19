# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from typing import TYPE_CHECKING, Any

from lisa import schema
from lisa.feature import Feature

if TYPE_CHECKING:
    from .platform_ import BareMetalPlatform


class ClusterFeature(Feature):
    def __getattr__(self, key: str) -> Any:
        assert self._inner, "inner is not set"
        return getattr(self._inner, key)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        _feature_type = self._get_inner_type()
        self._inner = _feature_type(
            schema.FeatureSettings.create(_feature_type.name()),
            self._node,
            self._platform,
            *args,
            **kwargs,
        )
        self._inner.initialize()


class StartStop(ClusterFeature):
    def _get_inner_type(self) -> Feature:
        platform: BareMetalPlatform = self._platform  # type: ignore
        return platform.cluster.get_start_stop()  # type: ignore


class SerialConsole(ClusterFeature):
    def _get_inner_type(self) -> Feature:
        platform: BareMetalPlatform = self._platform  # type: ignore
        return platform.cluster.get_serial_console()  # type: ignore
