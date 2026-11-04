# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import sys
from datetime import datetime, timezone
from importlib import import_module
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa import microsoft as microsoft_package
from lisa import schema
from lisa.operating_system import Windows
from lisa.sut_orchestrator.azure.features import ArchitectureSettings
from lisa.util import LisaException

sys.modules.setdefault("microsoft", microsoft_package)
hibernate_resume_module = import_module(
    "lisa.microsoft.testsuites.vm_extensions.runtime_extensions.hibernate_resume"
)
hibernate_extension_module = import_module(
    "lisa.microsoft.testsuites.vm_extensions.runtime_extensions."
    "hibernate_extension_base"
)
HibernateResumeValidator = hibernate_resume_module.HibernateResumeValidator
HibernateExtensionTestBase = hibernate_extension_module.HibernateExtensionTestBase
hibernate_extension_requirement = (
    hibernate_extension_module.hibernate_extension_requirement
)


class _WindowsHibernateExtensionTestBase(HibernateExtensionTestBase):
    PUBLISHER = "Microsoft.CPlat.Core"
    EXTENSION_TYPE = "WindowsHibernateExtension"
    EXTENSION_KEY = "windows_hibernate_extension"
    EXTENSION_RESOURCE_NAME = "AzureHibernateExtension"
    EXPECTED_INSTANCE_VIEW_TYPES = (
        "Microsoft.Azure.Extensions.Edp.WindowsHibernateTestExtension",
    )
    EXPECTED_OS = Windows
    PLATFORM_MANAGED = True


class HibernateExtensionRequirementTestCase(TestCase):
    def test_requirement_restricts_architecture_to_x64(self) -> None:
        requirement = hibernate_extension_requirement(Windows)

        assert requirement.environment
        features = requirement.environment.nodes[0].features
        assert features
        architecture = next(
            feature
            for feature in features.items
            if isinstance(feature, ArchitectureSettings)
        )

        self.assertEqual(schema.ArchitectureType.x64, architecture.arch)


