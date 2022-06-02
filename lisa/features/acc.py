# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.feature import Feature

FEATURE_NAME_ACC = "ACC"


class ACC(Feature):
    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_ACC

    @classmethod
    def can_disable(cls) -> bool:
        return False

    def enabled(self) -> bool:
        return True
