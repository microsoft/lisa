# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time
import sys

from assertpy import assert_that
from typing import Any, Dict, List

from lisa import (
    Node,
    Logger,
    UnsupportedDistroException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)

from lisa.tools import Cat, Echo, Lsmod, Lsblk
from lisa.operating_system import Suse, CoreOs, CentOs, Oracle, Redhat, Ubuntu, Debian
from lisa.tools.mkfs import Mkfsext
from lisa.util import SkippedException


def install_sshpass(node: Node, log: Logger) -> None:
    cmd_result = node.execute("which sshpass", sudo=True)
    if cmd_result.exit_code != 0:
        log.debug("sshpass not installed\n Installing now...")
        exit_code = check_package(["sshpass"], node, log)
        if exit_code != 0:
            install_package(["gcc", "make", "wget"], node, log)
            log.debug("sshpass not installed\n Build it from source code now...")
            package_name = "sshpass-1.06"
            source_url = "https://sourceforge.net/projects/sshpass/files/sshpass/1.06/$package_name.tar.gz"
            node.execute(f"wget {source_url}", sudo=True)
            node.execute(f"tar -xf {package_name}.tar.gz", sudo=True)
            node.execute(f"cd {package_name}", sudo=True)
            node.execute(
                "./configure --prefix=/usr/ && make && make install", sudo=True
            )
            node.execute("cd ..")
        else:
            install_package(["sshpass"], node, log)

        cmd_result = node.execute("which sshpass", sudo=True)
        assert_that(cmd_result.exit_code).described_as(
            "Still no sshpass on the vm. sshpass installation failed."
        ).is_equal_to(0)


def get_available_disks(node: Node) -> List[str]:
    available_disks: List[str] = []
    blocks = node.tools[Lsblk].get_blocks()
    for block in blocks:
        if block.type.upper() == "disk".upper() and "sd" in block.name:
            count = node.execute(f"df | grep -c {block.name}", sudo=True).stdout
            if count == "0":
                available_disks.append(block.name)

    return available_disks


def remove_raid(disks: List[str], node: Node, log: Logger) -> None:
    cmd_result = node.tools[Cat].run("/proc/mdstat").stdout.splitlines()
    for result in cmd_result:
        if "md" in result:
            md_vol = result.split(":")[0].strip()
            log.debug(f"/dev/{md_vol} already exits...removing first")
            node.execute(f"umount /dev/{md_vol}", sudo=True)
            # IMPROVE: CREATE MDADM TOOL
            node.execute(f"mdadm --stop /dev/{md_vol}", sudo=True)
            node.execute(f"mdadm --remove /dev/{md_vol}", sudo=True)
            for disk in disks:
                log.debug(f"formatting disk /dev/{disk}")
                node.tools[Mkfsext].mkfs(f"/dev/{disk}", "mkfs.ext4")


def create_raid0(disks: List[str], device_name: str, node: Node, log: Logger) -> None:
    count = 0
    raid_devices = ""
    for disk in disks:
        log.debug(f"Partition disk /dev/{disk}")
        # TODO: CHECK THIS LINE AND LINE 84
        node.execute(
            f"(echo d; echo n; echo p; echo 1; echo; echo; echo t; echo fd; echo w;) | fdisk /dev/{disk}",
            sudo=True,
        )
        raid_devices = f"{raid_devices} /dev/{disk}1"
        count += 1

    log.debug(f"Creating RAID of {count} devices.")
    time.sleep(1)
    log.debug(
        f"Run cmd: yes | mdadm --create {device_name} --level 0 --raid-devices {count} {raid_devices}"
    )
    cmd_result = node.execute(
        f"yes | mdadm --create {device_name} --level 0 --raid-devices {count} {raid_devices}",
        sudo=True,
    )
    cmd_result.assert_exit_code(message=f"Unable to create raid {device_name}.")

    log.debug(f"Raid {device_name} create successfully.")


