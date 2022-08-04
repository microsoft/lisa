# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.feature import Feature

FEATURE_NAME_ISOLATED_RESOURCE = "isolated_resource"


class IsolatedResource(Feature):
    """
    This is for VMs or bare metal machines, which don't share resources with
    other machines. This kind of machine can run perf tests directly.
    """

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_ISOLATED_RESOURCE

    @classmethod
    def can_disable(cls) -> bool:
        return False

    def enabled(self) -> bool:
        return True
