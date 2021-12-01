# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from lisa.feature import Feature

FEATURE_NAME_INFINIBAND = "Infiniband"


class Infiniband(Feature):
    def enabled(self) -> bool:
        return True

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_INFINIBAND

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def is_over_sriov(self) -> bool:
        raise NotImplementedError

    # nd stands for network direct
    # example SKU: Standard_H16mr
    def is_over_nd(self) -> bool:
        raise NotImplementedError
