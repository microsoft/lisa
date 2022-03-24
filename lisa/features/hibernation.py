# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.feature import Feature

FEATURE_NAME_HIBERNATION = "Hibernation"


class Hibernation(Feature):
    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_HIBERNATION

    @classmethod
    def enabled(cls) -> bool:
        return True

    @classmethod
    def can_disable(cls) -> bool:
        return True
