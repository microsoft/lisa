# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, List, Optional, Type, Union

from lisa.executable import ExecutableResult, Tool
from lisa.tools.dmesg import Dmesg
from lisa.tools.kernel_config import KLDStat
from lisa.tools.lsmod import Lsmod
from lisa.util import UnsupportedOperationException


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
                    try:
                        # This call will raise ExecutableException on failure
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
                        self._debug_modprobe_remove_failure(mod_name)
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
        mod_names: List[str],
    ) -> None:
        for mod_name in mod_names:
            if self.is_module_loaded(mod_name, force_run=True):
                # hv_netvsc reload requires resetting the network interface
                if mod_name == "hv_netvsc":
                    # handle special case
                    self._reload_hv_netvsc()
                else:
                    # execute the command for regular non-network modules
                    self.node.execute(
                        f"modprobe -r {mod_name}; modprobe {mod_name};",
                        sudo=True,
                        shell=True,
                    )

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

    def _debug_modprobe_remove_failure(self, mod_name: str) -> None:
        """
        Helper function to log debug information when modprobe -r fails.
        """
        self._log.info(
            f"Failed to remove module {mod_name}. "
            f"Collecting additional debug information."
        )

        # Use Lsmod tool to check current status of the module
        lsmod_tool = self.node.tools[Lsmod]
        lsmod_output = lsmod_tool.run(
            sudo=True, force_run=True, expected_exit_code=0
        ).stdout
        # Manually filter for the module, similar to 'grep mod_name || true'
        filtered_lsmod_output = "\\\\n".join(
            [line for line in lsmod_output.splitlines() if mod_name in line]
        )
        if not filtered_lsmod_output:  # if grep finds nothing
            filtered_lsmod_output = (
                f"(Module {mod_name} not found in lsmod output)"
            )

        self._log.info(
            f"Debug: Output of lsmod for {mod_name}:\\\\n"
            f"{filtered_lsmod_output}"
        )

        # Use Dmesg tool for recent kernel messages
        dmesg_tool = self.node.tools[Dmesg]
        dmesg_output = dmesg_tool.get_output(force_run=True)
        dmesg_lines = dmesg_output.splitlines()
        # Get last 20 lines, similar to 'tail -n 20'
        recent_dmesg_output = "\\\\n".join(dmesg_lines[-20:])
        self._log.info(
            f"Debug: Recent dmesg output (last 20 lines):\\\\n"
            f"{recent_dmesg_output}"
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
