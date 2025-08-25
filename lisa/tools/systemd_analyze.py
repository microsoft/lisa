# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import PurePath

from retry import retry

from lisa.executable import Tool
from lisa.messages import ProvisionBootTimeMessage
from lisa.util import LisaException, find_groups_in_lines


class SystemdAnalyze(Tool):
    # Startup finished in 2.020ms (kernel) + 8.866s (initrd) + 14.894s (userspace) = 25.782s  # noqa: E501
    # Startup finished in 3.312s (kernel) + 37.194s (userspace) = 40.506s  # noqa: E501
    # Startup finished in 4.160s (firmware) + 2.796s (loader) + 5.831s (kernel) + 18.885s (userspace) = 31.673s  # noqa: E501
    # Startup finished in 4.797s (kernel) + 57.966s (userspace) = 1min 2.764s  # noqa: E501
    BOOT_TIME_PATTERN = re.compile(
        r"Startup finished in ((?P<firmware_boot_time>.*) \(firmware\) \+ )?"
        r"((?P<loader_boot_time>.*) \(loader\) \+ )?(?P<kernel_boot_time>.*)"
        r" \(kernel\)((?P<initrd_boot_time>.*) \(initrd\))? \+ "
        r"(?P<userspace_boot_time>.*) \(userspace\) = (?P<total_time>.*)",
        re.M,
    )
    # 1min 2.764s
    # 40.506s
    # 2.020ms
    VALUE_UNIT_PATTERN = re.compile(r"(?P<value>[\d]+(.[\d]+)?)(?P<unit>[\w]+)", re.M)

    @property
    def command(self) -> str:
        return "systemd-analyze"

    @property
    def can_install(self) -> bool:
        return False

    @retry(exceptions=LisaException, tries=30, delay=2)  # type: ignore
    def get_boot_time(self, force_run: bool = True) -> ProvisionBootTimeMessage:
        result = self.run(
            parameters="time",
            force_run=force_run,
            sudo=True,
        )
        if result.exit_code != 0:
            if "Bootup is not yet finished" in result.stdout:
                raise LisaException("Bootup is not yet finished, retry ...")
            else:
                raise LisaException("fail to run systemd-analyze time")
        matched = find_groups_in_lines(
            result.stdout, self.BOOT_TIME_PATTERN, single_line=True
        )
        assert matched[0], "not find matched result from systemd-analyze time"
        boot_time = ProvisionBootTimeMessage()
        boot_time.kernel_boot_time = self._convert_rawstr_into_value(
            matched[0]["kernel_boot_time"]
        )
        if matched[0]["initrd_boot_time"]:
            boot_time.initrd_boot_time = self._convert_rawstr_into_value(
                matched[0]["initrd_boot_time"]
            )
        if matched[0]["firmware_boot_time"]:
            boot_time.firmware_boot_time = self._convert_rawstr_into_value(
                matched[0]["firmware_boot_time"]
            )
        if matched[0]["loader_boot_time"]:
            boot_time.loader_boot_time = self._convert_rawstr_into_value(
                matched[0]["loader_boot_time"]
            )
        boot_time.userspace_boot_time = self._convert_rawstr_into_value(
            matched[0]["userspace_boot_time"]
        )
        boot_time.boot_times = int(
            self.node.execute(
                "last reboot | grep -i  'system boot' | wc -l", sudo=True, shell=True
            ).stdout
        )
        boot_time.provision_time = self.node.provision_time
        return boot_time

    def plot(self, output_file: PurePath, sudo: bool = False) -> None:
        self.run(f"plot > {output_file}", shell=True, sudo=sudo, expected_exit_code=0)

    def _convert_rawstr_into_value(self, raw_str: str) -> float:
        value_list = raw_str.strip().split()
        total_time: float = 0
        for va in value_list:
            entries = find_groups_in_lines(
                va, self.VALUE_UNIT_PATTERN, single_line=True
            )
            for entry in entries:
                total_time += self._convert_value_into_ms(entry["value"], entry["unit"])
        return total_time

    def _convert_value_into_ms(self, value: str, unit: str) -> float:
        rate = 0
        if unit == "min":
            rate = 60000
        elif unit == "s":
            rate = 1000
        elif unit == "ms":
            rate = 1
        else:
            raise LisaException(f"please handle unit {unit} properly")
        if value is None:
            value = 0
        return float(value) * rate
