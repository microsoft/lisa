# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
import time
from datetime import date
from typing import List

from assertpy import assert_that

from lisa import Environment, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata, schema
from lisa.base_tools import Cat, Uname
from lisa.features import Disk, StartStop
from lisa.operating_system import SLES, Redhat, Ubuntu
from lisa.testsuite import TestCaseMetadata
from lisa.tools import Dmesg, Echo, Fdisk, Sed, Swap, SwapOn
from lisa.tools.blkid import Blkid
from lisa.util import LisaException, SkippedException, find_patterns_in_lines
from lisa.util.logger import Logger
from lisa.util.shell import wait_tcp_port_ready


def check_vm_feature_support_status(min_support_version: str, node: Node) -> bool:
    if not min_support_version:
        raise SkippedException("No min support kernel version provided!")
    
    kernel_version = node.tools[Uname].get_linux_information().kernel_version
    if kernel_version > min_support_version:
        return True
    elif kernel_version < min_support_version:
        return False
    
    return True

def get_year(node: Node) -> str:
    hard_ware_clock = node.execute(
        "hwclock",
        shell=True,
        sudo=True
    ).stdout
    if isinstance(node.os, Ubuntu) and node.os.information.version == '16.4.0':
        year = re.split('\s+', hard_ware_clock)[3]
    else:
        # hwclock format: '2022-02-04 11:38:06.949136+0000'
        year = re.split('\s+', hard_ware_clock)[0]
    return year

def check_is_file(node: Node, path: str) -> bool:
    cmd_res = node.execute(
        f"if [ -f {path}]; then echo 'yes'; else echo 'no'; fi", 
        shell=True, 
        sudo=True
    )
    if cmd_res.stdout == 'yes':
        return True
    else:
        return False

def found_sys_log(node: Node, message: str) -> bool:
    if check_is_file(node, '/var/log/messages'):
        _ret = node.tools[Cat].read_with_filter(
            "/var/log/messages",
            message,
            sudo=True
        )
    elif check_is_file(node, '/var/log/syslog'):
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


