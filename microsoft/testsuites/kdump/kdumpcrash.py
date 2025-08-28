# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from random import randint
from typing import Any

from lisa import (
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    node_requirement,
    schema,
    search_space,
    simple_requirement,
)
from lisa.features.security_profile import CvmDisabled
from lisa.operating_system import BSD, Windows
from lisa.tools import KdumpCheck, Lscpu


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
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if isinstance(node.os, BSD) or isinstance(node.os, Windows):
            raise SkippedException(f"{node.os} is not supported.")
        self.kdump_util = node.tools[KdumpCheck]

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
        self.kdump_util.kdump_test(log_path=log_path)

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
        self.kdump_util.trigger_kdump_on_specified_cpu(cpu_num=1, log_path=log_path)

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
        thread_count = lscpu.get_thread_count()
        cpu_num = randint(0, thread_count - 1)
        self.kdump_util.trigger_kdump_on_specified_cpu(
            cpu_num=cpu_num,
            log_path=log_path,
        )

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
        self.kdump_util.trigger_kdump_on_specified_cpu(
            cpu_num=32,
            log_path=log_path,
        )

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
        self.kdump_util.trigger_kdump_on_specified_cpu(
            cpu_num=192,
            log_path=log_path,
        )

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
        self.kdump_util.trigger_kdump_on_specified_cpu(
            cpu_num=415,
            log_path=log_path,
        )

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
        self.kdump_util.kdump_test(log_path=log_path, is_auto=True)

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
        self.kdump_util.kdump_test(log_path=log_path, is_auto=True)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        # kdump cases will trigger crash
        # therefore we mark the node dirty to prevent future testing on this environment
        # to aviod detecting the panic call trace wrongly
        kwargs["node"].mark_dirty()
