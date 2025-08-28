# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePosixPath
from typing import List, Optional, Pattern, cast

from assertpy.assertpy import assert_that
from packaging.version import Version

from lisa import (
    Node,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    simple_requirement,
)
from lisa.base_tools.uname import Uname
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
    Linux,
    Oracle,
    Posix,
    Redhat,
    RPMRepositoryInfo,
    Suse,
    SuseRepositoryInfo,
    Ubuntu,
)
from lisa.sut_orchestrator import AZURE, HYPERV, READY
from lisa.sut_orchestrator.azure.features import AzureDiskOptionSettings
from lisa.sut_orchestrator.azure.tools import Waagent
from lisa.tools import (
    Cat,
    Dmesg,
    Find,
    Journalctl,
    KernelConfig,
    Ls,
    Lsblk,
    Lscpu,
    Pgrep,
    Ssh,
    Stat,
    Swap,
)
from lisa.tools.lsblk import DiskInfo
from lisa.util import (
    LisaException,
    PassedException,
    SkippedException,
    UnsupportedDistroException,
    find_patterns_groups_in_lines,
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
    # These modules are essential for Hyper-V / Azure platform.
    _essential_modules_configuration = {
        "wdt": "CONFIG_WATCHDOG",
        "cifs": "CONFIG_CIFS",
    }
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
        # hamless mellanox warning that does not affect functionality of the system
        re.compile(
            r"^(.*mlx5_core0: WARN: mlx5_fwdump_prep:92:\(pid 0\).*)$",
            re.M,
        ),
        # ACPI failback to PDC
        re.compile(
            r"^(.* ACPI: _OSC evaluation for CPUs failed, trying _PDC\r)$",
            re.M,
        ),
        # Buffer I/O error on dev sr0, logical block 1, async page read
        re.compile(
            r"^(.*Buffer I/O error on dev sr0, logical block 1, async page read\r)$",
            re.M,
        ),
        # I/O error,dev sr0,sector 8 op 0x0:(READ) flags 0x80700 phys_seg 1 prio class 2
        # I/O error,dev sr0,sector 8 op 0x0:(READ) flags 0x0 phys_seg 1 prio class 2
        re.compile(
            r"^(.* I/O error, dev sr0, sector 8 op 0x0:\(READ\) flags 0x[0-9a-fA-F]+ phys_seg 1 prio class 2\r)$",  # noqa: E501
            re.M,
        ),
        # 2025-01-16T08:51:16.449922+00:00 azurelinux kernel: audit: type=1103
        # audit(1737017476.442:257): pid=1296 uid=0 auid=4294967295 ses=4294967295
        # subj=unconfined msg=\'op=PAM:setcred grantors=? acct="l****t"
        # exe="/usr/lib/systemd/systemd-executor" hostname=? addr=?terminal=?res=failed
        re.compile(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00\s)?"
            r"(?P<hostname>[a-zA-Z0-9\-]+)\s(kernel:\s)?\[\s*(?P<kernel_time>\d+\.\d+)\s*\]"  # noqa: E501
            r"(?:\s*)?audit:\s+type=(?P<type>\d+)\s+audit\((?P<audit_time>\d+\.\d+):"
            r"(?P<audit_id>\d+)\):\s+pid=(?P<pid>\d+)\s+uid=(?P<uid>\d+)\s+auid="
            r"(?P<auid>\d+)\s+ses=(?P<ses>\d+)\s+subj=(?P<subj>[a-zA-Z0-9\-]+)\s+"
            r"msg=\'op=PAM:setcred\s+grantors=\?[\s\S]*?acct=\"(?P<acct>[a-zA-Z0-9\*\-]+)\""  # noqa: E501
            r"\s+exe=\"(?P<exe>[^\"]+)\"\s+hostname=\? addr=\? terminal=\? res="
            r"(?P<res>[a-zA-Z]+)\'\r"
        ),
    ]

    # Python 3.8.10
    # Python 2.6
    # 3.8.10
    # 2.6
    _python_version_pattern = re.compile(r"(?:Python\s*)?(\d+\.\d+(?:\.\d+)?)")

    # OpenSSL 3.0.0
    # OpenSSL 1.1
    # 3.0.0
    # 1.1
    _openssl_version_pattern = re.compile(r"(?:Python\s*)?(\d+\.\d+(?:\.\d+)?)")

    # OMI-1.9.1-0 - Wed Aug 28 23:16:27 PDT 2024
    # ii  omi    1.9.1.0    amd64    Open Management Infrastructure
    # omi-1.9.1-0.x86_64
    _omi_version_pattern = re.compile(
        r"(?:OMI-|omi\s+|omi-)(\d+\.\d+\.\d+(?:\.\d+|-\d+)?)"
    )

    # /etc/passwd
    # root:x:0:0:root:/root:/bin/bash
    # shutdown:x:6:0:shutdown:/sbin:/sbin/shutdown
    # platform:x:998:995::/home/platform:/sbin/nologin
    # username (no colons):password (usually x or *):UID (numeric):GID (numeric):GECOS field (can be empty):home directory:shell (rest of line)  # noqa: E501
    _passwd_entry_regex = re.compile(
        r"^(?P<username>[^:]+):(?P<password>[^:]*):(?P<uid>\d+):(?P<gid>\d+):(?P<gecos>[^:]*):(?P<home_dir>[^:]*):(?P<shell>.*)$"  # noqa: E501
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
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
            supported_platform_type=[AZURE, READY, HYPERV], unsupported_os=[BSD]
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
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
        is enabled on Fedora based distros. For Fedora version > 39, it checks if
        /etc/NetworkManager/system-connections/ exists and is enabled.

        Steps:
        1. Verify that network file exists.
        2. Verify that networking is enabled in the file.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
    )
    def verify_network_file_configuration(self, node: Node) -> None:
        if isinstance(node.os, Fedora):
            if node.os.information.version >= "39.0.0":
                # Fedora 39 and later use NetworkManager
                # Check if /etc/NetworkManager/system-connections/ exists
                nm_connections_path = "/etc/NetworkManager/system-connections"
                eth0_exists = node.shell.exists(
                    PurePosixPath(f"{nm_connections_path}/eth0.nmconnection")
                ) or node.shell.exists(
                    PurePosixPath(f"{nm_connections_path}/cloud-init-eth0.nmconnection")
                )
                assert_that(
                    eth0_exists,
                    "A NetworkManager connection profile for eth0 or cloud-init-eth0"
                    "should exist in /etc/NetworkManager/system-connections",
                ).is_true()
                connections = node.execute("nmcli -g NAME connection show", shell=True)
                assert_that(
                    "eth0" in connections.stdout
                    or "cloud-init eth0" in connections.stdout,
                    "A network connection for eth0 should exist in NetworkManager",
                ).is_true()
                # Check if the connections is active
                eth0_active = node.execute("nmcli -g DEVICE,STATE device", shell=True)
                assert_that(
                    "eth0:connected" in eth0_active.stdout
                    or "cloud-init eth0:connected" in eth0_active.stdout,
                    "The eth0 connection should be active in NetworkManager",
                ).is_true()
            else:
                # For fedora < 39, check if /etc/sysconfig/network file exists
                network_file_path = "/etc/sysconfig/network"
                file_exists = node.shell.exists(PurePosixPath(network_file_path))

                assert_that(
                    file_exists,
                    f"The network file should be present at {network_file_path}",
                ).is_true()
                assert_that(
                    file_exists,
                    f"The network file should be present at {network_file_path}",
                ).is_true()

                network_file = node.tools[Cat].read(network_file_path)
                assert_that(
                    network_file.upper(),
                    f"networking=yes should be present in {network_file_path}",
                ).contains("networking=yes".upper())
                network_file = node.tools[Cat].read(network_file_path)
                assert_that(
                    network_file.upper(),
                    f"networking=yes should be present in {network_file_path}",
                ).contains("networking=yes".upper())
        elif isinstance(node.os, CBLMariner):
            network_file_path = "/etc/systemd/networkd.conf"
            file_exists = node.shell.exists(PurePosixPath(network_file_path))
            assert_that(
                file_exists,
                f"The network file should be present at {network_file_path}",
            ).is_true()
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
    )
    def verify_ifcfg_eth0(self, node: Node) -> None:
        if isinstance(node.os, Fedora):
            # Fedora 39 and later use NetworkManager and do not have ifcfg-eth0
            if node.os.information.version >= "39.0.0":
                # Check if the autoconnect is enabled for eth0
                autoconnect_result = node.execute(
                    "nmcli -g connection.autoconnect connection show"
                    " 'cloud-init eth0'",
                    shell=True,
                )
                assert_that(
                    autoconnect_result.stdout.strip(),
                    "connection.autoconnect should be 'yes' for eth0",
                ).is_equal_to("yes")
                # Check if the connection is set to use DHCP
                dhcp_result = node.execute(
                    "nmcli -g ipv4.method connection show 'cloud-init eth0'", shell=True
                )
                assert_that(
                    dhcp_result.stdout.strip(),
                    "connection.ipv4.method should be 'auto' for eth0",
                ).is_equal_to("auto")
            else:
                # For Fedora versions < 39, check ifcfg-eth0 file
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
    )
    def verify_udev_rules_moved(self, node: Node) -> None:
        if isinstance(node.os, CoreOs):
            udev_file_path_75_rule = (
                "/usr/lib64/udev/rules.d/75-persistent-net-generator.rules"
            )
            udev_file_path_70_rule = "/usr/lib64/udev/rules.d/70-persistent-net.rules"
        elif isinstance(node.os, Fedora) or isinstance(node.os, CBLMariner):
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
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
        elif isinstance(node.os, CBLMariner):
            if node.os.information.version.major == 3:
                dhcp_file_path = "/etc/dhcpcd.conf"
                dhcp_file_content = "option host_name"
            else:
                dhcp_file_path = "/etc/dhcp/dhclient.conf"
                dhcp_file_content = "host-name"
            file_exists = node.shell.exists(PurePosixPath(dhcp_file_path))

            assert_that(
                file_exists,
                f"The dhcp file should be present at {dhcp_file_path}",
            ).is_true()

            dhcp_file = node.tools[Cat].read(dhcp_file_path)
            assert_that(
                dhcp_file,
                f"option host_name should be present in file {dhcp_file_path}",
            ).contains(dhcp_file_content)
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
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
                # Debug: Log actual repository IDs for troubleshooting
                repo_ids = [repo.id for repo in fedora_repositories]
                node.log.info(f"Found repositories: {repo_ids}")

                is_base_repository_present = any(
                    any(
                        pattern in repository.id.lower()
                        for pattern in [
                            "base",
                            "baseos",
                            "rhel",
                            "fedora",
                            "centos",
                            "rhui",
                        ]
                    )
                    for repository in fedora_repositories
                )
                assert_that(
                    is_base_repository_present,
                    f"Base repository should be present. Found repositories: "
                    f"{repo_ids}",
                ).is_true()

                # Validate optional repositories (updates, extras, etc.)
                optional_patterns = ["updates", "extras", "appstream", "optional"]
                optional_repos = [
                    repo.id
                    for repo in fedora_repositories
                    if any(pattern in repo.id.lower() for pattern in optional_patterns)
                ]

                if optional_repos:
                    node.log.info(f"Found optional repositories: {optional_repos}")
                else:
                    node.log.warning(
                        f"No optional repositories found. Available: {repo_ids}"
                    )

            # verify that at least five repositories are present in Redhat
            if type(node.os) is Redhat:
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
        elif type(node.os) is FreeBSD:
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
        This test verifies that Serial Console is properly enabled in the kernel
        command line.

        Steps:
        1. Check the kernel command line by "cat proc/cmdline" for the console device
           1.1. Expected to see 'console=ttyAMA0' for aarch64.
           1.2. Expected to see 'console=ttyS0' for x86_64.
           FreeBSD doesn't have /proc/cmdline, then check the logs.
        2. If there is no expected pattern, get the kernel command line from
           /var/log/messages, /var/log/syslog, dmesg, or journalctl output.
        3. Check expected setting from kernel command line.
            3.1. Expected to see 'console [ttyAMA0] enabled' for aarch64.
            3.2. Expected to see 'console [ttyS0] enabled' for x86_64.
            3.3. Expected to see 'uart0: console (115200,n,8,1)' for FreeBSD.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
    )
    def verify_serial_console_is_enabled(self, node: Node) -> None:
        if isinstance(node.os, CBLMariner):
            if node.os.information.version < "2.0.0":
                raise SkippedException(
                    "CBLMariner 1.0 has a known 'wont fix' issue with this test"
                )
        console_device = {
            CpuArchitecture.X64: "ttyS0",
            CpuArchitecture.ARM64: "ttyAMA0",
        }
        lscpu = node.tools[Lscpu]
        arch = lscpu.get_architecture()
        current_console_device = console_device[arch]

        # Check /proc/cmdline for the console device firstly
        console_enabled_pattern = re.compile(rf"console={current_console_device}")
        cmdline_path = "/proc/cmdline"
        if not isinstance(node.os, FreeBSD):
            cmdline = node.tools[Cat].read(cmdline_path)
            if get_matched_str(cmdline, console_enabled_pattern):
                # Pass the test
                return

        # Check logs for the console device
        console_enabled_pattern = re.compile(
            rf"^(.*console \[{current_console_device}\] enabled.*)$", re.M
        )
        freebsd_pattern = re.compile(r"^(.*uart0: console \(115200,n,8,1\).*)$", re.M)
        patterns = [console_enabled_pattern, freebsd_pattern]
        key_word = "console"
        logs_checked = []
        pattern_found = False
        # Check dmesg output for the patterns if certain OS detected
        if (
            (isinstance(node.os, Ubuntu) and node.os.information.version >= "22.10.0")
            or isinstance(node.os, CBLMariner)
            or isinstance(node.os, FreeBSD)
        ):
            dmesg_tool = node.tools[Dmesg]
            log_output = dmesg_tool.get_output()
            logs_checked.append(f"{dmesg_tool.command}")
            if any(find_patterns_in_lines(log_output, patterns)):
                pattern_found = True
        else:
            # Check each log source, if it is accessible, for the defined patterns
            # If log files can be read, add to list of logs checked
            # If pattern detected, break out of loop and pass test
            log_sources = [
                ("/var/log/syslog", node.tools[Cat]),
                ("/var/log/messages", node.tools[Cat]),
            ]
            for log_file, tool in log_sources:
                if node.shell.exists(node.get_pure_path(log_file)):
                    current_log_output = tool.read_with_filter(
                        log_file, key_word, sudo=True, ignore_error=True
                    )
                    if current_log_output:
                        logs_checked.append(log_file)
                        if any(find_patterns_in_lines(current_log_output, patterns)):
                            pattern_found = True
                            break
            # Check journalctl logs if patterns were not found in other log sources
            journalctl_tool = node.tools[Journalctl]
            if not pattern_found and journalctl_tool.exists:
                current_log_output = journalctl_tool.filter_logs_by_pattern(key_word)
                if current_log_output:
                    logs_checked.append(f"{journalctl_tool.command}")
                    if any(find_patterns_in_lines(current_log_output, patterns)):
                        pattern_found = True
        # Raise an exception if the patterns were not found in any of the checked logs
        if not pattern_found:
            # "Fail to find console enabled line" is the failure triage pattern. Please
            # be careful when changing this string.
            raise LisaException(
                "Fail to find console enabled line "
                f"'console [{current_console_device}] enabled' "
                "or 'uart0: console (115200,n,8,1)' "
                f"from {', '.join(logs_checked)} output. Serial console might not be "
                "properly enabled in this image. Please set the kernel parameter to "
                "enable diagnostic log for troubleshooting an issue related to VM "
                "deployment."
            )

    @TestCaseMetadata(
        description="""
        This test verifies that bash/shell history files of all the bash/shell users
        are either non-existent or empty in the image.

        Steps:
        1. Get all the bash/shell users' main directory from /etc/passwd file.
        2. Using command 'find <user_main_dir> -type f
           (-name ".*sh_history" -o -name ".history")' to get all the history files.
        3. Using command 'ls -lt <history_file>' to check if the history file exists.
        4. If it doesn't exist, the test passes as this indicates the image is properly
           prepared.
        5. If the history file exists, verify it is empty. If not empty, the test
           fails as bash history should be cleared.

        The history file name of the users of "/bin/bash" and "/bin/sh" is
        ".bash_history". The following shell types and their history file names
        are listed below:
        /bin/tcsh: .history
        /bin/csh: .history
        /bin/zsh: .zsh_history
        /bin/ksh: .sh_history
        /bin/dash: .sh_history
        /bin/ash: .sh_history
        /bin/pdksh: .sh_history
        /bin/mksh: .sh_history
        """,
        priority=1,
        use_new_environment=True,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
    )
    def verify_bash_history_is_empty(self, node: Node) -> None:
        remote_node = cast(RemoteNode, node)
        current_user = str(remote_node.connection_info.get("username"))

        # Get the bash and shell users' main directory from /etc/passwd file
        cat = node.tools[Cat]
        passwd_file = "/etc/passwd"
        outputs = cat.read_with_filter(passwd_file, current_user, True, True, True)
        passwd_entries = find_patterns_groups_in_lines(
            outputs, [self._passwd_entry_regex]
        )[0]

        for entry in passwd_entries:
            home_dir = entry["home_dir"]
            shell_type = entry["shell"]

            if shell_type.endswith("bash") or shell_type.endswith("sh"):
                find = node.tools[Find]
                hist_files = find.find_files(
                    start_path=node.get_pure_path(home_dir),
                    name_pattern=[".*sh_history", ".history"],
                    file_type="f",
                    sudo=True,
                    ignore_not_exist=True,
                )
                for hist_file in hist_files:
                    cmd_result = node.execute(
                        f"ls -lt {hist_file}",
                        sudo=True,
                        shell=True,
                    )
                    if 0 != cmd_result.exit_code:
                        continue

                    stat = node.tools[Stat]
                    hist_size = stat.get_total_size(hist_file, sudo=True)
                    # ".*history is not empty, containing .* bytes" is the failure
                    # triage pattern. Please be careful when changing this string.
                    if hist_size:
                        raise LisaException(
                            f"{hist_file} is not empty, containing {hist_size} bytes. "
                            "This could include private information or plain-text "
                            "credentials for other systems. It might be vulnerable and"
                            " exposing sensitive data. Please remove the bash/shell "
                            "history completely."
                        )

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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
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
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
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
        This test validates ClientAliveInterval setting in sshd config is present and
        set to an appropriate value.

        Steps:
        1. Examine the sshd_config file to locate the ClientAliveInterval parameter.
           The default sshd config file is /etc/ssh/sshd_config. If the file is not
           present, use command "find / -name sshd_config" to locate it.
           For Ubuntu, the ClientAliveInterval is set in
           /etc/ssh/sshd_config.d/50-cloudimg-settings.conf
        2. Verify the parameter exists. The test fails if ClientAliveInterval is not
           found.
        3. Confirm the value is within the acceptable range (> 0 and < 236 ). The test
           fails if the value is outside this range. It is recommended to set
           ClientAliveInterval to 180. For Azure certification, values between 30 and
           235 are acceptable depending on application requirements. For more details,
           refer to https://aka.ms/Linux-Testcases.
        """,
        priority=2,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
    )
    def verify_client_active_interval(self, node: Node) -> None:
        ssh = node.tools[Ssh]
        setting = "ClientAliveInterval"
        value = ssh.get(setting)
        if not value:
            raise LisaException(f"not find {setting} in sshd_config")
        if not (int(value) > 0 and int(value) < 236):
            # "The ClientAliveInterval configuration of OpenSSH is set to" is the
            # failure triage pattern. Please be careful when changing this string.
            raise LisaException(
                f"The {setting} configuration of OpenSSH is set to {int(value)} "
                "seconds in this image. A properly configured ClientAliveInterval "
                "helps maintain secure SSH connections. Please set ClientAliveInterval"
                " to 180. On the application need, values between 30 and 235 are "
                "acceptable. For more details, refer to https://aka.ms/Linux-Testcases."
            )

    @TestCaseMetadata(
        description="""
        This test will check no pre added users existing in vm.

        Steps:
        1. Exclude current user from all users' list.
        2. Fail the case if the password of any above user existing.
        3. Fail the case if the key of any user existing.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
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
        if schema.ResourceDiskType.NVME == node.features[Disk].get_resource_disk_type():
            raise SkippedException(
                "Resource disk type is NVMe. NVMe disks are not formatted or mounted by"
                " default and readme file wont be available"
            )

        # verify that resource disk is mounted. raise exception if not
        node.features[Disk].check_resource_disk_mounted()

        resource_disk_mount_point = node.features[Disk].get_resource_disk_mount_point()

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
        node_disc = node.features[Disk]
        if schema.ResourceDiskType.NVME == node.features[Disk].get_resource_disk_type():
            raise SkippedException(
                "Resource disk type is NVMe. NVMe disks are not formatted or mounted by default"  # noqa: E501
            )
        # verify that resource disk is mounted. raise exception if not
        node_disc.check_resource_disk_mounted()
        resource_disk_mount_point = node_disc.get_resource_disk_mount_point()
        disk_info = node.tools[Lsblk].find_disk_by_mountpoint(resource_disk_mount_point)
        for partition in disk_info.partitions:
            # by default, resource disk comes with ntfs type
            # waagent or cloud-init will format it unless there are some commands
            # hung or interrupt
            assert_that(
                partition.fstype,
                "Resource disk file system type should not equal to ntfs",
            ).is_not_equal_to("ntfs")

    @TestCaseMetadata(
        description="""
        This test verifies the version of the Microsoft Azure Linux Agent (waagent).

        Steps:
        1. Retrieve the version of waagent.
        2. Check if the version is lower than the minimum supported version.
           The minimum supported version can be found at:
           https://learn.microsoft.com/en-us/troubleshoot/azure/virtual-machines/
           windows/support-extensions-agent-version
        3. Check if auto update is enabled.
        4. Fail the test if the version is lower than the minimum supported version
           and auto update is not enabled, otherwise pass.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE]),
    )
    def verify_waagent_version(self, node: Node) -> None:
        minimum_version = Version("2.2.53.1")
        waagent = node.tools[Waagent]
        waagent_version = waagent.get_version()
        try:
            current_version = Version(waagent_version)
        except Exception as e:
            raise LisaException(
                f"Failed to parse waagent version '{waagent_version}'. Error: {str(e)}"
            )

        if current_version < minimum_version:
            waagent_auto_update_enabled = waagent.is_autoupdate_enabled()
            if not waagent_auto_update_enabled:
                # "The waagent version.*is lower than the required version.*and auto
                # update is not enabled" is the failure triage pattern. Please be
                # careful when changing this string.
                raise LisaException(
                    f"The waagent version {waagent_version} is lower than the required "
                    f"version {minimum_version} and auto update is not enabled. Please "
                    f"update the waagent to a version >= {minimum_version}. Please "
                    "refer to https://learn.microsoft.com/en-us/azure/virtual-machines/"
                    "extensions/update-linux-agent?tabs=ubuntu for more details to "
                    "update."
                )

    @TestCaseMetadata(
        description="""
        This test verifies the version of Python installed on the system.

        Steps:
        1. Retrieve the Python version.
        2. Check if the version is lower than the minimum supported version.
           The minimum supported version can be found at:
           https://devguide.python.org/versions/
        3. Fail the test if the version is lower than the minimum supported version,
           otherwise pass.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE]),
    )
    def verify_python_version(self, node: Node) -> None:
        minimum_version = Version("3.9")
        next_minimum_version = Version("3.10")
        eof_date = "2025-10-31"
        python_command = ["python3 --version", "python --version"]
        self._verify_version_by_pattern_value(
            node=node,
            commands=python_command,
            version_pattern=self._python_version_pattern,
            minimum_version=minimum_version,
            next_minimum_version=next_minimum_version,
            eof_date=eof_date,
            library_name="Python",
        )

    @TestCaseMetadata(
        description="""
        This test verifies the version of OpenSSL installed on the system. Please
        refer to https://www.openssl-library.org/source/ for supported versions.

        Steps:
        1. Retrieve the OpenSSL version.
        2. Check if the version is lower than the minimum supported version 3.0.0.
        3. If the version is lower than 3.0.0, check if the version is 1.1.1 or 1.0.2.
        4. Fail the test if the version is lower than the minimum supported version
        and not the versions having extended support, otherwise pass.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE]),
    )
    def verify_openssl_version(self, node: Node) -> None:
        minimum_version = Version("3.0.0")
        openssl_command = ["openssl version"]
        extended_support_versions = [Version("1.1.1"), Version("1.0.2")]
        self._verify_version_by_pattern_value(
            node=node,
            commands=openssl_command,
            version_pattern=self._openssl_version_pattern,
            minimum_version=minimum_version,
            extended_support_versions=extended_support_versions,
            library_name="OpenSSL",
        )

    @TestCaseMetadata(
        description="""
        This test verifies that the Linux operating system has a 64-bit architecture.

        Steps:
        1. Retrieve the OS architecture using the Uname tool.
        2. Verify that the architecture is either x86_64/amd64 or aarch64/arm64.
        3. Fail the test if the architecture is not 64-bit.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE]),
    )
    def verify_azure_64bit_os(self, node: Node) -> None:
        uname_tool = node.tools[Uname]
        arch = uname_tool.get_machine_architecture()
        arch_64bit = [CpuArchitecture.X64, CpuArchitecture.ARM64]
        if arch not in arch_64bit:
            # "Architecture .* is not supported" is the failure triage pattern. Please
            # be careful when changing this string.
            raise LisaException(
                f"Architecture '{arch.value}' is not supported. Azure only supports "
                f"64-bit architectures: {', '.join(str(a.value) for a in arch_64bit)}."
            )

    @TestCaseMetadata(
        description="""
        This test verifies the version of the Open Management Infrastructure (OMI)
        installed on the system is not vulnerable to the "OMIGOD" vulnerabilities.

        The "OMIGOD" vulnerabilities (CVE-2021-38647, CVE-2021-38648,
        CVE-2021-38645, CVE-2021-38649) were fixed in OMI version 1.6.8.1.

        OMI github: https://github.com/microsoft/omi

        Steps:
        1. Check if OMI is installed on the system.
           a. If OMI is installed, the version can be got by using
              ""/opt/omi/bin/omiserver --version"" command.
           b. If omiserver command fails, use ""dpkg -l omi | grep omi"" and
              ""rpm -q omi"" to double-check whether the OMI package is installed.
           c. If all the commands fail, it means OMI is not installed.
        2. Verify that the version is 1.6.8.1 or later.
        3. Pass if OMI is not installed or the version is secure.
                """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE]),
    )
    def verify_omi_version(self, node: Node) -> None:
        minimum_secure_version = Version("1.6.8.1")
        # LISA has node.os.package_exists to check if a package is installed. However,
        # since this test case is for Azure image certification, we prefer to use
        # simpler and more generic commands to support a wider range of distributions.
        # OMI supports most modern Linux platforms, including Ubuntu, Debian, CentOS,
        # Oracle, Red Hat, SUSE, Rocky, and Alma. All of these distributions include
        # either the dpkg command (for Debian-based systems like Ubuntu and Debian)
        # or the rpm command (for RPM-based systems like CentOS and SUSE).
        commands = [
            "/opt/omi/bin/omiserver --version",
            "dpkg -l omi | grep omi",
            "rpm -q omi",
        ]

        try:
            self._verify_version_by_pattern_value(
                node=node,
                commands=commands,
                version_pattern=self._omi_version_pattern,
                minimum_version=minimum_secure_version,
                library_name="OMI",
            )
        except LisaException as e:
            if "lower than the required version" in str(e):
                # "Vulnerable OMI version detected" is the failure triage pattern.
                # Please be careful when changing this string.
                raise LisaException(
                    f"Vulnerable OMI version detected. You have an OMI framework "
                    f"version less than {minimum_secure_version}. "
                    f"Please update OMI to the version {minimum_secure_version} or "
                    "later. For more information, please see the OMI update guidance at"
                    f" https://aka.ms/omi-updation. Error details: {e}"
                ) from e
            elif "Failed to retrieve" in str(e):
                node.log.info("OMI is not installed on the system. Pass the case.")
            elif "Failed to parse" in str(e):
                raise LisaException(
                    "OMI is installed but could not determine version. Please verify "
                    "manually that the OMI version is at least "
                    f"{minimum_secure_version} to prevent OMIGOD vulnerabilities. Error"
                    f" details: {e}"
                ) from e

    @TestCaseMetadata(
        description="""
        This test verifies that there is no swap partition or swap file on the OS disk

        Azure's policy 200.3.3 Linux:
        No swap partition on the OS disk. Swap can be requested for creation on the
        local resource disk by the Linux Agent. It is recommended that a single root
        partition is created for the OS disk.

        There should be no Swap Partition or swap file on OS Disk. OS disk has IOPS
        limit. When memory pressure causes swapping, IOPS limit may be reached easily
        and cause VM performance to go down disastrously, because aside from memory
        issues it now also has IO issues.

        Steps:
        1. Use 'cat /proc/swaps' or 'swapon -s' to list all swap devices and swap files
            If it is a swap file, use 'df <swap_file>' to get the partition name.
            Note: For FreeBSD, use 'swapinfo -k'. FreeBSD only supports swap partition.
        2. Use 'lsblk <swap_part> -P -o NAME' to get the real block device name for
           each swap partition. If there is no swap partition, pass the case.
        3. Use 'lsblk' to identify the OS disk and get all its partitions and logical
           devices through matching the mount point '/'.
            Note: For FreeBSD, if there is no lsblk, install it and run the command
        4. Compare if the device name of each swap partition is the same as the device
           name of one OS disk partition or logical device. If yes, fail the case.
        5. Pass the case if no swap partition is found on the OS disk.
        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE]),
    )
    def verify_no_swap_on_osdisk(self, node: Node) -> None:
        swap_tool = node.tools[Swap]
        swap_parts = swap_tool.get_swap_partitions()
        if not swap_parts:
            return
        node.log.info(f"Swap partitions: {swap_parts}")

        # For some images like audiocodes audcovoc acovoce4azure 8.4.591, the swap
        # partition is created on a logical device, such as /dev/dm-5. In this case,
        # we need to get the real block device name.
        lsblk = node.tools[Lsblk]
        os_disk = self._find_os_disk_with_fallbacks(node, lsblk)

        for swap_part in swap_parts:
            block_name = lsblk.get_block_name(swap_part.partition)
            if block_name == "":
                raise LisaException(
                    "Failed to get the device name for swap partition/file "
                    f"'{swap_part.filename}'."
                )
            node.log.info(
                f"Swap partition '{swap_part.filename}' is on device '{block_name}'."
            )
            for part in os_disk.partitions:
                # e.g. 'sda1', 'vg-root', 'vg-home'
                parts = [part] + part.logical_devices
                for p in parts:
                    node.log.info(f"OS disk partition or logical device: {p.name}")
                    if p.name == block_name:
                        # "Swap partition .* is found on OS disk" is a failure triage
                        # pattern. Please be careful when changing this string.
                        raise LisaException(
                            f"Swap partition/file '{swap_part.filename}' is found on "
                            f"OS disk partition or logical device '{p.name}'. There "
                            "should be no Swap Partition on OS Disk. OS disk has IOPS"
                            " limit. When memory pressure causes swapping, IOPS limit"
                            " may be reached easily and cause VM performance to go "
                            "down disastrously, as aside from memory issues it now "
                            "also has IO issues."
                        )

    @TestCaseMetadata(
        description="""
        This test case verifies the enablement of essential kernel modules like wdt and
        cifs.
        """,
        priority=1,
    )
    def verify_essential_kernel_modules(self, node: Node) -> None:
        if not isinstance(node.os, Linux):
            raise SkippedException(
                "This test is only applicable for Linux distributions."
            )
        not_enabled_modules = self._get_not_enabled_modules(node)

        assert_that(not_enabled_modules).described_as(
            "Not enabled essential kernel modules for Hyper-V / Azure platform found."
        ).is_length(0)

    def _verify_version_by_pattern_value(
        self,
        node: Node,
        commands: List[str],
        version_pattern: Pattern[str],
        minimum_version: Version,
        eof_date: Optional[str] = None,
        next_minimum_version: Optional[Version] = None,
        extended_support_versions: Optional[List[Version]] = None,
        library_name: str = "library",
        group_index: int = 1,
    ) -> None:
        """
        Verifies the version of a library or tool against a minimum required version.
        Args:
            node: The node to execute commands on
            commands: List of commands to try to get version information
            version_pattern: Regex pattern to extract version string from command
                    output
            minimum_version: Minimum required version. Please use dots (.) to separate
                    version numbers for proper version comparison, e.g. "1.2.3" or
                    "1.2.3.4"
            next_minimum_version: Optional version that is the next minimum version.
            eof_date: Optional end-of-life date for the minimum_version.
            extended_support_versions: Optional list of versions that are still
                    supported despite being lower than minimum_version
            library_name: Name of the library/tool being checked (for messages)
            group_index: Index of the regex group that contains the version string
        """
        version_output = None

        for command in commands:
            result = node.execute(command, shell=True)
            if result.exit_code == 0:
                version_output = result.stdout.strip()
                break
        if not version_output:
            raise LisaException(
                f"Failed to retrieve {library_name} version. Ensure {library_name} is "
                "installed on the system."
            )

        match = version_pattern.search(version_output)
        if not match:
            raise LisaException(
                f"Failed to parse {library_name} version from output: {version_output}"
            )

        # The reason we don't use 'parse_version' and 'LisaVersionInfo' here is because
        # they don't support the four-part version like "1.2.3.4". Some versions of
        # waagent have this format. So we use 'Version' class from 'packaging'.
        #
        # Version class supports multiple formats but is unable comparing versions with
        # hyphens like "1.2.3-4" and "1.2.3-5". So we replace "-" with "." for proper
        # version comparison.
        #
        # e.g. the version of OMI has the format of "1.9.0-1". Changing it to "1.9.0.1"
        # allows proper comparison with the minimum version.
        #
        # "The .* version .* is lower than the required version .* Please update .* to
        # a version.*" is the failure triage pattern. Please be careful when changing
        # this string.
        current_version = Version(match.group(group_index).replace("-", "."))
        if current_version < minimum_version:
            message = (
                f"The {library_name} version {current_version} is lower than the "
                f"required version {minimum_version}. "
            )
            action_message = (
                f"Please update {library_name} to a version >= {minimum_version}."
            )
            if (
                extended_support_versions
                and current_version not in extended_support_versions
            ):
                message += (
                    f"It is not in the extended support versions "
                    f"{extended_support_versions}. "
                )
                raise LisaException(message + action_message)
            elif not extended_support_versions:
                raise LisaException(message + action_message)
        if next_minimum_version and eof_date and current_version < next_minimum_version:
            raise PassedException(
                f"Support for {library_name} {minimum_version} will end on {eof_date}."
                f" Please consider upgrading to {library_name} {next_minimum_version} "
                "or later to ensure continued support."
            )

    def _get_not_enabled_modules(self, node: Node) -> List[str]:
        """
        Returns the list of essential kernel modules that are neither integrated
        into the kernel nor compiled as loadable modules.
        """
        not_enabled_modules = []

        for module in self._essential_modules_configuration:
            if not node.tools[KernelConfig].is_enabled(
                self._essential_modules_configuration[module]
            ):
                not_enabled_modules.append(module)
        return not_enabled_modules

    def _find_os_disk_with_fallbacks(self, node: Node, lsblk: Lsblk) -> DiskInfo:
        """
        Helper method to find OS disk with multiple fallback strategies.
        Returns the identified OS disk or raises an exception if not found.
        """
        try:
            # First try: Find disk by root mountpoint
            os_disk = lsblk.find_disk_by_mountpoint("/")
            if os_disk:
                return os_disk
        except LisaException as e:
            node.log.debug(f"Could not find disk with root mountpoint /: {str(e)}")
        try:
            # Get all disks for fallback strategies
            disks = lsblk.get_disks(force_run=True)
            # Second try: Find disk marked as OS disk
            for disk in disks:
                if hasattr(disk, "is_os_disk") and disk.is_os_disk:
                    node.log.debug(
                        f"Found OS disk by is_os_disk attribute: {disk.name}"
                    )
                    return disk

            # Third try: Find disk containing boot partition
            for disk in disks:
                if any(
                    p.mountpoint and p.mountpoint.startswith("/boot")
                    for p in disk.partitions
                ):
                    node.log.debug(f"Found OS disk by boot partition: {disk.name}")
                    return disk

            # Use the largest disk as OS disk
            if disks:
                largest_disk = max(disks, key=lambda d: d.size_in_gb)
                node.log.warning(
                    f"Could not definitively identify OS disk, using largest disk: "
                    f"{largest_disk.name}"
                )
                return largest_disk

        except Exception as e:
            raise LisaException(
                f"Failed to get disk information for OS disk identification: {str(e)}"
            ) from e

        # If we reach here, no OS disk could be identified
        raise LisaException(
            "Could not identify OS disk for swap validation. This may be due to "
            "modern filesystem configurations like btrfs subvolumes or no disks found."
        )