def install_kvm_dependendcies(node: Node, log: Logger) -> None:
    distro_version = str(node.os.information.version)

    # if distro_name == "sles" or "sle_hpc":
    if isinstance(node.os, Suse):
        add_sles_network_utilities_repo(distro_version, node, log)
    # if distro_name == "coreos":
    if isinstance(node.os, CoreOs):
        log.debug("Distro not supported. Skip the test.")
        sys.exit()  # TODO: NOT SURE IF USE SYS.EXIT()     THIS MAY ALSO EXIT FURTHER TEST CASES?

    cmd_result = node.execute("lscpu | grep -i vt", sudo=True)
    if cmd_result.exit_code != 0:
        log.debug("CPU type is not VT-x. Skip the test.")
        sys.exit()  # TODO: NOT SURE IF USE SYS.EXIT()     THIS MAY ALSO EXIT FURTHER TEST CASES?

    update_repos(node, log)
    install_package(["qemu-kvm"], node, log)
    exit_code = check_package(["bridge-utils"], node, log)
    if exit_code != 0:
        install_package(["bridge-utils"], node, log)

    if not node.tools[Lsmod].module_exists("kvm_intel"):
        log.debug("Failed to install KVM")
        sys.exit()

    # if distro_name == "centos" or "rhel" or "oracle":
    if (
        isinstance(node.os, CentOs)
        or isinstance(node.os, Redhat)
        or isinstance(node.os, Oracle)
    ):
        log.debug("Install epel repository")
        install_epel(node, log)
        log.debug("Install qemu-system-x86")
        exit_code = check_package(["qemu-system-x86"], node, log)
        if exit_code == 0:
            install_package(["qemu-system-x86"], node, log)
        node.execute(
            "[ -f /usr/libexec/qemu-kvm ] && ln -s /usr/libexec/qemu-kvm /sbin/qemu-system-x86_64",
            shell=True,
            sudo=True,
        )

    cmd_result = node.execute("which qemu-system-x86_64", sudo=True)
    if cmd_result.exit_code != 0:
        log.debug("Cannot find qemu-system-x86_64")
        sys.exit()

    exit_code = check_package(["aria2"], node, log)
    if exit_code == 0:
        install_epel(node, log)
        install_package(["aria2"], node, log)
    else:
        install_package(["make"], node, log)
        node.execute(
            "wget https://github.com/q3aql/aria2-static-builds/releases/download/v1.35.0/aria2-1.35.0-linux-gnu-64bit-build1.tar.bz2",
            sudo=True,
        )
        node.execute("tar -xf aria2-1.35.0-linux-gnu-64bit-build1.tar.bz2", sudo=True)
        node.execute("cd aria2-1.35.0-linux-gnu-64bit-build1/", sudo=True)
        node.execute("make install", sudo=True)
        node.execute("cd ..", sudo=True)

    # ifconfig command is needed
    install_net_tools(node)
    # dnsmasq is needed
    exit_code = check_package(["dnsmasq"], node, log)
    if exit_code == 0:
        install_package(["dnsmasq"], node, log)


def download_image_files(
    destination_image_name: str, source_image_url: str, node: Node, log: Logger
) -> None:
    node.execute("[ ! -d /mnt/resource ] && mkdir /mnt/resource", sudo=True)
    log.debug(f"Downloading {source_image_url}")

    node.execute(f"rm -f /mnt/resource/{destination_image_name}", sudo=True)
    cmd_result = node.execute(
        f"aria2c -d /mnt/resource -o {destination_image_name} -x 10 {source_image_url}",
        sudo=True,
    )
    if cmd_result.exit_code != 0:
        log.debug(f"Download image: {source_image_url} fail.")
        sys.exit()


def prepare_nested_vm(
    disks: List[str],
    user: str,
    password: str,
    port: str,
    nested_cpu_num: int,
    nested_mem_mb: int,
    image_name: str,
    host_fwd_port: int,
    node: Node,
    log: Logger,
) -> None:
    cmd = f"qemu-system-x86_64 -machine pc-i440fx-2.0,accel=kvm -smp {nested_cpu_num} -m {nested_mem_mb} -hda /mnt/resource/{image_name} -display none -device e1000,netdev=user.0 -netdev user,id=user.0,hostfwd=tcp::{host_fwd_port}-:22 -enable-kvm -daemonize"
    for disk in disks:
        cmd = f"${cmd} -drive id=datadisk-${disk},file=/dev/${disk},cache=none,if=none,format=raw,aio=threads -device virtio-scsi-pci -device scsi-hd,drive=datadisk-${disk}"

    start_nested_vm(user, password, port, cmd, node, log)
    enable_root(user, password, port, image_name, node, log)
    reboot_nested_vm(user, password, port, node, log)


