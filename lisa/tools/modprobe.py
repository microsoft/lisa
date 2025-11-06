# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
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

    # hv_netvsc needs a special case, since reloading it has the potential
    # to leave the node without a network connection if things go wrong.
    def _reload_hv_netvsc(self) -> None:
        # These commands must be sent together, bundle them up as one line
        # If the VM is disconnected after running below command, wait 60s is enough.
        # Don't need to wait the default timeout 600s. So set timeout 60.
        self.node.execute(
            "modprobe -r hv_netvsc; modprobe hv_netvsc; "
            "ip link set eth0 down; ip link set eth0 up;"
            "dhclient -r eth0; dhclient eth0",
            sudo=True,
            shell=True,
            nohup=True,
            timeout=60,
        )

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

        # Copy the modprobe_reloader.sh script to the remote node/VM
        script_local_path = Path(__file__).parent.joinpath("scripts", "modprobe_reloader.sh")
        script_remote_path = f"/home/{username}/modprobe_reloader.sh"
        

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
        # Capture baseline dmesg for module before starting script
        baseline_dmesg_lines = 0
        self._log.info(f"DEBUG: mod_name is '{mod_name}', type: {type(mod_name)}")
        try:
            baseline_result = self.node.execute(
                f"dmesg | grep {mod_name} | wc -l",
                sudo=True,
                shell=True,
                no_info_log=True,
                no_error_log=True,
            )
            baseline_dmesg_lines = int(baseline_result.stdout.strip())
            self._log.info(f"Baseline dmesg lines for {mod_name}: {baseline_dmesg_lines}")
        except Exception as e:
            self._log.debug(f"Failed to get baseline dmesg count: {e}")

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

        # Capture new dmesg messages generated after script started
        try:
            # Get current total lines
            current_result = self.node.execute(
                f"dmesg | grep {mod_name} | wc -l",
                sudo=True,
                shell=True,
                no_info_log=True,
                no_error_log=True,
            )
            current_dmesg_lines = int(current_result.stdout.strip())
            self._log.info(f"Current dmesg lines for {mod_name}: {current_dmesg_lines} (baseline was {baseline_dmesg_lines})")
            
            if current_dmesg_lines > baseline_dmesg_lines:
                # Get all dmesg lines for module after script execution
                new_dmesg_result = self.node.execute(
                    f"dmesg | grep {mod_name} | tail -n +{baseline_dmesg_lines + 1}",
                    sudo=True,
                    shell=True,
                    no_info_log=True,
                    no_error_log=True,
                )
                if new_dmesg_result.stdout.strip():
                    self._log.info(
                        f"New dmesg messages for {mod_name} generated during script execution:\n"
                        f"{new_dmesg_result.stdout}"
                    )
                else:
                    self._log.info(f"No new dmesg content found for {mod_name}")
            else:
                self._log.info(f"No new dmesg messages found for {mod_name} (count unchanged)")
        except Exception as e:
            self._log.debug(f"Failed to get new dmesg messages: {e}")

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

        module_path_raw = self.node.tools[Modinfo].get_filename(mod_name=mod_name)
        module_file_base_name = os.path.basename(module_path_raw)

        rmmod_count = int(
            self.node.execute(
                f"grep -E 'rmmod {mod_name}' {nohup_output_log_file_name} | wc -l",
                sudo=True,
                shell=True,
            ).stdout.strip()
        )

        insmod_count = int(
            self.node.execute(
                f"grep -E 'insmod .*{module_file_base_name}' "
                f"{nohup_output_log_file_name} | wc -l",
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

        # Print the complete nohup log file content for debugging
        try:
            nohup_log_content = self.node.execute(
                f"cat {nohup_output_log_file_name}",
                sudo=True,
                shell=True,
                no_info_log=True,
                no_error_log=True,
            )
            if nohup_log_content.stdout.strip():
                self._log.info(
                    f"Complete nohup log content for {mod_name}:\n"
                    f"{'='*50}\n"
                    f"{nohup_log_content.stdout}\n"
                    f"{'='*50}"
                )
            else:
                self._log.info(f"Nohup log file {nohup_output_log_file_name} is empty")
        except Exception as e:
            self._log.debug(f"Failed to read nohup log file: {e}")

        # Commented out log cleanup to preserve logs for debugging
        # if cleanup_logs:
        #     self.node.execute(
        #         f"rm -f {nohup_output_log_file_name} {loop_process_pid_file_name}",
        #         sudo=True,
        #         shell=True,
        #     )

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
