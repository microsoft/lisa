# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import Dict, List, Tuple, Type

from assertpy import assert_that, fail
from microsoft.testsuites.dpdk.dpdktestpmd import DpdkTestpmd
from microsoft.testsuites.dpdk.dpdkutil import DpdkDevnameInfo
from semver import VersionInfo

from lisa.executable import Tool
from lisa.nic import NicInfo
from lisa.operating_system import Debian, Fedora
from lisa.tools import Cat, Chown, Gcc, Git, Ip, Make, Modprobe, Uname, Whoami
from lisa.util import SkippedException, UnsupportedDistroException


class DpdkOvs(Tool):
    ubuntu_packages = ["automake", "autoconf", "libtool", "libcap-ng-dev"]
    _version_regex = re.compile(
        r"v(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)"
    )
    OVS_BRIDGE_NAME = "br-dpdk"  # name for the bridge, can be anything

    # OVS records the DPDK release each OVS release builds against in its own
    # source tree, so parse the pairing from the checkout instead of keeping a
    # copy here that goes stale every release.
    # rendered at https://docs.openvswitch.org/en/latest/faq/releases/
    OVS_RELEASES_DOC = "Documentation/faq/releases.rst"

    # matches the rows of the "Open vSwitch / DPDK" table, ex: "3.3.x  23.11.7"
    _ovs_dpdk_pairing_regex = re.compile(
        r"^\s*(?P<ovs>\d+\.\d+)\.x\s+(?P<dpdk>\d+(?:\.\d+)+)\s*$",
        re.MULTILINE,
    )

    # constants for tracking setup state
    INIT = 0
    MODULE_LOAD = 1
    SERVICE_START = 2
    BRIDGE_ADD = 3
    PORT_ADD = 4
    INTERFACE_UP = 5

    @property
    def command(self) -> str:
        return "ovs"

    @property
    def dependencies(self) -> List[Type[Tool]]:
        # dependencies are needed for build script! Don't delete
        return [Git, Gcc, Make, Git]

    # FIXME: Redhat, SUSE, and any distro supported by the DpdkTestpmd tool.
    # should work here as well. They just need to be implemented and tested.
    # If we ever generalize this to test OVS without dpdk, the requirements can
    # be relaxed since OVS without dpdk supports kernels > 3.3
    # For reference: https://docs.openvswitch.org/en/latest/intro/install/general/
    @property
    def can_install(self) -> bool:
        return self.node.is_posix

    def _install_os_packages(self) -> None:
        os = self.node.os
        if isinstance(os, Debian):
            os.install_packages(self.ubuntu_packages)
        elif isinstance(self.node.os, Fedora):
            # NOTE: RHEL 8 works without additional packages,
            # an edit may be needed later after further testing.
            pass
        else:
            raise UnsupportedDistroException(
                os,
                "OVS install for this test is not implemented on this platform",
            )

    def _install(self) -> bool:
        # NOTE: defer building until we can provide the DPDK source dir as a parameter.
        # _install just checks out our resources and sets up the version info
        node = self.node
        kernel_version = node.tools[Uname].get_linux_information().kernel_version
        if not (
            kernel_version > "4.4.0"
            and (isinstance(node.os, Debian) or isinstance(node.os, Fedora))
        ):
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, "OVS is not available for this platform"
                )
            )

        self._install_os_packages()
        if isinstance(node.os, Fedora):
            node.os.group_install_packages("Development Tools")
        elif isinstance(node.os, Debian):
            node.os.install_packages("autotools-dev")
        else:
            raise SkippedException("Unsupported OS for OVS tests.")

        # NOTE: dpdk build is big, use this function to find a safe spot to build.
        build_path = node.find_partition_with_freespace(size_in_gb=64)
        self.ovs_build_path = node.get_pure_path(build_path).joinpath("ovs_build")

        # create the dir and chown it since partition ownership is not guaranteed
        node.shell.mkdir(self.ovs_build_path)
        username = node.tools[Whoami].get_username()
        node.tools[Chown].change_owner(self.ovs_build_path, username, recurse=True)

        # checkout git and get latest version tag
        git = self.node.tools[Git]
        self.repo_dir = git.clone(
            "https://github.com/openvswitch/ovs.git",
            cwd=self.ovs_build_path,
        )
        latest_version_tag = git.get_tag(cwd=self.repo_dir)
        git.checkout(latest_version_tag, cwd=self.repo_dir)

        # parse version info from git tag to validate the right dpdk version is used
        self._set_version_info(latest_version_tag)

        return True

    def _set_version_info(self, version: str) -> None:
        match = self._version_regex.search(version)
        if not match or not all(
            [match.group("major"), match.group("minor"), match.group("patch")]
        ):
            fail(
                f"Could not match version tag '{version}' "
                f"with regex '{self._version_regex.pattern}'"
            )
        else:
            major, minor, patch = map(
                int, [match.group("major"), match.group("minor"), match.group("patch")]
            )
            self.ovs_version = VersionInfo(major, minor, patch)

    @staticmethod
    def _as_version_tuple(version: str) -> Tuple[int, ...]:
        return tuple(int(part) for part in version.split("."))

    def _get_dpdk_to_ovs_version_map(self) -> Dict[int, str]:
        # Parse the "Open vSwitch / DPDK" build compatibility table out of the
        # OVS docs. _install checks out the newest OVS tag, so the table is as
        # up to date as the OVS release we cloned.
        releases_doc = self.node.tools[Cat].read(
            str(self.repo_dir.joinpath(self.OVS_RELEASES_DOC)),
            force_run=True,
        )

        version_map: Dict[int, str] = {}
        for match in self._ovs_dpdk_pairing_regex.finditer(releases_doc):
            ovs_version = match.group("ovs")
            # DPDK uses YY.MM versioning, so the major identifies the release
            # year. The table only pairs against the YY.11 LTS releases.
            dpdk_major = int(match.group("dpdk").split(".")[0])
            current = version_map.get(dpdk_major)
            # Multiple OVS releases build against the same DPDK release. Keep
            # the oldest, it is the minimum OVS version for that DPDK.
            if current is None or self._as_version_tuple(
                ovs_version
            ) < self._as_version_tuple(current):
                version_map[dpdk_major] = ovs_version

        if not version_map:
            fail(
                "Could not parse the OVS/DPDK version table from "
                f"{self.OVS_RELEASES_DOC}. The OVS doc format may have changed, "
                "check https://docs.openvswitch.org/en/latest/faq/releases/"
            )
        return version_map

    def _force_ovs_dpdk_compatibility(self, dpdk_tool: DpdkTestpmd) -> None:
        dpdk_version = dpdk_tool.get_dpdk_version()

        # check if dpdk version too low
        if dpdk_version < "19.11.0":
            raise SkippedException(
                f"Dpdk version {dpdk_version} is not supported by this test."
            )

        # confirm supported ovs:dpdk version pairing using the table published
        # in the OVS source tree we checked out during _install.
        dpdk_to_ovs_minimum_version = self._get_dpdk_to_ovs_version_map()

        # check if DPDK version is above the versions in the table.
        if int(dpdk_version.major) not in dpdk_to_ovs_minimum_version.keys():
            # we've already checked out latest OVS
            # DPDK version is newer than any release OVS documents, warn
            # and proceed.
            self.node.log.info(
                "DPDK version is above the maximum in the version match "
                "table. Using latest OVS. If test fails, OVS may not support "
                "this DPDK release yet. "
                "check https://docs.openvswitch.org/en/latest/faq/releases/"
            )
            return

        # fetch the minimum version from the map
        minimum_version = dpdk_to_ovs_minimum_version[int(dpdk_version.major)]

        # we'll check out the latest version of that release
        git = self.node.tools[Git]

        # build a filter to select tags with the version prefix
        version_major_and_minor = "\\.".join(minimum_version.split(".")[:2])

        # get the tags, picks the latest with that prefix
        tag = git.get_tag(cwd=self.repo_dir, filter_=f"^v{version_major_and_minor}.*")

        # checkout the revision into a local branch
        git.checkout(tag, cwd=self.repo_dir, checkout_branch=f"local-{tag}")
        self._set_version_info(tag)

    def build_with_dpdk(
        self, dpdk_tool: DpdkTestpmd, use_latest_ovs: bool = False
    ) -> None:
        node = self.node
        # run dpdk version check if not forcing latest OVS
        if not use_latest_ovs:
            self._force_ovs_dpdk_compatibility(dpdk_tool)
        make = node.tools[Make]

        node.execute(
            "./boot.sh",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Could not run bootstrap script from OVS"
            ),
            cwd=self.repo_dir,
        )
        node.execute(
            (
                "./configure --prefix=/usr --localstatedir=/var "
                "--sysconfdir=/etc --with-dpdk=static"
            ),
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Could not configure with configure script generated by ./boot.sh"
            ),
            cwd=self.repo_dir,
        )
        make.make(
            "",
            cwd=self.repo_dir,
        )
        make.make_install(
            cwd=self.repo_dir,
        )

    def _get_eal_and_device_args(
        self, nics: List[NicInfo], dpdk_tool: DpdkTestpmd
    ) -> Tuple[str, str]:
        assert_that(nics).described_as(
            "setup_ovs needs at least one test nic to attach to the bridge"
        ).is_not_empty()

        # dpdk-devname enumerates the ports the EAL actually sees. Running it
        # both validates the netvsc PMD setup and gives us the EAL device
        # arguments needed to select those ports.
        devname_info = DpdkDevnameInfo(testpmd=dpdk_tool)
        devname_info.get_port_info(nics, expect_ports=len(nics))

        # the devname args are built for a shell invocation, but OVS hands the
        # value straight to the EAL, so the embedded quoting has to go.
        eal_args = devname_info.nic_args.replace('"', "")

        # The netvsc PMD drives the synthetic vmbus device, so the PCI address
        # of the VF does not name the port. Select it by MAC instead, which is
        # bus agnostic. See netdev_dpdk_process_devargs in lib/netdev-dpdk.c.
        device_args = f"class=eth,mac={nics[0].mac_addr}"
        return eal_args, device_args

    def setup_ovs(self, nics: List[NicInfo], dpdk_tool: DpdkTestpmd) -> None:
        # setup OVS and track which state we are in.
        # this will allow a try/except to catch a failure and hold it until
        # until after the teardown. It should also allow teardown
        # to leave the node in a clean state even if the test fails.
        node = self.node
        modprobe = node.tools[Modprobe]
        self.teardown_state = self.INIT

        eal_args, device_args = self._get_eal_and_device_args(nics, dpdk_tool)

        # load ovs driver
        modprobe.load("openvswitch")
        self.teardown_state = self.MODULE_LOAD

        # start OVS service
        node.execute(
            "/usr/share/openvswitch/scripts/ovs-ctl start",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Could not start ovs-ctl",
        )
        self.teardown_state = self.SERVICE_START

        # Pass the device selection to the EAL. This has to happen before
        # dpdk-init flips to true, since that is when OVS runs rte_eal_init.
        node.execute(
            (
                "ovs-vsctl --no-wait set Open_vSwitch . "
                f'other_config:dpdk-extra="{eal_args}"'
            ),
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Could not set the EAL device arguments for OVS"
            ),
        )

        # OVS 4.0 stopped probing devices during EAL init, which breaks the
        # "class=eth,mac=" lookup because it only searches ports that are
        # already probed. Older releases probe at init and ignore this key.
        node.execute(
            (
                "ovs-vsctl --no-wait set Open_vSwitch . "
                "other_config:dpdk-probe-at-init=true"
            ),
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Could not enable device probing at DPDK init for OVS"
            ),
        )

        # enable dpdk in ovs config
        node.execute(
            "ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Could not init dpdk properties for OVS",
        )
        # NOTE: this is just config step and doesn't need a teardown step.

        # add a bridge to OVS
        node.execute(
            (
                f"ovs-vsctl add-br {self.OVS_BRIDGE_NAME} -- "
                f"set bridge {self.OVS_BRIDGE_NAME} datapath_type=netdev"
            ),
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Could not create dpdk bridge pseudo-device"
            ),
        )
        self.teardown_state = self.BRIDGE_ADD

        # add the dpdk port and give it the address of the interface to use
        node.execute(
            (
                f"ovs-vsctl add-port {self.OVS_BRIDGE_NAME} p1 -- "
                f'set Interface p1 type=dpdk options:dpdk-devargs="{device_args}"'
            ),
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Could not add dpdk port to the OVS bridge"
            ),
        )
        self.teardown_state = self.PORT_ADD

        # set interface UP
        ip = node.tools[Ip]
        ip.up(self.OVS_BRIDGE_NAME)
        self.teardown_state = self.INTERFACE_UP

    def stop_ovs(self) -> None:
        # teardown based on the state that was reached during setup_ovs
        # this allows use in a 'finally' block
        # leave the node in a usable state for the next test.
        node = self.node
        ip = node.tools[Ip]
        modprobe = node.tools[Modprobe]
        if self.teardown_state == self.INTERFACE_UP:
            ip.down(self.OVS_BRIDGE_NAME)
        if self.teardown_state >= self.PORT_ADD:
            node.execute(
                f"ovs-vsctl del-port {self.OVS_BRIDGE_NAME} p1",
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Could not destroy dpdk port to the OVS bridge"
                ),
            )
        if self.teardown_state >= self.BRIDGE_ADD:
            node.execute(
                (f"ovs-vsctl del-br {self.OVS_BRIDGE_NAME}"),
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Could not destroy dpdk bridge pseudo-device"
                ),
            )
        if self.teardown_state >= self.SERVICE_START:
            node.execute(
                "/usr/share/openvswitch/scripts/ovs-ctl stop",
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="Could not stop ovs-ctl",
            )
        if self.teardown_state >= self.MODULE_LOAD:
            modprobe.remove(["openvswitch"])