def run_fio(
    nested_user_password: str, host_fwd_port: str, node: Node, log: Logger
) -> None:
    remote_copy(
        "localhost",
        "root",
        nested_user_password,
        "put",
        "/root",
        "./utils.sh",
        host_fwd_port,
        node,
        log,
    )
    remote_copy(
        "localhost",
        "root",
        nested_user_password,
        "put",
        "/root",
        "./StartFioTest.sh",
        host_fwd_port,
        node,
        log,
    )
    remote_copy(
        "localhost",
        "root",
        nested_user_password,
        "put",
        "/root",
        "./constants.sh",
        host_fwd_port,
        node,
        log,
    )
    remote_copy(
        "localhost",
        "root",
        nested_user_password,
        "put",
        "/root",
        "./ParseFioTestLogs.sh",
        host_fwd_port,
        node,
        log,
    )
    remote_copy(
        "localhost",
        "root",
        nested_user_password,
        "put",
        "/root",
        "./nested_kvm_perf_fio.sh",
        host_fwd_port,
        node,
        log,
    )
    remote_copy(
        "localhost",
        "root",
        nested_user_password,
        "put",
        "/root",
        "./fio_jason_parser.sh",
        host_fwd_port,
        node,
        log,
    )
    remote_copy(
        "localhost",
        "root",
        nested_user_password,
        "put",
        "/root",
        "./gawk",
        host_fwd_port,
        node,
        log,
    )
    remote_copy(
        "localhost",
        "root",
        nested_user_password,
        "put",
        "/root",
        "./JSON.awk",
        host_fwd_port,
        node,
        log,
    )

    remote_exec(
        "localhost",
        "root",
        nested_user_password,
        "/root/StartFioTest.sh",
        host_fwd_port,
        node,
        log,
    )


def stop_nested_vm(node: Node, log: Logger) -> None:
    log.debug("Stop the nested VMs")
    cmd_result = node.execute("pidof qemu-system-x86_64", sudo=True)
    pid = cmd_result.stdout
    if cmd_result.exit_code == 0:
        node.execute(f"kill -9 {pid}", sudo=True)


def add_sles_network_utilities_repo(
    distro_version: str, node: Node, log: Logger
) -> int:
    # if distro_name == "sles" or "sle_hpc":
    if isinstance(node.os, Suse):
        if distro_version.startswith("11"):
            repo_url = "https://download.opensuse.org/repositories/network:/utilities/SLE_11_SP4/network:utilities.repo"
        elif distro_version.startswith("12"):
            repo_url = "https://download.opensuse.org/repositories/network:utilities/SLE_12_SP3/network:utilities.repo"
        elif distro_version.startswith("15"):
            repo_url = "https://download.opensuse.org/repositories/network:utilities/SLE_15/network:utilities.repo"
        else:
            log.debug(
                f"Unsupported SLES version {distro_version} for add_sles_network_utilities_repo"
            )

        check_install_lock_sles(node, log)

        node.execute(f"zypper addrepo {repo_url}", shell=True, sudo=True)
        node.execute(f"zypper --no-gpg-checks refresh", shell=True, sudo=True)
        return 0
    else:
        log.debug("Unsupported distribution for add_sles_network_utilities_repo")
        return 1


# TODO: COULD THIS BE A DEAD LOCK???
def check_install_lock_sles(node: Node, log: Logger) -> None:
    pid = node.execute("pidof zypper", sudo=True).stdout
    if pid:
        log.debug("Another install is in progress. Waiting 1 seconds.")
        time.sleep(1)
        check_install_lock_sles(node, log)
    else:
        log.debug("No zypper lock present.")


def update_repos(node: Node, log: Logger) -> int:
    # if distro_name == "oracle" or "rhel" or "centos":
    if (
        isinstance(node.os, Oracle)
        or isinstance(node.os, Redhat)
        or isinstance(node.os, CentOs)
    ):
        node.execute("yum clean all", sudo=True)
    # elif distro_name == "ubuntu" or "debian":
    elif isinstance(node.os, Ubuntu) or isinstance(node.os, Debian):
        node.execute("dpkg_configure", sudo=True)
        node.execute("apt-get update", sudo=True)
    # elif distro_name == "suse" or "opensuse" or "sles" or "sle_hpc":
    elif isinstance(node.os, Suse):
        ret = node.execute("zypper refresh", sudo=True).stdout
        azure_kernel = node.execute("uname -r", sudo=True).stdout
        if ("Warning" in ret) and ("default" in azure_kernel):
            log.debug("SAP or BYOS do not have repo configuration. Abort the test")
            return 1
    else:
        raise UnsupportedDistroException(node.os.name, node.os.information.version)
    return 0


