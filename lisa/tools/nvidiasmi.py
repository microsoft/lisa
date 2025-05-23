# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from lisa.executable import Tool
from lisa.tools.dmesg import Dmesg
from lisa.tools.journalctl import Journalctl
from lisa.tools.lsmod import Lsmod
from lisa.tools.lspci import Lspci
from lisa.util import LisaException


class NvidiaSmi(Tool):
    # tuple of gpu device names and their device id pattern
    # e.g. Tesla GPU device has device id "47505500-0001-0000-3130-444531303244"
    # A10-4Q device id "56475055-0002-0000-3130-444532323336"
    gpu_devices = (
        ("Tesla", "47505500", 0),
        ("A100", "44450000", 6),
        ("H100", "44453233", 0),
        ("A10-4Q", "56475055", 0),
        ("A10-8Q", "3e810200", 0),
        ("GB200", "42333130", 0),
    )

    @property
    def command(self) -> str:
        return "nvidia-smi"

    @property
    def can_install(self) -> bool:
        return False

    def get_gpu_count(self) -> int:
        result = self.run("-L")
        if result.exit_code != 0 or (result.exit_code == 0 and result.stdout == ""):
            self._log.warning(
                "First attempt to run nvidia-smi -L failed or returned empty. "
                "Retrying with sudo."
            )
            result = self.run("-L", sudo=True)
            if result.exit_code != 0 or (
                result.exit_code == 0 and result.stdout == ""
            ):
                self._log.error(
                    f"nvidia-smi -L failed even with sudo. "
                    f"Exit code: {result.exit_code}, "
                    f"stdout: '{result.stdout}'. "
                    "Attempting to gather debug information."
                )
                self._debug_driver_issues()  # Call the debug helper
                raise LisaException(
                    f"Nvidia-smi command failed (exit code: {result.exit_code}, "
                    f"stdout: '{result.stdout}'). Suspected NVIDIA driver or "
                    "setup issue. Check debug logs for more details."
                )
        gpu_types = [x[0] for x in self.gpu_devices]
        device_count = 0
        for gpu_type in gpu_types:
            device_count += result.stdout.count(gpu_type)

        return device_count

    def _debug_driver_issues(self) -> None:
        """
        Collects and logs debug information when nvidia-smi fails, to help diagnose
        NVIDIA driver issues.
        """
        self._log.info(
            "nvidia-smi command failed. "
            "Collecting debug information for NVIDIA driver."
        )
        self._debug_pci_devices()
        self._debug_kernel_modules()
        self._debug_dmesg()
        self._debug_journalctl()
        self._log.info("Finished collecting debug information for NVIDIA driver.")

    def _debug_pci_devices(self) -> None:
        # 1. Check PCI devices and their drivers
        try:
            lspci_tool = self.node.tools[Lspci]
            lspci_params = "-nnk | grep -iA3 nvidia"
            lspci_out = lspci_tool.run(
                lspci_params,
                shell=True,
                sudo=True,
                timeout=120,
                expected_exit_code=None,
                expected_exit_code_failure_message=(
                    "lspci command execution failed unexpectedly."
                ),
            )
            if lspci_out.exit_code == 0 and lspci_out.stdout.strip():
                self._log.debug(
                    "NVIDIA PCI devices, kernel drivers, and modules:\n"
                    f"{lspci_out.stdout.strip()}"
                )
            elif lspci_out.exit_code == 1:
                self._log.debug(
                    "No NVIDIA devices found via 'lspci -nnk | grep -iA3 nvidia'. "
                    "This might indicate the hardware is not detected at PCI level, "
                    "the grep pattern needs adjustment, or no NVIDIA driver is "
                    "claiming the device."
                )
            else:
                self._log.warning(
                    f"lspci command for NVIDIA returned unexpected exit code: "
                    f"{lspci_out.exit_code}. Stdout: {lspci_out.stdout}. "
                    f"Stderr: {lspci_out.stderr}"
                )
        except Exception as e:
            self._log.warning(f"Failed to get lspci info for NVIDIA: {e}")

    def _debug_kernel_modules(self) -> None:
        # 2. Check loaded kernel modules
        try:
            lsmod_tool = self.node.tools[Lsmod]
            lsmod_params = "| grep nvidia"
            lsmod_out = lsmod_tool.run(
                lsmod_params,
                shell=True,
                sudo=True,
                timeout=60,
                expected_exit_code=None,
                expected_exit_code_failure_message=(
                    "lsmod command execution failed unexpectedly."
                ),
            )
            if lsmod_out.exit_code == 0 and lsmod_out.stdout.strip():
                self._log.debug(
                    "Loaded NVIDIA kernel modules (lsmod):\n"
                    f"{lsmod_out.stdout.strip()}"
                )
            elif lsmod_out.exit_code == 1:
                self._log.debug(
                    "No NVIDIA kernel modules found via 'lsmod | grep nvidia'. "
                    "This is a strong indicator the NVIDIA driver modules "
                    "are not loaded."
                )
            else:
                self._log.warning(
                    f"lsmod command for NVIDIA returned unexpected exit code: "
                    f"{lsmod_out.exit_code}. Stdout: {lsmod_out.stdout}. "
                    f"Stderr: {lsmod_out.stderr}"
                )
        except Exception as e:
            self._log.warning(f"Failed to get lsmod info for NVIDIA: {e}")

    def _debug_dmesg(self) -> None:
        # 3. Check dmesg for errors related to nvidia, nouveau, or drm
        try:
            dmesg_tool = self.node.tools[Dmesg]
            dmesg_output = dmesg_tool.get_output(force_run=True)
            relevant_dmesg_lines = [
                line
                for line in dmesg_output.splitlines()
                if "nvidia" in line.lower()
                or "nouveau" in line.lower()
                or "drm" in line.lower()
            ]
            if relevant_dmesg_lines:
                self._log.debug(
                    "Relevant dmesg logs (nvidia, nouveau, drm) "
                    "(last 20 lines):\n"
                    + "\n".join(relevant_dmesg_lines[-20:])
                )
            else:
                self._log.debug(
                    "No specific nvidia, nouveau, or drm messages found in dmesg."
                )
        except Exception as e:
            self._log.warning(f"Failed to get and parse dmesg info: {e}")

    def _debug_journalctl(self) -> None:
        # 4. Check journalctl for kernel errors related to NVIDIA/Nouveau/DRM
        try:
            journalctl_tool = self.node.tools[Journalctl]
            journalctl_params = (
                "-k -p err -b --no-pager "
                "| grep -Ei 'nvidia|nouveau|drm' | tail -n 20"
            )
            journal_out = journalctl_tool.run(
                journalctl_params,
                shell=True,
                sudo=True,
                timeout=120,
                expected_exit_code=None,
                expected_exit_code_failure_message=(
                    "journalctl command execution failed unexpectedly."
                ),
            )
            if journal_out.exit_code == 0 and journal_out.stdout.strip():
                self._log.debug(
                    "Recent kernel error messages (journalctl) related to "
                    "NVIDIA/Nouveau/DRM:\n"
                    f"{journal_out.stdout.strip()}"
                )
            elif journal_out.exit_code == 1:
                self._log.debug(
                    "No recent kernel error messages for NVIDIA/Nouveau/DRM "
                    "found in journalctl (-k -p err -b | grep)."
                )
            else:
                self._log.warning(
                    f"journalctl command for NVIDIA returned unexpected exit code: "
                    f"{journal_out.exit_code}. Stdout: {journal_out.stdout}. "
                    f"Stderr: {journal_out.stderr}"
                )
        except Exception as e:
            self._log.warning(
                f"Failed to get journalctl info for NVIDIA/Nouveau/DRM: {e}"
            )
