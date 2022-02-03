# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re, time

from assertpy import assert_that

from lisa import (
    Node,
    TestSuite,
    TestSuiteMetadata,
    TestCaseMetadata,
    Environment
)
from lisa.base_tools.cat import Cat
from lisa.operating_system import SLES, CentOs, Redhat
from lisa.testsuite import TestCaseMetadata
from lisa.tools.echo import Echo
from lisa.util import SkippedException
from lisa.util.logger import Logger

def check_vm_feature_support_status(min_support_version: str, node: Node) -> bool:
    if not min_support_version:
        return False
    
    kernel_array = node.execute(
        "uname -r | awk -F '[.-]' '{print $1,$2,$3,$4}'"
    ).stdout.split()
    support_kernel_array = re.split('\.|\-', min_support_version)
    for indx in range(4):
        if kernel_array[indx] > support_kernel_array[indx]:
            return True
        elif kernel_array[indx] < support_kernel_array[indx]:
            return False
    return True


@TestSuiteMetadata(
    area="power",
    category="functional",
    description="""
    """
)
class power(TestSuite):
    HB_CUSTOM_KERNEL_URL = "git://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"
    HB_CUSTOM_KERNEL_BRANCH = "stable"
    HB_URL = ""

    @TestCaseMetadata(
        description="""
        This test can be performed in Azure and Hyper-V both. But this script only covers Azure.
        1. Prepare swap space for hibernation
        2. Compile a new kernel (optional)
        3. Update the grub.cfg with resume=UUID=xxxx where is from blkid swap disk
        4. Set RTC to future time or past time
        5. Hibernate the VM
        5. Resume the VM
        6. Read RTC timestamp and compare to the original value
        """,
        priority=3
    )
    def power_clock_sync_hibernate(self, environment: Environment, node: Node, log: Logger) -> None:
        max_kernel_compile_min = 90
        
        # Prepare the swap space in the target VM
        resource_group = 
        vm_name = 
        location = 
        storage_type = "StandardSSD_LRS"
        data_disk_name = vm_name + "_datadisk1"

        is_disk_added = False
        lun = 0
        # TODO: CHECK IS_DISK_ADDED


        test_command = "echo disk > /sys/power/state"
        env_setup_result = node.execute(
            "dmesg | grep -i root= | grep -i resume | wc -l", shell = True, sudo = True
        )
        log.debug("Env Setup Result: " + env_setup_result.stdout)
        if env_setup_result.stdout > "0":
            log.info("Evironment has been set up...")
        else:
            # Configuration for hibernation
            node.execute(
                "umask 022"
            )

            # GetDistro
            distro = ""
            # TODO: ADD THIS SECTION

            # GetGuestGeneration
            exit_code = node.execute(
                "ls /sys/firmware/efi/"
            ).exit_code
            os_generation = 2 if exit_code == 0 else 1
            
            if "redhat" in distro and self.HB_URL == "":
                min_support_kernel = "4.18.0-202"
                check_vm_support_res = check_vm_feature_support_status(min_support_kernel)
                current_kernel_version = node.execute(
                    "uname -r", shell = True, sudo = True
                )
                assert_that(
                    check_vm_support_res,
                    f"Hibernation is supported since kernel-4.18.0-202. Current version: {current_kernel_version}. Skip the test."
                ).is_true()

            if isinstance(node.os, Redhat):
                linux_path = "/mnt/linux"
            else:
                linux_path = "/usr/src/linux"
            
            # prepare swap space
            # Get the latest device name which should be the new attached data disk
            data_dev = node.execute(
                "ls /dev/sd*[a-z] | sort -r | head -1", shell = True, sudo = True
            ).stdout
            keys = ('n', 'p', '1', '2048', '', 't', '82', 'p', 'w')
            for key in keys:
                node.execute(
                    f"echo {key} >> keys.txt"
                )
            cmd_res = node.execute(
                f"cat keys.txt | fdisk {data_dev}"
            )
            log.debug(f"{cmd_res.exit_code}: Executed fdisk command")
            # Need to wait for system complete the swap disk update.
            log.info("Waiting 10 seconds for swap disk update")
            time.sleep(10)
            cmd_res = node.execute(
                "ls /dev/sd*", shell = True, sudo = True
            )
            log.info(f"{cmd_res.exit_code}: List out /dev/sd* - {cmd_res.stdout}")

            # TODO: WHAT IF THE DISK IS MOUNTED OR BEING USED???
            cmd_res = node.execute(
                f"mkswap {data_dev}1", shell=True, sudo=True
            )
            log.info(f"{cmd_res.exit_code}: Set up the swap space")

            cmd_res = node.execute(
                f"swapon {data_dev}1", shell=True, sudo=True
            )
            log.info(f"{cmd_res.exit_code}: Enabled the swap space")
            time.sleep(2)

            cmd_res = node.execute(
                "swapon -s", shell=True, sudo=True
            )
            log.info(f"{cmd_res.exit_code}: Show the swap oninformation - {cmd_res.stdout}")

            cmd_res = node.execute(
                "blkid | grep -i sw | awk '{print $2}' | tr -d \" \" | sed 's/\"//g'", shell = True, sudo = True
            )
            sw_uuid = cmd_res.stdout
            log.info(f"{cmd_res.exit_code}: Found the Swap space disk UUID: {sw_uuid}")
            if not sw_uuid:
                raise SkippedException("Swap space disk UUID is empty. Abort the test.")

            node.execute(
                "chmod 766 /etc/fstab", shell = True, sudo = True
            )

            node.tools[Echo].write_to_file(
                f"{sw_uuid} none swap sw 0 0",
                "/etc/fstab",
                sudo = True,
                append = True
            )

            if isinstance(node.os, Redhat) or isinstance(CentOs):
                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub",
                    "rootdelay=",
                    sudo=True
                )
                if _entry:
                    cmd_res = node.execute(
                        f"sed -i -e 's/rootdelay=300/rootdelay=300 resume={sw_uuid}/g' /etc/default/grub", shell=True, sudo=True
                    )
                    log.info(f"{cmd_res.exit_code}: Updated the /etc/default/grub with resume={sw_uuid}")
                else:
                    node.tools[Echo].write_to_file(
                        f'GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS0 earlyprintk=ttyS0 rootdelay=300 resume={sw_uuid}"',
                        "/etc/default/grub",
                        sudo=True,
                        append=True
                    )
                    log.info(f"Added resume={sw_uuid} in /etc/default/grub file")

                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub",
                    '^GRUB_HIDDEN_TIMEOUT=',
                    sudo=True
                )
                if _entry:
                    cmd_res = node.execute(
                        f'sed -i -e "s/GRUB_HIDDEN_TIMEOUT=*.*/GRUB_HIDDEN_TIMEOUT=30/g" /etc/default/grub', shell=True, sudo=True
                    )
                    log.info(f"{cmd_res.exit_code}: Updated GRUB_HIDDEN_TIMEOUT value with 30")
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
                    cmd_res = node.execute(
                        f'sed -i -e "s/GRUB_TIMEOUT=.*/GRUB_TIMEOUT=30/g" /etc/default/grub', shell=True, sudo=True
                    )
                    log.info(f"{cmd_res.exit_code}: Updated GRUB_TIMEOUT value with 30")
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
                    cmd_res = node.execute(
                        "if [ -f /boot/grub2/grub.cfg]; then echo 'yes'; else echo 'no'; fi", shell=True, sudo=True
                    )
                    if cmd_res.stdout == 'yes':
                        grub_cfg="/boot/grub2/grub.cfg"
                    else:
                        grub_cfg="/boot/grub/grub.cfg"

                cmd_res = node.execute(
                    f"grub2-mkconfig -o {grub_cfg}", shell=True, sudo=True
                )
                log.info(f"{cmd_res.exit_code}: Run grub2-mkconfig -o {grub_cfg}")

                if self.HB_URL == "":
                    cmd_res = node.execute(
                        "uname -r", shell=True, sudo=True
                    )
                    vmlinux_file = f"/boot/vmlinuz-{cmd_res.stdout}"
                else:
                    node.execute(
                        "ls /boot/vmlinuz* > new_state.txt", shell=True, sudo=True
                    )
                    vmlinux_file = node.execute(
                        "diff old_state.txt new_state.txt | tail -n 1 | cut -d ' ' -f2", shell=True, sudo=True
                    ).stdout
                
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
                log.info(f"Original boot parameters {original_args}")
                
                node.execute(
                    f"grubby --args=\"{original_args} resume={sw_uuid}\" --update-kernel={vmlinux_file}", shell=True, sudo=True
                )
                cmd_res = node.execute(
                    f"grubby --set-default={vmlinux_file}", shell=True, sudo=True
                )
                log.info(f"{cmd_res.exit_code}: Set f{vmlinux_file} to the default kernel")

                new_args = node.execute(
                    f"grubby --info=ALL", shell=True, sudo=True
                ).stdout
                log.info(f"Updated grubby output {new_args}")

                grubby_output = node.execute(
                    "grubby --default-kernel", shell=True, sudo=True
                ).stdout
                log.info(f"grubby default-kernel output {grubby_output}")

                # Must run dracut -f, or it cannot recover image in boot after hibernation
                cmd_res = node.execute(
                    "dracut -f", shell=True, sudo=True
                )
                log.info(f"{cmd_res}: Run dracut -f")

            elif isinstance(node.os, SLES):
                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub",
                    'rootdelay=',
                    sudo=True
                )
                if _entry:
                    cmd_res = node.execute(
                        'sed -i -e "s/GRUB_HIDDEN_TIMEOUT=*.*/GRUB_HIDDEN_TIMEOUT=30/g" /etc/default/grub', 
                        shell=True, 
                        sudo=True
                    )
                    log.info(f"{cmd_res.exit}: Updated GRUB_HIDDEN_TIMEOUT value with 30")
                else:
                    node.tools[Echo].write_to_file(
                        'GRUB_HIDDEN_TIMEOUT=30',
                        '/etc/default/grub',
                        sudo=True,
                        append=True
                    )
                    log.info("Added GRUB_HIDDEN_TIMEOUT=30 in /etc/default/grub file")
                
                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub",
                    '^GRUB_TIMEOUT=',
                    sudo=True
                )
                if _entry:
                    cmd_res = node.execute(
                        'sed -i -e "s/GRUB_TIMEOUT=.*/GRUB_TIMEOUT=30/g" /etc/default/grub', shell=True, sudo=True
                    )
                    log.info(f"{cmd_res.exit_code}: Updated GRUB_TIMEOUT value with 30")
                else:
                    node.tools[Echo].write_to_file(
                        "GRUB_TIMEOUT=30",
                        "/etc/default/grub",
                        sudo=True,
                        append=True
                    )
                    log.info("Added GRUB_TIMEOUT=30 in /etc/default/grub file")
                
                # TODO: EXTRACT DUPLICATED CODES
                if os_generation == 2:
                    grub_cfg = "/boot/efi/EFI/redhat/grub.cfg"
                else:
                    cmd_res = node.execute(
                        "if [ -f /boot/grub2/grub.cfg]; then echo 'yes'; else echo 'no'; fi", shell=True, sudo=True
                    )
                    if cmd_res.stdout == 'yes':
                        grub_cfg="/boot/grub2/grub.cfg"
                    else:
                        grub_cfg="/boot/grub/grub.cfg"
                cmd_res = node.execute(
                    f"grub2-mkconfig -o {grub_cfg}", shell=True, sudo=True
                )
                log.info(f"{cmd_res.exit_code}: Run grub2-mkconfig -o {grub_cfg}")

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
                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub.d/50-cloudimg-settings.cfg",
                    'rootdelay=',
                    sudo=True
                )
                # Change boot kernel parameters in 50-cloudimg-settings.cfg
		        # resume= defines the disk partition address where the hibernation image goes in and out.
		        # For stress test purpose, we need to increase the log file size bigger like 200MB.
                if _entry:
                    cmd_res = node.execute(
                        f'sed -i -e "s/rootdelay=300/rootdelay=300 log_buf_len=200M resume={sw_uuid}/g" /etc/default/grub.d/50-cloudimg-settings.cfg',
                        shell=True,
                        sudo=True
                    )
                    log.info(f"{cmd_res.exit_code}: Updated the 50-cloudimg-settings.cfg with resume={sw_uuid}")
                else:
                    _entry = node.tools[Cat].read_with_filter(
                        "/etc/default/grub.d/50-cloudimg-settings.cfg",
                        '^GRUB_CMDLINE_LINUX_DEFAULT',
                        sudo=True
                    )
                    if _entry:
                        node.execute(
                            f"sed -i '/^GRUB_CMDLINE_LINUX_DEFAULT=/ s/\"$/ rootdelay=300 log_buf_len=200M resume='{sw_uuid}'\"/'  /etc/default/grub.d/50-cloudimg-settings.cfg", 
                            shell=True, 
                            sudo=True
                        )
                    else:
                        node.tools[Echo].write_to_file(
                            f'GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS0 earlyprintk=ttyS0 rootdelay=300 log_buf_len=200M resume={sw_uuid}"',
                            "/etc/default/grub.d/50-cloudimg-settings.cfg",
                            sudo=True,
                            append=True
                        )

                    log.info(f"Added resume={sw_uuid} in 50-cloudimg-settings.cfg file")
                
                # This is the case about GRUB_HIDDEN_TIMEOUT
                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub.d/50-cloudimg-settings.cfg",
                    '^GRUB_HIDDEN_TIMEOUT=',
                    sudo=True
                )
                if _entry:
                    cmd_res = node.execute(
                        'sed -i -e "s/GRUB_HIDDEN_TIMEOUT=*.*/GRUB_HIDDEN_TIMEOUT=30/g" /etc/default/grub.d/50-cloudimg-settings.cfg',
                        shell=True,
                        sudo=True
                    )
                    log.info(f"{cmd_res.exit_code}: Updated GRUB_HIDDEN_TIMEOUT value with 30")
                else:
                    node.tools[Echo].write_to_file(
                        "GRUB_HIDDEN_TIMEOUT=30",
                        '/etc/default/grub.d/50-cloudimg-settings.cfg',
                        sudo=True,
                        append=True
                    )
                    log.info("Added GRUB_HIDDEN_TIMEOUT=30 in 50-cloudimg-settings.cfg file")
                
                # This is the case about GRUB_TIMEOUT
                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub.d/50-cloudimg-settings.cfg",
                    '^GRUB_TIMEOUT=',
                    sudo=True
                )
                if _entry:
                    cmd_res = node.execute(
                        'sed -i -e "s/GRUB_TIMEOUT=.*/GRUB_TIMEOUT=30/g" /etc/default/grub.d/50-cloudimg-settings.cfg',
                        shell=True,
                        sudo=True
                    )
                    log.info(f"{cmd_res.exit_code}: Updated GRUB_TIMEOUT value with 30")
                else:
                    node.tools[Echo].write_to_file(
                        "'GRUB_TIMEOUT=30'",
                        "/etc/default/grub.d/50-cloudimg-settings.cfg",
                        sudo=True,
                        append=True
                    )
                    log.info("Added GRUB_TIMEOUT=30 in 50-cloudimg-settings.cfg file")
                
                # This is the case about GRUB_FORCE_PARTUUID
                _entry = node.tools[Cat].read_with_filter(
                    "/etc/default/grub.d/40-force-partuuid.cfg",
                    '^GRUB_FORCE_PARTUUID=',
                    sudo=True
                )
                if _entry:
                    cmd_res = node.execute(
                        'sed -i -e "s/GRUB_FORCE_PARTUUID=.*/#GRUB_FORCE_PARTUUID=/g" /etc/default/grub.d/40-force-partuuid.cfg',
                        shell=True,
                        sudo=True
                    )
                    log.info(f"{cmd_res.exit_code}: Commented out GRUB_FORCE_PARTUUID line")

                node.execute(
                    "update-grub2", sudo=True
                )
                log.info("Ran update-grub2")

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

        
