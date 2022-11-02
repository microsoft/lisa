# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, List

from lisa.feature import Feature

FEATURE_NAME_OFFLOAD = "OffloadOvl"
FEATURE_TYPE_OVL = "Ovl"


class Ovl(Feature):
    @classmethod
    def name(cls) -> str:
        return FEATURE_TYPE_OVL

    @classmethod
    def can_disable(cls) -> bool:
        return False

    def enabled(self) -> bool:
        return True