class HibernateResumeValidatorTestCase(TestCase):
    def setUp(self) -> None:
        self.validator = HibernateResumeValidator.__new__(HibernateResumeValidator)

    def test_parse_memory_load_requires_initial_threshold(self) -> None:
        with self.assertRaisesRegex(LisaException, "Invalid memory-load state"):
            self.validator._parse_memory_state("HRMEM:10:20:1000:899")

    def test_parse_memory_load_accepts_post_resume_diagnostic_usage(self) -> None:
        state = self.validator._parse_memory_state(
            "HRMEM:10:20:1000:1",
            require_target_threshold=False,
        )

        self.assertEqual(10, state.pid)
        self.assertEqual(20, state.start_ticks)
        self.assertEqual(1000, state.target_bytes)
        self.assertEqual(1, state.held_bytes)

    def test_parse_boot_time_accepts_linux_and_windows_formats(self) -> None:
        linux_time = self.validator._parse_boot_time(
            "HRBOOT:2026-11-03 14:15:16:HRBOOT"
        )
        windows_time = self.validator._parse_boot_time(
            "HRBOOT:2026-11-03T14:15:16.1234567Z:HRBOOT"
        )

        self.assertEqual(2026, linux_time.year)
        self.assertEqual(123456, windows_time.microsecond)
        offset = windows_time.utcoffset()
        assert offset is not None
        self.assertEqual(0, offset.total_seconds())

    @patch.object(hibernate_resume_module, "wait_operation")
    def test_run_guest_command_returns_stdout(self, wait: MagicMock) -> None:
        wait.return_value = {
            "value": [
                {
                    "code": "ComponentStatus/StdOut/succeeded",
                    "level": "Info",
                    "message": "result",
                }
            ]
        }
        virtual_machines = MagicMock()
        virtual_machines.begin_run_command.return_value = MagicMock()
        self.validator._is_windows = False
        self.validator._compute_client = MagicMock(virtual_machines=virtual_machines)
        self.validator._resource_group_name = "rg"
        self.validator._vm_name = "vm"
        self.validator._log = MagicMock()

        output = self.validator._run_guest_command("echo result")

        self.assertEqual("result", output)
        parameters = virtual_machines.begin_run_command.call_args.kwargs["parameters"]
        self.assertEqual("RunShellScript", parameters.command_id)

    @patch.object(hibernate_resume_module, "wait_operation")
    def test_run_guest_command_rejects_failed_status(self, wait: MagicMock) -> None:
        wait.return_value = {
            "value": [
                {
                    "code": "ComponentStatus/RunShellScript/failed",
                    "level": "Error",
                    "message": "script failed",
                }
            ]
        }
        self.validator._is_windows = False
        self.validator._compute_client = MagicMock()
        self.validator._resource_group_name = "rg"
        self.validator._vm_name = "vm"
        self.validator._log = MagicMock()

        with self.assertRaisesRegex(LisaException, "script failed"):
            self.validator._run_guest_command("exit 1")

    def test_windows_memory_script_delimits_target_variable(self) -> None:
        with patch.object(
            self.validator,
            "_run_guest_command",
            return_value="HRMEM:10:20:1000:1000",
        ) as run_guest_command, patch.object(
            self.validator,
            "_encode_asset",
            return_value="c291cmNl",
        ):
            self.validator._start_windows_memory_load(0.1, None)

        script = run_guest_command.call_args.args[0]
        self.assertIn('"${target}:$($process.PrivateMemorySize64)"', script)

    @patch.object(hibernate_resume_module.time, "sleep")
    @patch.object(hibernate_resume_module, "create_timer")
    @patch.object(hibernate_resume_module, "wait_operation")
    def test_vm_operation_retry_uses_fresh_timer(
        self,
        wait_operation: MagicMock,
        create_timer: MagicMock,
        sleep: MagicMock,
    ) -> None:
        first_timer = MagicMock()
        second_timer = MagicMock()
        second_timer.elapsed.return_value = 1
        create_timer.side_effect = [first_timer, second_timer]
        wait_operation.side_effect = [LisaException("timeout"), None]
        operation_factory = MagicMock(side_effect=[MagicMock(), MagicMock()])
        self.validator._log = MagicMock()

        self.validator._run_vm_operation(
            operation_factory=operation_factory,
            operation_name="resume",
            timeout=3000,
        )

        self.assertEqual(2, operation_factory.call_count)
        self.assertEqual(2, create_timer.call_count)
        sleep.assert_called_once_with(10)

    @patch.object(hibernate_resume_module.time, "sleep")
    @patch.object(hibernate_resume_module, "create_timer")
    def test_windows_resume_substatus_waits_for_resume(
        self,
        create_timer: MagicMock,
        sleep: MagicMock,
    ) -> None:
        timer = MagicMock()
        timer.elapsed.side_effect = [0, 10]
        create_timer.return_value = timer
        start_status = SimpleNamespace(
            code="ComponentStatus/VMBootState/Start/succeeded"
        )
        fresh_resume_status = SimpleNamespace(
            code="ComponentStatus/VMBootState/Resume/succeeded",
        )
        stale_status_time = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)
        fresh_status_time = datetime(2026, 11, 3, 10, 1, tzinfo=timezone.utc)

        def create_vm(
            status_time: datetime,
            *substatuses: SimpleNamespace,
        ) -> SimpleNamespace:
            extension = SimpleNamespace(
                name="AzureHibernateExtension",
                statuses=[
                    SimpleNamespace(
                        code="ProvisioningState/succeeded",
                        time=status_time,
                    )
                ],
                substatuses=list(substatuses),
            )
            return SimpleNamespace(
                instance_view=SimpleNamespace(extensions=[extension])
            )

        self.validator._extension_name = "AzureHibernateExtension"
        self.validator._get_vm = MagicMock(
            side_effect=[
                create_vm(stale_status_time, start_status),
                create_vm(fresh_status_time, fresh_resume_status),
            ]
        )

        status_time = self.validator._validate_windows_resume_substatus(
            previous_status_time=stale_status_time
        )

        self.assertEqual(2, self.validator._get_vm.call_count)
        self.assertEqual(fresh_status_time, status_time)
        sleep.assert_called_once_with(10)

    @patch.object(hibernate_resume_module.time, "sleep")
    @patch.object(hibernate_resume_module, "create_timer")
    def test_windows_resume_substatus_rejects_failed_extension(
        self,
        create_timer: MagicMock,
        sleep: MagicMock,
    ) -> None:
        timer = MagicMock()
        timer.elapsed.side_effect = [0, 181]
        create_timer.return_value = timer
        extension = SimpleNamespace(
            name="AzureHibernateExtension",
            statuses=[
                SimpleNamespace(
                    code="ProvisioningState/failed",
                    time=datetime(2026, 11, 3, 10, 1, tzinfo=timezone.utc),
                )
            ],
            substatuses=[
                SimpleNamespace(
                    code="ComponentStatus/VMBootState/Resume/succeeded",
                )
            ],
        )
        self.validator._extension_name = "AzureHibernateExtension"
        self.validator._get_vm = MagicMock(
            return_value=SimpleNamespace(
                instance_view=SimpleNamespace(extensions=[extension])
            )
        )

        with self.assertRaisesRegex(LisaException, "ProvisioningState/failed"):
            self.validator._validate_windows_resume_substatus(
                previous_status_time=datetime(
                    2026,
                    11,
                    3,
                    10,
                    0,
                    tzinfo=timezone.utc,
                )
            )

        sleep.assert_called_once_with(10)


