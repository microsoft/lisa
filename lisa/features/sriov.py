# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.feature import Feature

FEATURE_NAME_SRIOV = "Sriov"


class Sriov(Feature):
    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_SRIOV

    @classmethod
    def enabled(cls) -> bool:
        return True

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def _switch(self, enable: bool) -> None:
        raise NotImplementedError()

    def enable(self) -> None:
        self._switch(True)

    def disable(self) -> None:
        self._switch(False)
