# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from enum import Enum
from typing import Tuple

from lisa.feature import Feature
from lisa.schema import NodeSpace

FEATURE_NAME_RESIZE = "Resize"


class ResizeAction(str, Enum):
    IncreaseCoreCount = "IncreaseCpuCount"
    DecreaseCoreCount = "DecreaseCpuCount"


class Resize(Feature):
    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_RESIZE

    @classmethod
    def can_disable(cls) -> bool:
        raise NotImplementedError()

    def enabled(self) -> bool:
        raise NotImplementedError()

    def is_supported(self) -> bool:
        raise NotImplementedError()

    def resize(
        self, resize_action: ResizeAction = ResizeAction.IncreaseCoreCount
    ) -> Tuple[NodeSpace, str, str]:
        raise NotImplementedError()
