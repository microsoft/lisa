# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import time
from pathlib import Path
from random import randint
from typing import cast

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
)
from lisa.features import SerialConsole
from lisa.operating_system import Redhat
from lisa.tools import Dmesg, Echo, KdumpBase, KernelConfig, Lscpu
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
    crash_kernel = "512M"

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
        priority=1,
        requirement=node_requirement(
            node=schema.NodeSpace(
                core_count=1, memory_mb=search_space.IntRange(min=2048)
            ),
        ),
    )
    def kdumpcrash_validate_single_core(
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
            )
        ),
    )
    def kdumpcrash_validate_smp(self, node: Node, log_path: Path, log: Logger) -> None:
        self._trigger_kdump_on_specified_cpu(1, node, log_path, log)

    @TestCaseMetadata(
        description="""
        This test case verifies if the kdump is effect when VM has any cores, and
        trigger kdump on the random cpu.
        The test steps are same as `kdumpcrash_validate_single_core`.
        """,
        priority=2,
    )
    def kdumpcrash_validate_on_random_cpu(
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
            node=schema.NodeSpace(core_count=search_space.IntRange(min=33, max=192))
        ),
    )
    def kdumpcrash_validate_on_cpu32(
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
            node=schema.NodeSpace(core_count=search_space.IntRange(min=193, max=415))
        ),
    )
    def kdumpcrash_validate_on_cpu192(
        self, node: Node, log_path: Path, log: Logger
    ) -> None:
        self._trigger_kdump_on_specified_cpu(192, node, log_path, log)

    @TestCaseMetadata(
        description="""
        This test case verifies if the kdump is effect when VM has more than 415 cpus,
        and trigger kdump on the 416th cpu(cpu415), which is designed by a known issue.
        The test steps are same as `kdumpcrash_validate_single_core`.
        """,
        priority=2,
        requirement=node_requirement(
            node=schema.NodeSpace(core_count=search_space.IntRange(min=416))
        ),
    )
    def kdumpcrash_validate_on_cpu415(
        self, node: Node, log_path: Path, log: Logger
    ) -> None:
        self._trigger_kdump_on_specified_cpu(415, node, log_path, log)

    @TestCaseMetadata(
        description="""
        This test case verifies if the kdump is effect when crashkernel is set auto.
        The test steps are same as `kdumpcrash_validate_single_core`.
        """,
        priority=2,
    )
    def kdumpcrash_validate_auto_size(
        self, node: Node, log_path: Path, log: Logger
    ) -> None:
        self.crash_kernel = "auto"
        self._kdump_test(node, log_path, log)

    @TestCaseMetadata(
        description="""
        This test case verifies if the kdump is effect when crashkernel is set auto and
        the memory is more than 2T. With the crashkernel=auto parameter, system will
        reserved a suitable size memory for crash kernel. We want to see if the
        crashkernel=auto can also handle this scenario when the system memory is large.

        The test steps are same as `kdumpcrash_validate_single_core`.
        """,
        priority=2,
        requirement=node_requirement(
            node=schema.NodeSpace(memory_mb=search_space.IntRange(min=2097152)),
        ),
    )
    def kdumpcrash_validate_large_memory_auto_size(
        self, node: Node, log_path: Path, log: Logger
    ) -> None:
        self.crash_kernel = "auto"
        self._kdump_test(node, log_path, log)

    def _check_supported(self, node: Node) -> None:
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
        # Rehat/Centos has this "auto crashkernel" feature. For version 7, it needs the
        # CONFIG_KEXEC_AUTO_RESERVE. For version 8, the ifdefine of that config is
        # removed. For these changes we can refer to Centos kernel, gotten according
        # to https://wiki.centos.org/action/show/Sources?action=show&redirect=sources
        # In addition, we didn't see upstream kernel has the auto crashkernel feature.
        # It may be a patch owned by Redhat/Centos.
        if not (
            isinstance(node.os, Redhat) and node.os.information.version >= "8.0.0-0"
        ):
            if self.crash_kernel == "auto" and not node.tools[KernelConfig].is_built_in(
                "CONFIG_KEXEC_AUTO_RESERVE"
            ):
                raise SkippedException("crashkernel=auto doesn't work for the distro.")

        # Check the kernel config for kdump supported
        kdump = node.tools[KdumpBase]
        kdump.check_required_kernel_config()

    def _kdump_test(self, node: Node, log_path: Path, log: Logger) -> None:
        try:
            self._check_supported(node)
        except UnsupportedDistroException as identifier:
            raise SkippedException(identifier)

        kdump = node.tools[KdumpBase]
        kdump.config_crashkernel_memory(self.crash_kernel)
        kdump.config_dump_path()
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

        try:
            # Trigger kdump. After execute the trigger cmd, the VM will be disconnected
            # We set a timeout time 10.
            node.execute(
                self.trigger_kdump_cmd,
                shell=True,
                sudo=True,
                timeout=10,
            )
        except Exception as identifier:
            log.debug(f"ignorable ssh exception: {identifier}")

        # Wait for the VM dump file and boot up
        # When the crash kernel boots up, port 22 can be connected even if dump file
        # is not completed. So we can't use wait_tcp_port_ready function to judge if
        # the dump process is completed and the VM already boots up. We can use
        # try_connect function
        timer = create_timer()
        remote_node = cast(RemoteNode, node)
        stdout = None
        while not stdout and timer.elapsed(False) < self.timeout_of_dump_crash:
            try:
                stdout = try_connect(remote_node._connection_info)
            except Exception as identifier:
                log.debug(
                    "failed to connect SSH "
                    f"{remote_node._connection_info.address}:"
                    f"{remote_node._connection_info.port}. "
                    f"{identifier.__class__.__name__}: {identifier}. Retry..."
                )
                time.sleep(10)
            if not stdout:
                serial_console = node.features[SerialConsole]
                serial_console.check_initramfs(
                    saved_path=log_path, stage="after_trigger_crash", force_run=True
                )
        if not stdout:
            raise LisaException("Timeout to connect the VM after triggering kdump.")

        # After trigger kdump, the VM will reboot. We need to close and re-initialize
        node.close()
        node.initialize()
        # Verify if the kernel kdump process creates a vmcore file of size 10M+
        kdump.check_vmcore_exist()

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
