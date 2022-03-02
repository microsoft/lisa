# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import time
from datetime import date

from assertpy import assert_that

from lisa import (
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
)
from lisa.base_tools import Cat, Uname
from lisa.features import StartStop
from lisa.operating_system import Redhat, Suse, Ubuntu
from lisa.sut_orchestrator.azure.tools import VmGeneration
from lisa.testsuite import simple_requirement
from lisa.tools import Blkid, Dmesg, Echo, Fdisk, Hwclock, Sed, Swap, SwapOn
from lisa.util import (
    LisaException,
    SkippedException,
    find_patterns_in_lines,
)
from lisa.util.logger import Logger
from lisa.util.shell import wait_tcp_port_ready


def _check_vm_feature_support_status(min_support_version: str, node: Node) -> bool:
    if not min_support_version:
        raise LisaException("No min support kernel version provided!")

    kernel_version = node.tools[Uname].get_linux_information().kernel_version
    if kernel_version > min_support_version:
        return True
    elif kernel_version < min_support_version:
        return False

    return True


def _found_sys_log(node: Node, message: str) -> bool:
    if node.shell.exists('/var/log/messages'):
        _ret = node.tools[Cat].read_with_filter(
            "/var/log/messages",
            message,
            sudo=True
        )
    elif node.shell.exists('/var/log/syslog'):
        _ret = node.tools[Cat].read_with_filter(
            "/var/log/syslog",
            message,
            sudo=True
        )
    else:
        _ret = node.execute(
            f'dmesg | grep -i {message}',
            shell=True,
            sudo=True
        ).stdout
    if message in _ret:
        return True
    else:
        return False


def _is_vm_running(node: Node, log: Logger, timeout: int = 300) -> bool:
    is_ready, tcp_error_code = wait_tcp_port_ready(
        node.public_address,
        node.public_port,
        log=log,
        timeout=timeout,
    )
    return is_ready


def _backup_file(
    node: Node,
    log: Logger,
    file_path: str,
    files_and_backups: dict
) -> None:
    file_name = file_path.split('/')[-1]
    backup_file_path = file_path.replace(file_name, 'hibernate_' + file_name + '.bak')
    node.execute(
        f'cp {file_path} {backup_file_path}',
        shell=True,
        sudo=True
    )
    files_and_backups[file_path] = backup_file_path
    log.debug(f"Backup {file_path} to {backup_file_path}")


def _recover_files(node: Node, log: Logger, files_and_backups: dict) -> None:
    for file in files_and_backups:
        log.debug(f'Recovering file: {file} from backup: {files_and_backups[file]}')
        node.execute(
            f"mv {files_and_backups[file]} {file}",
            shell=True,
            sudo=True
        )


