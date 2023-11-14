# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa import Node
from lisa.operating_system import Debian, Oracle, Redhat, Suse, Ubuntu
from lisa.util import UnsupportedDistroException

DPDK_STABLE_GIT_REPO = "https://dpdk.org/git/dpdk-stable"

# azure routing table magic subnet prefix
# signals 'route all traffic on this subnet'
AZ_ROUTE_ALL_TRAFFIC = "0.0.0.0/0"


def check_dpdk_support(node: Node) -> None:
    # check requirements according to:
    # https://docs.microsoft.com/en-us/azure/virtual-network/setup-dpdk
    supported = False
    if isinstance(node.os, Debian):
        if isinstance(node.os, Ubuntu):
            supported = node.os.information.version >= "18.4.0"
        else:
            supported = node.os.information.version >= "10.0.0"
    elif isinstance(node.os, Redhat) and not isinstance(node.os, Oracle):
        supported = node.os.information.version >= "7.5.0"
    elif isinstance(node.os, Suse):
        supported = node.os.information.version >= "15.0.0"
    else:
        # this OS is not supported
        raise UnsupportedDistroException(
            node.os, "This OS is not supported by the DPDK test suite for Azure."
        )

    if not supported:
        raise UnsupportedDistroException(
            node.os, "This OS version is EOL and is not supported for DPDK on Azure"
        )