class HibernateExtensionTestBaseTestCase(TestCase):
    def setUp(self) -> None:
        self.suite = object.__new__(_WindowsHibernateExtensionTestBase)
        self.compute_client = MagicMock()
        self.node_context = SimpleNamespace(
            resource_group_name="resource-group",
            vm_name="vm",
        )

    def _candidate(
        self,
        *,
        version: str = "1.0.8",
        type_: str = ("Microsoft.Azure.Extensions.Edp.WindowsHibernateTestExtension"),
    ) -> SimpleNamespace:
        return SimpleNamespace(
            name="AzureHibernateExtension",
            type=type_,
            type_handler_version=version,
            statuses=[SimpleNamespace(code="ProvisioningState/succeeded")],
        )

    def _validate_candidate(
        self,
        requested_version: str,
        candidate: SimpleNamespace,
    ) -> str:
        self.compute_client.virtual_machines.get.return_value = SimpleNamespace(
            instance_view=SimpleNamespace(extensions=[candidate])
        )
        with patch.object(
            self.suite,
            "_get_azure_context",
            return_value=(None, self.compute_client),
        ), patch.object(
            hibernate_extension_module,
            "get_node_context",
            return_value=self.node_context,
        ):
            return self.suite._validate_platform_managed_candidate(
                node=MagicMock(),
                log=MagicMock(),
                environment=MagicMock(),
                variables={"extension_version": requested_version},
            )

    def test_platform_managed_candidate_accepts_requested_major_minor(self) -> None:
        extension_name = self._validate_candidate(
            "1.0",
            self._candidate(version="1.0.8"),
        )

        self.assertEqual("AzureHibernateExtension", extension_name)

    def test_platform_managed_candidate_rejects_wrong_major_minor(self) -> None:
        with self.assertRaisesRegex(LisaException, "version mismatch"):
            self._validate_candidate(
                "99.0",
                self._candidate(version="1.0.8"),
            )

    def test_platform_managed_candidate_rejects_unknown_version(self) -> None:
        with self.assertRaisesRegex(LisaException, "version mismatch"):
            self._validate_candidate(
                "1.0",
                self._candidate(version="unknown"),
            )

    def test_platform_managed_candidate_rejects_wrong_handler_type(self) -> None:
        with self.assertRaisesRegex(LisaException, "handler type mismatch"):
            self._validate_candidate(
                "1.0.8",
                self._candidate(type_="Microsoft.Compute.CustomScriptExtension"),
            )
