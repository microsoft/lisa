# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePosixPath
from typing import cast

from assertpy.assertpy import assert_that

from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import (
    SLES,
    CoreOs,
    Debian,
    DebianRepositoryInfo,
    Fedora,
    FedoraRepositoryInfo,
    Oracle,
    Posix,
    Redhat,
    Suse,
    SuseRepositoryInfo,
    Ubuntu,
)
from lisa.tools import Cat, Dmesg, Pgrep
from lisa.util import (
    LisaException,
    PassedException,
    SkippedException,
    find_patterns_in_lines,
    get_matched_str,
)


@TestSuiteMetadata(
    area="azure_image_standard",
    category="functional",
    description="""
    This test suite is used to check azure image configuration.
    """,
)
class AzureImageStandard(TestSuite):

    # Defaults targetpw
    _uncommented_default_targetpw_regex = re.compile(
        r"(\nDefaults\s+targetpw)|(^Defaults\s+targetpw.*)"
    )

    # repo-oss
    _oss_repo_regex = re.compile(r"^(?!.*(debug|non)).*oss.*$")

    # suse_cloud_application_platform_tools_module_x86_64:sle-module-cap-tools15-sp2-debuginfo-updates
    _update_repo_regex = re.compile(r"^(?!.*(debug|non)).*update.*$")

    # rhui-microsoft-azure-rhel7                                       Micr enabled: 8
    #  rhui-rhel-7-server-rhui-optional-rpms/7Server/x86_64             Red  disabled
    _redhat_repo_regex = re.compile(
        r"rhui-(?P<name>\S+)\s+(?P<source>\S+)\s+(enabled|disabled)"
    )

    @TestCaseMetadata(
        description="""
        This test will verify that `Defaults targetpw` is not enabled in the
        `/etc/sudoers` file.

        If `targetpw` is set, `sudo` will prompt for the
        password of the user specified by the -u option (defaults to root)
        instead of the password of the invoking user when running a command
        or editing a file. More information can be found here :
        https://linux.die.net/man/5/sudoers

        Steps:
        1. Get the content of `/etc/sudoers` file.
        2. Verify that `Defaults targetpw` should be disabled, if present.
        """,
        priority=1,
    )
    def verify_default_targetpw(self, node: Node) -> None:
        sudoers_out = (
            node.tools[Cat].run("/etc/sudoers", sudo=True, force_run=True).stdout
        )
        matched = get_matched_str(sudoers_out, self._uncommented_default_targetpw_regex)
        assert_that(
            matched, "Defaults targetpw should not be enabled in /etc/sudoers"
        ).is_empty()

    @TestCaseMetadata(
        description="""
        This test will check the configuration of the grub file and verify that numa
        is disabled for Redhat distro version < 6.6.0

        Steps:
        1. Verify grub configuration depending on the distro type.
        2. For Redhat based distros, verify that numa is disabled for versions < 6.6.0
        """,
        priority=1,
    )
    def verify_grub(self, node: Node) -> None:
        # check grub configuration file
        if isinstance(node.os, Debian):
            grub_output = node.tools[Cat].read("/boot/grub/grub.cfg", sudo=True)
        elif isinstance(node.os, Suse):
            if node.shell.exists(PurePosixPath("/boot/grub2/grub.cfg")):
                grub_output = node.tools[Cat].read("/boot/grub2/grub.cfg", sudo=True)
            elif node.shell.exists(PurePosixPath("/boot/grub/grub.conf")):
                grub_output = node.tools[Cat].read("/boot/grub/grub.conf", sudo=True)
            else:
                raise LisaException("Unable to locate grub file")
        elif isinstance(node.os, Fedora):
            if isinstance(node.os, Redhat) and node.os.information.version >= "8.0.0":
                grub_output = node.tools[Cat].read("/boot/grub2/grubenv", sudo=True)
            elif node.shell.exists(PurePosixPath("/boot/grub2/grub.cfg")):
                grub_output = node.tools[Cat].read("/boot/grub2/grub.cfg", sudo=True)
            elif node.shell.exists(PurePosixPath("/boot/grub/menu.lst")):
                grub_output = node.tools[Cat].read("/boot/grub/menu.lst", sudo=True)
            else:
                raise LisaException("Unable to locate grub file")
        elif isinstance(node.os, CoreOs):
            # in core os we don't have access to boot partition
            grub_output = node.tools[Dmesg].run().stdout
        else:
            raise LisaException(f"Test cannot run on distro {node.os}")

        assert_that(
            grub_output, f"console=ttyS0 should be present in {grub_output}."
        ).contains("console=ttyS0")
        assert_that(
            grub_output,
            f"libata.atapi_enabled=0 should not be present in {grub_output}.",
        ).does_not_contain("libata.atapi_enabled=0")
        assert_that(
            grub_output, f"reserve=0x1f0,0x8 should not be present in {grub_output}."
        ).does_not_contain("reserve=0x1f0,0x8")

        # check numa=off in grub for Redhat version < 6.6.0
        # https://access.redhat.com/solutions/436883
        if isinstance(node.os, Redhat):
            if node.os.information.version < "6.6.0":
                assert_that(
                    grub_output, f"numa=off should be present in {grub_output}"
                ).contains("numa=off")

    @TestCaseMetadata(
        description="""
        This test will verify that network manager doesn't conflict with the
        waagent on Fedora based distros.

        Steps:
        1. Get the output of command `rpm -q NetworkManager` and verify that
        network manager is not installed.
        """,
        priority=1,
    )
    def verify_network_manager_not_installed(self, node: Node) -> None:
        if isinstance(node.os, Fedora):
            network_manager_output = node.execute("rpm -q NetworkManager").stdout
            if isinstance(node.os, Redhat) and node.os.information.version >= "7.0.0":
                # NetworkManager package no longer conflicts with the waagent on
                # Redhat >= "7.0.0"
                raise SkippedException(
                    "NetworkManager package no longer conflicts with the "
                    "waagent on Redhat 7.0+"
                )
            assert_that(
                network_manager_output, "NetworkManager should not be installed"
            ).contains("is not installed")
        else:
            raise SkippedException(f"unsupported distro type: {type(node.os)}")

    @TestCaseMetadata(
        description="""
        This test will verify that network file exists in /etc/sysconfig and networking
        is enabled on Fedora based distros.

        Steps:
        1. Verify that network file exists.
        2. Verify that networking is enabled in the file.
        """,
        priority=1,
    )
    def verify_network_file_configuration(self, node: Node) -> None:
        if isinstance(node.os, Fedora):
            network_file_path = "/etc/sysconfig/network"
            file_exists = node.shell.exists(PurePosixPath(network_file_path))

            assert_that(
                file_exists,
                f"The network file should be present at {network_file_path}",
            ).is_true()

            network_file = node.tools[Cat].read(network_file_path)
            assert_that(
                network_file.upper(),
                f"networking=yes should be present in {network_file_path}",
            ).contains("networking=yes".upper())
        else:
            raise SkippedException(f"unsupported distro type: {type(node.os)}")

    @TestCaseMetadata(
        description="""
        This test will verify contents of ifcfg-eth0 file on Fedora based distros.

        Steps:
        1. Read the ifcfg-eth0 file and verify that "DEVICE=eth0", "BOOTPROTO=dhcp" and
        "ONBOOT=yes" is present in network file.
        """,
        priority=1,
    )
    def verify_ifcfg_eth0(self, node: Node) -> None:
        if isinstance(node.os, Fedora):
            ifcfg_eth0 = node.tools[Cat].read(
                "/etc/sysconfig/network-scripts/ifcfg-eth0"
            )

            assert_that(
                ifcfg_eth0,
                "DEVICE=eth0 should be present in "
                "/etc/sysconfig/network-scripts/ifcfg-eth0 file",
            ).contains("DEVICE=eth0")
            assert_that(
                ifcfg_eth0,
                "BOOTPROTO=dhcp should be present in "
                "/etc/sysconfig/network-scripts/ifcfg-eth0 file",
            ).contains("BOOTPROTO=dhcp")
            assert_that(
                ifcfg_eth0,
                "ONBOOT=yes should be present in "
                "/etc/sysconfig/network-scripts/ifcfg-eth0 file",
            ).contains("ONBOOT=yes")
        else:
            raise SkippedException(f"unsupported distro type: {type(node.os)}")

    @TestCaseMetadata(
        description="""
        This test will verify that udev rules have been moved out in CoreOS
        and Fedora based distros

        Steps:
        1. Verify that 75-persistent-net-generator.rules and 70-persistent-net.rules
        files are not present.
        """,
        priority=1,
    )
    def verify_udev_rules_moved(self, node: Node) -> None:
        if isinstance(node.os, CoreOs):
            udev_file_path_75_rule = (
                "/usr/lib64/udev/rules.d/75-persistent-net-generator.rules"
            )
            udev_file_path_70_rule = "/usr/lib64/udev/rules.d/70-persistent-net.rules"
        elif isinstance(node.os, Fedora):
            udev_file_path_75_rule = (
                "/lib/udev/rules.d/75-persistent-net-generator.rules"
            )
            udev_file_path_70_rule = "/etc/udev/rules.d/70-persistent-net.rules"
        else:
            raise SkippedException(f"Unsupported distro type : {type(node.os)}")

        assert_that(
            node.shell.exists(PurePosixPath(udev_file_path_75_rule)),
            f"file {udev_file_path_75_rule} should not be present",
        ).is_false()
        assert_that(
            node.shell.exists(PurePosixPath(udev_file_path_70_rule)),
            f"file {udev_file_path_70_rule} should not be present",
        ).is_false()

    @TestCaseMetadata(
        description="""
        This test will verify that dhcp file exists at
        `/etc/sysconfig/network/dhcp` and `DHCLIENT_SET_HOSTNAME` is set
        to `no`.

        Steps:
        1. Verify that dhcp file exists.
        2. Verify that DHCLIENT_SET_HOSTNAME="no" is present in the file.
        """,
        priority=1,
    )
    def verify_dhcp_file_configuration(self, node: Node) -> None:
        if isinstance(node.os, Suse):
            dhcp_file_path = "/etc/sysconfig/network/dhcp"
            file_exists = node.shell.exists(PurePosixPath(dhcp_file_path))

            assert_that(
                file_exists,
                f"The dhcp file should be present at {dhcp_file_path}",
            ).is_true()

            # DHCLIENT_SET_HOSTNAME="no" should be set
            # https://docs.microsoft.com/en-us/azure/virtual-machines/linux/suse-create-upload-vhd#prepare-suse-linux-enterprise-server-for-azure  # noqa: E501
            dhcp_file = node.tools[Cat].read(dhcp_file_path)
            assert_that(
                dhcp_file,
                'DHCLIENT_SET_HOSTNAME="no" should be present in '
                f"file {dhcp_file_path}",
            ).contains('DHCLIENT_SET_HOSTNAME="no"')
        else:
            raise SkippedException(f"Unsupported distro type : {type(node.os)}")

    @TestCaseMetadata(
        description="""
        This test will verify content of `yum.conf` file on Fedora based distros
        for version < 6.6.0

        Steps:
        1. Read the `yum.conf` file and verify that "http_caching=packages" is
        present in the file.
        """,
        priority=1,
    )
    def verify_yum_conf(self, node: Node) -> None:
        if isinstance(node.os, Fedora):
            if node.os.information.version < "6.6.0":
                ym_conf = node.tools[Cat].read("/etc/yum.conf")
                assert_that(
                    ym_conf, "http_caching=packages should be present in /etc/yum.conf"
                ).contains("http_caching=packages")
            else:
                raise SkippedException("This check is only for Fedora version < 6.6.0")
        else:
            raise SkippedException(f"Unsupported distro type : {type(node.os)}")

    @TestCaseMetadata(
        description="""
        This test will check that `hv-kvp-daemon-init` is installed on Debian based
        distros. This is an optional requirement.

        Steps:
        1. Verify that list of running process matching name `hv_kvp_daemon`
        has length greater than zero.
        """,
        priority=1,
    )
    def verify_hv_kvp_daemon_installed(self, node: Node) -> None:
        if isinstance(node.os, Debian):
            running_processes = node.tools[Pgrep].get_processes("hv_kvp_daemon")
            if len(running_processes) == 0:
                raise PassedException("hv_kvp_daemon is not installed")
        else:
            raise SkippedException(f"Unsupported distro type : {type(node.os)}")

    @TestCaseMetadata(
        description="""
        This test will check that repositories are correctly installed.

        Steps:
        1. Verify the repository configuration depending on the distro type.
        """,
        priority=1,
    )
    def verify_repository_installed(self, node: Node) -> None:
        assert isinstance(node.os, Posix)
        repositories = node.os.get_repositories()

        if isinstance(node.os, Debian):
            debian_repositories = [
                cast(DebianRepositoryInfo, repo) for repo in repositories
            ]
            # verify that atleast one repository is `Hit`
            is_repository_hit = any(
                [repository.status == "Hit" for repository in debian_repositories]
            )
            assert_that(
                is_repository_hit,
                "Hit should be present in `apt-get update` output atleast "
                "one repository",
            ).is_true()

            # verify repository configuration
            if isinstance(node.os, Ubuntu):
                contains_security_repo_url = any(
                    [
                        "security.ubuntu.com" in repository.uri
                        for repository in debian_repositories
                    ]
                )
                contains_security_keyword_url = any(
                    [
                        "-security" in repository.uri
                        for repository in debian_repositories
                    ]
                )
                contains_archive_repo_url = any(
                    [
                        "archive.ubuntu.com" in repository.uri
                        for repository in debian_repositories
                    ]
                )
                contains_ports_repo_url = any(
                    [
                        "ports.ubuntu.com" in repository.uri
                        for repository in debian_repositories
                    ]
                )

                is_repository_configured_correctly = (
                    contains_security_repo_url and contains_archive_repo_url
                ) or (contains_security_keyword_url and contains_ports_repo_url)
                assert_that(
                    is_repository_configured_correctly,
                    "`security.ubuntu.com`,`azure.archive.ubuntu.com` or "
                    "`security`,`ports.ubuntu.com` should be in `apt-get "
                    "update` output",
                ).is_true()
            else:
                is_repository_configured_correctly = any(
                    [
                        "deb.debian.org" in repository.uri
                        or "debian-archive.trafficmanager.net" in repository.uri
                        for repository in debian_repositories
                    ]
                )
                assert_that(
                    is_repository_configured_correctly,
                    "`deb.debian.org` or `debian-archive.trafficmanager.net` should "
                    "be in the `apt-get update` output",
                ).is_true()
        elif isinstance(node.os, Suse):
            suse_repositories = [
                cast(SuseRepositoryInfo, repo) for repo in repositories
            ]

            if isinstance(node.os, SLES):
                # Get `zypper lr` output and check if the pool and update
                # repositories are present.
                zypper_out = node.execute("zypper lr", sudo=True).stdout

                assert_that(
                    zypper_out, "'Pool' should be present in the output of zypper -lr"
                ).contains("Pool")
                assert_that(
                    zypper_out,
                    "'Updates' should be present in the output of zypper -lr",
                ).contains("Updates")
            else:
                # get list of repositories and verify statistics for `oss` and
                # `update` repositories.
                oss_repo_count = 0
                update_repo_count = 0
                oss_repo_enable_refresh_count = 0
                update_repo_enable_refresh_count = 0
                for repo in suse_repositories:
                    full_name = f"{repo.alias} {repo.name}"
                    full_name = full_name.lower()

                    # set oss repo statistics
                    if re.match(self._oss_repo_regex, full_name):
                        oss_repo_count += 1
                        if repo.refresh:
                            oss_repo_enable_refresh_count += 1

                    # set update repo statistics
                    if re.match(self._update_repo_regex, full_name):
                        update_repo_count += 1
                        if repo.refresh:
                            update_repo_enable_refresh_count += 1

                assert_that(
                    int(oss_repo_count),
                    "One or more expected `Oss` repositories are not present",
                ).is_greater_than(0)
                assert_that(
                    int(update_repo_count),
                    "One or more expected `Update` repositories are not present",
                ).is_greater_than(0)
                assert_that(
                    int(oss_repo_enable_refresh_count),
                    "One or more expected `Oss` repositories are not enabled/refreshed",
                ).is_greater_than(2)
                assert_that(
                    int(update_repo_enable_refresh_count),
                    "One or more expected `Update` repositories are not "
                    "enabled/refreshed",
                ).is_greater_than(2)
        elif isinstance(node.os, Oracle):
            oracle_repositories = [
                cast(FedoraRepositoryInfo, repo) for repo in repositories
            ]

            # verify that `base` repository is present
            is_latest_repository_present = any(
                ["latest" in repository.id for repository in oracle_repositories]
            )
            assert_that(
                is_latest_repository_present, "Latest repository should be present"
            ).is_true()
        elif isinstance(node.os, Fedora):
            fedora_repositories = [
                cast(FedoraRepositoryInfo, repo) for repo in repositories
            ]

            # verify that `base` repository is present
            is_base_repository_present = any(
                ["base" in repository.id for repository in fedora_repositories]
            )
            assert_that(
                is_base_repository_present, "Base repository should be present"
            ).is_true()

            if node.os.information.version >= "8.0.0":
                # verify that `appstream` repository is present
                is_appstream_repository_present = any(
                    ["appstream" in repository.id for repository in fedora_repositories]
                )
                assert_that(
                    is_appstream_repository_present,
                    "AppStream repository should be present",
                ).is_true()
            else:
                # verify that `update` repository is not present
                is_updates_repository_present = any(
                    ["updates" in repository.id for repository in fedora_repositories]
                )
                assert_that(
                    is_updates_repository_present,
                    "Updates repository should be present",
                ).is_true()

            # verify that atleast five repositories are present in Redhat
            if isinstance(node.os, Redhat):
                fedora_repositories = find_patterns_in_lines(
                    node.execute("yum repolist all -q", sudo=True).stdout,
                    [self._redhat_repo_regex],
                )[0]

                assert_that(
                    len(fedora_repositories),
                    "yum repolist all should be greater than 5",
                ).is_greater_than(5)
        else:
            raise LisaException(f"Unsupported distro type : {type(node.os)}")
