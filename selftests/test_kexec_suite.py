# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Tuple, cast
from unittest import TestCase
from unittest.mock import MagicMock

from lisa import RemoteNode
from lisa.microsoft.testsuites.kexec.kexec_suite import KexecSuite
from lisa.operating_system import Posix
from lisa.sut_orchestrator import CLOUD_HYPERVISOR, OPENVMM


class KexecSuiteTestCase(TestCase):
    _suite_type = cast(Any, KexecSuite).__wrapped__

    def test_running_openvmm_guests_are_checked_before_host_kexec(self) -> None:
        suite, guest, host, environment = self._create_scenario(OPENVMM, "azure")
        log = MagicMock()
        result = MagicMock()

        suite.verify_kexec_reboot_systemd_with_running_guests(
            guest, environment, log, result
        )

        suite._record_peer_boot_ids.assert_called_once_with([guest], log)
        suite._run_kexec_test.assert_called_once_with(
            host, log, result, use_systemctl=True
        )
        suite._validate_peer_nodes.assert_not_called()

    def test_existing_platform_guest_continuity_expectations_are_preserved(
        self,
    ) -> None:
        for platform_type in ("azure", CLOUD_HYPERVISOR):
            with self.subTest(platform=platform_type):
                suite, guest, host, environment = self._create_scenario(
                    "remote", platform_type
                )
                log = MagicMock()
                result = MagicMock()

                suite.verify_kexec_reboot_systemd_with_running_guests(
                    guest, environment, log, result
                )

                suite._run_kexec_test.assert_called_once_with(
                    host, log, result, use_systemctl=True
                )
                if platform_type == CLOUD_HYPERVISOR:
                    suite._validate_peer_nodes.assert_not_called()
                else:
                    suite._validate_peer_nodes.assert_called_once_with(
                        [(guest, "guest-boot-id")], log
                    )

    def _create_scenario(
        self, guest_type: str, platform_type: str
    ) -> Tuple[Any, MagicMock, MagicMock, MagicMock]:
        suite = self._suite_type.__new__(self._suite_type)
        host = MagicMock(spec=RemoteNode)
        host.name = "host"
        host.os = MagicMock(spec=Posix)
        host.execute.return_value.exit_code = 0
        guest = MagicMock(spec=RemoteNode)
        guest.name = "guest"
        guest.parent = host
        guest.os = MagicMock(spec=Posix)
        guest.type_name.return_value = guest_type
        environment = MagicMock()
        environment.platform.type_name.return_value = platform_type
        environment.platform.host_node = host
        environment.nodes.list.return_value = [guest]
        suite._record_peer_boot_ids = MagicMock(return_value=[(guest, "guest-boot-id")])
        suite._run_kexec_test = MagicMock()
        suite._validate_peer_nodes = MagicMock()
        return suite, guest, host, environment