@TestSuiteMetadata(
    area="power",
    category="functional",
    description="""
    """
)
class power(TestSuite):
    REBOOT_TIME_OUT = 300

    @TestCaseMetadata(
        description="""
        This test can be performed in Azure and Hyper-V both. But this script only covers Azure.
        1. Prepare swap space for hibernation
        2. Update the grub.cfg with resume=UUID=xxxx where is from blkid swap disk
        3. Set RTC to future time or past time
        4. Hibernate the VM
        5. Resume the VM
        6. Read RTC timestamp and compare to the original value
        """,
        priority=3
    )
    def power_clock_sync_hibernate(self, environment: Environment, node: Node, log: Logger) -> None:     
        # Prepare the swap space in the target VM
        resource_group = environment.get_information()['resource_group_name']
        # data_disk_name = node.name + "_datadisk1"
        data_disk_name = 'lisa_data_disk_0'
        disks = node.features[Disk]
        # data_disks = disks.get_raw_data_disks()
        pattern = re.compile(r"/dev/disk/azure/scsi[1-9]/lun[0-9][0-9]?", re.M)
        cmd_result = node.execute(
            "ls -d /dev/disk/azure/scsi*/*", shell=True, sudo=True
        )
        matched = find_patterns_in_lines(cmd_result.stdout, [pattern])
        matched_disk_array = set(matched[0])
        disk_array: List[str] = [""] * len(matched_disk_array)
        for disk in matched_disk_array:
            # readlink -f /dev/disk/azure/scsi1/lun0
            # /dev/sdc
            cmd_result = self._node.execute(
                f"readlink -f {disk}", shell=True, sudo=True
            )
            disk_array[int(disk.split("/")[-1].replace("lun", ""))] = cmd_result.stdout
        if disk_array and disk_array[0] == data_disk_name:
        # if data_disks and data_disks[0] == data_disk_name:
            log.info("Data disk has already been added")
        else:
            disks.add_data_disk(1, schema.DiskType.StandardSSDLRS, 1024)

        dmesg = node.tools[Dmesg]
        root_msg = re.findall('root=', dmesg.get_output(force_run=True), re.IGNORECASE)
        env_setup_result = [res for res in root_msg if 'resume' in res]

        log.debug("Env Setup Result: " + ''.join(env_setup_result))
        if env_setup_result:
            log.info("Evironment has been set up...")
        else:
            # Configuration for hibernation
            node.execute(
                "umask 022"
            )

            # GetGuestGeneration
            exit_code = node.execute(
                "ls /sys/firmware/efi/"
            ).exit_code
            os_generation = 2 if exit_code == 0 else 1
            
            if isinstance(node.os, Redhat):
                min_support_kernel = "4.18.0-202"
                check_vm_support_res = check_vm_feature_support_status(min_support_kernel)
                current_kernel_version = node.execute(
                    "uname -r", shell = True, sudo = True
                )
                assert_that(
                    check_vm_support_res,
                    f"Hibernation is supported since kernel-4.18.0-202. Current version: {current_kernel_version}. Skip the test."
                ).is_true()
            
            # prepare swap space
            # Get the latest device name which should be the new attached data disk
            # TODO: USE FDISK TOOL
            data_dev = node.execute(
                "ls /dev/sd*[a-z] | sort -r | head -1", shell = True, sudo = True
            ).stdout
            fdisk = node.tools[Fdisk]
            # 82  Linux swap / So
            fdisk.change_partition_type(data_dev, '82')
            log.debug("Executed fdisk command to change partition type to swap.")
        
            cmd_res = node.execute(
                "ls /dev/sd*", shell = True, sudo = True
            )

            # TODO: THERE COULD BE A CASE THE PARTITION IS MOUNTED
            # NEED TO UMOUNT AND MKSWAP BEFORE SWAPON
            swap_partition = data_dev + '1'
            node.tools[Swap].set_up_swap_space(swap_partition)

            node.tools[SwapOn].run(swap_partition, shell=True, sudo=True)

            cmd_res = node.tools[SwapOn].run("-s", shell=True, sudo=True)

            # Seems there may not be 'sw' in blkid, so use partition name to check
            partition_info = node.tools[Blkid].get_partition_info_by_name(swap_partition)
            sw_uuid = partition_info.uuid
            log.debug(f"Found the Swap space disk UUID: {sw_uuid}")
            if not sw_uuid:
                raise SkippedException("Swap space disk UUID is empty. Abort the test.")

            # Config the swap partition in /etc/fstab
            # So it will be mounted automatically during reboot
            node.execute(
                "chmod 766 /etc/fstab", shell = True, sudo = True
            )
            node.tools[Echo].write_to_file(
                f"{sw_uuid} none swap sw 0 0",
                "/etc/fstab",
                sudo = True,
                append = True
            )

            if isinstance(node.os, Redhat):
                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub",
                    "rootdelay=",
                    sudo=True
                )
                if _entry:
                    node.tools[Sed].substitute(
                        'rootdelay=300', 
                        f'rootdelay=300 resume={sw_uuid}', 
                        '/etc/default/grub', 
                        sudo=True)
                    log.debug(f"Updated the /etc/default/grub with resume={sw_uuid}")
                else:
                    node.tools[Echo].write_to_file(
                        f'GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS0 earlyprintk=ttyS0 rootdelay=300 resume={sw_uuid}"',
                        "/etc/default/grub",
                        sudo=True,
                        append=True
                    )
                    log.debug(f"Added resume={sw_uuid} in /etc/default/grub file")

                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub",
                    '^GRUB_HIDDEN_TIMEOUT=',
                    sudo=True
                )
                if _entry:
                    node.tools[Sed].substitute(
                        'GRUB_HIDDEN_TIMEOUT=*.*',
                        'GRUB_HIDDEN_TIMEOUT=30',
                        '/etc/default/grub',
                        sudo=True
                    )
                    log.debug(f"Updated GRUB_HIDDEN_TIMEOUT value with 30.")
                else:
                    node.tools[Echo].write_to_file(
                        'GRUB_HIDDEN_TIMEOUT=30',
                        '/etc/default/grub',
                        sudo=True,
                        append=True
                    )
                
                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub",
                    '^GRUB_TIMEOUT=',
                    sudo=True
                )
                if _entry:
                    node.tools[Sed].substitute(
                        'GRUB_TIMEOUT=.*',
                        'GRUB_TIMEOUT=30',
                        '/etc/default/grub',
                        sudo=True
                    )
                    log.debug(f"Updated GRUB_TIMEOUT value with 30.")
                else:
                    node.tools[Echo].write_to_file(
                        'GRUB_TIMEOUT=30',
                        '/etc/default/grub',
                        sudo=True,
                        append=True
                    )
                
                if os_generation == 2:
                    grub_cfg = '/boot/efi/EFI/redhat/grub.cfg'
                else:
                    if check_is_file(node, '/boot/grub2/grub.cfg'):
                        grub_cfg="/boot/grub2/grub.cfg"
                    else:
                        grub_cfg="/boot/grub/grub.cfg"

                cmd_res = node.execute(
                    f"grub2-mkconfig -o {grub_cfg}", shell=True, sudo=True
                )

                cmd_res = node.execute(
                    "uname -r", shell=True, sudo=True
                )
                vmlinux_file = f"/boot/vmlinuz-{cmd_res.stdout}"
                
                cmd_res = node.execute(
                    f'if [ -f "{vmlinux_file}"]; then echo "yes"; else echo "no"; fi', shell=True, sudo=True
                )
                assert_that(cmd_res.stdout).described_as(
                    f"Can not set new vmlinuz file in grubby command. Expected new vmlinuz file, but found {vmlinux_file}"
                    "Aborting."
                ).is_equal_to_ignoring_case("yes")
                
                original_args = node.execute(
                    "grubby --info=0 | grep -i args | cut -d '\"' -f 2", shell=True, sudo=True
                ).stdout
                log.debug(f"Original boot parameters {original_args}")
                
                node.execute(
                    f"grubby --args=\"{original_args} resume={sw_uuid}\" --update-kernel={vmlinux_file}", shell=True, sudo=True
                )
                cmd_res = node.execute(
                    f"grubby --set-default={vmlinux_file}", shell=True, sudo=True
                )
                log.debug(f"Set f{vmlinux_file} to the default kernel")

                new_args = node.execute(
                    f"grubby --info=ALL", shell=True, sudo=True
                ).stdout
                log.debug(f"Updated grubby output {new_args}")

                grubby_output = node.execute(
                    "grubby --default-kernel", shell=True, sudo=True
                ).stdout
                log.debug(f"grubby default-kernel output {grubby_output}")

                # Must run dracut -f, or it cannot recover image in boot after hibernation
                cmd_res = node.execute(
                    "dracut -f", shell=True, sudo=True
                )

            elif isinstance(node.os, SLES):
                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub",
                    'rootdelay=',
                    sudo=True
                )
                if _entry:
                    node.tools[Sed].substitute(
                        'GRUB_HIDDEN_TIMEOUT=*.*',
                        'GRUB_HIDDEN_TIMEOUT=30',
                        '/etc/default/grub',
                        sudo=True
                    )
                    log.debug(f"Updated GRUB_HIDDEN_TIMEOUT value with 30")
                else:
                    node.tools[Echo].write_to_file(
                        'GRUB_HIDDEN_TIMEOUT=30',
                        '/etc/default/grub',
                        sudo=True,
                        append=True
                    )
                    log.debug("Added GRUB_HIDDEN_TIMEOUT=30 in /etc/default/grub file")
                
                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub",
                    '^GRUB_TIMEOUT=',
                    sudo=True
                )
                if _entry:
                    node.tools[Sed].substitute(
                        'GRUB_TIMEOUT=.*',
                        'GRUB_TIMEOUT=30',
                        '/etc/default/grub',
                        sudo=True
                    )
                    log.debug(f"Updated GRUB_TIMEOUT value with 30")
                else:
                    node.tools[Echo].write_to_file(
                        "GRUB_TIMEOUT=30",
                        "/etc/default/grub",
                        sudo=True,
                        append=True
                    )
                    log.debug("Added GRUB_TIMEOUT=30 in /etc/default/grub file")
                
                # TODO: EXTRACT DUPLICATED CODES
                if os_generation == 2:
                    grub_cfg = "/boot/efi/EFI/redhat/grub.cfg"
                else:
                    if check_is_file(node, '/boot/grub2/grub.cfg'):
                        grub_cfg="/boot/grub2/grub.cfg"
                    else:
                        grub_cfg="/boot/grub/grub.cfg"
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

            else:
                # Canonical Ubuntu
                try:
                    _entry = node.tools[Cat].read_with_filter(
                        "/etc/default/grub.d/50-cloudimg-settings.cfg",
                        'rootdelay=',
                        sudo=True
                    )
                # Change boot kernel parameters in 50-cloudimg-settings.cfg
		        # resume= defines the disk partition address where the hibernation image goes in and out.
		        # For stress test purpose, we need to increase the log file size bigger like 200MB.
                # if _entry:
                    node.tools[Sed].substitute(
                        'rootdelay=300',
                        f'rootdelay=300 log_buf_len=200M resume={sw_uuid}',
                        '/etc/default/grub.d/50-cloudimg-settings.cfg',
                        sudo=True
                    )
                    log.debug(f"Updated the 50-cloudimg-settings.cfg with resume={sw_uuid}")
                except AssertionError:
                    # If Cat.read_with_filter found no result
                    _entry = node.tools[Cat].read_with_filter(
                        "/etc/default/grub.d/50-cloudimg-settings.cfg",
                        '^GRUB_CMDLINE_LINUX_DEFAULT',
                        sudo=True
                    )
                    if _entry:
                        node.tools[Sed].substitute(
                            '"$',
                            f' rootdelay=300 log_buf_len=200M resume={sw_uuid}"',
                            '/etc/default/grub.d/50-cloudimg-settings.cfg',
                            '^GRUB_CMDLINE_LINUX_DEFAULT=',
                            sudo=True
                        )
                    else:
                        node.tools[Echo].write_to_file(
                            f'GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS0 earlyprintk=ttyS0 rootdelay=300 log_buf_len=200M resume={sw_uuid}"',
                            "/etc/default/grub.d/50-cloudimg-settings.cfg",
                            sudo=True,
                            append=True
                        )
                    log.debug(f"Added resume={sw_uuid} in 50-cloudimg-settings.cfg file")
                
                # This is the case about GRUB_HIDDEN_TIMEOUT
                try:
                    _entry = node.tools[Cat].read_with_filter(
                        "/etc/default/grub.d/50-cloudimg-settings.cfg",
                        '^GRUB_HIDDEN_TIMEOUT=',
                        sudo=True
                    )
                    # if _entry:
                    node.tools[Sed].substitute(
                        'GRUB_HIDDEN_TIMEOUT=*.*',
                        'GRUB_HIDDEN_TIMEOUT=30',
                        '/etc/default/grub.d/50-cloudimg-settings.cfg',
                        sudo=True
                    )
                    log.debug("Updated GRUB_HIDDEN_TIMEOUT value with 30")
                except AssertionError:
                    node.tools[Echo].write_to_file(
                        "GRUB_HIDDEN_TIMEOUT=30",
                        '/etc/default/grub.d/50-cloudimg-settings.cfg',
                        sudo=True,
                        append=True
                    )
                    log.debug("Added GRUB_HIDDEN_TIMEOUT=30 in 50-cloudimg-settings.cfg file")
                
                # This is the case about GRUB_TIMEOUT
                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub.d/50-cloudimg-settings.cfg",
                    '^GRUB_TIMEOUT=',
                    sudo=True
                )
                if _entry:
                    node.tools[Sed].substitute(
                        'GRUB_TIMEOUT=.*',
                        'GRUB_TIMEOUT=30',
                        '/etc/default/grub.d/50-cloudimg-settings.cfg',
                        sudo=True
                    )
                    log.debug("Updated GRUB_TIMEOUT value with 30.")
                else:
                    node.tools[Echo].write_to_file(
                        "'GRUB_TIMEOUT=30'",
                        "/etc/default/grub.d/50-cloudimg-settings.cfg",
                        sudo=True,
                        append=True
                    )
                    log.debug("Added GRUB_TIMEOUT=30 in 50-cloudimg-settings.cfg file.")
                
                # This is the case about GRUB_FORCE_PARTUUID
                try:
                    _entry = node.tools[Cat].read_with_filter(
                        "/etc/default/grub.d/40-force-partuuid.cfg",
                        '^GRUB_FORCE_PARTUUID=',
                        sudo=True
                    )
                # if _entry:
                    node.tools[Sed].substitute(
                        'GRUB_FORCE_PARTUUID=.*',
                        '#GRUB_FORCE_PARTUUID=',
                        '/etc/default/grub.d/40-force-partuuid.cfg',
                        sudo=True
                    )
                    log.debug("Commented out GRUB_FORCE_PARTUUID line.")
                except AssertionError:
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
                    f"{_entry1} - Missing config update in 50-cloudimg-settings.cfg file"
                ).is_true()

                _entry2 = node.tools[Cat].read_with_filter(
                    "/etc/default/grub.d/50-cloudimg-settings.cfg",
                    '^GRUB_HIDDEN_TIMEOUT=30',
                    sudo=True
                )
                assert_that(_entry2).described_as(
                    f"{_entry2} - Missing config update in 50-cloudimg-settings.cfg file"
                ).is_true()

                _entry3 = node.tools[Cat].read_with_filter(
                    "/etc/default/grub.d/50-cloudimg-settings.cfg",
                    '^GRUB_TIMEOUT=30',
                    sudo=True
                )
                assert_that(_entry3).described_as(
                    f"{_entry3} - Missing config update in 50-cloudimg-settings.cfg file"
                ).is_true()

                log.info("Successfully updated 50-cloudimg-settings.cfg file with all three entries.\n"
                "Setup Hibernate Kernel Completed.")

        #################################
        #      SETUP HIBERNATE DONE     #
        #################################

        # Reboot VM to apply swap setup changes
        log.info("Rebooting VM")
        start_stop = node.features[StartStop]
        start_stop.restart()
        # Check VM status, confirm it's running
        is_ready, tcp_error_code = wait_tcp_port_ready(
            node.public_address,
            node.public_port,
            log=log,
            timeout=self.REBOOT_TIME_OUT,
        )
        if not is_ready:
            raise LisaException("Can not identify VM status before hibernate.")


        cmd_res = node.execute(
            "hwclock --set --date='2033-07-01 12:00:00'",
            shell=True,
            sudo=True
        )
        
        before_time_stamp = get_year(node)
        log.debug(f"Got before time stamp: {before_time_stamp}")

        try:
            node.tools[Echo].write_to_file(
                "disk",
                "/sys/power/state",
                sudo=True
            )
        except AssertionError:
            log.debug("Expected non-zero exit code of echo disk > /sys/power/state, continue...")

        log.info("Sent hibernate command to the VM and continue checking its status in every 15 seconds until 10 minutes timeout.")

        # Verify the VM status
		# Can not find if VM hibernation completion or not as soon as it disconnects the network. Assume it is in timeout.
        timeout = 600
        start_time = time.time()
        while (time.time() - start_time < timeout):
            time.sleep(15)
            is_ready, tcp_error_code = wait_tcp_port_ready(
                node.public_address,
                node.public_port,
                log=log,
                timeout=self.REBOOT_TIME_OUT,
            )
            if not is_ready:
                break
            else:
                log.debug("VM is not stopped. Waiting for 15s.......")
        
        is_ready, tcp_error_code = wait_tcp_port_ready(
            node.public_address,
            node.public_port,
            log=log,
            timeout=30,
        )
        if not is_ready:
            log.info("Verified successfully VM status is stopped after hibernation command sent")
        else:
            raise LisaException("Failed to change VM status to be stopped after hibernation command sent")
        
        # Resume the VM
        try:
            start_stop.start()
        except:
            log.debug("Something wrong when starting vm. Continue test, will recheck vm status before other steps...")
        # start_stop.restart()
        log.debug(f"Waked up the VM in Resource Group {resource_group} and continue checking its status in every 15 seconds until 15 minutes timeout")

        # Wait for VM resume for 15 min-timeout
        timeout = 900
        complete = False
        start_time = time.time()
        while (time.time() - start_time < timeout):
            time.sleep(15)
            cmd_res = node.execute(
                "date > /dev/null; echo $?"
            )
            if cmd_res.stdout:
                cmd_res = node.execute(
                    "dmesg | grep -i 'hibernation exit'",
                    shell=True,
                    sudo=True
                )
                res = re.search(r'(.*?hibernation exit.*?)', dmesg.get_output(force_run=True), re.re.IGNORECASE)
                if res.group(1) != "hibernation exit":
                    log.error("VM resumed successfully but could not determine hibernation completion")
                else:
                    log.info("VM resumed successfully")
                    complete = True
            else:
                log.info("VM is still resuming!")   

        if complete:
            log.info("VM resume completed")
        else:
            raise LisaException("VM resume did not finish.")
        
        # Note that if you use NTP, the hardware clock is automatically synchronized to the system clock every 11 minutes,
		# and this command is useful only at boot time to get a reasonable initial system time.
        log.info("Waiting for RTC re-sync in 12 minutes")
        time.sleep(720)

        log.info("Capturing the RTC timestmap")
        after_time_stamp = get_year(node)
        is_ready, tcp_error_code = wait_tcp_port_ready(
            node.public_address,
            node.public_port,
            log=log,
            timeout=self.REBOOT_TIME_OUT,
        )
        if is_ready == 'VM running':
            log.info("Verified successfully VM status is running after resuming")
        else:
            raise LisaException("Can not identify VM status after resuming")
        
        # Verify the kernel panic, call trace or fatal error
        res = re.findall('(call trace|fatal error)', dmesg.get_output(force_run=True), re.IGNORECASE)
        if len(res):
            log.error("Found Call Trace or Fatal error in dmesg")
            # This is linux-next, so there is high chance to get call trace from other issue. For now, only print the error.
        else:
            log.info("Not found Call Trace and Fatal error in dmesg")
        
        log.info("Waiting 60-second for logging sync")
        time.sleep(60)

        # Check the system log if it shows Power Management log
        log.debug("Searching the keyword: 'hibernation entry' and 'hibernation exit'")
        if found_sys_log(node, 'hibernation entry') and found_sys_log(node, 'hibernation exit'):
            log.debug("Successfully found Power Management log in dmesg")
        else:
            raise LisaException("Could not find Power Management log in dmesg")
        
        if before_time_stamp != after_time_stamp:
            log.info("Successfully verified the before_time_stamp was different from after_time_stamp")
        else:
            raise LisaException(f"Did not find time synced. {before_time_stamp} to {after_time_stamp}")

        controller_time_stamp = date.today().year
        if after_time_stamp == controller_time_stamp:
            log.info("Successfully verified the system date changed back to correct date")
        else:
            raise LisaException(f"Expected VM time changed back to the correct one after sync-up, but found {after_time_stamp}")
