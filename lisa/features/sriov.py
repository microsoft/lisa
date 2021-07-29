# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.feature import Feature
from lisa.util import SwitchableMixin

FEATURE_NAME_SRIOV = "Sriov"


class Sriov(Feature, SwitchableMixin):
    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_SRIOV

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def enabled(self) -> bool:
        raise NotImplementedError()
