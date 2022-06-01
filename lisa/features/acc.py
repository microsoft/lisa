# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Type

from lisa import schema
from lisa.feature import Feature


class ACC(Feature):
    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return schema.ACCOptionSettings

    @classmethod
    def can_disable(cls) -> bool:
        return False

    def enabled(self) -> bool:
        return True