def install_package(package_list: List[str], node: Node, log: Logger) -> int:
    for package in package_list:
        # if distro_name == "oracle" or "rhel" or "centos":
        if (
            isinstance(node.os, Oracle)
            or isinstance(node.os, Redhat)
            or isinstance(node.os, CentOs)
        ):
            node.execute(f"yum_install {package}", sudo=True)
        # elif distro_name == "ubuntu" or "debian":
        elif isinstance(node.os, Ubuntu) or isinstance(node.os, Debian):
            node.execute(f"apt_get_install {package}", sudo=True)
        # elif distro_name == "suse" or "opensuse" or "sles" or "sle_hpc":
        elif isinstance(node.os, Suse):
            node.execute(f"zypper_install {package}", sudo=True)
        else:
            raise UnsupportedDistroException(node.os.name, node.os.information.version)
    return 0


def check_package(package_list: List[str], node: Node, log: Logger) -> int:
    for package in package_list:
        # if distro_name == "oracle" or "rhel" or "centos":
        if (
            isinstance(node.os, Oracle)
            or isinstance(node.os, Redhat)
            or isinstance(node.os, CentOs)
        ):
            cmd = f"yum --showduplicates list {package} > /dev/null 2>&1"
        # elif distro_name == "ubuntu" or "debian":
        elif isinstance(node.os, Ubuntu) or isinstance(node.os, Debian):
            cmd = f"apt-cache policy {package} | grep 'Candidate' | grep -v 'none'"
        # elif distro_name == "suse" or "opensuse" or "sles" or "sle_hpc":
        elif isinstance(node.os, Suse):
            cmd = f"zypper search {package}"
        else:
            raise UnsupportedDistroException(node.os.name, node.os.information.version)

        node.execute(f"{cmd}", sudo=True)
    return 0


def install_epel(node: Node, log: Logger) -> None:
    distro_version = node.os.information.version
    # if distro_name == "oracle" or "rhel" or "centos":
    if (
        isinstance(node.os, Oracle)
        or isinstance(node.os, Redhat)
        or isinstance(node.os, CentOs)
    ):
        cmd_result = node.execute("yum -y install epel-release", sudo=True)
        # TODO: CHECK REGX https://github.com/microsoft/lisa/blob/d89ba032af3c05359fd7bb50ff6c41b19aa2f0ee/Testscripts/Linux/utils.sh#L2311
        if cmd_result.exit_code != 0:
            if "6." in distro_version:
                epel_rpm_url = "https://dl.fedoraproject.org/pub/epel/epel-release-latest-6.noarch.rpm"
            elif "7." in distro_version:
                epel_rpm_url = "https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm"
            elif "8.0" in distro_version:
                epel_rpm_url = "https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm"
            else:
                log.debug("Unsupported version to install epel repository")
                return 1
            node.execute(f"sudo rpm -ivh {epel_rpm_url}", sudo=True)
            # TODO: ADD EXIT CODE CHECK HERE
    else:
        raise UnsupportedDistroException(node.os.name, node.os.information.version)


def install_net_tools(node: Node) -> None:
    distro_version = str(node.os.information.version)  # THIS MAY NEED CHANGE
    # if ((distro_name == "sles") and (distro_version.startswith("15"))) or (distro_name == "sle_hpc"):
    if (
        "sles" in node.os.name and distro_version.startswith("15")
    ) or "sle_hpc" in node.os.name:
        node.execute(
            "zypper_install 'net-tools-deprecated' > /dev/null 2>&1", sudo=True
        )
    # if distro_name == "ubuntu":
    if isinstance(node.os, Ubuntu):
        node.execute("apt_get_install 'net-tools' > /dev/null 2>&1", sudo=True)


def start_nested_vm(
    user: str, password: str, port: str, cmd: str, node: Node, log: Logger
) -> None:
    if user == "" or password == "" or port == "" or cmd == "":
        return

    log.debug(f"Run command: {cmd}")
    node.execute(cmd, sudo=True)
    log.debug("Wait for the nested VM to boot up ...")
    time.sleep(10)

    retry_times = 20
    exit_status = 1
    while exit_status != 0 and retry_times > 0:
        retry_times -= 1
        if retry_times == 0:
            log.debug("Timeout to connect to the nested VM")
            return
        else:
            time.sleep(10)
            log.debug(
                f"Try to connect to the nested VM, left retry times: {retry_times}"
            )
            exit_status = remote_exec("localhost", user, password, cmd, port, node, log)

    if exit_status != 0:
        # THIS LOGIC MAY NEED CHANGE
        return exit_status


