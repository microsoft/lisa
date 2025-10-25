# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
import re
from typing import Any, Dict, List, Optional, Type, cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Git, Make
from lisa.util import LisaException, find_patterns_in_lines
from lisa.util.process import ExecutableResult


class Nvmecli(Tool):
    repo = "https://github.com/linux-nvme/nvme-cli"
    # error_count\t: 0
    __error_count_pattern = re.compile(r"^error_count.*:[ ]+([\d]+)\r?$", re.M)
    # [3:3] : 0     NS Management and Attachment Supported
    __ns_management_attachement_support = "NS Management and Attachment Supported"
    # [1:1] : 0x1   Format NVM Supported
    __format_device_support = "Format NVM Supported"
    # Higher version nvme-cli add a mandatory parameter `--block-size` after
    #  v1.6 (not included)
    # https://github.com/linux-nvme/nvme-cli/blob/v1.7/nvme.c#L3040
    # FLBAS corresponding to block size 0 not found
    # Please correct block size, or specify FLBAS directly
    __missing_block_size_parameter = "FLBAS corresponding to block size 0 not found"
    # '/dev/nvme0n1          351f1f720e5a00000001 Microsoft NVMe Direct Disk               1           0.00   B /   1.92  TB    512   B +  0 B   NVMDV001' # noqa: E501
    _namespace_cli_pattern = re.compile(
        r"(?P<namespace>/dev/nvme[0-9]n[0-9])", re.MULTILINE
    )

    @property
    def command(self) -> str:
        return "nvme"

    @property
    def can_install(self) -> bool:
        return True

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return BSDNvmecli

    def _install_from_src(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages([Git, Make, "pkg-config"])
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path)
        make = self.node.tools[Make]
        code_path = tool_path.joinpath("nvme-cli")
        make.make_install(cwd=code_path)

    def create_namespace(self, namespace: str) -> ExecutableResult:
        cmd_result = self.run(f"create-ns {namespace}", shell=True, sudo=True)
        if self.__missing_block_size_parameter in cmd_result.stdout:
            cmd_result = self.run(
                f"create-ns {namespace} --block-size 4096", shell=True, sudo=True
            )
        return cmd_result

    def delete_namespace(self, namespace: str, id_: int) -> ExecutableResult:
        return self.run(f"delete-ns -n {id_} {namespace}", shell=True, sudo=True)

    def detach_namespace(self, namespace: str, id_: int) -> ExecutableResult:
        return self.run(f"detach-ns -n {id_} {namespace}", shell=True, sudo=True)

    def format_namespace(self, namespace: str) -> ExecutableResult:
        return self.run(f"format {namespace}", shell=True, sudo=True)

    def install(self) -> bool:
        if not self._check_exists():
            posix_os: Posix = cast(Posix, self.node.os)
            package_name = "nvme-cli"
            posix_os.install_packages(package_name)
            if not self._check_exists():
                self._install_from_src()
        return self._check_exists()

    def get_error_count(self, namespace: str) -> int:
        error_log = self.run(f"error-log {namespace}", shell=True, sudo=True)
        error_count = 0
        # for row in error_log.stdout.splitlines():
        errors = find_patterns_in_lines(error_log.stdout, [self.__error_count_pattern])
        if errors[0]:
            error_count = sum([int(element) for element in errors[0]])
        return error_count

    def support_ns_manage_attach(self, device_name: str) -> bool:
        cmd_result = self.run(f"id-ctrl -H {device_name}", shell=True, sudo=True)
        cmd_result.assert_exit_code()
        return self.__ns_management_attachement_support in cmd_result.stdout

    def support_device_format(self, device_name: str) -> bool:
        cmd_result = self.run(f"id-ctrl -H {device_name}", shell=True, sudo=True)
        cmd_result.assert_exit_code()
        return self.__format_device_support in cmd_result.stdout

    def get_namespaces(self, force_run: bool = False) -> List[str]:
        namespaces_cli = []
        nvme_list = self.run("list", shell=True, sudo=True, force_run=force_run)
        for row in nvme_list.stdout.splitlines():
            matched_result = self._namespace_cli_pattern.match(row)
            if matched_result:
                namespaces_cli.append(matched_result.group("namespace"))
        return namespaces_cli

    def get_devices(self, force_run: bool = False) -> Any:
        # get nvme devices information ignoring stderror
        nvme_list = self.run(
            "list -o json 2>/dev/null",
            shell=True,
            sudo=True,
            force_run=force_run,
            no_error_log=True,
        )
        # NVMe list command returns empty string when no NVMe devices are found.
        if not nvme_list.stdout:
            raise LisaException(
                "No NVMe devices found. "
                "The 'nvme list' command returned an empty string."
            )
        nvme_devices = json.loads(nvme_list.stdout)
        return nvme_devices["Devices"]

    # def get_disks(self, force_run: bool = False) -> List[str]:
    #     nvme_devices = self.get_devices(force_run=force_run)
    #     return [device["DevicePath"] for device in nvme_devices]

    # def get_disks(self, force_run: bool = False) -> List[str]:
    #     """
    #     Return NVMe device nodes (e.g., /dev/nvme0n1) in a way that works across
    #     nvme-cli JSON schema versions.

    #     Rationale:
    #     - Upstream nvme-cli changed the JSON structure in v2.11+, removing the old
    #     top-level `.Devices[].DevicePath` and nesting device info under:
    #     Subsystems → Controllers → Namespaces.
    #     - Reference: JSON rework discussion and breakage report:
    #     https://github.com/linux-nvme/nvme-cli/issues/2749
    #     (mentions commit 929f461 as the change point)
    #     - This jq program first uses legacy `.DevicePath` when present and otherwise
    #     walks the new nested structure to reconstruct `/dev/<NameSpace>` paths.

    #     Requirements:
    #     - `jq` must be available on the target system.
    #     """

    #     cmd = r"""list -o json 2>/dev/null | jq -r '
    #     .Devices[]? as $d |
    #     if ($d | has("DevicePath")) and ($d.DevicePath != null) then
    #         # Legacy / RHEL-patched builds: use the flat field directly
    #         $d.DevicePath
    #     else
    #         # Newer schema: Subsystems → Controllers → Namespaces → NameSpace
    #         [$d.Subsystems[]? | .Controllers[]? | .Namespaces[]? | "/dev/" + (.NameSpace // "")]
    #         | map(select(length > 5))    # drop empties like "/dev/"
    #         | .[]
    #     end
    #     '"""

    #     result = self.run(
    #         cmd,
    #         shell=True,
    #         sudo=True,
    #         force_run=force_run,
    #         no_error_log=True,
    #     )

    #     nodes = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
    #     if not nodes:
    #         raise LisaException(
    #             "No NVMe devices found. The jq-based pipeline returned no paths."
    #         )
    #     return nodes

    def get_disks(self, force_run: bool = False) -> List[str]:
        """
        Return NVMe device nodes (`/dev/...`) robustly across nvme-cli schemas.

        Upstream change context:
        - nvme-cli reworked `nvme list -o json` around v2.11, removing the
            legacy top-level `.Devices[].DevicePath` and nesting device info under:
            Subsystems → Controllers → Namespaces.
        - Reference discussion and breakage report:
            https://github.com/linux-nvme/nvme-cli/issues/2749
            (thread points to commit 929f461 as the change introducing the new JSON)
        - Some distro builds (e.g., certain RHEL package revisions) may still
            emit `DevicePath`. This logic supports both.

        - jq option is implemented to simplify parsing, but a pure-Python
            fallback is also provided if `jq` is not available on the target system.
            jq option is more efficient and robust, so it is preferred when possible.
        Returns:
            List[str]: device nodes like `/dev/nvme0n1`
        """

        check = self.node.execute("command -v jq", shell=True, sudo=True, no_error_log=True)
        # a new tool for jq can also be written if used frequently
        if check.exit_code != 0 or not (check.stdout or "").strip():
            use_jq = False
        else:
            use_jq = True
        use_jq = False  # temporarily disable jq usage due to test environment issues
        if use_jq:
            # -------------------------------
            # jq pipeline
            # -------------------------------
            # Rationale: First prefer legacy `.DevicePath` if present, else build
            # `/dev/<NameSpace>` from the new nested schema.
            # Reference: https://github.com/linux-nvme/nvme-cli/issues/2749

            cmd = r"""list -o json 2>/dev/null | jq -r '
            .Devices[]? as $d |
            if ($d | has("DevicePath")) and ($d.DevicePath != null) then
                # Legacy / RHEL-patched builds: use the flat field directly
                $d.DevicePath
            else
                # Newer schema: Subsystems → Controllers → Namespaces → NameSpace
                [$d.Subsystems[]? | .Controllers[]? | .Namespaces[]? | "/dev/" + (.NameSpace // "")]
                | map(select(length > 5))    # drop empties like "/dev/"
                | .[]
            end
            '"""

            result = self.run(
                cmd,
                shell=True,
                sudo=True,
                force_run=force_run,
                no_error_log=True,
            )

            nodes = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
            if not nodes:
                raise LisaException(
                    "No NVMe devices found. The jq-based pipeline returned no paths."
                )
            return nodes
        else:
            # -------------------------------
            # Pure Python (no jq)
            # -------------------------------
            nvme_devices = self.get_devices(force_run=force_run)  # raw ["Devices"]
            nodes: List[str] = []

            def _add(p: str) -> None:
                if isinstance(p, str) and p.startswith("/dev/") and len(p) > 5:
                    nodes.append(p)

            for d in nvme_devices or []:
                # Legacy schema (flat fields):
                _add(d.get("DevicePath"))
                _add(d.get("GenericPath"))

                # New schema: Subsystems → Controllers → Namespaces
                for ss in (d.get("Subsystems") or []):
                    for ctrl in (ss or {}).get("Controllers") or []:
                        for ns in (ctrl or {}).get("Namespaces") or []:
                            ns_name = ns.get("NameSpace")   # e.g., "nvme0n1"
                            gen_name = ns.get("Generic")    # e.g., "ng0n1"
                            if isinstance(ns_name, str) and ns_name:
                                _add(f"/dev/{ns_name}")
                            if isinstance(gen_name, str) and gen_name:
                                _add(f"/dev/{gen_name}")

            nodes = sorted(set(nodes))
            if not nodes:
                raise LisaException(
                    "No NVMe device nodes could be derived from 'nvme list -o json'."
                )
            return nodes


    # NVME namespace ids are unique for each disk under any NVME controller.
    # These are useful in detecting the lun id of the remote azure disk disks.
    # Example output of nvme -list -o json and nvme -list
    # root@lisa--170-e0-n0:/home/lisa# nvme -list -o json
    # {
    #  "Devices" : [
    #    {
    #      "NameSpace" : 1,
    #      "DevicePath" : "/dev/nvme0n1",
    #      "Firmware" : "v1.00000",
    #      "Index" : 0,
    #      "ModelNumber" : "MSFT NVMe Accelerator v1.0",
    #      "ProductName" : "Non-Volatile memory controller: Microsoft Corporation Device 0x00a9",  # noqa: E501
    #      "SerialNumber" : "SN: 000001",
    #      "UsedBytes" : 536870912000,
    #      "MaximumLBA" : 1048576000,
    #      "PhysicalSize" : 536870912000,
    #      "SectorSize" : 512
    #    },
    #    {
    #      "NameSpace" : 2,
    #      "DevicePath" : "/dev/nvme0n2",
    #      "Firmware" : "v1.00000",
    #      "Index" : 0,
    #      "ModelNumber" : "MSFT NVMe Accelerator v1.0",
    #      "ProductName" : "Non-Volatile memory controller: Microsoft Corporation Device 0x00a9",  # noqa: E501
    #      "SerialNumber" : "SN: 000001",
    #      "UsedBytes" : 4294967296,
    #      "MaximumLBA" : 8388608,
    #      "PhysicalSize" : 4294967296,
    #      "SectorSize" : 512
    #    }
    #   ]
    # }
    # root@lisa--170-e0-n0:/home/lisa# nvme -list
    # Node                  SN                   Model                                    Namespace Usage                      Format           FW Rev   # noqa: E501
    # --------------------- -------------------- ---------------------------------------- --------- -------------------------- ---------------- -------  # noqa: E501
    # /dev/nvme0n1          SN: 000001           MSFT NVMe Accelerator v1.0               1         536.87  GB / 536.87  GB    512   B +  0 B   v1.0000  # noqa: E501
    # /dev/nvme0n2          SN: 000001           MSFT NVMe Accelerator v1.0               2           4.29  GB /   4.29  GB    512   B +  0 B   v1.0000  # noqa: E501
    # /dev/nvme0n3          SN: 000001           MSFT NVMe Accelerator v1.0               15         44.02  GB /  44.02  GB    512   B +  0 B   v1.0000  # noqa: E501
    # /dev/nvme0n4          SN: 000001           MSFT NVMe Accelerator v1.0               14          6.44  GB /   6.44  GB    512   B +  0 B   v1.0000  # noqa: E501
    # /dev/nvme1n1          68e8d42a7ed4e5f90002 Microsoft NVMe Direct Disk v2            1         472.45  GB / 472.45  GB    512   B +  0 B   NVMDV00  # noqa: E501
    # /dev/nvme2n1          68e8d42a7ed4e5f90001 Microsoft NVMe Direct Disk v2            1         472.45  GB / 472.45  GB    512   B +  0 B   NVMDV00  # noqa: E501

    def get_namespace_ids(self, force_run: bool = False) -> List[Dict[str, int]]:
        nvme_devices = self.get_devices(force_run=force_run)
        # Older versions of nvme-cli do not have the NameSpace key in the output
        # skip the test if NameSpace key is not available
        if not nvme_devices:
            raise LisaException("No NVMe devices found. Unable to get namespace ids.")
        if "NameSpace" not in nvme_devices[0]:
            raise LisaException(
                "The version of nvme-cli is too old,"
                " it doesn't support to get namespace ids."
            )

        return [
            {device["DevicePath"]: int(device["NameSpace"])} for device in nvme_devices
        ]


