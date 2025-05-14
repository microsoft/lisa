# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from func_timeout import FunctionTimedOut, func_set_timeout  # type: ignore

from lisa.operating_system import Redhat
from lisa.tools.df import Df
from lisa.tools.dmesg import Dmesg
from lisa.tools.echo import Echo
from lisa.tools.free import Free
from lisa.tools.kdump import KdumpBase
from lisa.tools.kernel_config import KernelConfig
from lisa.tools.lscpu import Lscpu
from lisa.tools.stat import Stat
from lisa.util import LisaException, SkippedException, UnsupportedDistroException
from lisa.util.logger import Logger
from lisa.util.perf_timer import create_timer
from lisa.util.shell import try_connect

if TYPE_CHECKING:
    from lisa.node import Node, RemoteNode


class Kdump:
    def __init__(
        self,
        crashdump_timeout: int = 800,
        kdump_cmd: str = "echo c > /proc/sysrq-trigger",
    ) -> None:
        # When with large system memory, the dump file can achieve more than 7G. It will
        # cost about 10min to copy dump file to disk for some distros, such as Ubuntu.
        # So we set the timeout time 800s to make sure the dump file is completed.
        self.timeout_of_dump_crash = crashdump_timeout
        self.trigger_kdump_cmd = kdump_cmd

    # This method might stuck after triggering crash,
    # so use timeout to recycle it faster.
    @func_set_timeout(10)  # type: ignore
    def _try_connect(self, remote_node: RemoteNode) -> Any:
        return try_connect(remote_node._connection_info)

    def _check_supported(self, node: Node, is_auto: bool = False) -> None:
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
            if is_auto and not node.tools[KernelConfig].is_built_in(
                "CONFIG_KEXEC_AUTO_RESERVE"
            ):
                raise SkippedException("crashkernel=auto doesn't work for the distro.")

    def _get_resource_disk_dump_path(self, node: Node) -> str:
        from lisa.features import Disk

        mount_point = node.features[Disk].get_resource_disk_mount_point()
        dump_path = mount_point + "/crash"
        return dump_path

    def _is_system_with_more_memory(self, node: Node) -> bool:
        free = node.tools[Free]
        total_memory_in_gb = free.get_total_memory_gb()

        df = node.tools[Df]
        available_space_in_os_disk = df.get_filesystem_available_space("/", True)

        if total_memory_in_gb > available_space_in_os_disk:
            return True
        return False

    def _kdump_test(
        self,
        node: Node,
        log_path: Path,
        log: Logger,
        is_auto: bool = False,
    ) -> None:
        try:
            self._check_supported(node, is_auto=is_auto)
        except UnsupportedDistroException as e:
            raise SkippedException(e)

        kdump = node.tools[KdumpBase]
        free = node.tools[Free]
        total_memory = free.get_total_memory()
        self.crash_kernel = kdump.calculate_crashkernel_size(total_memory)
        if is_auto:
            self.crash_kernel = "auto"

        if self._is_system_with_more_memory(node):
            # As system memory is more than free os disk size, need to
            # change the dump path and increase the timeout duration
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
        except Exception as e:
            log.debug(f"ignorable ssh exception: {e}")

        # Check if the vmcore file is generated after triggering a crash
        self._check_kdump_result(node, log_path, log, kdump)

        # We should clean up the vmcore file since the test is passed
        node.execute(f"rm -rf {kdump.dump_path}/*", shell=True, sudo=True)

    def _is_system_connected(self, node: Node, log: Logger) -> bool:
        from lisa.node import RemoteNode as RMNode

        remote_node = cast(RMNode, node)
        try:
            self._try_connect(remote_node)
        except FunctionTimedOut as e:
            # The FunctionTimedOut must be caught separated, or the process will exit.
            log.debug(f"ignorable timeout exception: {e}")
            return False
        except Exception as e:
            log.debug(
                "Fail to connect SSH "
                f"{remote_node._connection_info.address}:"
                f"{remote_node._connection_info.port}. "
                f"{e.__class__.__name__}: {e}. Retry..."
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
        from lisa.features import SerialConsole

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
                except Exception as e:
                    log.debug(
                        "Fail to execute command. It may be caused by the system kernel"
                        " reboot after dumping vmcore."
                        f"{e.__class__.__name__}: {e}. Retry..."
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
