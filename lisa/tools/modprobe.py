# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, List, Optional, Type, Union, cast

from lisa.executable import ExecutableResult, Tool
from lisa.tools.kernel_config import KLDStat
from lisa.tools import Cat, Dhclient
from lisa.util import UnsupportedOperationException
from random import randint
import time
from lisa.util.perf_timer import create_timer
import spur
import os
from pathlib import Path
from lisa.executable import CustomScriptBuilder
from .whoami import Whoami
from lisa.util.shell import try_connect

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
                    self.run(
                        f"-r {mod_name}",
                        force_run=True,
                        sudo=True,
                        shell=True,
                        expected_exit_code=0,
                        expected_exit_code_failure_message="Fail to remove module "
                        f"{mod_name}",
                    )

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
        nohup: bool = False,
    ) -> str:
        if not self.is_module_loaded(mod_name, force_run=True):
            return

        dhclient_renew_command = self.node.tools[Dhclient].generate_renew_command() if mod_name == "hv_netvsc" else ""

        username = self.node.tools[Whoami].get_username()
        unique_id = randint(0, 10000)
        nohup_output_log_file_name = f"/tmp/nohup_log_{mod_name}_{str(unique_id)}.out"
        loop_process_pid_file_name = (
            f"/home/{username}/loop_process_pid_{mod_name}_{str(unique_id)}.pid"
        )

        # if mod_name == "hv_netvsc":
        #     # hv_netvsc needs a special case, since reloading it has the potential
        #     # to leave the node without a network connection if things go wrong.

        #     # These commands must be sent together, bundle them up as one line
        #     # If the VM is disconnected after running below command, wait 60s is enough.
        #     # however, go with bigger timeout if times > 1 (multiple times of reload)
        #     renew_command = self.node.tools[Dhclient].generate_renew_command()
        #     reload_command = f"(for i in $(seq 1 {times}); do modprobe -r {v}{mod_name} >> {nohup_output_log_file_name} 2>&1; modprobe {v}{mod_name} >> {nohup_output_log_file_name} 2>&1; done; sleep 1; ip link set eth0 down; ip link set eth0 up; {renew_command}) & echo $! > {loop_process_pid_file_name}"
        # else:
        #     reload_command = f"(for i in $(seq 1 {times}); do modprobe -r {v}{mod_name} >> {nohup_output_log_file_name} 2>&1; modprobe {v}{mod_name} >> {nohup_output_log_file_name} 2>&1; done) & echo $! > {loop_process_pid_file_name}"

        # self.node.execute(reload_command, sudo=True, nohup=nohup, shell=True)
        
        # Dynamically determine the script path relative to this file
        # script_dir = os.path.dirname(os.path.abspath(__file__))
        # script_path = os.path.join(script_dir, "..", "microsoft", "utils", "modprobe_reloader.sh")

        if verbose:
            verbose_flag = "true"
        else:
            verbose_flag = "false"

        modprobe_reloader_tool = CustomScriptBuilder(
            Path(__file__).parent.joinpath("scripts"), ["modprobe_reloader.sh"]
        )
        # parameters = f"{mod_name} {times} {v} {nohup_output_log_file_name} {loop_process_pid_file_name} \"{dhclient_renew_command}\""

        parameters = f"{nohup_output_log_file_name} {loop_process_pid_file_name} {mod_name} {times} {verbose_flag} \"{dhclient_renew_command}\""
        # self.node.tools[modprobe_reloader_tool].run()
        self.node.tools[modprobe_reloader_tool].run(parameters)
        # time.sleep(10)
        # Construct the command to execute the shell script
        # command = f"{script_path} {mod_name} {times} {v} {nohup_output_log_file_name} {loop_process_pid_file_name} \"{dhclient_renew_command}\""

        # self.node.execute(command, sudo=True, nohup=nohup, shell=True)
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
                        "rechecking after 1 second..."
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
                    "\nTrying to reconnect to the remote node..."
                )
                
                time.sleep(5)
                # from lisa.node import RemoteNode
                # remote_node = cast(RemoteNode, self.node)
                # try:
                #     try_connect(remote_node.connection_info)
                # except Exception as reconnect_error:
                #     self._log.error(
                #         f"Failed to reconnect to the remote node: {reconnect_error}"
                #     )

                # self._log.debug(
                #     "Retrying to check the loop process status..."
                # )

        self._log.debug(
            f"Time taken to reload {mod_name}: {timer.elapsed(False)} seconds"
        )

        rmmod_count = int(
            self.node.execute(
                f"grep -o 'rmmod' {nohup_output_log_file_name} | wc -l",
                sudo=True,
                shell=True,
            ).stdout.strip()
        )
        insmod_count = int(
            self.node.execute(
                f"grep -o 'insmod' {nohup_output_log_file_name} | wc -l",
                sudo=True,
                shell=True,
            ).stdout.strip()
        )
        is_in_use_count = int(
            self.node.execute(
                f"grep -o 'is in use' {nohup_output_log_file_name} | wc -l",
                sudo=True,
                shell=True,
            ).stdout.strip()
        )
        device_or_resource_busy_count = int(
            self.node.execute(
                f"grep -o 'Device or resource busy' {nohup_output_log_file_name} | wc -l",
                sudo=True,
                shell=True,
            ).stdout.strip()
        )

        # self.node.execute(
        #     f"rm -f {nohup_output_log_file_name} {loop_process_pid_file_name}",
        #     sudo=True,
        #     shell=True,
        # )

        return {
            "rmmod_count": rmmod_count,
            "insmod_count": insmod_count,
            "in_use_count": is_in_use_count,
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
