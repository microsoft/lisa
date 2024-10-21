# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import time
from pathlib import Path
from random import randint
from typing import Any, cast

from func_timeout import FunctionTimedOut, func_set_timeout  # type: ignore

from lisa import (
    LisaException,
    Logger,
    Node,
    RemoteNode,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedDistroException,
    node_requirement,
    schema,
    search_space,
    simple_requirement,
)
from lisa.features import Disk, SerialConsole
from lisa.features.security_profile import CvmDisabled
from lisa.operating_system import BSD, Redhat, Windows
from lisa.tools import Dmesg, Echo, KdumpBase, KernelConfig, Lscpu, Stat
from lisa.tools.free import Free
from lisa.util.perf_timer import create_timer
from lisa.util.shell import try_connect


@TestSuiteMetadata(
    area="kdump",
    category="functional",
    description="""
    This test suite is used to verify if kernel crash dump is effect, which is judged
    through vmcore file is generated after triggering kdump by sysrq.

    It has 7 test cases. They verify if kdump is effect when:
        1. VM has 1 cpu
        2. VM has 2-8 cpus and trigger kdump on cpu 1
        3. VM has 33-192 cpus and trigger kdump on cpu 32
        4. VM has 193-415 cpus and trigger kdump on cpu 192
        5. VM has more than 415 cpus and trigger kdump on cpu 415
        6. crashkernel is set "auto"
        7. crashkernel is set "auto" and VM has more than 2T memory
    """,
)
class KdumpCrash(TestSuite):
    # When with large system memory, the dump file can achieve more than 7G. It will
    # cost about 10min to copy dump file to disk for some distros, such as Ubuntu.
    # So we set the timeout time 800s to make sure the dump file is completed.
    timeout_of_dump_crash = 800
    trigger_kdump_cmd = "echo c > /proc/sysrq-trigger"
    is_auto = False

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if isinstance(node.os, BSD) or isinstance(node.os, Windows):
            raise SkippedException(f"{node.os} is not supported.")

    @TestCaseMetadata(
        description="""
        This test case verifies if kdump is effect when VM has 1 cpu.
        VM need 2G memory at least to make sure it has enough memory to load crash
        kernel.

        Steps:
        1. Check if vmbus version and kernel configurations support for crash dump.
        2. Specify the memory reserved for crash kernel in kernel cmdline, setting the
            "crashkernel" option to the required value.
            a. Modify the grub config file to add crashkernel option or change the
                value to the required one. (For Redhat 8, no need to modify grub config
                file. It can specify crashkernel by using grubby command directly)
            b. Update grub config
        4. If needed, config the dump path.
        3. Reboot system to make kdump effect.
        4. Check if the crash kernel is loaded.
            a. Check if kernel cmdline has crashkernel option and the value is expected
            b. Check if /sys/kernel/kexec_crash_loaded file exists and the value is '1'
            c. Check if /proc/iomem is reserved memory for crash kernel
        5. Trigger kdump through 'echo c > /proc/sysrq-trigger', or trigger on
            specified CPU by using command "taskset -c".
        6. Check if vmcore is generated under the dump path we configure after system
            boot up.
        """,
        priority=2,
        requirement=node_requirement(
            node=schema.NodeSpace(
                core_count=1, memory_mb=search_space.IntRange(min=2048)
            ),
            supported_features=[CvmDisabled()],
        ),
    )
    def verify_kdumpcrash_single_core(
        self, node: Node, log_path: Path, log: Logger
    ) -> None:
        self._kdump_test(node, log_path, log)

    @TestCaseMetadata(
        description="""
        This test case verifies if the kdump is effect when VM has 2~8 cpus, and
        trigger kdump on the second cpu(cpu1), which is designed by a known issue.
        The test steps are same as `kdumpcrash_validate_single_core`.
        """,
        priority=2,
        requirement=node_requirement(
            node=schema.NodeSpace(
                core_count=search_space.IntRange(min=2, max=8),
            ),
            supported_features=[CvmDisabled()],
        ),
    )
    def verify_kdumpcrash_smp(self, node: Node, log_path: Path, log: Logger) -> None:
        self._trigger_kdump_on_specified_cpu(1, node, log_path, log)

    @TestCaseMetadata(
        description="""
        This test case verifies if the kdump is effect when VM has any cores, and
        trigger kdump on the random cpu.
        The test steps are same as `kdumpcrash_validate_single_core`.
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[CvmDisabled()],
        ),
    )
    def verify_kdumpcrash_on_random_cpu(
        self, node: Node, log_path: Path, log: Logger
    ) -> None:
        lscpu = node.tools[Lscpu]
        cpu_count = lscpu.get_core_count()
        cpu_num = randint(0, cpu_count - 1)
        self._trigger_kdump_on_specified_cpu(cpu_num, node, log_path, log)

    @TestCaseMetadata(
        description="""
        This test case verifies if the kdump is effect when VM has 33~192 cpus and
        trigger kdump on the 33th cpu(cpu32), which is designed by a known issue.
        The test steps are same as `kdumpcrash_validate_single_core`.
        """,
        priority=2,
        requirement=node_requirement(
            node=schema.NodeSpace(core_count=search_space.IntRange(min=33, max=192)),
            supported_features=[CvmDisabled()],
        ),
    )
    def verify_kdumpcrash_on_cpu32(
        self, node: Node, log_path: Path, log: Logger
    ) -> None:
        self._trigger_kdump_on_specified_cpu(32, node, log_path, log)

    @TestCaseMetadata(
        description="""
        This test case verifies if the kdump is effect when VM has 193~415 cpus, and
        trigger kdump on the 193th cpu(cpu192), which is designed by a known issue.
        The test steps are same as `kdumpcrash_validate_single_core`.
        """,
        priority=2,
        requirement=node_requirement(
            node=schema.NodeSpace(core_count=search_space.IntRange(min=193, max=415)),
            supported_features=[CvmDisabled()],
        ),
    )
    def verify_kdumpcrash_on_cpu192(
        self, node: Node, log_path: Path, log: Logger
    ) -> None:
        self._trigger_kdump_on_specified_cpu(192, node, log_path, log)

    @TestCaseMetadata(
        description="""
        This test case verifies if the kdump is effect when VM has more than 415 cpus,
        and trigger kdump on the 416th cpu(cpu415), which is designed by a known issue.
        The test steps are same as `kdumpcrash_validate_single_core`.
        """,
        priority=4,
        requirement=node_requirement(
            node=schema.NodeSpace(core_count=search_space.IntRange(min=416)),
            supported_features=[CvmDisabled()],
        ),
    )
    def verify_kdumpcrash_on_cpu415(
        self, node: Node, log_path: Path, log: Logger
    ) -> None:
        self._trigger_kdump_on_specified_cpu(415, node, log_path, log)

    @TestCaseMetadata(
        description="""
        This test case verifies if the kdump is effect when crashkernel is set auto.
        The test steps are same as `kdumpcrash_validate_single_core`.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[CvmDisabled()],
        ),
    )
    def verify_kdumpcrash_auto_size(
        self, node: Node, log_path: Path, log: Logger
    ) -> None:
        self.is_auto = True
        self._kdump_test(node, log_path, log)

    @TestCaseMetadata(
        description="""
        This test case verifies if the kdump is effect when crashkernel is set auto and
        the memory is more than 2T. With the crashkernel=auto parameter, system will
        reserved a suitable size memory for crash kernel. We want to see if the
        crashkernel=auto can also handle this scenario when the system memory is large.

        The test steps are same as `kdumpcrash_validate_single_core`.
        """,
        priority=3,
        requirement=node_requirement(
            node=schema.NodeSpace(memory_mb=search_space.IntRange(min=2097152)),
            supported_features=[CvmDisabled()],
        ),
    )
    def verify_kdumpcrash_large_memory_auto_size(
        self, node: Node, log_path: Path, log: Logger
    ) -> None:
        self.is_auto = True
        self._kdump_test(node, log_path, log)

    # This method might stuck after triggering crash,
    # so use timeout to recycle it faster.
    @func_set_timeout(10)  # type: ignore
    def _try_connect(self, remote_node: RemoteNode) -> Any:
        return try_connect(remote_node._connection_info)

    def _check_supported(self, node: Node) -> None:
        # Check the kernel config for kdump supported
        kdump = node.tools[KdumpBase]
        kdump.check_required_kernel_config()

        # Check the VMBus version for kdump supported
        dmesg = node.tools[Dmesg]
        vmbus_version = dmesg.get_vmbus_version()
        if vmbus_version < "3.0.0":
            raise SkippedException(
                f"No negotiated VMBus version {vmbus_version}. "
                "Kernel might be old or patches not included. "
                "Full support for kdump is not present."
            )

        # Below code aims to check the kernel config for "auto crashkernel" supported.
        # Redhat/Centos has this "auto crashkernel" feature. For version 7, it needs the
        # CONFIG_KEXEC_AUTO_RESERVE. For version 8, the ifdefine of that config is
        # removed. For these changes we can refer to Centos kernel, gotten according
        # to https://wiki.centos.org/action/show/Sources?action=show&redirect=sources
        # In addition, we didn't see upstream kernel has the auto crashkernel feature.
        # It may be a patch owned by Redhat/Centos.
        # Note that crashkernel=auto option in the boot command line is no longer
        # supported on RHEL 9 and later releases
        if not (
            isinstance(node.os, Redhat)
            and node.os.information.version >= "8.0.0-0"
            and node.os.information.version < "9.0.0-0"
        ):
            if self.is_auto and not node.tools[KernelConfig].is_built_in(
                "CONFIG_KEXEC_AUTO_RESERVE"
            ):
                raise SkippedException("crashkernel=auto doesn't work for the distro.")

    def _get_resource_disk_dump_path(self, node: Node) -> str:
        mount_point = node.features[Disk].get_resource_disk_mount_point()
        dump_path = mount_point + "/crash"
        return dump_path

    def _is_system_with_more_memory(self, node: Node) -> bool:
        free = node.tools[Free]
        total_memory = free.get_total_memory()
        # Return true when system memory is 10 GiB higher than the OS disk size
        if "T" in total_memory or (
            "G" in total_memory
            and (
                node.capability.disk
                and isinstance(node.capability.disk.os_disk_size, int)
                and (
                    float(total_memory.strip("G"))
                    > (node.capability.disk.os_disk_size - 10)
                )
            )
        ):
            return True
        return False

    def _kdump_test(self, node: Node, log_path: Path, log: Logger) -> None:
        try:
            self._check_supported(node)
        except UnsupportedDistroException as identifier:
            raise SkippedException(identifier)

        kdump = node.tools[KdumpBase]
        free = node.tools[Free]
        total_memory = free.get_total_memory()
        self.crash_kernel = kdump.calculate_crashkernel_size(total_memory)
        if self.is_auto:
            self.crash_kernel = "auto"

        if self._is_system_with_more_memory(node):
            # System memory is more os disk size, need to change the dump path
            # and increase the timeout duration
            kdump.config_resource_disk_dump_path(
                self._get_resource_disk_dump_path(node)
            )
            self.timeout_of_dump_crash = 1200
            if "T" in total_memory and float(total_memory.strip("T")) > 6:
                self.timeout_of_dump_crash = 2000

        kdump.config_crashkernel_memory(self.crash_kernel)
        kdump.enable_kdump_service()
        # Cleaning up any previous crash dump files
        node.execute(
            f"mkdir -p {kdump.dump_path} && rm -rf {kdump.dump_path}/*",
            shell=True,
            sudo=True,
        )

        # Reboot system to make kdump take effect
        node.reboot()

        # Confirm that the kernel dump mechanism is enabled
        kdump.check_crashkernel_loaded(self.crash_kernel)
        # Activate the magic SysRq option
        echo = node.tools[Echo]
        echo.write_to_file("1", node.get_pure_path("/proc/sys/kernel/sysrq"), sudo=True)
        node.execute("sync", shell=True, sudo=True)

        kdump.capture_info()

        try:
            # Trigger kdump. After execute the trigger cmd, the VM will be disconnected
            # We set a timeout time 10.
            node.execute_async(
                self.trigger_kdump_cmd,
                shell=True,
                sudo=True,
            )
        except Exception as identifier:
            log.debug(f"ignorable ssh exception: {identifier}")

        # Check if the vmcore file is generated after triggering a crash
        self._check_kdump_result(node, log_path, log, kdump)

        # We should clean up the vmcore file since the test is passed
        node.execute(f"rm -rf {kdump.dump_path}/*", shell=True, sudo=True)

    def _is_system_connected(self, node: Node, log: Logger) -> bool:
        remote_node = cast(RemoteNode, node)
        try:
            self._try_connect(remote_node)
        except FunctionTimedOut as identifier:
            # The FunctionTimedOut must be caught separated, or the process will exit.
            log.debug(f"ignorable timeout exception: {identifier}")
            return False
        except Exception as identifier:
            log.debug(
                "Fail to connect SSH "
                f"{remote_node._connection_info.address}:"
                f"{remote_node._connection_info.port}. "
                f"{identifier.__class__.__name__}: {identifier}. Retry..."
            )
            return False
        return True

    def _is_dump_file_generated(self, node: Node, kdump: KdumpBase) -> bool:
        result = node.execute(
            f"find {kdump.dump_path} -type f -size +10M "
            "\\( -name vmcore -o -name dump.* -o -name vmcore.* \\) "
            "-exec ls -lh {} \\;",
            shell=True,
            sudo=True,
        )
        if result.stdout:
            return True
        return False

    def _check_incomplete_dump_file_generated(
        self, node: Node, kdump: KdumpBase
    ) -> str:
        # Check if has dump incomplete file
        result = node.execute(
            f"find {kdump.dump_path} -name '*incomplete*'",
            shell=True,
            sudo=True,
        )
        return result.stdout

    def _check_kdump_result(
        self, node: Node, log_path: Path, log: Logger, kdump: KdumpBase
    ) -> None:
        # We use this function to check if the dump file is generated.
        # Steps:
        # 1. Try to connect the VM;
        # 2. If connected:
        #    1). Check if the dump file is generated. If so, then jump the loop.
        #       The test is passed.
        #    2). If there is no dump file, check the incomplete file (When dumping
        #        hasn't completed, the dump file is named as "*incomplete").
        #           a. If there is no incomplete file either, then raise and exception.
        #           b. If there is an incomplete file, then check if the file size
        #              is growing. If so, check it in a loop until the dump completes
        #              or incomplete file doesn't grow or timeout.
        # 3. The VM can be connected may just when the crash kernel boots up. When
        #    dumping or rebooting after dump completes, the VM might be disconnected.
        #    We need to catch the exception, and retry to connect the VM. Then follow
        #    the same steps to check.
        timer = create_timer()
        has_checked_console_log = False
        serial_console = node.features[SerialConsole]
        while timer.elapsed(False) < self.timeout_of_dump_crash:
            if not self._is_system_connected(node, log):
                if not has_checked_console_log and timer.elapsed(False) > 60:
                    serial_console.check_initramfs(
                        saved_path=log_path, stage="after_trigger_crash", force_run=True
                    )
                    has_checked_console_log = True
                continue

            # After trigger kdump, the VM will reboot. We need to close the node
            node.close()
            saved_dumpfile_size = 0
            max_tries = 20
            check_incomplete_file_tries = 0
            check_dump_file_tries = 0
            # Check in this loop until the dump file is generated or incomplete file
            # doesn't grow or timeout
            while True:
                try:
                    if self._is_dump_file_generated(node, kdump):
                        return
                    incomplete_file = self._check_incomplete_dump_file_generated(
                        node=node, kdump=kdump
                    )
                    if incomplete_file:
                        check_dump_file_tries = 0
                        stat = node.tools[Stat]
                        incomplete_file_size = stat.get_total_size(incomplete_file)
                except Exception as identifier:
                    log.debug(
                        "Fail to execute command. It may be caused by the system kernel"
                        " reboot after dumping vmcore."
                        f"{identifier.__class__.__name__}: {identifier}. Retry..."
                    )
                    # Hit exception, break this loop and re-try to connect the system
                    break
                if incomplete_file:
                    # If the incomplete file doesn't grow in 100s, then raise exception
                    if incomplete_file_size > saved_dumpfile_size:
                        saved_dumpfile_size = incomplete_file_size
                        check_incomplete_file_tries = 0
                    else:
                        check_incomplete_file_tries += 1
                        if check_incomplete_file_tries >= max_tries:
                            serial_console.get_console_log(
                                saved_path=log_path, force_run=True
                            )
                            node.execute("df -h")
                            raise LisaException(
                                "The vmcore file is incomplete with file size"
                                f" {round(incomplete_file_size/1024/1024, 2)}MB"
                            )
                else:
                    # If there is no any dump file in 100s, then raise exception
                    check_dump_file_tries += 1
                    if check_dump_file_tries >= max_tries:
                        serial_console.get_console_log(
                            saved_path=log_path, force_run=True
                        )
                        raise LisaException(
                            "No vmcore or vmcore-incomplete is found under "
                            f"{kdump.dump_path} with file size greater than 10M."
                        )
                if timer.elapsed(False) > self.timeout_of_dump_crash:
                    serial_console.get_console_log(saved_path=log_path, force_run=True)
                    raise LisaException("Timeout to dump vmcore file.")
                time.sleep(5)
        serial_console.get_console_log(saved_path=log_path, force_run=True)
        raise LisaException("Timeout to connect the VM after triggering kdump.")

    def _trigger_kdump_on_specified_cpu(
        self, cpu_num: int, node: Node, log_path: Path, log: Logger
    ) -> None:
        lscpu = node.tools[Lscpu]
        cpu_count = lscpu.get_core_count()
        if cpu_count > cpu_num:
            self.trigger_kdump_cmd = (
                f"taskset -c {cpu_num} echo c > /proc/sysrq-trigger"
            )
            self._kdump_test(node, log_path, log)
        else:
            raise SkippedException(
                "The cpu count can't meet the test case's requirement. "
                f"Expected more than {cpu_num} cpus, actual {cpu_count}"
            )

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        # kdump cases will trigger crash
        # therefore we mark the node dirty to prevent future testing on this environment
        # to aviod detecting the panic call trace wrongly
        kwargs["node"].mark_dirty()