class BSDNvmecli(Nvmecli):
    # nvme0ns1 (1831420MB)
    # nvme10ns12 (1831420MB)
    _namespace_cli_pattern = re.compile(r"(?P<namespace>nvme\d+ns\d+)")
    # nvme0ns1 (10293847MB)
    _devicename_from_namespace_pattern = re.compile(r"(?P<devicename>nvme\d+)ns\d+")
    # Total NVM Capacity:          1920383410176 bytes
    _total_storage_pattern = re.compile(
        r"Total NVM Capacity:\s+(?P<storage>\d+)\s+bytes"
    )
    # Format NVM:                  Supported
    __format_device_support = "Format NVM:                  Supported"
    # Namespace Management:        Supported
    __ns_management_attachement_support = "Namespace Management:        Supported"

    @property
    def command(self) -> str:
        return "nvmecontrol"

    @property
    def can_install(self) -> bool:
        return False

    def get_namespaces(self, force_run: bool = False) -> List[str]:
        output = self.run(
            "devlist",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Unable to get namespaces information",
            force_run=force_run,
        )
        namespaces_cli = []
        matched = find_patterns_in_lines(output.stdout, [self._namespace_cli_pattern])
        if matched[0]:
            matched_namespaces = matched[0]
            for namespace in matched_namespaces:
                namespaces_cli.append(f"/dev/{namespace}")

        return namespaces_cli

    def support_device_format(self, device_name: str) -> bool:
        name_without_dev = device_name.replace("/dev/", "")
        cmd_result = self.run(f"identify {name_without_dev}", shell=True, sudo=True)
        cmd_result.assert_exit_code(
            message=f"Failed to identify settings for {device_name}."
        )
        return self.__format_device_support in cmd_result.stdout

    def support_ns_manage_attach(self, device_name: str) -> bool:
        name_without_dev = device_name.replace("/dev/", "")
        cmd_result = self.run(f"identify {name_without_dev}", shell=True, sudo=True)
        cmd_result.assert_exit_code()
        return self.__ns_management_attachement_support in cmd_result.stdout

    def create_namespace(self, namespace: str) -> ExecutableResult:
        device_name = find_patterns_in_lines(
            namespace, [self._devicename_from_namespace_pattern]
        )[0][0]
        cmd_result = self.run(f"identify {device_name}", shell=True, sudo=True)
        cmd_result.assert_exit_code(
            message="Failed to identify devicename and collect"
            " requirements for namespace creation."
        )
        total_storage_space_in_bytes = find_patterns_in_lines(
            cmd_result.stdout, [self._total_storage_pattern]
        )[0][0]
        # Using the same block size as linux tests of 4096 bytes
        total_storage_space_in_blocks = int(total_storage_space_in_bytes) // 4096
        cmd_result = self.run(
            f"ns create -s {total_storage_space_in_blocks} -c "
            f"{total_storage_space_in_blocks} {device_name}",
            shell=True,
            sudo=True,
        )
        return cmd_result

    def delete_namespace(self, namespace: str, id_: int) -> ExecutableResult:
        device_name = find_patterns_in_lines(
            namespace, [self._devicename_from_namespace_pattern]
        )[0][0]
        return self.run(f"ns delete -n {id_} {device_name}", shell=True, sudo=True)

    def detach_namespace(self, namespace: str, id_: int) -> ExecutableResult:
        device_name = find_patterns_in_lines(
            namespace, [self._devicename_from_namespace_pattern]
        )[0][0]
        return self.run(f"ns detach -n {id_} -c 0 {device_name}", shell=True, sudo=True)

    def format_namespace(self, namespace: str) -> ExecutableResult:
        name_without_dev = namespace.replace("/dev/", "")
        return self.run(f"format {name_without_dev}", shell=True, sudo=True)
