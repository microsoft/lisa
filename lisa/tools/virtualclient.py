# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import csv
import json
import re
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, cast

from assertpy import assert_that

from lisa import notifier
from lisa.base_tools import Uname, Wget
from lisa.executable import Tool
from lisa.messages import (
    MetricRelativity,
    VCMetricsMessage,
    create_perf_message,
    send_unified_perf_message,
)
from lisa.operating_system import Posix
from lisa.util import LisaException
from lisa.util.process import Process

from .chmod import Chmod
from .chown import Chown
from .git import Git
from .ln import Ln
from .parted import Parted
from .unzip import Unzip
from .whoami import Whoami

if TYPE_CHECKING:
    from lisa import Environment, Node, TestResult
    from lisa.node import RemoteNode


class VcTargetInfo:
    def __init__(self, role: str, node: "RemoteNode") -> None:
        self.role = role
        self.node = node
        self.virtual_client = node.tools[VirtualClientTool]


class VirtualClientTool(Tool):
    _version = "1.14.36"

    @property
    def command(self) -> str:
        return "virtualclient"

    @property
    def can_install(self) -> bool:
        return True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        uname = self.node.tools[Uname]
        arch = uname.get_linux_information().hardware_platform
        if arch == "x86_64":
            arch = "x64"
        elif arch == "aarch64":
            arch = "arm64"
        else:
            raise LisaException(f"not supported architecture {arch}")

        self._vc_download_path: str = (
            f"{self.node.working_path.parent.parent}/virtualclient"
        )
        self._vc_raw_tool_path: str = (
            f"{self._vc_download_path}/content/linux-{arch}/VirtualClient"
        )
        self._vc_profile_file_path: str = (
            f"{self._vc_download_path}/content/linux-{arch}/profiles"
        )
        self._vc_log_path: str = f"{self._vc_download_path}/content/linux-{arch}/logs"

    def install(self) -> bool:
        posix_os: Posix = self.node.os  # type: ignore
        posix_os.install_packages(["gnupg", "lshw"])
        _ = self.node.tools[Git]
        _ = self.node.tools[Parted]

        vc_download_url = (
            f"https://www.nuget.org/api/v2/package/VirtualClient/{self._version}"
        )
        package_name = f"virtualclient.{self._version}.nupkg"
        wget_tool = self.node.tools[Wget]
        wget_tool.get(
            vc_download_url, str(self.node.working_path.parent.parent), package_name
        )

        unzip = self.node.tools[Unzip]
        unzip.extract(
            f"{self.node.working_path.parent.parent}/{package_name}",
            self._vc_download_path,
        )

        self.node.tools[Chmod].chmod(self._vc_raw_tool_path, "777")
        ln = self.node.tools[Ln]
        ln.create_link(self._vc_raw_tool_path, "/usr/bin/virtualclient")
        return self._check_exists()

    def generate_layout(self, clients_info: List[VcTargetInfo]) -> str:
        clients_list = []
        for client_info in clients_info:
            client_dict = {
                "name": client_info.node.name,
                "ipAddress": client_info.node.internal_address,
                "role": client_info.role,
            }
            clients_list.append(client_dict)
        data = {"clients": clients_list}
        json_data = json.dumps(data, indent=4)
        file_path = f"{self.node.working_path}/layout.json"
        self.node.execute(f"echo '{json_data}' > {file_path}", shell=True)
        return file_path

    def run_vc_command_async(
        self,
        profile_name: str,
        client_id: str = "",
        port: int = 0,
        clean_target: str = "",
        content_path: str = "",
        debug: bool = False,
        event_hub_connection_str: str = "",
        system: str = "Azure",
        flush_wait: int = 0,
        experiment_id: str = "",
        fail_fast: bool = False,
        dependencies: bool = False,
        iterations: int = 0,
        layout_path: str = "",
        log_retention: int = 0,
        log_to_file: bool = False,
        log_level: int = 0,
        meta_data: str = "",
        packages: str = "https://virtualclient.blob.core.windows.net/packages",
        parameters: str = "",
        proxy_api: str = "",
        seed: int = 0,
        scenarios: str = "",
        timeout: int = 1440,
    ) -> Process:
        cmd = self._build_command(
            profile_name,
            client_id,
            port,
            clean_target,
            content_path,
            debug,
            event_hub_connection_str,
            system,
            flush_wait,
            experiment_id,
            fail_fast,
            dependencies,
            iterations,
            layout_path,
            log_retention,
            log_to_file,
            log_level,
            meta_data,
            packages,
            parameters,
            proxy_api,
            seed,
            scenarios,
            timeout,
        )
        process = self.node.execute_async(
            f"{self.command} {cmd}", shell=True, sudo=True
        )
        return process

    def _build_command(
        self,
        profile_name: str,
        client_id: str,
        port: int,
        clean_target: str,
        content_path: str,
        debug: bool,
        event_hub_connection_str: str,
        system: str,
        flush_wait: int,
        experiment_id: str,
        fail_fast: bool,
        dependencies: bool,
        iterations: int,
        layout_path: str,
        log_retention: int,
        log_to_file: bool,
        log_level: int,
        meta_data: str,
        packages: str,
        parameters: str,
        proxy_api: str,
        seed: int,
        scenarios: str,
        timeout: int,
    ) -> str:
        cmd_parts = [
            f" --profile={self._vc_profile_file_path}/{profile_name}.json ",
            f" --timeout={timeout}",
        ]

        def add_if_non_empty(option: str, value: Any) -> None:
            if value:
                cmd_parts.append(f" {option}={value} ")

        def add_if_true(option: str, flag: Any) -> None:
            if flag:
                cmd_parts.append(f" {option} ")

        add_if_non_empty("--clientId", client_id)
        add_if_non_empty("--port", port)
        add_if_non_empty("--clean", clean_target)
        add_if_non_empty("--cp", content_path)
        add_if_true("--verbose", debug)
        add_if_non_empty("--eventHubConnectionString", event_hub_connection_str)
        add_if_non_empty("--system", system)
        add_if_non_empty("--flush-wait", flush_wait)
        add_if_non_empty("--experimentId", experiment_id)
        add_if_true("--fail-fast", fail_fast)
        add_if_true("--dependencies", dependencies)
        add_if_non_empty("--iterations", iterations)
        if layout_path:
            cmd_parts.append(f" --layoutPath={self.node.get_pure_path(layout_path)} ")
        add_if_non_empty("--log-retention", log_retention)
        add_if_true("--log-to-file", log_to_file)
        add_if_non_empty("--log-level", log_level)
        add_if_non_empty("--metadata", meta_data)
        add_if_non_empty("--packages", packages)
        add_if_non_empty("--parameters", parameters)
        add_if_non_empty("--proxy-api", proxy_api)
        add_if_non_empty("--seed", seed)
        add_if_non_empty("--scenarios", scenarios)

        return "".join(cmd_parts)

    def download_raw_data_file(self, local_log_path: Path) -> Path:
        local_path = local_log_path / "metrics.csv"
        remote_path = self.node.get_pure_path(f"{self._vc_log_path}/metrics.csv")
        current_user = self.node.tools[Whoami].get_username()
        self.node.tools[Chown].change_owner(remote_path, current_user)
        self.node.shell.copy_back(
            remote_path,
            local_path,
        )
        return local_path

    def send_metrics_messages(
        self,
        metrics_file: Path,
        node: "Node",
        test_result: "TestResult",
    ) -> None:
        with open(metrics_file, mode="r", newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                fields = {
                    "time": self._parse_timestamp(row["Timestamp"]),
                    "tool": row["ToolName"],
                    "experiment_id": row["ExperimentId"],
                    "client_id": row["ClientId"],
                    "profile": row["Profile"],
                    "profile_name": row["ProfileName"],
                    "scenario_name": row["ScenarioName"],
                    "scenario_start_time": self._parse_timestamp(
                        row["ScenarioStartTime"]
                    ),
                    "scenario_end_time": self._parse_timestamp(row["ScenarioEndTime"]),
                    "metric_categorization": row["MetricCategorization"],
                    "metric_name": row["MetricName"],
                    "metric_value": Decimal(row["MetricValue"]),
                    "metric_unit": row["MetricUnit"],
                    "metric_description": row["MetricDescription"],
                    "metric_relativity": row["MetricRelativity"],
                    "execution_system": row["ExecutionSystem"],
                    "operating_system_platform": row["OperatingSystemPlatform"],
                    "operation_id": row["OperationId"],
                    "operation_parent_id": row["OperationParentId"],
                    "app_host": row["AppHost"],
                    "app_name": row["AppName"],
                    "app_version": row["AppVersion"],
                    "app_telemetry_version": row["AppTelemetryVersion"],
                    "tags": row["Tags"],
                }
                message = create_perf_message(
                    message_type=VCMetricsMessage,
                    node=node,
                    test_result=test_result,
                    test_case_name=test_result.name,
                    other_fields=fields,
                )
                notifier.notify(message)

                # send by unified perf messages
                send_unified_perf_message(
                    node=node,
                    test_result=test_result,
                    test_case_name=test_result.name,
                    metric_name=row["MetricName"],
                    metric_value=Decimal(row["MetricValue"]),
                    metric_unit=row["MetricUnit"],
                    metric_description=row["MetricDescription"],
                    metric_relativity=MetricRelativity.parse(row["MetricRelativity"]),
                )

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        # Strip 'Z' and limit microseconds to 6 digits
        timestamp_str = timestamp_str.rstrip("Z")
        # Split timestamp and microseconds
        if "." in timestamp_str:
            main_time, microseconds = timestamp_str.split(".")
            # Truncate microseconds to 6 digits
            microseconds = microseconds[:6]
            timestamp_str = f"{main_time}.{microseconds}"
        return datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S.%f")


class VcRunner:
    # [07/08/2024 13:58:15] Exit Code: 0\r\n
    exit_code_pattern = re.compile(r"([\w\W]*?)Exit Code: (?P<exit_code>\d+)")

    def __init__(self, environment: "Environment", roles: List[str]):
        if len(roles) > len(environment.nodes):
            raise ValueError(
                "More roles specified than available nodes in the environment"
            )

        self._targets: List[VcTargetInfo] = []
        nodes = [cast("RemoteNode", environment.nodes[i]) for i in range(len(roles))]

        for role, node in zip(roles, nodes):
            self._targets.append(VcTargetInfo(role=role, node=node))

    def run(
        self,
        node: "Node",
        test_result: "TestResult",
        profile_name: str,
        log_path: Path,
        experiment_id: str = "",
        system: str = "Azure",
        timeout: int = 10,
    ) -> None:
        layout_file = self._generate_layout_file()
        experiment_id = experiment_id or str(uuid.uuid4())

        client_params = self._generate_client_params(
            profile_name,
            system,
            layout_file,
            timeout,
            experiment_id,
        )

        results = self._execute_commands(client_params)
        self._wait_for_client_result(results, timeout)
        self._process_results(node=node, test_result=test_result, log_path=log_path)

    def _generate_layout_file(
        self,
    ) -> str:
        layout_file = ""
        # The layout file is required if there are 2 or more roles.
        # Since the layout file path is the same for all roles,
        # return the path from the last role.
        if len(self._targets) > 1:
            for target in self._targets:
                layout_file = target.virtual_client.generate_layout(self._targets)
        return layout_file

    def _generate_client_params(
        self,
        profile_name: str,
        system: str,
        layout_file: str,
        timeout: int,
        experiment_id: str,
    ) -> Any:
        return {
            node_info.node.name: {
                "profile_name": profile_name,
                "system": system,
                "client_id": node_info.node.name,
                "layout_path": layout_file,
                "timeout": timeout,
                "experiment_id": experiment_id,
            }
            for node_info in self._targets
        }

    def _execute_commands(
        self,
        client_params: Any,
    ) -> Dict[str, Process]:
        results = {}
        for target in self._targets:
            node_name = target.virtual_client.node.name
            params = client_params.get(node_name, {})
            results[node_name] = target.virtual_client.run_vc_command_async(**params)
        return results

    def _wait_for_client_result(
        self,
        results: Dict[str, Process],
        timeout: int,
    ) -> None:
        client_info = next(info for info in self._targets if info.role == "client")
        client_process = results[client_info.node.name]
        process_result = client_process.wait_result(timeout=(timeout + 5) * 60)
        matched = self.exit_code_pattern.match(process_result.stdout)
        assert matched, "can't find the matched str 'Exit Code'"
        assert_that(matched.group("exit_code")).described_as(
            f"Exit code on {client_info.node.name} is unexpected"
        ).is_equal_to("0")
        for node_info in self._targets:
            node_info.node.close()

    def _process_results(
        self, node: "Node", test_result: "TestResult", log_path: Path
    ) -> None:
        for target in self._targets:
            local_path = target.virtual_client.download_raw_data_file(
                local_log_path=log_path
            )
            target.virtual_client.send_metrics_messages(
                metrics_file=local_path, node=node, test_result=test_result
            )