@TestSuiteMetadata(
    area="power",
    category="functional",
    description="""
    """
)
class Power(TestSuite):
    REBOOT_TIME_OUT = 300
    files_and_backups = {}

    @TestCaseMetadata(
        description="""
        This test can be performed in Azure and Hyper-V both.
        But this script only covers Azure.
        1. Prepare swap space for hibernation
        2. Update the grub.cfg with resume=UUID=xxxx where is from blkid swap disk
        3. Set RTC to future time or past time
        4. Hibernate the VM
        5. Resume the VM
        6. Read RTC timestamp and compare to the original value
        """,
        priority=4,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.StandardSSDLRS,
                data_disk_iops=search_space.IntRange(min=2000),
                data_disk_count=search_space.IntRange(min=1),
            ),
        )
    )
    def clock_sync_hibernate(
        self,
        node: Node,
        log: Logger
    ) -> None:
        try:
            self._test_clock_sync(node, log)
        finally:
            # Recover modified files
            _recover_files(node, log, self.files_and_backups)

    def _test_clock_sync(
        self,
        node: Node,
        log: Logger
    ) -> None:
        self._test_preparation(node, log)

        hwclock = node.tools[Hwclock]
        hwclock.set_hardware_time('2033-07-01 12:00:00')
        before_time_stamp = hwclock.get_hardware_time_year()
        log.debug(f"Got before time stamp: {before_time_stamp}")

        self._send_hibernation_and_check_vm_status(node, log)

        # Note that if you use NTP, the hardware clock is
        # automatically synchronized to the system clock every 11 minutes,
        # and this command is useful only at boot time
        # to get a reasonable initial system time.
        log.info("Checking RTC re-sync, timeout in 12 minutes...")
        controller_time_stamp = str(date.today().year)
        time_synced = time_correct = False
        timeout = 720
        start_time = time.time()
        while (time.time() - start_time < timeout):
            after_time_stamp = hwclock.get_hardware_time_year()
            log.debug(f"Got after_time_stamp: {after_time_stamp}")
            if not time_synced and before_time_stamp != after_time_stamp:
                time_synced = True
                log.info(
                    "Successfully verified "
                    "the before_time_stamp was different from after_time_stamp")
            if not time_correct and after_time_stamp == controller_time_stamp:
                time_correct = True
                log.info(
                    "Successfully verified the system date correct")
            if time_synced and time_correct:
                break
            time.sleep(5)

        if not time_synced:
            raise LisaException(
                f"Did not find time synced. {before_time_stamp} to {after_time_stamp}")
        if not time_correct:
            raise LisaException(
                "Expected VM time changed back to the correct one after sync-up,"
                f" but found {after_time_stamp}")

        self._check_call_trace_and_log_sync(node, log)

    def _test_preparation(self, node: Node, log: Logger) -> None:
        if isinstance(node.os, Redhat):
            min_support_kernel = "4.18.0-202"
            check_vm_support_res = _check_vm_feature_support_status(
                min_support_kernel)
            current_kernel_version = node.execute(
                "uname -r", shell=True, sudo=True
            )
            if not check_vm_support_res:
                raise SkippedException(
                    "Hibernation is supported since kernel-4.18.0-202. "
                    f"Current version: {current_kernel_version}.")

        self.files_and_backups = {}
        dmesg = node.tools[Dmesg]
        dmesg_output = dmesg.get_output(force_run=True)
        search_pattern = re.compile(r'root=.*resume', flags=re.M | re.IGNORECASE)
        env_setup_result = re.findall(search_pattern, dmesg_output)
        log.debug("Env Setup Result: " + ''.join(env_setup_result))
        if env_setup_result:
            log.info("Evironment has been set up...")
        else:
            self._setup_hibernate(node, log)

        # Reboot VM to apply swap setup changes
        start_stop = node.features[StartStop]
        start_stop.restart()
        # Check VM status, confirm it's running
        if not _is_vm_running(node, log, self.REBOOT_TIME_OUT):
            raise LisaException("Can not identify VM status before hibernate.")

    def _setup_hibernate(
        self,
        node: Node,
        log: Logger
    ) -> None:
        # Configuration for hibernation
        node.execute(
            "umask 022"
        )

        # GetGuestGeneration
        os_generation = node.tools[VmGeneration].get_generation()

        # prepare swap space
        # TODO: USE FDISK TOOL
        data_dev = node.execute(
            "ls /dev/sd*[a-z] | sort -r | head -1", shell=True, sudo=True
        ).stdout
        data_dev = node.execute(
            'readlink -f /dev/disk/azure/scsi1/lun0',
            shell=True,
            sudo=True
        ).stdout
        assert_that(data_dev).described_as(
            "Did not find data disk. "
            "Something wrong during environment deployment... "
        ).is_true()
        fdisk = node.tools[Fdisk]
        # 82  Linux swap / So
        fdisk.change_partition_type(data_dev, '82')
        log.debug("Executed fdisk command to change partition type to swap.")

        cmd_res = node.execute(
            "ls /dev/sd*", shell=True, sudo=True
        )

        swap_partition = data_dev + '1'
        node.tools[Swap].create_swap(swap_partition)

        node.tools[SwapOn].run(swap_partition, shell=True, sudo=True)
        node.tools[SwapOn].run("-s", shell=True, sudo=True)

        # Seems there may not be 'sw' in blkid, so use partition name to check
        partition_info = node.tools[Blkid].get_partition_info_by_name(
            swap_partition)
        sw_uuid = "UUID=" + partition_info.uuid
        log.debug(f"Found the Swap space disk UUID: {sw_uuid}")
        if not sw_uuid:
            raise LisaException("Swap space disk UUID is empty. Abort the test.")

        # Config the swap partition in /etc/fstab
        # So it will be mounted automatically during reboot
        fstab_file = '/etc/fstab'
        node.execute(
            f"chmod 766 {fstab_file}", shell=True, sudo=True
        )
        _backup_file(node, log, fstab_file, self.files_and_backups)
        node.tools[Echo].write_to_file(
            f"{sw_uuid} none swap sw 0 0",
            fstab_file,
            sudo=True,
            append=True
        )

        if isinstance(node.os, Redhat):
            default_grub_file = "/etc/default/grub"
            file_output_default_grub = node.tools[Cat].read(
                default_grub_file,
                sudo=True
            )
            _backup_file(node, log, default_grub_file, self.files_and_backups)

            node.tools[Sed].substitute_or_append(
                file_output=file_output_default_grub,
                regexp='rootdelay=300',
                replacement=f'rootdelay=300 resume={sw_uuid}',
                text='GRUB_CMDLINE_LINUX_DEFAULT="'
                'console=tty1 console=ttyS0 earlyprintk=ttyS0 rootdelay=300'
                f' resume={sw_uuid}"',
                file=default_grub_file,
                sudo=True
            )
            log.debug(f"Added/Updated the /etc/default/grub with resume={sw_uuid}")

            node.tools[Sed].substitute_or_append(
                file_output=file_output_default_grub,
                regexp='GRUB_HIDDEN_TIMEOUT=*.*',
                replacement='GRUB_HIDDEN_TIMEOUT=30',
                text='GRUB_HIDDEN_TIMEOUT=30',
                file=default_grub_file,
                sudo=True
            )

            node.tools[Sed].substitute_or_append(
                file_output=file_output_default_grub,
                regexp='GRUB_TIMEOUT=.*',
                replacement='GRUB_TIMEOUT=30',
                text='GRUB_TIMEOUT=30',
                file=default_grub_file,
                sudo=True
            )

            if os_generation == '2':
                grub_cfg = '/boot/efi/EFI/redhat/grub.cfg'
            else:
                if node.shell.exists('/boot/grub2/grub.cfg'):
                    grub_cfg = "/boot/grub2/grub.cfg"
                else:
                    grub_cfg = "/boot/grub/grub.cfg"

            cmd_res = node.execute(
                f"grub2-mkconfig -o {grub_cfg}", shell=True, sudo=True
            )

            cmd_res = node.execute(
                "uname -r", shell=True, sudo=True
            )
            vmlinux_file = f"/boot/vmlinuz-{cmd_res.stdout}"
            assert_that(node.shell.exists(vmlinux_file)).described_as(
                "Can not set new vmlinuz file in grubby command. "
                f"Expected new vmlinuz file, but found {vmlinux_file}"
                "Aborting."
            ).is_true()

            original_args = node.execute(
                "grubby --info=0 | grep -i args | cut -d '\"' -f 2",
                shell=True,
                sudo=True
            ).stdout
            log.debug(f"Original boot parameters {original_args}")
            node.execute(
                f"grubby --args=\"{original_args} resume={sw_uuid}\" "
                f"--update-kernel={vmlinux_file}",
                shell=True,
                sudo=True
            )
            cmd_res = node.execute(
                f"grubby --set-default={vmlinux_file}", shell=True, sudo=True
            )
            log.debug(f"Set f{vmlinux_file} to the default kernel")

            new_args = node.execute(
                "grubby --info=ALL", shell=True, sudo=True
            ).stdout
            log.debug(f"Updated grubby output {new_args}")

            grubby_output = node.execute(
                "grubby --default-kernel", shell=True, sudo=True
            ).stdout
            log.debug(f"grubby default-kernel output {grubby_output}")

            # Must run dracut -f
            # or it cannot recover image in boot after hibernation
            cmd_res = node.execute(
                "dracut -f", shell=True, sudo=True
            )

        elif isinstance(node.os, Suse):
            default_grub_file = "/etc/default/grub"
            file_output_default_grub = node.tools[Cat].read(
                default_grub_file,
                sudo=True
            )
            _backup_file(node, log, default_grub_file, self.files_and_backups)

            node.tools[Sed].substitute_or_append(
                file_output=file_output_default_grub,
                regexp='rootdelay=300',
                replacement=f'rootdelay=300 log_buf_len=200M resume={sw_uuid}',
                text='GRUB_CMDLINE_LINUX_DEFAULT="'
                'console=tty1 console=ttyS0 earlyprintk=ttyS0 '
                f'rootdelay=300 log_buf_len=200M resume={sw_uuid}"',
                file=default_grub_file,
                sudo=True
            )
            log.debug(f"Added/Updated resume={sw_uuid} in /etc/default/grub file")

            node.tools[Sed].substitute_or_append(
                file_output=file_output_default_grub,
                regexp='GRUB_HIDDEN_TIMEOUT=*.*',
                replacement='GRUB_HIDDEN_TIMEOUT=30',
                text='GRUB_HIDDEN_TIMEOUT=30',
                file=default_grub_file,
                sudo=True
            )
            log.debug(
                "Added/Updated GRUB_HIDDEN_TIMEOUT=30 in /etc/default/grub file")

            node.tools[Sed].substitute_or_append(
                file_output=default_grub_file,
                regexp='GRUB_TIMEOUT=.*',
                replacement='GRUB_TIMEOUT=30',
                text='GRUB_TIMEOUT=30',
                file=default_grub_file,
                sudo=True
            )
            log.debug("Updated/Added GRUB_TIMEOUT=30 in /etc/default/grub file")

            if os_generation == '2':
                grub_cfg = "/boot/efi/EFI/redhat/grub.cfg"
            else:
                if node.shell.exists('/boot/grub2/grub.cfg'):
                    grub_cfg = "/boot/grub2/grub.cfg"
                else:
                    grub_cfg = "/boot/grub/grub.cfg"
            cmd_res = node.execute(
                f"grub2-mkconfig -o {grub_cfg}", shell=True, sudo=True
            )

            _entry1 = node.tools[Cat].read_with_filter(
                "/etc/default/grub",
                'resume=',
                sudo=True
            )
            assert_that(_entry1).described_as(
                f"{_entry1} - Missing config update in grub file"
            ).is_true()

            _entry2 = node.tools[Cat].read_with_filter(
                "/etc/default/grub",
                '^GRUB_HIDDEN_TIMEOUT=30',
                sudo=True
            )
            assert_that(_entry2).described_as(
                f"{_entry2} - Missing config update in grub file"
            ).is_true()

            _entry3 = node.tools[Cat].read_with_filter(
                "/etc/default/grub",
                '^GRUB_TIMEOUT=30',
                sudo=True
            )
            assert_that(_entry3).described_as(
                f"{_entry3} - Missing config update in grub file"
            ).is_true()

        elif isinstance(node.os, Ubuntu):
            # Canonical Ubuntu
            # Change boot kernel parameters in 50-cloudimg-settings.cfg
            # resume= defines the disk partition address
            # where the hibernation image goes in and out.
            # For stress test purpose,
            # we need to increase the log file size bigger
            # like 200MB.
            _50_cloudimg_settings_file = \
                "/etc/default/grub.d/50-cloudimg-settings.cfg"
            file_output_50_cloudimg_settings = node.tools[Cat].read(
                _50_cloudimg_settings_file,
                sudo=True
            )
            _backup_file(node, log, _50_cloudimg_settings_file, self.files_and_backups)

            if 'rootdelay=' in file_output_50_cloudimg_settings:
                node.tools[Sed].substitute(
                    'rootdelay=300',
                    f'rootdelay=300 log_buf_len=200M resume={sw_uuid}',
                    _50_cloudimg_settings_file,
                    sudo=True
                )
                log.debug(
                    f"Updated the 50-cloudimg-settings.cfg with resume={sw_uuid}")
            else:
                search_pattern = re.compile(r"^GRUB_CMDLINE_LINUX_DEFAULT", re.M)
                node.tools[Sed].substitute_or_append(
                    is_substitute=find_patterns_in_lines(
                        file_output_50_cloudimg_settings,
                        [search_pattern])[0],
                    regexp='"$',
                    replacement=' rootdelay=300 log_buf_len=200M '
                    f'resume={sw_uuid}"',
                    text='GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS0 '
                    'earlyprintk=ttyS0 rootdelay=300 '
                    f'log_buf_len=200M resume={sw_uuid}"',
                    file=_50_cloudimg_settings_file,
                    match_lines='^GRUB_CMDLINE_LINUX_DEFAULT=',
                    sudo=True
                )
                log.debug(
                    f"Added resume={sw_uuid} in 50-cloudimg-settings.cfg file")

            # This is the case about GRUB_HIDDEN_TIMEOUT
            node.tools[Sed].substitute_or_append(
                file_output=file_output_50_cloudimg_settings,
                regexp='GRUB_HIDDEN_TIMEOUT=*.*',
                replacement='GRUB_HIDDEN_TIMEOUT=30',
                text="GRUB_HIDDEN_TIMEOUT=30",
                file=_50_cloudimg_settings_file,
                sudo=True,
            )
            log.debug(
                "Updated/Added GRUB_HIDDEN_TIMEOUT value with 30 "
                "in 50-cloudimg-settings.cfg file.")

            # This is the case about GRUB_TIMEOUT
            node.tools[Sed].substitute_or_append(
                file_output_50_cloudimg_settings,
                regexp='GRUB_TIMEOUT=.*',
                replacement='GRUB_TIMEOUT=30',
                text='GRUB_TIMEOUT=30',
                file=_50_cloudimg_settings_file,
                sudo=True
            )
            log.debug(
                "Updated/Added GRUB_TIMEOUT=30 in 50-cloudimg-settings.cfg file.")

            # This is the case about GRUB_FORCE_PARTUUID
            _40_force_partuuid_file = "/etc/default/grub.d/40-force-partuuid.cfg"
            if node.shell.exists(_40_force_partuuid_file):
                output_40_force_partuuid = node.tools[Cat].read(
                    _40_force_partuuid_file,
                    sudo=True
                )
                _backup_file(
                    node,
                    log,
                    _40_force_partuuid_file,
                    self.files_and_backups)

                search_pattern = re.compile(r'^GRUB_FORCE_PARTUUID=', re.M)
                if find_patterns_in_lines(
                        output_40_force_partuuid, search_pattern)[0]:
                    node.tools[Sed].substitute(
                        'GRUB_FORCE_PARTUUID=.*',
                        '#GRUB_FORCE_PARTUUID=',
                        _40_force_partuuid_file,
                        sudo=True
                    )
                    log.debug(
                        "Commented out GRUB_FORCE_PARTUUID line in "
                        f"{_40_force_partuuid_file}.")
                else:
                    log.debug("No force part uuid to be replaced, continue test...")

            node.execute(
                "update-grub2", sudo=True
            )

            _entry1 = node.tools[Cat].read_with_filter(
                "/etc/default/grub.d/50-cloudimg-settings.cfg",
                'resume=',
                sudo=True
            )
            assert_that(_entry1).described_as(
                f"{_entry1} - Missing config update"
                " in 50-cloudimg-settings.cfg file"
            ).is_true()

            _entry2 = node.tools[Cat].read_with_filter(
                "/etc/default/grub.d/50-cloudimg-settings.cfg",
                '^GRUB_HIDDEN_TIMEOUT=30',
                sudo=True
            )
            assert_that(_entry2).described_as(
                f"{_entry2} - Missing config update "
                "in 50-cloudimg-settings.cfg file"
            ).is_true()

            _entry3 = node.tools[Cat].read_with_filter(
                "/etc/default/grub.d/50-cloudimg-settings.cfg",
                '^GRUB_TIMEOUT=30',
                sudo=True
            )
            assert_that(_entry3).described_as(
                f"{_entry3} - Missing config update "
                "in 50-cloudimg-settings.cfg file"
            ).is_true()

            log.info(
                "Successfully updated 50-cloudimg-settings.cfg file"
                " with all three entries.\n"
                "Setup Hibernate Kernel Completed.")

        else:
            raise LisaException("Unsupported distro.")

    def _send_hibernation_and_check_vm_status(
        self,
        node: Node,
        log: Logger
    ) -> None:
        node.execute_async(
            'echo disk > /sys/power/state',
            shell=True,
            sudo=True
        )
        log.info(
            "Sent hibernate command to the VM and continue checking its status"
            " until 10 minutes timeout.")

        # Verify the VM status
        # Can not find if VM hibernation completion
        # or not as soon as it disconnects the network. Assume it is in timeout.
        timeout = 600
        start_time = time.time()
        vm_stopped = False
        while (time.time() - start_time < timeout):
            time.sleep(2)
            if not _is_vm_running(node, log, self.REBOOT_TIME_OUT):
                vm_stopped = True
                break
            else:
                log.debug("VM is not stopped. Waiting for 15s.......")

        if vm_stopped:
            log.info(
                "Verified VM status is stopped after hibernation command sent")
        else:
            raise LisaException(
                "Failed to change VM status to be stopped"
                " after hibernation command sent")

        # Resume the VM
        start_stop = node.features[StartStop]
        start_stop.start()
        log.info(
            "Waked up the VM and continue checking its status"
            " in every 15 seconds until 15 minutes timeout")

        # Wait for VM resume for 15 min-timeout
        timeout = 900
        vm_resumed = False
        start_time = time.time()
        while (time.time() - start_time < timeout):
            time.sleep(15)
            if _is_vm_running(node, log, 30):
                # TODO: THIS DMESG CHECKING APPROACH MAY NEED IMPROVE
                res = re.search(r'(.*?hibernation exit.*?)',
                                node.tools[Dmesg].get_output(force_run=True),
                                re.IGNORECASE)
                if not res or "hibernation exit" not in res.group(1):
                    log.error(
                        "VM resumed successfully "
                        "but could not determine hibernation completion")
                else:
                    log.info("VM resumed successfully")
                    vm_resumed = True
                    break
            else:
                log.debug("VM is still resuming!")

        if vm_resumed:
            log.info("VM resume completed.")
        else:
            raise LisaException("VM resume did not finish.")

    def _check_call_trace_and_log_sync(self, node: Node, log: Logger) -> None:
        # Verify the kernel panic, call trace or fatal error
        res = re.findall('(call trace|fatal error)',
                         node.tools[Dmesg].get_output(force_run=True), re.IGNORECASE)
        if res:
            log.error("Found Call Trace or Fatal error in dmesg")
            # This is linux-next,
            # so there is high chance to get call trace from other issue.
            # For now, only print the error.
        else:
            log.info("Not found Call Trace and Fatal error in dmesg")

        log.info("Checking logging sync. Timeout in 60s.")
        find_hibernation_dmesg = False
        timeout = 60
        start_time = time.time()
        while (time.time() - start_time < timeout):
            time.sleep(2)
            # Check the system log if it shows Power Management log
            log.debug(
                "Searching the keyword: 'hibernation entry' and 'hibernation exit'")
            if _found_sys_log(node, 'hibernation entry') and \
                    _found_sys_log(node, 'hibernation exit'):
                find_hibernation_dmesg = True
                log.debug("Successfully found Power Management log in dmesg")

        if not find_hibernation_dmesg:
            raise LisaException("Could not find Power Management log in dmesg")
