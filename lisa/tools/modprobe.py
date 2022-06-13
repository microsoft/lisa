# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, List, Union

from lisa.executable import Tool


class Modprobe(Tool):
    @property
    def command(self) -> str:
        return self._command

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
                self.node.execute(f"rmmod {mod_name}", sudo=True)
            else:
                if self.is_module_loaded(mod_name, force_run=True):
                    self.run(
                        f"-r {mod_name}",
                        force_run=True,
                        sudo=True,
                        expected_exit_code=0,
                        expected_exit_code_failure_message="Fail to remove module "
                        f"{mod_name}",
                    )

    def load(
        self,
        modules: Union[str, List[str]],
        dry_run: bool = False,
    ) -> bool:

        if isinstance(modules, list):
            modules_str = "-a " + " ".join(modules)
        else:
            modules_str = modules
        command = f"{modules_str}"
        if dry_run:
            command = f"--dry-run {command}"
        result = self.run(
            command,
            force_run=True,
            sudo=True,
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
                self.node.execute(
                    (
                        f"modprobe -r {mod_name} && modprobe {mod_name} && "
                        "ip link set eth0 down && ip link set eth0 up && "
                        "dhclient -r && dhclient"
                    ),
                    sudo=True,
                    shell=True,
                )

    def load_by_file(self, file_name: str) -> None:
        # the insmod support to load from file.
        self.node.execute(
            f"insmod {file_name}",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"failed to load module {file_name}",
        )
