# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List

from lisa.feature import Feature
from lisa.util import SwitchableMixin


class DiskEphemeral(Feature, SwitchableMixin):
    @classmethod
    def name(cls) -> str:
        return cls.__name__

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def enabled(self) -> bool:
        return True

    @staticmethod
    def get_disk_id() -> str:
        raise NotImplementedError


class DiskPremiumLRS(Feature, SwitchableMixin):
    @classmethod
    def name(cls) -> str:
        return cls.__name__

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def enabled(self) -> bool:
        return True

    @staticmethod
    def get_disk_id() -> str:
        raise NotImplementedError


class DiskStandardHDDLRS(Feature, SwitchableMixin):
    @classmethod
    def name(cls) -> str:
        return cls.__name__

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def enabled(self) -> bool:
        return True

    @staticmethod
    def get_disk_id() -> str:
        raise NotImplementedError


class DiskStandardSSDLRS(Feature, SwitchableMixin):
    @classmethod
    def name(cls) -> str:
        return cls.__name__

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def enabled(self) -> bool:
        return True

    @staticmethod
    def get_disk_id() -> str:
        raise NotImplementedError


class DiskType:
    DISK_EPHEMERAL: str = DiskEphemeral.name()
    DISK_PREMIUM: str = DiskPremiumLRS.name()
    DISK_STANDARD_HDD: str = DiskStandardHDDLRS.name()
    DISK_STANDARD_SSD: str = DiskStandardSSDLRS.name()

    @staticmethod
    def get_disk_types() -> List[str]:
        return [
            DiskType.DISK_EPHEMERAL,
            DiskType.DISK_PREMIUM,
            DiskType.DISK_STANDARD_HDD,
            DiskType.DISK_STANDARD_SSD,
        ]