def enable_root(
    user: str, password: str, port: str, image_name: str, node: Node, log: Logger
) -> None:
    if user == "" or password == "" or port == "":
        return  # CHANGE THIS

    remote_copy(
        "localhost",
        user,
        password,
        "put",
        f"/home/{user}",
        "./utils.sh",
        port,
        node,
        log,
    )
    remote_copy(
        "localhost",
        user,
        password,
        "put",
        f"/home/{user}",
        "./enable_root.sh",
        port,
        node,
        log,
    )

    remote_exec(
        "localhost", user, password, f"chmod a+x /home/{user}/*.sh", port, node, log
    )
    remote_exec(
        "localhost",
        user,
        password,
        f"echo {password} | sudo -S /home/{user}/enable_root.sh -password {password}",
        port,
        node,
        log,
    )

    log.debug(f"Root enabled for VM: {image_name}")


def reboot_nested_vm(
    user: str, password: str, port: str, node: Node, log: Logger
) -> None:
    if user == "" or password == "" or port == "":
        return  # CHANGE THIS

    log.debug("Reboot the nested VM")
    remote_exec(
        "localhost",
        user,
        password,
        f"echo {password} | sudo -S reboot",
        port,
        node,
        log,
    )
    log.debug("Wait for the nested VM to boot up ...")

    time.sleep(30)
    retry_times = 20
    exit_status = 1
    while exit_status != 0 and retry_times > 0:
        retry_times = retry_times - 1
        if retry_times == 0:
            log.debug("Timeout to connect to the nested VM")
            # EXIT?
        else:
            time.sleep(10)
            log.debug(
                f"Try to connect to the nested VM, left retry times: {retry_times}"
            )
            exit_status = remote_exec(
                "localhost", user, password, "hostname", port, node, log
            )

    if exit_status != 0:
        log.debug("Timeout to connect to the nested VM")
        # return 1?


# TODO: SEEMS ALREADY HAVE THIS FUNCTION
def remote_copy(
    host: str,
    user: str,
    passwd: str,
    cmd: str,
    remote_path: str,
    filename: str,
    port: str,
    node: Node,
    log: Logger,
) -> None:
    if host == "" or user == "" or filename == "":
        return  # CHANGE THIS

    if port == "":
        port = "22"

    if cmd == "get":
        source_path = f"{user}@{host}:{remote_path}/{filename}"
        destination_path = "."
    elif cmd == "put":
        source_path = filename
        destination_path = f"{user}@{host}:{remote_path}"

    if passwd == "":
        status = node.execute(
            f"scp -o StrictHostKeyChecking=no -P {port} {source_path} {destination_path} 2>&1",
            sudo=True,
        ).exit_code
    else:
        install_sshpass(node, log)
        status = node.execute(
            f"sshpass -p {passwd} scp -o StrictHostKeyChecking=no -P {port} {source_path} {destination_path} 2>&1"
        ).exit_code

    assert_that(status).described_as(
        f"Failed to {cmd} file {filename} from {source_path} to {destination_path}"
    ).is_equal_to(0)


def remote_exec(
    host: str,
    user: str,
    passwd: str,
    cmd: str,
    port: str,
    node: Node,
    log: Logger,
) -> None:
    install_sshpass(node, log)

    # IMPROVEMENT: CHECK HOST, USER, PASSWD, CMD NOT NULL

    if port == "":
        port = "22"

    exit_code = node.execute(
        f"sshpass -p {passwd} ssh -t -o StrictHostKeyChecking=no -p {port} {user}@{host} {cmd} 2>&1",
        sudo=True,
    ).exit_code

    assert_that(exit_code).described_as(
        f"Failed to remote execute cmd: {cmd} on host {host} through port {port} by user {user}"
    ).is_equal_to(0)

    log.debug(
        f"Executing cmd: {cmd} on host {host} through port {port} by user {user} succeeded."
    )


