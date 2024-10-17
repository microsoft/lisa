# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import math

from assertpy import assert_that

from lisa import (
    Environment,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Nvme, NvmeSettings, Sriov
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.tools import Cat, Df, Echo, Fdisk, Lscpu, Lspci, Mkfs, Mount, Nvmecli
from lisa.tools.fdisk import FileSystem
from lisa.util.constants import DEVICE_TYPE_NVME, DEVICE_TYPE_SRIOV


def _format_mount_disk(
    node: Node,
    namespace: str,
    file_system: FileSystem,
    use_partitions: bool = True,
) -> None:
    mount_point = namespace.rpartition("/")[-1]
    fdisk = node.tools[Fdisk]
    mount = node.tools[Mount]
    mount.umount(namespace, mount_point)
    fdisk.delete_partitions(namespace)
    if use_partitions:
        fdisk.make_partition(namespace, file_system)
        mount.mount(f"{namespace}p1", mount_point)
    else:
        format_disk = node.tools[Mkfs]
        format_disk.mkfs(f"{namespace}", file_system)
        mount.mount(f"{namespace}", mount_point)


@TestSuiteMetadata(
    area="nvme",
    category="functional",
    name="Nvme",
    description="""
    This test suite is to validate NVMe disk on Linux VM.
    """,
)
class NvmeTestSuite(TestSuite):
    TIME_OUT = 300

    @TestCaseMetadata(
        description="""
        This test case will
        1. Get nvme devices and nvme namespaces from /dev/ folder,
         compare the count of nvme namespaces and nvme devices.

        2. Compare the count of nvme namespaces return from `nvme list`
          and list nvme namespaces under /dev/.

        3. Compare nvme devices count return from `lspci`
          and list nvme devices under /dev/.
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def verify_nvme_basic(self, environment: Environment, node: Node) -> None:
        self._verify_nvme_disk(environment, node)

    @TestCaseMetadata(
        description="""
        This case runs nvme_basic_validation test against 10 NVMe disks.
        The test steps are same as `nvme_basic_validation`.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[NvmeSettings(disk_count=10)],
        ),
    )
    def verify_nvme_max_disk(self, environment: Environment, node: Node) -> None:
        self._verify_nvme_disk(environment, node)

    @TestCaseMetadata(
        description="""
        This test case will do following things for each NVMe device.
        1. Get the number of errors from nvme-cli before operations.
        2. Create a partition, filesystem and mount it.
        3. Create a txt file on the partition, content is 'TestContent'.
        4. Create a file 'data' on the partition, get the md5sum value.
        5. Umount and remount the partition.
        6. Get the txt file content, compare the value.
        7. Compare the number of errors from nvme-cli after operations.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def verify_nvme_function(self, node: Node) -> None:
        self._verify_nvme_function(node)

    @TestCaseMetadata(
        description="""
        The test case is same as `verify_nvme_function`, except it uses
        unpartitioned disks.
        This test case will do following things for each NVMe device.
        1. Get the number of errors from nvme-cli before operations.
        2. Create filesystem and mount it.
        3. Create a txt file on the partition, content is 'TestContent'.
        4. Create a file 'data' on the partition, get the md5sum value.
        5. Umount and remount the partition.
        6. Get the txt file content, compare the value.
        7. Compare the number of errors from nvme-cli after operations.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def verify_nvme_function_unpartitioned(self, node: Node) -> None:
        self._verify_nvme_function(node, use_partitions=False)

    @TestCaseMetadata(
        description="""
        This test case will
        1. Create a partition, xfs filesystem and mount it.
        2. Check how much the mountpoint is trimmed before operations.
        3. Create a 300 gb file 'data' using dd command in the partition.
        4. Check how much the mountpoint is trimmed after creating the file.
        5. Delete the file 'data'.
        6. Check how much the mountpoint is trimmed after deleting the file,
         and compare the final fstrim status with initial fstrim status.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def verify_nvme_fstrim(self, node: Node) -> None:
        nvme = node.features[Nvme]
        nvme_namespaces = nvme.get_raw_nvme_disks()
        mount = node.tools[Mount]
        df = node.tools[Df]

        for namespace in nvme_namespaces:
            mount_point = namespace.rpartition("/")[-1]
            mount.umount(disk_name=namespace, point=mount_point)
            # 1. Create a partition, xfs filesystem and mount it.
            _format_mount_disk(node, namespace, FileSystem.xfs)

            # 2. Check how much the mountpoint is trimmed before operations.
            initial_fstrim = node.execute(
                f"fstrim {mount_point} -v", shell=True, sudo=True
            )
            initial_fstrim.assert_exit_code(
                message=f"{mount_point} not exist or fstrim command enounter "
                "unexpected error."
            )
            # 80% of free space is used to create a file.
            free_space_gb = int(df.get_filesystem_available_space(mount_point) * 0.8)
            # limit the free space to 300GB to avoid long time operation.
            free_space_gb = min(free_space_gb, 300)
            # 3. Create a file 'data' using dd command in the partition.
            cmd_result = node.execute(
                f"dd if=/dev/zero of={mount_point}/data bs=1G count={free_space_gb}",
                shell=True,
                sudo=True,
                timeout=1200,
            )
            cmd_result.assert_exit_code(
                message=f"{mount_point}/data is not created successfully, "
                "please check the disk space."
            )

            # 4. Check how much the mountpoint is trimmed after creating the file.
            intermediate_fstrim = node.execute(
                f"fstrim {mount_point} -v", shell=True, sudo=True
            )
            intermediate_fstrim.assert_exit_code(
                message=f"{mount_point} not exist or fstrim command enounter "
                "unexpected error."
            )

            # 5. Delete the file 'data'.
            node.execute(f"rm {mount_point}/data", shell=True, sudo=True)

            # 6. Check how much the mountpoint is trimmed after deleting the file,
            #  and compare the final fstrim status with initial fstrim status.
            node.tools[Echo].write_to_file(
                "2", node.get_pure_path("/proc/sys/vm/drop_caches"), sudo=True
            )
            final_fstrim = node.execute(
                f"fstrim {mount_point} -v", shell=True, sudo=True
            )
            mount.umount(disk_name=namespace, point=mount_point)
            assert_that(
                final_fstrim.stdout,
                "initial_fstrim should equal to final_fstrim after operations "
                "after umount and re-mount.",
            ).is_equal_to(initial_fstrim.stdout)

    @TestCaseMetadata(
        description="""
        This test case will
        1. Create a partition, xfs filesystem and mount it.
        2. Umount the mountpoint.
        3. Run blkdiscard command on the partition.
        4. Remount command should fail after run blkdiscard command.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def verify_nvme_blkdiscard(self, node: Node) -> None:
        os_information = node.os.information
        if "Ubuntu" == os_information.vendor and "14.04" == os_information.release:
            raise SkippedException(
                f"blkdiscard is not supported with distro {os_information.vendor} and "
                f"version {os_information.release}"
            )
        nvme = node.features[Nvme]
        nvme_namespaces = nvme.get_raw_nvme_disks()
        mount = node.tools[Mount]
        for namespace in nvme_namespaces:
            mount_point = namespace.rpartition("/")[-1]
            mount.umount(disk_name=namespace, point=mount_point)
            # 1. Create a partition, xfs filesystem and mount it.
            _format_mount_disk(node, namespace, FileSystem.xfs)

            # 2. Umount the mountpoint.
            mount.umount(disk_name=namespace, point=mount_point, erase=False)

            # 3. Run blkdiscard command on the partition.
            blkdiscard = node.execute(
                f"blkdiscard -v {namespace}p1", shell=True, sudo=True
            )
            if 0 != blkdiscard.exit_code:
                blkdiscard = node.execute(
                    f"blkdiscard -f -v {namespace}p1", shell=True, sudo=True
                )
            blkdiscard.assert_exit_code(
                message=f"{namespace}p1 not exist or blkdiscard command enounter "
                "unexpected error."
            )

            # 4. Remount command should fail after run blkdiscard command.
            mount_result = node.execute(
                f"mount {namespace}p1 {mount_point}", shell=True, sudo=True
            )
            mount_result.assert_exit_code(expected_exit_code=32)

    @TestCaseMetadata(
        description="""
        This test case will run commands 2-5, the commands are expected fail or not
         based on the capabilities of the device.
        1. Use `nvme id-ctrl device` command list the capabilities of the device.
        1.1 When 'Format NVM Supported' shown up in output of 'nvme id-ctrl device',
         then nvme disk can be format, otherwise, it can't be format.
        1.2 When 'NS Management and Attachment Supported' shown up in output of
         'nvme id-ctrl device', nvme namespace can be created, deleted and detached,
         otherwise it can't be managed.
        2. `nvme format namespace` - format a namespace.
        3. `nvme create-ns namespace` - create a namespace.
        4. `nvme delete-ns -n 1 namespace` - delete a namespace.
        5. `nvme detach-ns -n 1 namespace` - detach a namespace.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def verify_nvme_manage_ns(self, node: Node) -> None:
        nvme = node.features[Nvme]
        nvme_namespaces = nvme.get_raw_nvme_disks()
        nvme_devices = nvme.get_devices()
        nvme_cli = node.tools[Nvmecli]
        device_format_exit_code = 0
        ns_management_exit_code = [0]
        # 1. Use `nvme id-ctrl device` command list the capabilities of the device.
        # 1.1 When 'Format NVM Supported' shown up in output of 'nvme id-ctrl device',
        #  then nvme disk can be format, otherwise, it can't be format.
        if not nvme_cli.support_device_format(nvme_devices[0]):
            device_format_exit_code = 1
        # 1.2 When 'NS Management and Attachment Supported' shown up in output of
        #  'nvme id-ctrl device', nvme namespace can be created, deleted and detached,
        #  otherwise it can't be managed.
        if not nvme_cli.support_ns_manage_attach(nvme_devices[0]):
            # for old nvme cli version, it returns 22
            # for new nvme cli version, it returns 1
            # refer https://github.com/linux-nvme/nvme-cli/issues/1120
            ns_management_exit_code = [1, 22]
        for namespace in nvme_namespaces:
            # 2. `nvme format namespace` - format a namespace.
            format_namespace = nvme_cli.format_namespace(namespace)
            format_namespace.assert_exit_code(device_format_exit_code)
            # 3. `nvme create-ns namespace` - create a namespace.
            create_namespace = nvme_cli.create_namespace(namespace)
            create_namespace.assert_exit_code(ns_management_exit_code)
            # 4. `nvme delete-ns -n 1 namespace` - delete a namespace.
            delete_namespace = nvme_cli.delete_namespace(namespace, 1)
            delete_namespace.assert_exit_code(ns_management_exit_code)
            # 5. `nvme detach-ns -n 1 namespace` - detach a namespace.
            detach_namespace = nvme_cli.detach_namespace(namespace, 1)
            detach_namespace.assert_exit_code(ns_management_exit_code)

    @TestCaseMetadata(
        description="""
        This test case will
        1. Disable NVME devices.
        2. Enable PCI devices.
        3. Get NVMe devices slots.
        4. Check NVMe devices are back after rescan.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def verify_nvme_rescind(self, node: Node) -> None:
        lspci = node.tools[Lspci]
        # 1. Disable NVME devices.
        before_pci_count = lspci.disable_devices_by_type(
            device_type=DEVICE_TYPE_NVME, use_pci_ids=True
        )
        # 2. Enable PCI devices.
        lspci.enable_devices()
        # 3. Get PCI devices slots.
        after_devices_slots = lspci.get_device_names_by_type(
            DEVICE_TYPE_NVME, True, True
        )
        # 4. Check PCI devices are back after rescan.
        assert_that(
            after_devices_slots,
            "After rescan, the disabled NVMe PCI devices should be back.",
        ).is_length(before_pci_count)

    @TestCaseMetadata(
        description="""
        This test case does following steps to verify VM working normally during
         disable and enable nvme and sriov devices.
        1. Disable PCI devices.
        2. Enable PCI devices.
        3. Get PCI devices slots.
        4. Check PCI devices are back after rescan.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=Sriov(),
            supported_features=[Nvme],
        ),
    )
    def verify_nvme_sriov_rescind(self, node: Node) -> None:
        lspci = node.tools[Lspci]
        device_types = [DEVICE_TYPE_NVME, DEVICE_TYPE_SRIOV]
        for device_type in device_types:
            # 1. Disable PCI devices.
            before_pci_count = lspci.disable_devices_by_type(device_type, True)
            # 2. Enable PCI devices.
            lspci.enable_devices()
            # 3. Get PCI devices slots.
            after_devices_slots = lspci.get_device_names_by_type(
                device_type, True, True
            )
            # 4. Check PCI devices are back after rescan.
            assert_that(
                after_devices_slots,
                f"After rescan, the disabled {device_type} PCI devices should be back.",
            ).is_length(before_pci_count)

    def _verify_nvme_disk(self, environment: Environment, node: Node) -> None:
        # 1. Get nvme devices and nvme namespaces from /dev/ folder,
        #  compare the count of nvme namespaces and nvme devices.
        nvme = node.features[Nvme]
        nvme_device = nvme.get_devices()
        nvme_namespace = nvme.get_raw_nvme_disks()
        assert_that(nvme_device).described_as(
            "nvme devices count should be equal to namespace count by listing devices "
            "under folder /dev."
        ).is_length(len(nvme_namespace))

        # 2. Compare the count of nvme namespaces return from `nvme list`
        #  and list nvme namespaces under /dev/.
        nvme_namespace_cli = nvme.get_namespaces_from_cli()
        assert_that(nvme_namespace_cli).described_as(
            "nvme namespace count should be consistent between listed devides under "
            "folder /dev and return value from [nvme list]."
        ).is_length(len(nvme_namespace))

        # 3. Compare nvme devices count return from `lspci`
        #  and list nvme devices under /dev/.
        nvme_device_from_lspci = nvme.get_devices_from_lspci()
        assert_that(nvme_device).described_as(
            "nvme devices count should be consistent between return value from [lspci] "
            "and listed devices under folder /dev."
        ).is_length(len(nvme_device_from_lspci))

        # 4. Azure platform only, nvme devices count should equal to
        #  actual vCPU count / 8.
        if isinstance(environment.platform, AzurePlatform):
            lscpu_tool = node.tools[Lscpu]
            core_count = lscpu_tool.get_core_count()
            expected_count = math.ceil(core_count / 8)
            assert_that(nvme_namespace).described_as(
                "nvme devices count should be equal to [vCPU/8]."
            ).is_length(expected_count)

    def _verify_nvme_function(self, node: Node, use_partitions: bool = True) -> None:
        # Verify the basic function of all NVMe disks
        nvme = node.features[Nvme]
        nvme_namespaces = nvme.get_raw_nvme_disks()
        nvme_cli = node.tools[Nvmecli]
        cat = node.tools[Cat]
        mount = node.tools[Mount]
        for namespace in nvme_namespaces:
            # 1. Get the number of errors from nvme-cli before operations.
            error_count_before_operations = nvme_cli.get_error_count(namespace)

            # 2. Create a partition, filesystem and mount it.
            _format_mount_disk(node, namespace, FileSystem.ext4, use_partitions)

            # 3. Create a txt file on the partition, content is 'TestContent'.
            mount_point = namespace.rpartition("/")[-1]
            cmd_result = node.execute(
                f"echo TestContent > {mount_point}/testfile.txt", shell=True, sudo=True
            )
            cmd_result.assert_exit_code(
                message=f"{mount_point}/testfile.txt may not exist."
            )

            # 4. Create a file 'data' on the partition, get the md5sum value.
            cmd_result = node.execute(
                f"dd if=/dev/zero of={mount_point}/data bs=10M count=100",
                shell=True,
                sudo=True,
            )
            cmd_result.assert_exit_code(
                message=f"{mount_point}/data is not created successfully, "
                "please check the disk space."
            )
            initial_md5 = node.execute(
                f"md5sum {mount_point}/data", shell=True, sudo=True
            )
            initial_md5.assert_exit_code(
                message=f"{mount_point}/data not exist or md5sum command encountered"
                " unexpected error."
            )

            # 5. Umount and remount the partition.
            mount.umount(namespace, mount_point, erase=False)
            if use_partitions:
                mount.mount(f"{namespace}p1", mount_point)
            else:
                mount.mount(f"{namespace}", mount_point)

            # 6. Get the txt file content, compare the value.
            file_content = cat.run(f"{mount_point}/testfile.txt", shell=True, sudo=True)
            assert_that(
                file_content.stdout,
                f"content of {mount_point}/testfile.txt should keep consistent "
                "after umount and re-mount.",
            ).is_equal_to("TestContent")

            # 6. Get md5sum value of file 'data', compare with initial value.
            final_md5 = node.execute(
                f"md5sum {mount_point}/data", shell=True, sudo=True
            )
            assert_that(
                initial_md5.stdout,
                f"md5sum of {mount_point}/data should keep consistent "
                "after umount and re-mount.",
            ).is_equal_to(final_md5.stdout)

            # 7. Compare the number of errors from nvme-cli after operations.
            error_count_after_operations = nvme_cli.get_error_count(namespace)
            assert_that(
                error_count_before_operations,
                "error-log should not increase after operations.",
            ).is_equal_to(error_count_after_operations)

            mount.umount(disk_name=namespace, point=mount_point)
