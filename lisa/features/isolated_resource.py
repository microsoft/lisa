# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.feature import Feature

FEATURE_NAME_ISOLATED_RESOURCE = "isolated_resource"


class IsolatedResource(Feature):
    """
    This is for select VMs that allow reliable perf measurements,
      or for bare metal machines. This is for tests which are both
      resource-intensive and take a long time.

    Note: The azure version of this relies on a manually maintained allowlist.
        If you want to run a test on a size which isn't in it;
        either ignore the feature or reach out to your size to the list.

        'Isolation' in terms of taking up a whole node is no longer
        guaranteed in large skus going forward in Azure for skus > v5.
    """

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_ISOLATED_RESOURCE

    @classmethod
    def can_disable(cls) -> bool:
        return False

    def enabled(self) -> bool:
        return True
