# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Union

from lisa.executable import CustomScript, CustomScriptBuilder, ExecutableResult, Tool
from lisa.tools import Cat, Dhclient
from lisa.tools.dmesg import Dmesg
from lisa.tools.journalctl import Journalctl
from lisa.tools.kernel_config import KLDStat
from lisa.tools.lsmod import Lsmod
from lisa.tools.modinfo import Modinfo
from lisa.util import UnsupportedOperationException
from lisa.util.perf_timer import create_timer

from .whoami import Whoami


class Modprobe(Tool):
    @property
    def command(self) -> str:
        return self._command

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return ModprobeFreeBSD

    def _check_exists(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "modprobe"

    def is_module_loaded(
        self,
        mod_name: str,
        force_run: bool = False,
        no_info_log: bool = True,
        no_error_log: bool = True,
    ) -> bool:
        result = self.run(
            f"-nv {mod_name}",
            sudo=True,
            shell=True,
            force_run=force_run,
            no_info_log=no_info_log,
            no_error_log=no_error_log,
        )
        # Example possible outputs
        # 1) insmod /lib/modules/.../floppy.ko.xz
        #    Exists but is not loaded - return False
        # 2) FATAL: Module floppy not found.
        #    Module does not exist, therefore is not loaded - return False
        # 3) (no output)
        #    Module is loaded - return True
        could_be_loaded = result.stdout and "insmod" in result.stdout
        does_not_exist = (result.stderr and "not found" in result.stderr) or (
            result.stdout and "not found" in result.stdout
        )

        return not (could_be_loaded or does_not_exist)

    def remove(self, mod_names: List[str], ignore_error: bool = False) -> None:
        for mod_name in mod_names:
            if ignore_error:
                # rmmod support the module file, so use it here.
                self.node.execute(f"rmmod {mod_name}", sudo=True, shell=True)
            else:
                if self.is_module_loaded(mod_name, force_run=True):
                    try:
                        self.run(
                            f"-r {mod_name}",
                            force_run=True,
                            sudo=True,
                            shell=True,
                            expected_exit_code=0,
                            expected_exit_code_failure_message=(
                                f"Fail to remove module {mod_name}"
                            ),
                        )
                    except AssertionError as e:
                        self._collect_logs(mod_name)
                        raise e

    def load(
        self,
        modules: Union[str, List[str]],
        parameters: str = "",
        dry_run: bool = False,
    ) -> bool:
        if isinstance(modules, list):
            if parameters:
                raise UnsupportedOperationException(
                    "Modprobe does not support loading multiple modules with parameters"
                )
            modules_str = "-a " + " ".join(modules)
        else:
            modules_str = modules
        if parameters:
            command = f"{modules_str} {parameters}"
        else:
            command = f"{modules_str}"
        if dry_run:
            command = f"--dry-run {command}"
        result = self.run(
            command,
            force_run=True,
            sudo=True,
            shell=True,
        )
        if dry_run:
            return result.exit_code == 0

        result.assert_exit_code(
            expected_exit_code=0,
            message=f"Fail to load module[s]: {modules_str}.",
            include_output=True,
        )
        return True

    def module_exists(self, modules: Union[str, List[str]]) -> bool:
        return self.load(modules, dry_run=True)

    def reload(
        self,
        mod_name: str,
        times: int = 1,
        verbose: bool = False,
        timeout: int = 60,
        interface: str = "eth0",
        cleanup_logs: bool = True,
    ) -> Dict[str, int]:
        lsmod_tool = self.node.tools[Lsmod]
        module_exists = lsmod_tool.module_exists(
            mod_name=mod_name,
            force_run=True,
            no_debug_log=True,
        )
        if not module_exists:
            return {"module_exists": False}
        if not self.is_module_loaded(mod_name, force_run=True):
            return {}
        dhclient_command = self.node.tools[Dhclient].command

        username = self.node.tools[Whoami].get_username()
        unique_id = uuid.uuid4()
        nohup_output_log_file_name = (
            f"/home/{username}/nohup_log_{mod_name}_{str(unique_id)}.out"
        )
        loop_process_pid_file_name = (
            f"/home/{username}/loop_process_pid_{mod_name}_{str(unique_id)}.pid"
        )

        if verbose:
            verbose_flag = "true"
        else:
            verbose_flag = "false"

        modprobe_reloader_tool = CustomScriptBuilder(
            Path(__file__).parent.joinpath("scripts"), ["modprobe_reloader.sh"]
        )

        # here paramters are passed to the script modprobe_reloader.sh,
        # which is run on the remote node to reload the module.
        # The script is run in nohup mode, so it can continue running even if the
        # connection to the remote node is lost.
        # The script will run the modprobe command in a loop for the specified number
        # The parameters are:
        # nohup_output_log_file_name: file to store the output of the script
        # loop_process_pid_file_name: file to store the pid of the loop process
        # mod_name: name of the module to be reloaded e.g. hv_netvsc
        # times: number of times to reload the module
        # verbose_flag: whether to run the script in verbose mode or not
        # dhclient_command: command to run dhclient, e.g. dhclient or dhcpcd
        # interface: network interface to run dhclient on, e.g. eth0
        # The nohup_output_log_file_name and loop_process_pid_file_name are
        # created in the home directory of the user running the script.

        parameters = (
            f"{nohup_output_log_file_name} {loop_process_pid_file_name} "
            f"{mod_name} {times} {verbose_flag} {dhclient_command} {interface}"
        )
        self._log.debug(f"running with parameters: {parameters}")
        modprobe_reloader_script: CustomScript = self.node.tools[modprobe_reloader_tool]
        modprobe_reloader_script.run(parameters, sudo=True, shell=True, nohup=True)

        cat = self.node.tools[Cat]
        tried_times: int = 0
        timer = create_timer()
        # Wait for the loop process to start and check its status
        while (timer.elapsed(False) < timeout) or tried_times < 1:
            tried_times += 1
            try:
                pid = cat.read(loop_process_pid_file_name, force_run=True)
                r = self.node.execute(
                    f"ps -p {pid} > /dev/null && echo 'running' || echo 'not_running'",
                    sudo=True,
                    shell=True,
                )
                status = r.stdout.strip()
                if status == "running":
                    self._log.debug(
                        f"Reload operation for {mod_name} is {status}, pid: {pid}"
                        "\nrechecking after 1 second..."
                    )
                    time.sleep(1)
                else:
                    self._log.debug(
                        f"Reload operation for {mod_name} is {status}, pid: {pid}"
                    )
                    break
            except Exception as e:
                self._log.debug(
                    "An exception is caught, this could be due to the VM network "
                    f"going down during the module reload operation, {e}"
                    f"\nTime elapsed so far: {timer.elapsed(False)} seconds, "
                    "\nTrying to reconnect to the remote node in 2 sec..."
                )
                time.sleep(2)

        self._log.debug(
            f"Time taken to reload {mod_name}: {timer.elapsed(False)} seconds"
        )

        # in few OSes escape sequence is needed to be added. For example, this:
        # grep -E 'insmod /lib/modules/6.12.41+deb13-cloud-arm64/kernel/drivers/net
        # /hyperv/hv_netvsc.ko.xz' /home/lisatest/nohup_log_hv_netvsc_b8bc.out | wc -l
        # will have to be changed to this:
        # grep -E 'insmod\ /lib/modules/6\.12\.41\+deb13\-cloud\-arm64/kernel/drivers
        # /net/hyperv/hv_netvsc\.ko\.xz' /home/lisatest/nohup_log_hv_net14967835.out
        #  | wc -l
        # in order to get the correct count of insmod commands executed.

        module_path = re.escape(
            self.node.tools[Modinfo].get_filename(mod_name=mod_name)
        )

        rmmod_count = int(
            self.node.execute(
                f"grep -E 'rmmod {mod_name}' {nohup_output_log_file_name} | wc -l",
                sudo=True,
                shell=True,
            ).stdout.strip()
        )
        insmod_count = int(
            self.node.execute(
                f"grep -E 'insmod {module_path}' {nohup_output_log_file_name} | wc -l",
                sudo=True,
                shell=True,
            ).stdout.strip()
        )
        in_use_count = int(
            self.node.execute(
                f"grep -o 'is in use' {nohup_output_log_file_name} | wc -l",
                sudo=True,
                shell=True,
            ).stdout.strip()
        )
        device_or_resource_busy_count = int(
            self.node.execute(
                f"grep -o 'Device or resource busy' {nohup_output_log_file_name} "
                "| wc -l",
                sudo=True,
                shell=True,
            ).stdout.strip()
        )

        if cleanup_logs:
            self.node.execute(
                f"rm -f {nohup_output_log_file_name} {loop_process_pid_file_name}",
                sudo=True,
                shell=True,
            )

        return {
            "module_exists": True,
            "rmmod_count": rmmod_count,
            "insmod_count": insmod_count,
            "in_use_count": in_use_count,
            "busy_count": device_or_resource_busy_count,
        }

    def load_by_file(
        self, file_name: str, ignore_error: bool = False
    ) -> ExecutableResult:
        # the insmod support to load from file.
        result = self.node.execute(
            f"insmod {file_name}",
            sudo=True,
            shell=True,
        )
        if not ignore_error:
            result.assert_exit_code(0, f"failed to load module {file_name}")
        return result

    def _collect_logs(self, mod_name: str) -> None:
        self._log.info(
            f"Failed to remove module {mod_name}."
            " Collecting additional debug information."
        )
        self._log_lsmod_status(mod_name)
        self._tail_dmesg_log()
        self._tail_journalctl_for_module(mod_name)

    def _log_lsmod_status(self, mod_name: str) -> None:
        lsmod_tool = self.node.tools[Lsmod]
        module_exists = lsmod_tool.module_exists(
            mod_name=mod_name,
            force_run=True,
            no_debug_log=True,
        )
        if not module_exists:
            self._log.info(f"Module {mod_name} does not exist in lsmod output.")
        else:
            self._log.info(f"Module {mod_name} exists in lsmod output.")
            usedby_count, usedby_modules = lsmod_tool.get_used_by_modules(
                mod_name, sudo=True, force_run=True
            )
            if usedby_count == 0:
                self._log.info(f"Module '{mod_name}' is not used by any other modules.")
            else:
                self._log.info(
                    f"Module {mod_name} is used by {usedby_count} modules. "
                    f"Module names: '{usedby_modules}'"
                )

    def _tail_dmesg_log(self) -> None:
        dmesg_tool = self.node.tools[Dmesg]
        tail_lines = 20

        dmesg_output = dmesg_tool.get_output(
            force_run=True, no_debug_log=True, tail_lines=tail_lines
        )

        self._log.info(f"Last {tail_lines} dmesg lines: {dmesg_output}")

    def _tail_journalctl_for_module(self, mod_name: str) -> None:
        tail_lines = 20
        journalctl_tool = self.node.tools[Journalctl]
        journalctl_out = journalctl_tool.filter_logs_by_pattern(
            mod_name,
            tail_line_count=tail_lines,
            no_debug_log=True,
            no_error_log=True,
            no_info_log=True,
        )
        self._log.info(
            f"Last {tail_lines} journalctl lines for module {mod_name}:\n"
            f"{journalctl_out}"
        )


class ModprobeFreeBSD(Modprobe):
    def module_exists(self, modules: Union[str, List[str]]) -> bool:
        module_list = []
        if isinstance(modules, str):
            module_list.append(modules)
        for module in module_list:
            if not self.node.tools[KLDStat].module_exists(module):
                return False

        return True

    def load(
        self,
        modules: Union[str, List[str]],
        parameters: str = "",
        dry_run: bool = False,
    ) -> bool:
        if parameters:
            raise UnsupportedOperationException(
                "ModprobeBSD does not support loading modules with parameters"
            )
        if dry_run:
            raise UnsupportedOperationException("ModprobeBSD does not support dry-run")
        if isinstance(modules, list):
            for module in modules:
                if self.module_exists(module):
                    return True
                else:
                    self.node.tools[KLDLoad].load(module)
        else:
            if self.module_exists(modules):
                return True
            else:
                self.node.tools[KLDLoad].load(modules)
        return True


class KLDLoad(Tool):
    _MODULE_DRIVER_MAPPING = {
        "mlx5_core": "mlx5en",
        "mlx4_core": "mlx4en",
        "mlx5_ib": "mlx5ib",
    }

    @property
    def command(self) -> str:
        return "kldload"

    def load(self, module: str) -> bool:
        if module in self._MODULE_DRIVER_MAPPING:
            module = self._MODULE_DRIVER_MAPPING[module]
        result = self.run(
            f"{module}",
            sudo=True,
            shell=True,
        )
        result.assert_exit_code(
            expected_exit_code=0,
            message=f"Fail to load module: {module}.",
            include_output=True,
        )
        return True
