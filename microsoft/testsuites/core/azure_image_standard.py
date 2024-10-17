# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePosixPath
from typing import List, Pattern, cast

from assertpy.assertpy import assert_that

from lisa import (
    Node,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Disk
from lisa.operating_system import (
    BSD,
    SLES,
    CBLMariner,
    CoreOs,
    CpuArchitecture,
    Debian,
    DebianRepositoryInfo,
    Fedora,
    FreeBSD,
    Oracle,
    Posix,
    Redhat,
    RPMRepositoryInfo,
    Suse,
    SuseRepositoryInfo,
    Ubuntu,
)
from lisa.sut_orchestrator import AZURE, READY
from lisa.sut_orchestrator.azure.features import AzureDiskOptionSettings
from lisa.tools import Cat, Dmesg, Journalctl, Ls, Lsblk, Lscpu, Pgrep, Ssh
from lisa.util import (
    LisaException,
    PassedException,
    SkippedException,
    UnsupportedDistroException,
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

    # rhui-microsoft-azure-rhel7                                       Micr enabled
    # rhui-rhel-7-server-rhui-optional-rpms/7Server/x86_64             Red  disabled
    # rhui-rhel-8-for-x86_64-baseos-rhui-source-rpms            Red Hat Enter disabled
    _redhat_repo_regex = re.compile(r"rhui-(?P<name>\S+)[ ]*.*(enabled|disabled)", re.M)

    # pattern to get failure, error, warnings from dmesg, syslog/messages
    _error_fail_warnings_pattern: List[Pattern[str]] = [
        re.compile(r"^(.*fail.*)$", re.MULTILINE),
        re.compile(r"^(.*error.*)$", re.MULTILINE),
        re.compile(r"^(.*warning.*)$", re.MULTILINE),
    ]

    # pattern to get failure, error, warnings from cloud-init.log
    # examples from cloud-init.log:
    # [WARNING]: Running ['tdnf', '-y', 'upgrade'] resulted in stderr output.
    # cloud-init[958]: photon.py[ERROR]: Error while installing packages
    _ERROR_WARNING_pattern: List[Pattern[str]] = [
        re.compile(r"^(.*\[ERROR\]:.*)", re.MULTILINE),
        re.compile(r"^(.*\[WARNING\]:.*)", re.MULTILINE),
    ]

    # ignorable failure, error, warnings pattern which got confirmed
    _error_fail_warnings_ignorable_str_list: List[Pattern[str]] = [
        re.compile(r"^(.*Perf event create on CPU 0 failed with -2.*)$", re.M),
        re.compile(r"^(.*Fast TSC calibration.*)$", re.M),
        re.compile(r"^(.*acpi PNP0A03:00.*)$", re.M),
        re.compile(r"^(.*systemd-journald-audit.socket.*)$", re.M),
        re.compile(
            r"^(.*Failed to set file attributes: Inappropriate ioctl for device.*)$",
            re.M,
        ),
        re.compile(
            r"^(.*Failed to create new system journal: No such file or directory.*)$",
            re.M,
        ),
        re.compile(r"^(.*failed to get extended button data.*)$", re.M),
        re.compile(r"^(.*ipmi_si.*)$", re.M),
        re.compile(r"^(.*pci_root PNP0A03:00.*)$", re.M),
        re.compile(r"^(.*disabling PCIe ASPM.*)$", re.M),
        re.compile(r"^(.*systemd-journald.*)$", re.M),
        re.compile(r"^(.*Cannot add dependency job.*)$", re.M),
        re.compile(r"^(.*failsafe.*)$", re.M),
        re.compile(r"^(.*startpar-bridge.*)$", re.M),
        re.compile(r"^(.*Failed to spawn.*)$", re.M),
        re.compile(r"^(.*display-manager.service.*)$", re.M),
        re.compile(r"^(.*ACPI PCC probe failed.*)$", re.M),
        re.compile(r"^(.*Failed to access perfctr msr.*)$", re.M),
        re.compile(r"^(.*Failed to init entropy source hwrng.*)$", re.M),
        re.compile(r"^(.*augenrules.*: failure 1.*)$", re.M),
        re.compile(
            r"^(.*microcode_ctl: kernel version .* failed early load check for .*, skipping.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(
            r"^(.*rngd: Failed to init entropy source 0: Hardware RNG Device.*)$", re.M
        ),
        re.compile(
            r"^(.*open /dev/vmbus/hv_fcopy failed; error: 2 No such file or directory.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(
            r"^(.*open /dev/vmbus/hv_vss failed; error: 2 No such file or directory.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(r"^(.*hv-vss-daemon.service.*)$", re.M),
        re.compile(r"^(.*hv-fcopy-daemon.service.*)$", re.M),
        re.compile(r"^(.*dnf.*: Failed determining last makecache time.*)$", re.M),
        re.compile(
            r"^(.*dbus-daemon.*: .system. Activation via systemd failed for unit 'dbus-org.freedesktop.resolve1.service': Unit dbus-org.freedesktop.resolve1.service not found.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(r"^(.*TLS record write failed.*)$", re.M),
        re.compile(r"^(.*state ensure error.*)$", re.M),
        re.compile(r"^(.*got unexpected HTTP status code.*)$", re.M),
        re.compile(
            r'^(.*Error getting hardware address for "eth0": No such device.*)$', re.M
        ),
        re.compile(r"^(.*codec can't encode character.*)$", re.M),
        re.compile(
            r"^(.*Failed to set certificate key file \\[gnutls error -64: Error while reading file.\\].*)$",  # noqa: E501
            re.M,
        ),
        re.compile(
            r"^(.*audispd: Error - /etc/audisp/plugins.d/wdgsmart-syslog.conf isn't owned by root.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(
            r"^(.*Condition check resulted in Process error reports when automatic reporting is enabled.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(
            r"^(.*error trying to compare the snap system key: system-key missing on disk.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(
            r"^(.*open /dev/vmbus/hv_fcopy failed; error: 2 No such file or directory.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(
            r"^(.*open /dev/vmbus/hv_vss failed; error: 2 No such file or directory.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(r"^(.*mitigating potential DNS violation DVE-2018-0001.*)$", re.M),
        re.compile(r"^(.*end_request: I/O error, dev fd0, sector 0.*)$", re.M),
        re.compile(r"^(.*blk_update_request: I/O error, dev fd0, sector 0.*)$", re.M),
        re.compile(r"^(.*floppy: error -5 while reading block 0.*)$", re.M),
        re.compile(r"^(.*Broken pipe.*)$", re.M),
        re.compile(r"^(.*errors=remount-ro.*)$", re.M),
        re.compile(
            r"^(.*smartd.*: Device: /dev/.*, Bad IEC \\(SMART\\) mode page, err=5, skip device.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(r"^(.*GPT: Use GNU Parted to correct GPT errors.*)$", re.M),
        re.compile(r"^(.*RAS: Correctable Errors collector initialized.*)$", re.M),
        re.compile(r"^(.*BERT: Boot Error Record Table support is disabled.*)$", re.M),
        re.compile(r"^( Enable it by using bert_enable as kernel parameter.*)$", re.M),
        re.compile(
            r"^(.*WARNING Daemon VM is provisioned, but the VM unique identifie has changed -- clearing cached state.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(r"^(.*WARNING! Cached DHCP leases will be deleted.*)$", re.M),
        re.compile(
            r"^(.*Unconfined exec qualifier \\(ux\\) allows some dangerous environment variables.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(r"^(.*reloading interface list.*)$", re.M),
        re.compile(r"^(.*Server preferred version:.*)$", re.M),
        re.compile(r"^(.*WARNING Hostname record does not exist,.*)$", re.M),
        re.compile(r"^(.*Dhcp client is not running.*)$", re.M),
        re.compile(r"^(.*Write warning to Azure ephemeral disk.*)$", re.M),
        re.compile(r"^(.*Added ephemeral disk warning to.*)$", re.M),
        re.compile(r"^(.*Proceeding WITHOUT firewalling in effect!.*)$", re.M),
        re.compile(r"^(.*urandom warning.* missed due to ratelimiting.*)$", re.M),
        re.compile(
            r"^(.*kdumpctl.*: Warning: There might not be enough space to save a vmcore.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(
            r"^(.*WARNING ExtHandler ExtHandler cgroups v2 mounted at.*)$", re.M
        ),
        re.compile(r"^(.*dataloss warning file.*)$", re.M),
        re.compile(
            r"(.*temp-disk-dataloss-warning.*Deactivated successfully.*)$",
            re.M,
        ),
        re.compile(r"(.*temp-disk-dataloss-warning.service: Succeeded.*)$", re.M),
        re.compile(
            r"(.*was skipped because all trigger condition checks failed.*)$", re.M
        ),
        re.compile(r"(.*was skipped because of a failed condition check.*)$", re.M),
        re.compile(r"^(.*GRUB failed boot detection.*)$", re.M),
        re.compile(r"^(.*nofail.*)$", re.M),
        re.compile(
            r"^(.*SGI XFS with ACLs, security attributes, realtime, verbose warnings, quota, no debug enabled.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(
            r"^(.*platform regulatory\.0: Direct firmware load for regulatory\.db failed with error -2.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(r"^(.*failed to load regulatory\.db.*)$", re.M),
        re.compile(
            r"^(.*This warning is only shown for the first unit using IP firewalling.*)$",  # noqa: E501
            re.M,
        ),
        re.compile(r"^(.*Internal error: Cannot find counter: swap.*)$", re.M),
        re.compile(r"^(.*ACPI.*failed to evaluate _DSM \(0x1001\).*)$", re.M),
        # refer https://access.redhat.com/solutions/6732061
        re.compile(r"^(.*ib_srpt MAD registration failed for.*)$", re.M),
        re.compile(r"^(.*ib_srpt srpt_add_one\(.*\) failed.*)$", re.M),
        # this warning shown up because kvp file created after the cloud-init check
        re.compile(
            r"^(.*handlers.py\[WARNING\]: failed to truncate kvp pool file.*)$",
            re.M,
        ),
        # pam_unix,pam_faillock
        re.compile(r"^(.*pam_unix,pam_faillock.*)$", re.M),
    ]

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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
    )
    def verify_default_targetpw(self, node: Node) -> None:
        sudoers_out = (
            node.tools[Cat].run("/etc/sudoers", sudo=True, force_run=True).stdout
        )
        matched = get_matched_str(sudoers_out, self._uncommented_default_targetpw_regex)
        assert_that(
            matched, "Defaults targetpw should not be enabled in /etc/sudoers"
        ).is_length(0)

    @TestCaseMetadata(
        description="""
        This test will check the configuration of the grub file and verify that numa
        is disabled for Redhat distro version < 6.6.0

        Steps:
        1. Verify grub configuration depending on the distro type.
        2. For Redhat based distros, verify that numa is disabled for versions < 6.6.0
        """,
        priority=1,
        requirement=simple_requirement(
            supported_platform_type=[AZURE, READY], unsupported_os=[BSD]
        ),
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
        elif isinstance(node.os, Fedora) or isinstance(node.os, CBLMariner):
            if isinstance(node.os, Redhat) and node.os.information.version >= "8.0.0":
                grub_output = node.tools[Cat].read("/boot/grub2/grubenv", sudo=True)
            elif (
                node.execute("ls -lt /boot/grub2/grub.cfg", sudo=True, shell=True)
            ).exit_code == 0:
                grub_output = node.tools[Cat].read("/boot/grub2/grub.cfg", sudo=True)
            elif (
                node.execute("ls -lt /boot/grub/menu.lst", sudo=True, shell=True)
            ).exit_code == 0:
                grub_output = node.tools[Cat].read("/boot/grub/menu.lst", sudo=True)
            else:
                raise LisaException("Unable to locate grub file")
        elif isinstance(node.os, CoreOs):
            # in core os we don't have access to boot partition
            grub_output = node.tools[Dmesg].run().stdout
        else:
            raise LisaException(f"Test cannot run on distro {node.os.name}")

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
        priority=3,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
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
        priority=2,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
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
        Verify if there is any issues in and after 'os update'

        Steps:
        1. Run os update command.
        2. Reboot the VM and see if the VM is still in good state.
        """,
        priority=2,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
    )
    def verify_os_update(self, node: Node) -> None:
        if isinstance(node.os, Posix):
            node.os.update_packages("")
        else:
            raise SkippedException(f"Unsupported OS or distro type : {type(node.os)}")
        node.reboot()

    @TestCaseMetadata(
        description="""
        This test will check that kvp daemon is installed. This is an optional
        requirement for Debian based distros.

        Steps:
        1. Verify that list of running process matching name of kvp daemon
        has length greater than zero.
        """,
        priority=2,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
    )
    def verify_hv_kvp_daemon_installed(self, node: Node) -> None:
        if isinstance(node.os, Debian):
            running_processes = node.tools[Pgrep].get_processes("hv_kvp_daemon")
            if len(running_processes) == 0:
                raise PassedException("hv_kvp_daemon is not installed")
        elif isinstance(node.os, CBLMariner):
            running_processes = node.tools[Pgrep].get_processes("hypervkvpd")
            assert_that(running_processes, "Expected one running process").is_length(1)
            assert_that(
                running_processes[0].name, "Expected name 'hypervkvpd'"
            ).is_equal_to("hypervkvpd")
        else:
            raise SkippedException(f"Unsupported distro type : {type(node.os)}")

    @TestCaseMetadata(
        description="""
        This test will check that repositories are correctly installed.

        Steps:
        1. Verify the repository configuration depending on the distro type.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
    )
    def verify_repository_installed(self, node: Node) -> None:  # noqa: C901
        assert isinstance(node.os, Posix)

        if isinstance(node.os, Debian):
            repositories = node.os.get_repositories()
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
                repo_url_map = {
                    CpuArchitecture.X64: "azure.archive.ubuntu.com",
                    CpuArchitecture.ARM64: "ports.ubuntu.com",
                }
                lscpu = node.tools[Lscpu]
                arch = lscpu.get_architecture()
                repo_url = repo_url_map.get(arch, None)
                contains_security_keyword = any(
                    [
                        "-security" in repository.name
                        for repository in debian_repositories
                    ]
                )
                contains_repo_url = any(
                    [
                        str(repo_url) in repository.uri
                        for repository in debian_repositories
                    ]
                )
                contains_updates_keyword = any(
                    [
                        "-updates" in repository.name
                        for repository in debian_repositories
                    ]
                )

                is_repository_configured_correctly = (
                    contains_repo_url
                    and contains_security_keyword
                    and contains_updates_keyword
                )

                assert_that(
                    is_repository_configured_correctly,
                    f"`{repo_url}`, `security`, "
                    "`updates` should be in `apt-get "
                    "update` output",
                ).is_true()
            else:
                is_repository_configured_correctly = any(
                    [
                        "deb.debian.org" in repository.uri
                        or "debian-archive.trafficmanager.net" in repository.uri
                        or "azure.deb.debian.cloud/debian" in repository.uri
                        for repository in debian_repositories
                    ]
                )
                assert_that(
                    is_repository_configured_correctly,
                    "`deb.debian.org` or `debian-archive.trafficmanager.net` should "
                    "be in the `apt-get update` output",
                ).is_true()
        elif isinstance(node.os, Suse):
            repositories = node.os.get_repositories()
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
                ).is_greater_than(0)
                assert_that(
                    int(update_repo_enable_refresh_count),
                    "One or more expected `Update` repositories are not "
                    "enabled/refreshed",
                ).is_greater_than(2)
        elif isinstance(node.os, Oracle):
            repositories = node.os.get_repositories()
            oracle_repositories = [
                cast(RPMRepositoryInfo, repo) for repo in repositories
            ]

            # verify that `base` repository is present
            is_latest_repository_present = any(
                ["latest" in repository.id for repository in oracle_repositories]
            )
            assert_that(
                is_latest_repository_present, "Latest repository should be present"
            ).is_true()
        elif isinstance(node.os, Fedora):
            repositories = node.os.get_repositories()
            fedora_repositories = [
                cast(RPMRepositoryInfo, repo) for repo in repositories
            ]

            if node.os.information.version >= "8.0.0":
                # verify that `base` repository is present
                is_base_repository_present = any(
                    ["base" in repository.id for repository in fedora_repositories]
                )
                assert_that(
                    is_base_repository_present, "Base repository should be present"
                ).is_true()

                # verify that `appstream` repository is present
                is_appstream_repository_present = any(
                    ["appstream" in repository.id for repository in fedora_repositories]
                )
                assert_that(
                    is_appstream_repository_present,
                    "AppStream repository should be present",
                ).is_true()

            # verify that at least five repositories are present in Redhat
            if type(node.os) == Redhat:
                fedora_repositories = find_patterns_in_lines(
                    node.execute("yum repolist all -q", sudo=True).stdout,
                    [self._redhat_repo_regex],
                )[0]

                assert_that(
                    len(fedora_repositories),
                    "yum repolist all should be greater than 5",
                ).is_greater_than(5)
        elif isinstance(node.os, CBLMariner):
            repositories = node.os.get_repositories()
            mariner_repositories = [
                cast(RPMRepositoryInfo, repo) for repo in repositories
            ]

            if 3 == node.os.information.version.major:
                expected_repo_list = [
                    "azurelinux-official-base",
                    "azurelinux-official-ms-non-oss",
                    "azurelinux-official-ms-oss",
                ]
            else:
                expected_repo_list = [
                    "mariner-official-base",
                    "mariner-official-microsoft",
                ]
                if 1 == node.os.information.version.major:
                    expected_repo_list += ["mariner-official-update"]
                elif 2 == node.os.information.version.major:
                    expected_repo_list += ["mariner-official-extras"]

            for id_ in expected_repo_list:
                is_repository_present = any(
                    id_ in repository.id for repository in mariner_repositories
                )
                assert_that(
                    is_repository_present,
                    f"{id_} repository should be present",
                ).is_true()
        elif type(node.os) == FreeBSD:
            repositories = node.os.get_repositories()
            assert_that(
                len(repositories),
                "No repositories are present in FreeBSD",
            ).is_greater_than(0)
        else:
            raise UnsupportedDistroException(
                node.os, "repository check is missing for this distro"
            )

    @TestCaseMetadata(
        description="""
        This test will check the serial console is enabled from kernel command line
         in dmesg.

        Steps:
        1. Get the kernel command line from /var/log/messages or
            /var/log/syslog output.
        2. Check expected setting from kernel command line.
            2.1. Expected to see 'console=ttyAMA0' for aarch64.
            2.2. Expected to see 'console=ttyS0' for x86_64.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
    )
    def verify_serial_console_is_enabled(self, node: Node) -> None:
        console_device = {
            CpuArchitecture.X64: "ttyS0",
            CpuArchitecture.ARM64: "ttyAMA0",
        }
        if isinstance(node.os, CBLMariner):
            if node.os.information.version < "2.0.0":
                raise SkippedException(
                    "CBLMariner 1.0 has a known 'wont fix' issue with this test"
                )
        if isinstance(node.os, CBLMariner) or (
            isinstance(node.os, Ubuntu) and node.os.information.version >= "22.10.0"
        ):
            log_output = node.tools[Dmesg].get_output()
            log_file = "dmesg"
        else:
            cat = node.tools[Cat]
            if node.shell.exists(node.get_pure_path("/var/log/messages")):
                log_file = "/var/log/messages"
                log_output = cat.read(log_file, force_run=True, sudo=True)
            elif node.shell.exists(node.get_pure_path("/var/log/syslog")):
                log_file = "/var/log/syslog"
                log_output = cat.read(log_file, force_run=True, sudo=True)
            else:
                log_file = "journalctl"
                journalctl = node.tools[Journalctl]
                log_output = journalctl.first_n_logs_from_boot()
            if not log_output:
                raise LisaException(
                    "Neither /var/log/messages nor /var/log/syslog found."
                    "and journal ctl log is empty."
                )

        lscpu = node.tools[Lscpu]
        arch = lscpu.get_architecture()
        current_console_device = console_device[arch]
        console_enabled_pattern = re.compile(
            rf"^(.*console \[{current_console_device}\] enabled.*)$", re.M
        )
        freebsd_pattern = re.compile(r"^(.*uart0: console \(115200,n,8,1\).*)$", re.M)
        result = find_patterns_in_lines(
            log_output, [console_enabled_pattern, freebsd_pattern]
        )
        if not (result[0] or result[1]):
            raise LisaException(
                "Fail to find console enabled line "
                f"'console [{current_console_device}] enabled' "
                "or 'uart0: console (115200,n,8,1)' "
                f"from {log_file} output",
            )

    @TestCaseMetadata(
        description="""
        This test will check the /root/.bash_history not existing or is empty.

        Steps:
        1. Check .bash_history exist or not, if not, the image is prepared well.
        2. If the .bash_history existed, check the content is empty or not, if not, the
        image is not prepared well.
        """,
        priority=1,
        use_new_environment=True,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
    )
    def verify_bash_history_is_empty(self, node: Node) -> None:
        path_bash_history = "/root/.bash_history"
        cmd_result = node.execute(f"ls -lt {path_bash_history}", sudo=True, shell=True)
        if 0 == cmd_result.exit_code:
            cat = node.tools[Cat]
            bash_history = cat.read(path_bash_history, sudo=True)
            assert_that(bash_history).described_as(
                "/root/.bash_history is not empty, this image is not prepared well."
            ).is_empty()

    @TestCaseMetadata(
        description="""
        This test will check error, failure, warning messages from demsg,
         /var/log/syslog or /var/log/messages file.

        Steps:
        1. Get failure, error, warning messages from dmesg, /var/log/syslog or
         /var/log/messages file.
        2. If any unexpected failure, error, warning messages excluding ignorable ones
         existing, fail the case.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
    )
    def verify_boot_error_fail_warnings(self, node: Node) -> None:
        dmesg = node.tools[Dmesg]
        cat = node.tools[Cat]
        log_output = dmesg.get_output(force_run=True)
        if node.shell.exists(node.get_pure_path("/var/log/syslog")):
            log_output += cat.read("/var/log/syslog", force_run=True, sudo=True)
        if node.shell.exists(node.get_pure_path("/var/log/messages")):
            log_output += cat.read("/var/log/messages", force_run=True, sudo=True)

        ignored_candidates = list(
            (
                set(
                    [
                        x
                        for sublist in find_patterns_in_lines(
                            log_output, self._error_fail_warnings_ignorable_str_list
                        )
                        for x in sublist
                        if x
                    ]
                )
            )
        )
        found_results = [
            x
            for sublist in find_patterns_in_lines(
                log_output, self._error_fail_warnings_pattern
            )
            for x in sublist
            if x and x not in ignored_candidates
        ]
        assert_that(found_results).described_as(
            "unexpected error/failure/warnings shown up in bootup log of distro"
            f" {node.os.name} {node.os.information.version}"
        ).is_empty()

    @TestCaseMetadata(
        description="""
        This test will check ERROR, WARNING messages from /var/log/cloud-init.log
        and also check cloud-init exit status.

        Steps:
        1. Get ERROR, WARNING messages from /var/log/cloud-init.log.
        2. If any unexpected ERROR, WARNING messages or non-zero cloud-init status
         fail the case.
        """,
        priority=2,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
    )
    def verify_cloud_init_error_status(self, node: Node) -> None:
        cat = node.tools[Cat]
        if isinstance(node.os, CBLMariner):
            if node.os.information.version < "2.0.0":
                raise SkippedException(
                    "CBLMariner 1.0 is now obsolete so skip the test."
                )
            cloud_init_log = "/var/log/cloud-init.log"
            if node.shell.exists(node.get_pure_path(cloud_init_log)):
                log_output = cat.read(cloud_init_log, force_run=True, sudo=True)
                found_results = [
                    x
                    for sublist in find_patterns_in_lines(
                        log_output, self._ERROR_WARNING_pattern
                    )
                    for x in sublist
                    if x
                ]
                assert_that(found_results).described_as(
                    "unexpected ERROR/WARNING shown up in cloud-init.log"
                    f" {found_results}"
                    f" {node.os.name} {node.os.information.version}"
                ).is_empty()
                cmd_result = node.execute("cloud-init status --wait", sudo=True)
                cmd_result.assert_exit_code(
                    0, f"cloud-init exit status failed with {cmd_result.exit_code}"
                )
            else:
                raise LisaException("cloud-init.log not exists")
        else:
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, "unsupported distro to run verify_cloud_init test."
                )
            )

    @TestCaseMetadata(
        description="""
        This test will check ClientAliveInterval value in sshd config.

        Steps:
        1. Find ClientAliveInterval from sshd config.
        2. Pass with warning if not find it.
        3. Pass with warning if the value is not between 0 and 180.
        """,
        priority=2,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
    )
    def verify_client_active_interval(self, node: Node) -> None:
        ssh = node.tools[Ssh]
        setting = "ClientAliveInterval"
        value = ssh.get(setting)
        if not value:
            raise LisaException(f"not find {setting} in sshd_config")
        if not (int(value) > 0 and int(value) < 181):
            raise LisaException(f"{setting} should be set between 0 and 180")

    @TestCaseMetadata(
        description="""
        This test will check no pre added users existing in vm.

        Steps:
        1. Exclude current user from all users' list.
        2. Fail the case if the password of any above user existing.
        3. Fail the case if the key of any user existing.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
    )
    def verify_no_pre_exist_users(self, node: Node) -> None:
        key_pattern = re.compile(
            r"command=\"echo \'Please login as the user \\\".*\\\" rather than the user"
            r" \\\"root\\\".\';echo;sleep .*\"",
            re.M,
        )
        # For Bitnami images, the bitnami.service changes the uid of current user as
        # 1000 which user 'bitnami' already has.
        # From https://github.com/coreutils/coreutils/blob/master/src/whoami.c, whoami
        # gets name from EUID which is 1000. Then the output is 'bitnami' rather than
        # the current user. So modified to get the admin user from node connection_info
        remote_node = cast(RemoteNode, node)
        current_user = str(remote_node.connection_info.get("username"))
        cat = node.tools[Cat]
        if isinstance(node.os, FreeBSD):
            shadow_file = "/etc/master.passwd"
        else:
            shadow_file = "/etc/shadow"
        shadow_file_outputs = cat.read_with_filter(
            shadow_file, current_user, True, True, True
        )
        for shadow_raw_output in shadow_file_outputs.splitlines():
            # remove comments
            # # $FreeBSD$
            if shadow_raw_output.strip().startswith("#"):
                continue
            # sample line of /etc/shadow
            # root:x:0:0:root:/root:/bin/bash
            # sshd:!:19161::::::
            # systemd-coredump:!*:19178::::::
            # get first two columns of /etc/shadow
            shadow_matches = re.split(":", shadow_raw_output)
            user_name, user_passwd = shadow_matches[0], shadow_matches[1]
            if not (
                "*" in user_passwd
                or "!" in user_passwd
                or "x" == user_passwd
                or "" == user_passwd
            ):
                raise LisaException(
                    f"Password of user {user_name} is detected in {shadow_file} file. "
                    "It should be deleted."
                )
        passwd_file = "/etc/passwd"
        passwd_file_outputs = cat.read_with_filter(
            passwd_file, current_user, True, True, True
        )
        for passwd_raw_output in passwd_file_outputs.splitlines():
            if (
                passwd_raw_output.strip().startswith("#")
                or "nologin" in passwd_raw_output.strip()
            ):
                continue
            # sample line of /etc/passwd
            # centos:x:1000:1000::/home/centos:/bin/bash
            passwd_matches = re.split(":", passwd_raw_output)
            file_path = f"{passwd_matches[5]}/.ssh/authorized_keys"
            file_exists = node.tools[Ls].path_exists(file_path, sudo=True)
            if file_exists:
                # if content of authorized_keys matches below pattern
                # then it is harmless, otherwise fail the case
                # command="echo 'Please login as the user \"USERNAME\" rather than the user \"root\".';echo;sleep 10;exit 142"  # noqa: E501
                key_content = node.tools[Cat].read(file_path, sudo=True)
                if key_content:
                    key_match = key_pattern.findall(key_content)
                    if not (key_match and key_match[0]):
                        assert_that(
                            file_exists,
                            f"{file_path} is detected. It should be deleted.",
                        ).is_false()

    @TestCaseMetadata(
        description="""
        This test will check that the readme file existed in resource disk mount point.

        Steps:
        1. Obtain the mount point for the resource disk.
            If the /var/log/cloud-init.log file is present,
             attempt to read the customized mount point from
             the cloud-init configuration file.
            If mount point from the cloud-init configuration is unavailable,
             use the default mount location, which is /mnt.
            If none of the above sources provide the mount point,
             it is retrieved from the ResourceDisk.MountPoint entry
             in the waagent.conf configuration file.
        2. Verify that resource disk is mounted from the output of `mount` command.
        3. Verify lost+found folder exists.
        4. Verify DATALOSS_WARNING_README.txt file exists.
        5. Verify 'WARNING: THIS IS A TEMPORARY DISK' contained in
        DATALOSS_WARNING_README.txt file.
        """,
        priority=2,
        requirement=simple_requirement(
            disk=AzureDiskOptionSettings(has_resource_disk=True),
            supported_platform_type=[AZURE],
        ),
    )
    def verify_resource_disk_readme_file(self, node: RemoteNode) -> None:
        resource_disk_mount_point = node.features[Disk].get_resource_disk_mount_point()

        # verify that resource disk is mounted
        # function returns successfully if disk matching mount point is present
        node.features[Disk].get_partition_with_mount_point(resource_disk_mount_point)

        # Verify lost+found folder exists
        # Skip this step for BSD as it does not have lost+found folder
        # since it uses UFS file system
        if not isinstance(node.os, BSD):
            fold_path = f"{resource_disk_mount_point}/lost+found"
            folder_exists = node.tools[Ls].path_exists(fold_path, sudo=True)
            assert_that(folder_exists, f"{fold_path} should be present").is_true()

        # verify DATALOSS_WARNING_README.txt file exists
        file_path = f"{resource_disk_mount_point}/DATALOSS_WARNING_README.txt"
        file_exists = node.tools[Ls].path_exists(file_path, sudo=True)
        assert_that(file_exists, f"{file_path} should be present").is_true()

        # verify 'WARNING: THIS IS A TEMPORARY DISK' contained in
        # DATALOSS_WARNING_README.txt file.
        read_text = node.tools[Cat].read(file_path, force_run=True, sudo=True)
        assert_that(
            read_text,
            f"'WARNING: THIS IS A TEMPORARY DISK' should be present in {file_path}",
        ).contains("WARNING: THIS IS A TEMPORARY DISK")

    @TestCaseMetadata(
        description="""
        This test will check that resource disk is formatted correctly.

        Steps:
        1. Get the mount point for the resource disk. If `/var/log/cloud-init.log`
        file is present, mount location is `/mnt`, otherwise it is obtained from
        `ResourceDisk.MountPoint` entry in `waagent.conf` configuration file.
        2. Verify that resource disk file system type should not be 'ntfs'.
        """,
        priority=1,
        requirement=simple_requirement(
            disk=AzureDiskOptionSettings(has_resource_disk=True),
            supported_platform_type=[AZURE],
        ),
    )
    def verify_resource_disk_file_system(self, node: RemoteNode) -> None:
        resource_disk_mount_point = node.features[Disk].get_resource_disk_mount_point()
        node.features[Disk].get_partition_with_mount_point(resource_disk_mount_point)
        disk_info = node.tools[Lsblk].find_disk_by_mountpoint(resource_disk_mount_point)
        for partition in disk_info.partitions:
            # by default, resource disk comes with ntfs type
            # waagent or cloud-init will format it unless there are some commands hung
            # or interrupt
            assert_that(
                partition.fstype,
                "Resource disk file system type should not equal to ntfs",
            ).is_not_equal_to("ntfs")