@TestSuiteMetadata(
    area="nested",
    category="performance",
    description="""
    Nested VM tests. 
    """,
)
class nested(TestSuite):

    nested_user = "nesteduser"
    nested_cpu_num = 8
    nested_mem_mb = 8192
    host_fwd_port = 60022
    nested_vm_user = "root"
    nested_url = "https://eosgnestedstorage.blob.core.windows.net/images/nested-ubuntu-4.15.0-111-generic.qcow2?st=2020-07-17T09%3A06%3A07Z&se=2023-07-18T09%3A06%3A00Z&sp=rl&sv=2018-03-28&sr=c&sig=dhiXUGaNUDcsZEVVCzAzzJJ52m73oaBt2QhOEoDoKX4%3D"

    @TestCaseMetadata(
        description="""
        This test case will measure the storage throughput of guest VM.
        """,
        priority=2,
        requirement=simple_requirement(
            # supported_features = [Nested],
        ),
    )
    def nested_kvm_storage_single_disk(
        self, variables: Dict[str, Any], node: Node, log: Logger
    ) -> None:
        nested_image_url = variables.get("nested_image_url", self.nested_url)
        nested_user = variables.get("nested_user", self.nested_user)
        nested_user_password: str = variables.get("nested_user_password", "")

        # assert passwd not empty
        raise SkippedException("No nested password. Skip this case.")

        self.nested_kvm_storage_test(
            nested_user, nested_user_password, nested_image_url, "No RAID", node, log
        )

    def nested_kvm_storage_test(
        self,
        nested_user: str,
        nested_user_password: str,
        nested_image_url: str,
        raid_option: str,
        node: Node,
        log: Logger,
    ) -> None:

        # Create shell files 1. StartFIOTest 2. ParseFIOTestLogs
        # TODO: SET LOG_DIR
        # log_dir = node.local_log_path()
        # new_shell_script_files(node.local_log_path())

        # Upload these 2 logs
        # We may not need this in v3

        # Execute tests
        # test_execution_console_log = "/home/{user}/TestExecutionConsole.log"
        log.debug("Executing nested kvm storage performance test.")
        # param_dict = nested_vm.get_params() #NEED TO IMPLEMENT THIS FUNCTION

        image_name = "nested.qcow2"

        # Check constants
        assert_that(nested_image_url).described_as(
            "Nested image url should not be null or empty. Please add this param to runbook."
        ).is_true()
        assert_that(nested_user).described_as(
            "Nested user should not be null or empty. Please add this param to runbook."
        ).is_true()
        assert_that(nested_user_password).described_as(
            "Nested user password should not be null or empty. Please add this param to runbook."
        ).is_true()

        # if not variable_exists("LogFolder"):
        # log_folder = "."
        #     log.info("-logFolder is not mentioned. Using .")

        if raid_option == "RAID in L1" or "RAID in L2" or "NO RAID":
            log.debug("RaidOption is available")
        else:
            log.debug(f"RaidOption {raid_option} is invalid")
            sys.exit()

        # IMPROVEMENT: IMPLETEMENT TOUCH CMD IN TOOL
        # node.execute(f"touch {log_folder}/state.txt")
        log_file = "{log_folder}/nested_kvm_storage_perf.log"
        log_file = "./nested_kvm_storage_perf.log"
        node.execute(f"touch {log_file}")

        # Test main body
        available_disks = get_available_disks(node)
        remove_raid(available_disks, node, log)

        if raid_option == "RAID in L1":
            md_volume = "/dev/md0"
            # assert should fail the test case if exit code not 0
            create_raid0(available_disks, md_volume, node, log)
            # if cmd_result.exit_code:   # THIS REQUIRES COMMAND_RESULT CONTAINS EXIT CODE
            #     return
            available_disks = ["md0"]

        for disk in available_disks:
            node.tools[Echo].write_to_file(
                "0", f"/sys/block/{disk}/queue/rq_affinity", sudo=True
            )

        install_kvm_dependendcies(node, log)

        # Download Imange Files (on the vm)
        download_image_files(image_name, nested_image_url, node, log)

        # Prepare nested kvm
        prepare_nested_vm(
            available_disks,
            nested_user,
            nested_user_password,
            str(self.host_fwd_port),
            self.nested_cpu_num,
            self.nested_mem_mb,
            image_name,
            self.host_fwd_port,
            node,
            log,
        )

        run_fio(nested_user_password, str(self.host_fwd_port), node, log)

        # Collect test logs
        # $$$CHECK IF WE STILL NEED THIS$$$

        # Stop nested VM
        stop_nested_vm(node, log)

        # Download fioConsoleLogs and check result state

        # Store test result

    # @TestCaseMetadata()
