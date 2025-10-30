# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from functools import partial
from typing import Any, Optional, Type

from lisa import schema, search_space
from lisa.feature import Feature
from lisa.util import constants


class Virtualization(Feature):
    """
    Virtualization platform detection and filtering feature.

    This feature identifies the hypervisor or virtualization environment where
    the test is running and allows tests to specify compatibility requirements.
    The host_type field indicates which virtualization platform is in use.

    The host_type field can contain these values:
    - BareMetal: Physical hardware without virtualization
    - HyperV: Microsoft Hyper-V hypervisor
    - QEMU: QEMU/KVM virtualization stack
    - CloudHypervisor: Cloud Hypervisor
    - None: Unknown

    Tests can use this feature to ensure they only run on supported
    hypervisors or to skip execution on platforms where they have known
    compatibility issues.
    """

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return schema.VirtualizationSettings

    @classmethod
    def name(cls) -> str:
        return constants.FEATURE_VIRTUALIZATION

    @classmethod
    def can_disable(cls) -> bool:
        return False

    def enabled(self) -> bool:
        return True

    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        """
        Base implementation returns platform-agnostic settings.

        Platforms should override this to detect their actual hypervisor.
        """
        return schema.VirtualizationSettings(host_type=None)


# Helper functions for creating virtualization requirements


def _single_host_type_requirement(
    host_type: schema.VirtualizationHostType,
) -> partial[schema.VirtualizationSettings]:
    """
    Create a virtualization requirement for a specific host type.

    This helper function creates a partial VirtualizationSettings that can be
    used as a test requirement to filter tests by virtualization platform.

    Args:
        host_type: The specific virtualization host type to require

    Returns:
        Partial VirtualizationSettings configured for the specified host type
    """
    return partial(
        schema.VirtualizationSettings,
        host_type=search_space.SetSpace(True, [host_type]),
    )


# Host type requirements - predefined partial functions for common use cases
BareMetalHostType = _single_host_type_requirement(
    schema.VirtualizationHostType.BareMetal
)
HyperVHostType = _single_host_type_requirement(schema.VirtualizationHostType.HyperV)
QemuHostType = _single_host_type_requirement(schema.VirtualizationHostType.QEMU)
CloudHypervisorHostType = _single_host_type_requirement(
    schema.VirtualizationHostType.CloudHypervisor
)
